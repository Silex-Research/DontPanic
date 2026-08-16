#!/bin/bash
# Run a DontPanic eval suite: regression (gates) or capability (never gates).
set -euo pipefail

SUITE="${1:-regression}"
if [[ "$SUITE" != "regression" && "$SUITE" != "capability" ]]; then
  echo "usage: $0 regression|capability" >&2
  exit 2
fi

export PYTHONPATH="${PYTHONPATH:-}:scripts"
if [[ -x .venv/bin/python ]]; then
  PYTHON=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
else
  echo "python3 required" >&2
  exit 1
fi
"$PYTHON" - <<PY
import json, sys
from pathlib import Path
from dontpanic_orchestrate.smoke.suites import run_capability, run_regression

suite = "${SUITE}"
run = run_regression(execute=True) if suite == "regression" else run_capability(execute=True)
out = Path("eval-${SUITE}.json")
out.write_text(json.dumps(run.to_dict(), indent=2) + "\\n")
print(run.text, end="")
print(f"report: {out}")
sys.exit(run.exit_code)
PY
