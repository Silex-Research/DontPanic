---
id: 9999-12-31-003-fix-fixture-aux-gate-state
title: Fixture — auxiliary gate-state.json dispatch
type: fix
tier: cross-cutting
status: active
date: "9999-12-31"
description: |
  Validator fixture covering the v1 known-auxiliary skip case for
  `gate-state.json`. Pre-fix, the validator would attempt to validate
  this file against the Audit envelope schema and false-fail. Post-fix,
  the validator skips it with a clear info-line.
---

## Target

```yaml
target_env: dev
target_project: none
```
