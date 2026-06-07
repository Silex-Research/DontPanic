# operator-triage/v0 — F001 additive fields (contract note)

Plan 2026-06-06-004 F001. Additive extension of `operator-triage/v0` (no field renamed
or removed; CLI `operator brief` / `triage apply`, the agent brief, and the dashboard all
keep working). Producer: `scripts/dontpanic_orchestrate/operator_triage.py::build_triage`.

| Field | Type | Derivation | Render-truth / honesty rule |
|---|---|---|---|
| `resolution` | `string[]` | `resolution_for(bucket, exact_command)` — enumerated per bucket; `agent_runnable` → `["run"]` iff a command exists else `[]` | **Intents, not executable commands.** Names the operator's available resolution *intents*; renderers MUST map intents through the governed affordance/action layer (F003/F005) — never infer enabled/executable buttons from the strings alone. Closed vocab: approve · request_changes · reject · guided_setup · apply_fix · inspect · run |
| `asserted_at` | `string \| null` | the item's `updated_at` | The assertion's age, not a freshness proof. Null when the producer has no timestamp — never fabricated. |
| `freshness_basis` | `"live_supervisor_plan_match" \| "item_probe" \| null` | `"live_supervisor_plan_match"` when a live supervisor is joined to the item's plan (run_state ∈ {running, conflicted}); else `null` | **The basis for any freshness claim — never overstated.** A live supervisor proves the *plan* is live, NOT that this item/finding is current, so v0 only ever emits the plan-level basis or null. `"item_probe"` (item-level proof) is RESERVED — no v0 producer emits it. **RENDER CONTRACT: the filled freshness dot is reserved for `"item_probe"`.** Plan-level liveness drives the weaker, distinct run_state "running" signal — never the trust dot. In v0 the freshness dot is therefore hollow everywhere. |
| `provenance_source` | `string \| null` | first of `provenance_source` / `source` / `producer` / `produced_by` | A machine-joinable producer id; `actor_label` stays the human display name. Null when unknown — never a fabricated id. |

**Why `freshness_basis` and not a `proven_live` boolean** (review fix, D003): an earlier cut
emitted `proven_live = run_state ∈ {running, conflicted}`. That boolean conflates *plan-level*
liveness with *item-level* freshness — a renderer could fill the trust dot from it and
overstate how current a specific finding is. Replacing it with a typed *basis* makes the
distinction explicit and impossible to mislabel: the dashboard keys the filled dot on
`freshness_basis == "item_probe"`, which is never set in v0, so it cannot fake confidence.

**Parity:** every field above is read identically by the three renderers (verified: the agent
brief now carries them via `operator_brief._ITEM_FIELDS`). The F007 freshness grammar consumes
`freshness_basis`; the F003 resolution affordances consume `resolution` (as intents, mapped
through the action layer).
