---
name: changelog
description: Generates and writes a CHANGELOG entry.
invocation:
  mode: suggest
  lifecycle_stages: [review]
  required_inputs: [version]
  risk_flags: [repo_mutation]
  evidence_target: CHANGELOG.md
---
Mutates the repo; suggested rather than auto-run.
