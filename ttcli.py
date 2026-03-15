#!/usr/bin/env python3
"""Contest-like two-terminal CLI (no sockets).

Usage:
  ttcli.py judge
  ttcli.py submit [p01 p02 ...]
  ttcli.py repl

Design:
- Submit side writes JSON request files into state/tt_queue.
- Judge side monitors that queue, runs ./judge/submit.sh <pid> and prints results.

This intentionally keeps the UX minimal and close to the contest description.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional


ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / "state"
QUEUE_DIR = STATE_DIR / "tt_queue"
PROCESSING_DIR = STATE_DIR / "tt_processing"
DONE_DIR = STATE_DIR / "tt_done"
ACK_DIR = STATE_DIR / "tt_ack"
RESULTS_LOG = STATE_DIR / "tt_results.log"


_PID_RE = re.compile(r"^p(\d{1,3})$", re.IGNORECASE)


def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_dirs() -> None:
    for p in (QUEUE_DIR, PROCESSING_DIR, DONE_DIR, ACK_DIR):
        p.mkdir(parents=True, exist_ok=True)


def _fmt_local_time_ampm(ts: Optional[float] = None) -> str:
    d = datetime.fromtimestamp(ts if ts is not None else time.time())
    # Match sample style: 7:05:22 PM
    return d.strftime("%I:%M:%S %p").lstrip("0")


def _read_active_round_problem_ids(*, only_pending: bool) -> list[str]:
    """Return problem ids from state/round.json (e.g., ['p01','p02'])."""
    round_path = STATE_DIR / "round.json"
    if not round_path.exists():
        return []
    try:
        data = json.loads(round_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    probs = data.get("problems") or []
    out: list[str] = []
    if isinstance(probs, list):
        for p in probs:
            if not isinstance(p, dict):
                continue
            pid = p.get("id")
            if not isinstance(pid, str):
                continue
            if only_pending:
                if p.get("status") != "pending":
                    continue
            out.append(pid)
    return out


def _read_workspace_problem_ids() -> list[str]:
    """Fallback: infer available problems from workspace/*.cpp (e.g., p01.cpp)."""
    ws = ROOT / "workspace"
    if not ws.exists():
        return []
    ids: list[str] = []
    for p in sorted(ws.glob("p*.cpp")):
        name = p.stem  # p01
        if re.match(r"^p\d{2,3}$", name, re.IGNORECASE):
            ids.append(name.lower())
    return ids


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def _colorize(text: str, color: str) -> str:
    if not _supports_color():
        return text
    codes = {
        "green": "\x1b[32m",
        "red": "\x1b[31m",
        "yellow": "\x1b[33m",
        "reset": "\x1b[0m",
    }
    return f"{codes.get(color,'')}{text}{codes['reset']}"


def _strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def _verdict_label(verdict: str) -> tuple[str, Optional[str]]:
    v = verdict.upper()
    if v == "AC":
        return "Accepted", "green"
    if v == "WA":
        return "Wrong answer", "red"
    if v == "CE":
        return "Compile error", "yellow"
    return "Error", "red"


def _format_judge_row(timestamp: str, verdict: str, pid: str) -> tuple[str, str]:
    """Return (plain_row, colored_row)."""
    ts_col = timestamp
    label, color = _verdict_label(verdict)

    # Column widths
    w_ts = 19
    w_ver = 12
    w_pid = 7

    verdict_padded_plain = f"{label:<{w_ver}}"
    verdict_padded_colored = (
        _colorize(verdict_padded_plain, color) if color else verdict_padded_plain
    )

    plain = f"{ts_col:<{w_ts}}  {verdict_padded_plain}  {pid:<{w_pid}}"
    colored = f"{ts_col:<{w_ts}}  {verdict_padded_colored}  {pid:<{w_pid}}"
    return plain, colored


def normalize_problem_id(token: str) -> str:
    t = token.strip()
    if not t:
        raise ValueError("empty problem id")

    # Accept p01, P1, p001
    m = _PID_RE.match(t)
    if not m:
        raise ValueError(f"invalid problem id: {token!r} (expected p1, p01, p10, ...)")

    n = int(m.group(1))
    if n <= 0:
        raise ValueError(f"invalid problem number: {n}")

    return f"p{n:02d}"


@dataclass(frozen=True)
class SubmitRequest:
    request_id: str
    created_at: int
    problems: list[str]


def _new_request_id() -> str:
    # lexicographically sortable
    ms = int(time.time() * 1000)
    rnd = random.randrange(1_000_000)
    return f"{ms}_{rnd:06d}"


def enqueue_submit(problems: Iterable[str]) -> SubmitRequest:
    _ensure_dirs()

    normalized: list[str] = []
    seen = set()
    for raw in problems:
        pid = normalize_problem_id(raw)
        if pid not in seen:
            normalized.append(pid)
            seen.add(pid)

    if not normalized:
        raise ValueError("no problems provided")

    req = SubmitRequest(
        request_id=_new_request_id(),
        created_at=int(time.time()),
        problems=normalized,
    )

    out = {
        "request_id": req.request_id,
        "created_at": req.created_at,
        "problems": req.problems,
        "cwd": str(ROOT),
        "version": 1,
    }

    tmp = QUEUE_DIR / f"req_{req.request_id}.json.tmp"
    final = QUEUE_DIR / f"req_{req.request_id}.json"

    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, final)  # atomic on same filesystem
    return req


def _ack_path(request_id: str, pid: str) -> Path:
    # pid expected normalized (p01)
    return ACK_DIR / f"ack_{request_id}_{pid}.json"


def _wait_for_acks(
    request_id: str, pids: list[str], timeout_sec: float
) -> dict[str, dict]:
    """Wait for ack files from judge; returns dict pid->ack json."""
    deadline = time.time() + max(0.0, timeout_sec)
    remaining = set(pids)
    acks: dict[str, dict] = {}

    while remaining and time.time() <= deadline:
        for pid in list(remaining):
            ap = _ack_path(request_id, pid)
            if not ap.exists():
                continue
            try:
                acks[pid] = json.loads(ap.read_text(encoding="utf-8"))
                remaining.remove(pid)
            except Exception:
                # If partially written (shouldn't happen due to atomic replace), ignore and retry.
                pass
        if remaining:
            time.sleep(0.05)

    return acks


def _pick_next_request() -> Optional[Path]:
    if not QUEUE_DIR.exists():
        return None

    candidates = sorted(p for p in QUEUE_DIR.glob("req_*.json") if p.is_file())
    if not candidates:
        return None

    src = candidates[0]
    dst = PROCESSING_DIR / src.name
    try:
        os.replace(src, dst)
    except FileNotFoundError:
        return None
    return dst


def _find_bash() -> Optional[str]:
    # Prefer bash if available (Git Bash / WSL). judge scripts are bash.
    for cmd in ("bash",):
        if shutil_which(cmd) is not None:
            return cmd
    return None


def shutil_which(cmd: str) -> Optional[str]:
    # local tiny reimplementation to avoid importing shutil in very old setups
    pathext = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";")
    path = os.environ.get("PATH", "")
    paths = path.split(os.pathsep)

    def exists(p: Path) -> bool:
        try:
            return p.is_file()
        except OSError:
            return False

    c = Path(cmd)
    if c.parent != Path("."):
        return str(c) if exists(c) else None

    # Try with extensions on Windows
    for d in paths:
        base = Path(d) / cmd
        if exists(base):
            return str(base)
        for ext in pathext:
            if ext and not cmd.lower().endswith(ext.lower()):
                p2 = Path(d) / (cmd + ext)
                if exists(p2):
                    return str(p2)
    return None


def _run_bash_lc(command: str, *, timeout_sec: float | None = None) -> tuple[int, str]:
    """Run a bash -lc command from repo root; returns (rc, combined_output)."""
    bash = shutil_which("bash")
    if bash is None:
        return (
            127,
            "bash not found. This repo's judge scripts require bash (Git Bash/WSL).",
        )

    try:
        proc = subprocess.run(
            [bash, "-lc", command],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
        return proc.returncode, (proc.stdout or "")
    except subprocess.TimeoutExpired:
        return 124, f"Command timed out: {command}"


def _clean_tt_ipc_state() -> None:
    """Remove pending/ack/processing files so a new repl session starts clean."""
    _ensure_dirs()

    for folder in (QUEUE_DIR, PROCESSING_DIR, ACK_DIR):
        if not folder.exists():
            continue
        for p in folder.glob("*"):
            try:
                if p.is_file():
                    p.unlink()
            except OSError:
                pass


def _start_fresh_round() -> tuple[bool, str]:
    """Start a fresh round by invoking judge/start.sh.

    Note: start.sh already calls judge/clean.sh internally.
    """
    rc, out = _run_bash_lc("./judge/start.sh")
    return rc == 0, out


def run_submit_sh(pid: str) -> tuple[str, str]:
    """Run judge/submit.sh for a given pid.

    Returns: (verdict, raw_output)
    verdict: AC | WA | CE | ERR
    """

    bash = shutil_which("bash")

    if bash is None:
        return (
            "ERR",
            "bash not found. This repo's judge scripts require bash (Git Bash/WSL).",
        )

    # IMPORTANT: On Windows, passing a native path like D:\...\submit.sh to bash often fails.
    # Run via a POSIX-style relative path from the repo root.
    # Prefix variable assignment to guarantee TTCLI mode even if env propagation is quirky
    # between Windows <-> (Git Bash / WSL) environments.
    cmd = f"TTCLI=1 ./judge/submit.sh {pid}"
    env = dict(os.environ)
    env["TTCLI"] = "1"

    proc = subprocess.run(
        [bash, "-lc", cmd],
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    out = proc.stdout or ""

    verdict = "ERR"
    if "ACCEPTED" in out:
        verdict = "AC"
    elif "WRONG ANSWER" in out:
        verdict = "WA"
    elif "COMPILE ERROR" in out:
        verdict = "CE"

    return verdict, out


def log_result(line: str) -> None:
    _ensure_dirs()
    with RESULTS_LOG.open("a", encoding="utf-8") as f:
        f.write(_strip_ansi(line) + "\n")


def judge_loop(poll_ms: int) -> int:
    _ensure_dirs()
    header = f"{'TIMESTAMP':<19}  {'VERDICT':<12}  {'PROBLEM':<7}"
    print(header, flush=True)
    print("-" * len(_strip_ansi(header)), flush=True)

    while True:
        req_path = _pick_next_request()
        if req_path is None:
            time.sleep(max(0.05, poll_ms / 1000.0))
            continue

        try:
            req = json.loads(req_path.read_text(encoding="utf-8"))
        except Exception as e:
            stamp = _now_ts()
            line = f"[{stamp}] ERR ??? (invalid request: {e})"
            print(line)
            log_result(line)
            os.replace(req_path, DONE_DIR / req_path.name)
            continue

        problems = req.get("problems") or []
        if not isinstance(problems, list) or not problems:
            stamp = _now_ts()
            line = f"[{stamp}] ERR ??? (missing problems list)"
            print(line)
            log_result(line)
            os.replace(req_path, DONE_DIR / req_path.name)
            continue

        for raw_pid in problems:
            try:
                pid = normalize_problem_id(str(raw_pid))
            except Exception:
                pid = str(raw_pid)

            verdict, raw = run_submit_sh(pid)
            stamp = _now_ts()
            plain_row, colored_row = _format_judge_row(stamp, verdict, pid)
            print(colored_row, flush=True)
            log_result(plain_row)

            # Ack file so the submit terminal can display success/failure.
            ack = {
                "request_id": str(req.get("request_id") or ""),
                "pid": pid,
                "verdict": verdict,
                "timestamp": stamp,
                "epoch": int(time.time()),
            }
            rid = ack["request_id"] or "unknown"
            ack_tmp = _ack_path(rid, pid).with_suffix(".json.tmp")
            ack_final = _ack_path(rid, pid)
            ack_tmp.write_text(
                json.dumps(ack, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(ack_tmp, ack_final)

            # Store raw output for debugging (one file per pid)
            out_file = DONE_DIR / f"{req_path.stem}_{pid}.log"
            out_file.write_text(raw, encoding="utf-8", errors="replace")

        os.replace(req_path, DONE_DIR / req_path.name)


def submit_once(problem_tokens: list[str]) -> int:
    req = enqueue_submit(problem_tokens)
    print(f"Queued {len(req.problems)} problem(s): {' '.join(req.problems)}")
    return 0


def repl() -> int:
    _ensure_dirs()
    # New REPL session = new round (as requested).
    _clean_tt_ipc_state()
    ok, out = _start_fresh_round()
    if ok:
        # Keep it short; the judge script prints the chosen problems.
        print("✔ Metadata are fetched.")
    else:
        # Still allow REPL to run, but submissions will likely fail.
        print("✖ Failed to start a new round.")
        if out.strip():
            print(out.strip())

    while True:
        try:
            avail_all = _read_active_round_problem_ids(only_pending=False)
            if not avail_all:
                avail_all = _read_workspace_problem_ids()
            if avail_all:
                pretty = ", ".join(avail_all)
                print(f"Available problems: {pretty}")
            print("✔ Enter problem names separated by at least one space:")
            line = input("$ ")
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            return 0

        s = line.strip()
        if not s:
            continue
        if s.lower() in ("exit", "quit"):
            return 0
        if s.lower() in ("help", "?"):
            print("Type: p1 p2 ... then press Enter")
            continue

        parts = s.split()
        try:
            req = enqueue_submit(parts)
            # Show per-problem submit status, then allow next input.
            for pid in req.problems:
                print(f"Submitting {pid} at {_fmt_local_time_ampm()}...")

            # Wait for judge to ack. If judge isn't running, this will time out.
            acks = _wait_for_acks(req.request_id, req.problems, timeout_sec=10.0)
            for pid in req.problems:
                ack = acks.get(pid)
                if not ack:
                    print(f"✖ Failed to submit {pid}.")
                    continue
                # Consider ERR as a failed submission (judge couldn't run).
                verdict = str(ack.get("verdict") or "").upper()
                if verdict == "ERR":
                    print(f"✖ Failed to submit {pid}.")
                else:
                    print(f"✔ Submitted {pid}.")
        except Exception as e:
            print(f"Error: {e}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ttcli", add_help=True)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_j = sub.add_parser("judge", help="Run judge monitor (right terminal)")
    p_j.add_argument("--poll-ms", type=int, default=200, help="Polling interval (ms)")

    p_s = sub.add_parser("submit", help="Queue a submission (non-interactive)")
    p_s.add_argument("problems", nargs="+", help="Problem ids: p1 p01 p10 ...")
    p_s.add_argument(
        "--wait",
        action="store_true",
        help="Wait for judge ack and exit non-zero on timeout",
    )
    p_s.add_argument(
        "--timeout-sec",
        type=float,
        default=10.0,
        help="Ack wait timeout (seconds) when used with --wait",
    )

    sub.add_parser("repl", help="Interactive submit terminal (left terminal)")

    args = parser.parse_args(argv)

    if args.cmd == "judge":
        try:
            return judge_loop(args.poll_ms)
        except KeyboardInterrupt:
            return 0

    if args.cmd == "submit":
        req = enqueue_submit(args.problems)
        if not args.wait:
            print(f"Queued {len(req.problems)} problem(s): {' '.join(req.problems)}")
            return 0

        for pid in req.problems:
            print(f"Submitting {pid} at {_fmt_local_time_ampm()}...")
        acks = _wait_for_acks(
            req.request_id, req.problems, timeout_sec=float(args.timeout_sec)
        )
        ok = True
        for pid in req.problems:
            ack = acks.get(pid)
            if not ack:
                print(f"✖ Failed to submit {pid}.")
                ok = False
                continue
            verdict = str(ack.get("verdict") or "").upper()
            if verdict == "ERR":
                print(f"✖ Failed to submit {pid}.")
                ok = False
            else:
                print(f"✔ Submitted {pid}.")
        return 0 if ok else 3

    if args.cmd == "repl":
        return repl()

    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
