# external_refs contract — sync state machine + retry semantics

Plan: 2026-05-20-001-infra-external-integrations-bridge-v0 (F002)
Schema: agent-conventions plan.schema.json v1.10.0
Code: `scripts/dontpanic_orchestrate/external_refs_sync.py`
Evidence: `evidence/external_sync.json` (per plan)

## 1. Frontmatter shape

A plan may declare zero or more outbound integration pointers via the
optional `external_refs[]` frontmatter array. Each entry is:

```yaml
external_refs:
  - kind: pm_issue                       # category tag; v0 ships pm_issue only
    uri: linear://issue/ABC-123          # <scheme>://<entity_type>/<id>
    sync: push_status                    # one of: none | push_status
```

Schema constraints (enforced at parse time by the Pydantic `ExternalRef`
model in `claude/shared/schemas/v1.0/models/plan_model.py`):

- `kind` is a closed enum (`pm_issue`); other values are rejected.
- `uri` matches `^[a-z][a-z0-9_-]*://[a-z_]+/[A-Za-z0-9._-]+$`. The
  scheme MUST match a registered category-adapter wrapper's
  `uri_scheme` (e.g. `linear` → Linear PM-tool wrapper).
- `sync` is `none` (informational pointer; never written outbound) or
  `push_status` (plan close pushes DontPanic status flip outbound).

Plans without an `external_refs:` block validate unchanged; the field
is strictly additive.

## 2. Lifecycle hooks

```
                ┌──────────────────┐
plan.md ───────►│ dontpanic plan   │  validate_refs_for_lock(...)
                │ lock             │      • read_issue per ref (cached)
                └────────┬─────────┘      • push_status + unreachable → BLOCK
                         │                • none + unreachable → tolerated
                         ▼
                ┌──────────────────┐
                │ dontpanic plan   │  run_close_push(...)
                │ close [--dry-run]│      • push_status → adapter.push_status
                └────────┬─────────┘      • dry-run → PENDING (no vendor call)
                         │                • failures NEVER block close
                         ▼
                evidence/external_sync.json
                         ▲
                ┌────────┴─────────┐
                │ dontpanic plan   │  run_resync(...)
                │ resync <plan-id> │      • replays failed | pending
                └──────────────────┘      • pushed | skipped untouched
```

### 2.1 `plan lock`

Calls `validate_refs_for_lock(loaded.external_refs, resolver)`:

| ref.sync       | adapter reachable | adapter unreachable | no adapter registered |
| -------------- | ----------------- | ------------------- | --------------------- |
| `none`         | cache `read_issue`| tolerated (no block)| tolerated (no block)  |
| `push_status`  | cache `read_issue`| BLOCK loud          | BLOCK loud            |

A `read_issue` result is cached in a session-scoped per-URI dict so
repeat locks within the same process never re-hit the vendor. Tests
clear via `reset_read_cache()`.

### 2.2 `plan close [--dry-run]`

Calls `run_close_push(loaded.external_refs, resolver, plan_dir,
dry_run=...)`. Per acceptance #4, EVERY ref produces exactly one
durable `ExternalSyncRecord` in `evidence/external_sync.json`:

| ref.sync       | path                 | result status | adapter.push_status called? |
| -------------- | -------------------- | ------------- | --------------------------- |
| `none`         | (skip outbound)      | `skipped`     | NO                          |
| `push_status`  | dry_run=True         | `pending`     | NO  (acceptance #5)         |
| `push_status`  | dry_run=False, ok    | `pushed`      | YES                         |
| `push_status`  | dry_run=False, raise | `failed`      | YES (failure captured)      |
| `push_status`  | no adapter           | `failed`      | NO                          |

Failures NEVER raise — they appear as `status='failed'` records so the
close path stays unblocked. Multiple refs produce a multi-element array
with mixed statuses; partial failures DO NOT block plan close (acceptance
#4 explicit clause).

`--dry-run` constructs PENDING records directly without invoking
`push_status`. The pending record's `response` field carries
`{"uri": "<ref_uri>", "intended_status": "<status>"}` so operators see
the intended outbound payload before committing.

### 2.3 `plan resync <plan-id>`

Reads `evidence/external_sync.json`, retries any entry with
`status ∈ {failed, pending}` via the category adapter, leaves
`{pushed, skipped}` entries untouched (idempotent — acceptance #6).
Each retry produces a fresh record that replaces the prior entry at the
same URI; the file is rewritten as a complete snapshot.

## 3. ExternalSyncRecord shape

Defined in `dontpanic_orchestrate.integrations.pm_tool_sync` and
re-exported from `dontpanic_orchestrate.plan_loader`:

```python
class ExternalSyncRecord(BaseModel):
    ref_uri: str                       # the external_ref.uri attempted
    kind: str                          # mirrors external_ref.kind
    attempted_at: datetime             # tz-aware UTC
    status: ExternalSyncStatus         # pending | pushed | failed | skipped
    intended_status: PMStatus | None   # the DontPanic-side status the push tried to write
    response: dict | None              # adapter payload on PUSHED, intended payload on PENDING
    error: str | None                  # human-readable summary on FAILED
```

The model is `extra='forbid'` + `frozen=True` — every field is
load-bearing, no slack room for ad-hoc keys, and the record is
immutable once constructed. Tokens / vendor secrets MUST be sanitized
by the adapter before the record is built (the model carries no
sanitization itself).

## 4. State machine

```
            ┌─────────┐
            │ PENDING │ ◄── dry-run preview; queued for real push
            └────┬────┘
                 │ resync (push_status)
                 ▼
            ┌─────────┐
   ┌────────│ PUSHED  │ ◄── terminal success
   │        └─────────┘
   │             ▲
   │             │ retry (push_status succeeds)
   │             │
   │        ┌─────────┐
   │        │ FAILED  │ ◄── adapter raised; resync may retry
   │        └─────────┘
   │
   │        ┌─────────┐
   └────────│ SKIPPED │ ◄── ref.sync=none; never written outbound
            └─────────┘
```

- `PUSHED` and `SKIPPED` are terminal: `run_resync` does NOT touch them.
- `FAILED` and `PENDING` are retryable: `run_resync` replays via
  `push_status`. A successful replay flips the record to `PUSHED`; a
  repeat failure produces a fresh `FAILED` record (clock-stamp +
  error-string refreshed).
- A `PENDING` record persists between `plan close --dry-run` and a
  later `plan resync` — operators can preview, then promote, without
  re-running close.

## 5. Retry semantics

Retries are idempotent in the sense that:

1. Already-pushed records survive any number of `resync` invocations
   without re-hitting the vendor.
2. A failed record replayed against an already-pushed PM-tool entity
   is the wrapper's responsibility to handle gracefully (the bridge
   does not deduplicate at the wrapper boundary; that's a per-vendor
   contract).
3. `evidence/external_sync.json` is a snapshot, not an append log; each
   `close` / `resync` rewrites the file. The audit trail lives in
   `git log evidence/external_sync.json`.

## 6. Failure surfaces — what to do when

| Surface                             | Action                                           |
| ----------------------------------- | ------------------------------------------------ |
| `lock` blocks on push_status ref    | Fix URI, drop to `sync: none`, or register adapter |
| `close` writes `status='failed'`    | Inspect `error` field, then run `plan resync`    |
| `close --dry-run` shows wrong status| Adjust intended status mapping in adapter        |
| `resync` repeatedly produces failed | Likely vendor outage; check upstream status page |

## 7. Code references

- Schema: `claude/shared/schemas/v1.0/plan.schema.json` — `external_refs[]` array
- Pydantic: `claude/shared/schemas/v1.0/models/plan_model.py` — `ExternalRef`, `ExternalRefKind`, `ExternalRefSync`
- Loader: `scripts/dontpanic_orchestrate/plan_loader.py` — `LoadedPlan.external_refs`, re-exports `ExternalSyncRecord` + `ExternalSyncStatus`
- Sync layer: `scripts/dontpanic_orchestrate/external_refs_sync.py` — `validate_refs_for_lock`, `run_close_push`, `run_resync`
- Adapter contract: `scripts/dontpanic_orchestrate/integrations/pm_tool_sync.py` — `PMToolSyncHook` Protocol, `ExternalSyncRecord`
- Adapter registry: `scripts/dontpanic_orchestrate/integrations/adapter_registry.py` — operator-config-driven resolver bootstrap
- Tests: `scripts/dontpanic_orchestrate/tests/test_external_refs_sync_f002.py` — ≥12 cases including failure paths
