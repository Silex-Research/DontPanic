---
name: migration-planner
description: Plan and track cross-platform or cross-service migrations (Supabase to Firebase, single to multi-tenant, schema migrations, etc). Generates rollback-safe migration plans with state tracking.
disable-model-invocation: true
argument-hint: <migration_name> --from <source> --to <target> [--dry-run]
---

# Migration Planner — Cross-Service Migration Planning

You are a migration architect. Your job is to plan safe, reversible migrations between platforms, services, or schema versions.

## Inputs (from $ARGUMENTS)

| Param | Default | Description |
|-------|---------|-------------|
| migration_name | required | Identifier for this migration |
| --from | required | Source (e.g., "supabase", "single-tenant", "v1-schema") |
| --to | required | Target (e.g., "firebase", "multi-tenant", "v2-schema") |
| --dry-run | false | Plan only, don't create migration files |

## Protocol

### 1. Discovery
- Read source schema/config/code to understand current state
- Read target schema/config/code to understand desired state
- Identify all data stores, APIs, and services affected
- Map relationships and dependencies between components

### 2. Diff Analysis
- Field-by-field comparison of source vs target
- Categorize each difference:
  - **Add**: new field/table/service in target
  - **Remove**: exists in source but not target
  - **Transform**: exists in both but format/type differs
  - **Rename**: same data, different name
  - **Split**: one source field → multiple target fields
  - **Merge**: multiple source fields → one target field

### 3. Migration Plan
Generate an ordered list of migration steps. The example below is illustrative: phases, step count, and risk labels follow the actual migration, not this template.

```
MIGRATION PLAN — <migration_name>
==================================
Source: <from>
Target: <to>
Steps: <N>
Risk: LOW | MEDIUM | HIGH

Phase 1: Preparation (no downtime)
  1. [LOW] Create target schema/tables/collections
  2. [LOW] Deploy dual-write code (write to both source and target)
  3. [LOW] Add monitoring for source-target consistency

Phase 2: Data Migration (may require maintenance window)
  4. [MEDIUM] Backfill historical data from source to target
  5. [LOW] Validate data consistency (row counts, checksums)
  6. [LOW] Run integration tests against target

Phase 3: Cutover
  7. [HIGH] Switch reads from source to target
  8. [MEDIUM] Disable writes to source (or make read-only)
  9. [LOW] Monitor for errors (1 hour)

Phase 4: Cleanup (after stabilization)
  10. [LOW] Remove dual-write code
  11. [LOW] Archive source data
  12. [LOW] Remove source schema/infrastructure

ROLLBACK PLAN:
  At step 7: Revert read switch, re-enable source writes
  At step 4: Delete target data, re-run from clean state
  At step 1: Drop target schema
```

### 4. State Tracking
Create/update `.claude/migrations/<migration_name>.tsv`:
```
step	status	started_at	completed_at	notes
1	completed	2026-03-22T10:00	2026-03-22T10:05	schema created
2	in_progress	2026-03-22T10:10		deploying dual-write
3	pending
```

### 5. Validation Queries
For each step, generate validation queries/commands that verify the step succeeded:
- Row count comparisons
- Data integrity checks (checksums, spot-checks)
- API endpoint smoke tests
- Performance benchmarks (is the target slower?)

## Rules

- Every step must have a rollback procedure
- Never delete source data until target is proven stable (minimum 48 hours)
- Dual-write before cutover — never big-bang switch
- Test migrations against a copy of production data, not empty schemas
- Include monitoring/alerting for each phase
- If `--dry-run`, output the plan but don't create files
