---
name: browser-use
description: Drives a real browser session.
invocation:
  mode: approval_required
  lifecycle_stages: [implementation]
  required_inputs: [target_url]
  risk_flags: [network_access, external_writes]
---
Networked external interaction; approval required.
