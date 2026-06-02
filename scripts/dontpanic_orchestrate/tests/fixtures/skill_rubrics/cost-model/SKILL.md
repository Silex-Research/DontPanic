---
name: cost-model
description: Computes projected token/cost model from local data.
invocation:
  mode: auto_readonly
  lifecycle_stages: [planning]
  required_inputs: []
  risk_flags: []
  evidence_target: evidence/cost-model.json
  command_template: dontpanic skills run cost-model
---
Pure local computation over recorded usage.
