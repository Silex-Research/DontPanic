---
name: eval-harness
description: Runs an eval suite against model outputs.
invocation:
  mode: approval_required
  lifecycle_stages: [review]
  required_inputs: [eval_dataset]
  risk_flags: [paid, network_access, indefinite_loop]
  evidence_target: evidence/eval-results.json
---
Drives paid model calls in a loop; always gated behind approval.
