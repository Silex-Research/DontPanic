# Validation record

Base: afd692d344d6ccadedb61178897b37510df436e5, Python 3.11.16.
Dependencies: uv sync --locked --python 3.11 --extra dev --extra firebase.

Baseline before runtime edits: 6533 passed, 9 skipped in 541.78s.
Command: GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=commit.gpgsign
GIT_CONFIG_VALUE_0=false .venv/bin/python -m pytest scripts/dontpanic_orchestrate/tests -q
This process-only signing override mirrors CI's synthetic-repository behavior.

New public entrypoint probes before the integration fixes: 2 failed, 3 passed.
The failures were the missing goal-only skill advisory and missing doctor flag.

After integration, the new entrypoint tests and surrounding doctor, plan-review,
conventions, and runtime-evidence suites: 426 passed, 1 skipped in 61.63s.
The new module additionally checks skip-auth before callback execution and rejects
incompatible doctor modes. No paid agents, cloud capture, or operator credentials
were used. Unrelated doctor checks are stubbed in public-path unit tests; the
registry/import/wiring path itself is live.

Plan schema validation and git diff --check pass. This is local worktree evidence;
required CI and independent review of the eventual PR head are separate gates.
