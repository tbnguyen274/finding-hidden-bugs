#!/usr/bin/env bash
set -euo pipefail

# judge/next.sh
# Move to the next pending problem.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_PATH="$ROOT/state/round.json"

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

RESULT="$($PYTHON_BIN "${PYTHON_ARGS[@]}" - <<'PY'
import json, os

path = os.environ['STATE_PATH']
with open(path, 'r', encoding='utf-8') as f:
  data = json.load(f)

problems = data.get('problems', [])
cur = int(data.get('current_problem', 0))

next_idx = None
for i in range(cur + 1, len(problems)):
  if problems[i].get('status') == 'pending':
    next_idx = i
    break

if next_idx is None:
  # Try from beginning
  for i in range(0, len(problems)):
    if problems[i].get('status') == 'pending':
      next_idx = i
      break

if next_idx is None:
  print('DONE')
else:
  data['current_problem'] = next_idx
  with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
  print(problems[next_idx].get('id',''))
PY" )"

if [[ "$RESULT" == "DONE" ]]; then
  echo "No pending problems left."
  exit 0
fi

echo "Current problem: $RESULT"
