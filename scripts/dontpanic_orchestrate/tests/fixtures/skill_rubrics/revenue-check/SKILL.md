---
name: revenue-check
description: Reads production revenue dashboards.
invocation:
  mode: approval_required
  lifecycle_stages: [planning, review]
  required_inputs: [project_id]
  risk_flags: [credentialed_production_read, network_access]
  evidence_target: evidence/revenue.json
---
Credentialed production read; approval required.
