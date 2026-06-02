---
name: security-review
description: Read-only security review of pending changes.
invocation:
  mode: auto_readonly
  lifecycle_stages: [review]
  required_inputs: [changed_files]
  risk_flags: []
  evidence_target: evidence/security-review.json
  command_template: dontpanic skills run security-review
---
Static review of the current diff. No writes, no network.
