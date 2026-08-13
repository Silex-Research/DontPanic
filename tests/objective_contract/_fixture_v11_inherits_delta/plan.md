---
id: 9999-12-31-012-fix-fixture-v11-inherits-delta
title: Fixture — v1.1 fix plan inheriting a parent outcome
type: fix
tier: local
status: active
date: "9999-12-31"
schema_version: "1.1"
description: |
  Validator fixture for the optional contract-level inherits pointer: a fix
  plan that deltas a parent's outcome with ONE slice instead of restating the
  parent's full set. See scripts/test_objective_contract.py for the assertion.
goal_type: infra
links:
  objective_contract: ./objective_contract.json
---

## Target

```yaml
target_env: dev
target_project: none
```
