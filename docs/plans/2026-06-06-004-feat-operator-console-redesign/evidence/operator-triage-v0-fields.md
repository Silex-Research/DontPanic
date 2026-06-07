# operator-triage/v0 — F001 additive fields (contract note)

Plan 2026-06-06-004 F001. Additive extension of `operator-triage/v0` (no field renamed
or removed; CLI `operator brief` / `triage apply`, the agent brief, and the dashboard all
keep working). Producer: `scripts/dontpanic_orchestrate/operator_triage.py::build_triage`.

| Field | Type | Derivation | Render-truth / honesty rule |
|---|---|---|---|
| `resolution` | `string[]` | `resolution_for(bucket, exact_command)` — enumerated per bucket; `agent_runnable` → `["run"]` iff a command exists else `[]` | Derived from existing fields; claims **no new truth**. The human's buttons == the agent's options. Closed vocab: approve · request_changes · reject · guided_setup · apply_fix · inspect · run |
| `asserted_at` | `string \| null` | the item's `updated_at` | Null when the producer has no timestamp — never fabricated |
| `proven_live` | `bool` | `run_state ∈ {running, conflicted}` (a live supervisor confirmed the plan **this build**) | **Defaults `false`.** True only on positive live confirmation; everything else is honestly "asserted (from cache)" → renders the hollow `○ unverified` dot, never full confidence. v0 floor; producers carrying per-source freshness can raise more items later. |
| `provenance_source` | `string \| null` | first of `provenance_source` / `source` / `producer` / `produced_by` | A machine-joinable producer id; `actor_label` stays the human display name. Null when unknown — never a fabricated id. |

**Parity:** every field above is read identically by the three renderers; the redesign's
visual elements (resolution buttons, freshness dot, provenance line) map 1:1 to these. The
F007 freshness grammar and F003 resolution affordances consume them directly.
