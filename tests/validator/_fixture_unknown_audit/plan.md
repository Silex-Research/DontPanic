---
id: 9999-12-31-004-fix-fixture-unknown-audit
title: Fixture — unknown audit JSON dispatch
type: fix
tier: cross-cutting
status: active
date: "9999-12-31"
description: |
  Validator fixture covering the v1 unknown-audit-JSON warn-and-skip
  policy (D005). The validator emits a clear ⚠ info-line but does NOT
  increment the error count.
---

## Target

```yaml
target_env: dev
target_project: none
```
