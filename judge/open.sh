#!/usr/bin/env bash
set -euo pipefail

# judge/open.sh [problemId]
# Opens workspace/<id>.cpp
# - No args: open current problem
# - With problemId (e.g. p01): open that problem in the current round (order not required)
# Also sets per-problem start_time on first open.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_PATH="$ROOT/state/round.json"
WORKSPACE_DIR="$ROOT/workspace"

export STATE_PATH

PYTHON_BIN=""
PYTHON_ARGS=()
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=python3
elif command -v py >/dev/null 2>&1; then
  PYTHON_BIN=py
  PYTHON_ARGS=(-3)
else
  PYTHON_BIN=python
fi

if [[ ! -f "$STATE_PATH" ]]; then
  echo "No active round. Run ./judge/start.sh first." >&2
  exit 1
fi

TARGET_ID="${1:-}"
export TARGET_ID

PID="$($PYTHON_BIN "${PYTHON_ARGS[@]}" - <<'PY'
import json, time, os

path = os.environ['STATE_PATH']
target = os.environ.get('TARGET_ID') or ''

with open(path, 'r', encoding='utf-8') as f:
  data = json.load(f)

problems = data.get('problems', [])
if not problems:
  raise SystemExit('no problems in round')

if target:
  idx = next((i for i, p in enumerate(problems) if p.get('id') == target), None)
  if idx is None:
    raise SystemExit(f'problem not in round: {target}')
  data['current_problem'] = idx
else:
  idx = int(data.get('current_problem', 0))
  if idx < 0 or idx >= len(problems):
    raise SystemExit('current_problem out of range')

p = problems[idx]
if p.get('start_time') is None:
  p['start_time'] = int(time.time())

with open(path, 'w', encoding='utf-8') as f:
  json.dump(data, f, ensure_ascii=False, indent=2)

print(p.get('id',''))
PY
)"

if [[ -z "$PID" ]]; then
  echo "Cannot determine current problem." >&2
  exit 1
fi

FILE="$WORKSPACE_DIR/$PID.cpp"
if [[ ! -f "$FILE" ]]; then
  echo "File not found: $FILE" >&2
  echo "(Did you run ./judge/start.sh?)" >&2
  exit 1
fi

if command -v code >/dev/null 2>&1; then
  code "$FILE"
else
  echo "Open this file: $FILE"
fi
