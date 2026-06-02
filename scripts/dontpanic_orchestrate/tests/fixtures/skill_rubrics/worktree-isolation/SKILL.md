---
name: worktree-isolation
description: Creates an isolated git worktree.
invocation:
  mode: suggest
  lifecycle_stages: [implementation]
  required_inputs: []
  risk_flags: [repo_mutation]
---
Mutates git state; suggested.
