---
name: github-pr
description: Opens or updates a GitHub pull request.
invocation:
  mode: approval_required
  lifecycle_stages: [review]
  required_inputs: [branch]
  risk_flags: [external_writes, network_access]
---
External write to GitHub; approval required.
