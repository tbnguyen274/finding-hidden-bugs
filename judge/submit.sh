#!/usr/bin/env bash
set -euo pipefail

# judge/submit.sh
#
# Logic:
#   compile workspace/<pid>/main.cpp
#   for each problems/<pid>/tests/*.in:
#       run program, save output to workspace/<pid>/tests/<name>.out
#       compare to problems/<pid>/tests/<name>.out
#   if all correct: mark solved, +10
#   else: mark failed
#   if all problems finished: write history/<timestamp>.json and clear state/round.json

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_PATH="$ROOT/state/round.json"
PROBLEMS_DIR="$ROOT/problems"
WORKSPACE_DIR="$ROOT/workspace"
STATE_DIR="$ROOT/state"
HISTORY_DIR="$ROOT/history"

export STATE_PATH
export HISTORY_DIR

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

# Select target problem (optional) and get its index
SEL="$($PYTHON_BIN "${PYTHON_ARGS[@]}" - <<'PY'
import json, os

path = os.environ['STATE_PATH']
target = os.environ.get('TARGET_ID') or ''

with open(path,'r',encoding='utf-8') as f:
  data=json.load(f)

problems=data.get('problems',[])
if not problems:
  raise SystemExit('no problems in round')

if target:
  idx = next((i for i, p in enumerate(problems) if p.get('id') == target), None)
  if idx is None:
    raise SystemExit(f'problem not in round: {target}')
  data['current_problem'] = idx
  with open(path,'w',encoding='utf-8') as f:
    json.dump(data,f,ensure_ascii=False,indent=2)
else:
  idx=int(data.get('current_problem',0))
  if idx<0 or idx>=len(problems):
    raise SystemExit('current_problem out of range')

pid=problems[idx].get('id','')
print(f"{pid} {idx}")
PY
)"

PID="${SEL%% *}"
PROBLEM_INDEX="${SEL##* }"
export PID
export PROBLEM_INDEX

if [[ -z "$PID" ]]; then
  echo "Cannot determine current problem." >&2
  exit 1
fi

if [[ -z "$PROBLEM_INDEX" ]]; then
  echo "Cannot determine problem index." >&2
  exit 1
fi

SRC="$WORKSPACE_DIR/$PID.cpp"
if [[ ! -f "$SRC" ]]; then
  echo "File not found: $SRC" >&2
  exit 1
fi

TESTS_DIR="$PROBLEMS_DIR/$PID/tests"
if [[ ! -d "$TESTS_DIR" ]]; then
  echo "Tests not found: $TESTS_DIR" >&2
  echo "Run: ./judge/gen_tests.sh $PID" >&2
  exit 1
fi

RUN_DIR="$STATE_DIR/run/$PID"
mkdir -p "$RUN_DIR" "$STATE_DIR/build/$PID" "$HISTORY_DIR"

EXE="$STATE_DIR/build/$PID/submission.exe"

set +e
COMPILE_OUT=$(g++ -std=c++17 -O2 -pipe -s "$SRC" -o "$EXE" 2>&1)
RC=$?
set -e

if [[ $RC -ne 0 ]]; then
  echo "COMPILE ERROR (score 0)"
  echo "$COMPILE_OUT"
  $PYTHON_BIN "${PYTHON_ARGS[@]}" - <<'PY'
import json, os, time
path=os.environ['STATE_PATH']
pid=os.environ['PID']
idx=int(os.environ['PROBLEM_INDEX'])
now=int(time.time())
with open(path,'r',encoding='utf-8') as f:
  data=json.load(f)
p=data['problems'][idx]
if p.get('id')==pid:
  if p.get('start_time') is None:
    p['start_time']=now
  p['finish_time']=now
  p['status']='failed'
with open(path,'w',encoding='utf-8') as f:
  json.dump(data,f,ensure_ascii=False,indent=2)
PY

  # If all finished -> write history and clear round.json
  $PYTHON_BIN "${PYTHON_ARGS[@]}" - <<'PY'
import json, os, time
state_path=os.environ['STATE_PATH']
history_dir=os.environ['HISTORY_DIR']

def fmt(sec: int) -> str:
  sec = max(0, int(sec))
  m, s = divmod(sec, 60)
  return f"{m:02d}:{s:02d}"

with open(state_path,'r',encoding='utf-8') as f:
  data=json.load(f)

problems=data.get('problems',[])
all_done=all(p.get('status') in ('solved','failed') for p in problems)

score=sum(10 for p in problems if p.get('status')=='solved')
print(f"Score: {score}")

if not all_done:
  raise SystemExit(0)

start_time=int(data.get('start_time') or int(time.time()))
end_time=int(time.time())

total_sec = end_time - start_time

hist={
  'start_time': start_time,
  'end_time': end_time,
  'total_time_sec': total_sec,
  'total_time': fmt(total_sec),
  'problems': []
}

for p in problems:
  item={'id': p.get('id'), 'status': p.get('status')}
  if p.get('status')=='solved' and p.get('start_time') is not None and p.get('finish_time') is not None:
    tsec=int(p['finish_time'])-int(p['start_time'])
    item['time_sec']=tsec
    item['time']=fmt(tsec)
  hist['problems'].append(item)

os.makedirs(history_dir, exist_ok=True)
name=time.strftime('%Y-%m-%d-%H-%M', time.localtime(end_time)) + '.json'
out_path=os.path.join(history_dir, name)
with open(out_path, 'w', encoding='utf-8') as f:
  json.dump(hist, f, ensure_ascii=False, indent=2)

try:
  os.remove(state_path)
except FileNotFoundError:
  pass

print(f"Saved history: {out_path}")
PY
  exit 0
fi

# Run tests
FIRST_WRONG=""
TOTAL=0
for in_file in "$TESTS_DIR"/*.in; do
  if [[ ! -f "$in_file" ]]; then
    continue
  fi
  TOTAL=$((TOTAL+1))
  base="$(basename "$in_file" .in)"
  expected="$TESTS_DIR/$base.out"
  actual="$RUN_DIR/$base.out"

  set +e
  "$EXE" < "$in_file" > "$actual"
  RUN_RC=$?
  set -e
  if [[ $RUN_RC -ne 0 ]]; then
    FIRST_WRONG="$(basename "$in_file") (runtime error)"
    break
  fi

  OK="$(EXPECTED="$expected" ACTUAL="$actual" $PYTHON_BIN "${PYTHON_ARGS[@]}" - <<'PY'
import os, sys
exp=os.environ['EXPECTED']
act=os.environ['ACTUAL']
try:
  eb=open(exp,'rb').read()
  ab=open(act,'rb').read()
  sys.stdout.write('1' if eb==ab else '0')
except FileNotFoundError:
  sys.stdout.write('0')
PY
)"

  if [[ "$OK" != "1" ]]; then
    FIRST_WRONG="$(basename "$in_file")"
    break
  fi
done

if [[ "$TOTAL" -eq 0 ]]; then
  echo "No .in tests found in $TESTS_DIR" >&2
  exit 1
fi

NOW_EPOCH="$($PYTHON_BIN "${PYTHON_ARGS[@]}" - <<'PY'
import time
print(int(time.time()))
PY
)"

if [[ -z "$FIRST_WRONG" ]]; then
  echo "ACCEPTED (score +10)"
  STATUS="solved"
else
  echo "WRONG ANSWER (score 0) - first failing test: $FIRST_WRONG"
  STATUS="failed"
fi

export PID
export STATUS
export NOW_EPOCH

# Update round.json for this problem
$PYTHON_BIN "${PYTHON_ARGS[@]}" - <<'PY'
import json, os
path=os.environ['STATE_PATH']
pid=os.environ['PID']
idx=int(os.environ['PROBLEM_INDEX'])
status=os.environ['STATUS']
now=int(os.environ['NOW_EPOCH'])
with open(path,'r',encoding='utf-8') as f:
  data=json.load(f)
p=data['problems'][idx]
if p.get('id')==pid:
  if p.get('start_time') is None:
    p['start_time']=now
  p['finish_time']=now
  p['status']=status
with open(path,'w',encoding='utf-8') as f:
  json.dump(data,f,ensure_ascii=False,indent=2)
PY

# If all finished -> write history and clear round.json
$PYTHON_BIN "${PYTHON_ARGS[@]}" - <<'PY'
import json, os, time
state_path=os.environ['STATE_PATH']
history_dir=os.environ['HISTORY_DIR']

def fmt(sec: int) -> str:
  sec = max(0, int(sec))
  m, s = divmod(sec, 60)
  return f"{m:02d}:{s:02d}"

with open(state_path,'r',encoding='utf-8') as f:
  data=json.load(f)

problems=data.get('problems',[])
all_done=all(p.get('status') in ('solved','failed') for p in problems)

# Print score (solved * 10)
score=sum(10 for p in problems if p.get('status')=='solved')
print(f"Score: {score}")

if not all_done:
  raise SystemExit(0)

start_time=int(data.get('start_time') or int(time.time()))
end_time=int(time.time())

total_sec = end_time - start_time

hist={
  'start_time': start_time,
  'end_time': end_time,
  'total_time_sec': total_sec,
  'total_time': fmt(total_sec),
  'problems': []
}

for p in problems:
  item={'id': p.get('id'), 'status': p.get('status')}
  if p.get('status')=='solved' and p.get('start_time') is not None and p.get('finish_time') is not None:
    tsec=int(p['finish_time'])-int(p['start_time'])
    item['time_sec']=tsec
    item['time']=fmt(tsec)
  hist['problems'].append(item)

os.makedirs(history_dir, exist_ok=True)
name=time.strftime('%Y-%m-%d-%H-%M', time.localtime(end_time)) + '.json'
out_path=os.path.join(history_dir, name)
with open(out_path, 'w', encoding='utf-8') as f:
  json.dump(hist, f, ensure_ascii=False, indent=2)

# Clear active round
try:
  os.remove(state_path)
except FileNotFoundError:
  pass

print(f"Saved history: {out_path}")
PY
