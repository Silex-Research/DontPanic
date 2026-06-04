---
name: test-runner
description: Runs the targeted test suite.
invocation:
  mode: auto_safe
  lifecycle_stages: [implementation, review]
  required_inputs: [test_path]
  risk_flags: []
  evidence_target: evidence/test-output.txt
  command_template: pytest -q
---
Bounded, read-only-by-effect test execution.
