# Plan 2026-05-02-002 close-out memo — audit envelope filename includes feature_id (forward-only)

**Plan ID:** `2026-05-02-002-fix-audit-envelope-filename`
**Type:** `fix` · **Tier:** `local` · **agents:** `claude` + `codex`
**goal_type:** none declared (exempt-by-absence from F2 completion gate)
**Status flip:** `active` → `completed` on 2026-05-07 (UTC).

This memo synthesizes across F001 (single feature) and answers the operator-named filename-Q. The existing `evidence/closeout-memo.md` (impl-time F001 memo, 2026-05-02) is byte-untouched; this memo adds plan-level synthesis + filename-Q narrow answer + cross-plan deferred-finding resolution + non-claims list per close-out framing.

## Filename-Q (operator-named, central correctness claim)

> Does the plan make audit envelope filenames collision-resistant across feature/role/iteration without changing the schema identity of the audit envelope itself?

**Answer: yes — at the writer/callsite/test boundary only.** Verified at three levels:

| Property | Verified by |
|---|---|
| Filename now includes `feature_id` | `audit_writer.py:435` — `def write(audit, plan_dir, *, feature_id: str)`; filename construction at line 438+: `{agent}-{role}-{feature_id}-i{n}.json` |
| Collision-free across feature/role/iteration | F001 acceptance #3 + tests `test_collision_free_two_features_one_plan` + `test_collision_free_two_features_via_supervisor` |
| `feature_id` regex-validated at write boundary | `^F\d{3}$` matching `agent-conventions/schemas/v1.0/features.schema.json` regex (D002 — sanitization at write boundary, no raw strings in paths) |
| Schema identity (Audit pydantic model + `audit_id` payload field semantics) unchanged | D001 explicit: "Filename uniqueness fixed; **audit_id payload identity is unchanged legacy and deferred**" — no schema bump, no Audit model change, no envelope content change |
| Forward-only — old-pattern envelopes still readable | F001 acceptance #4 + `test_old_pattern_envelope_remains_readable` using a real Plan 2026-05-01-005 envelope as fixture; supervisor consumes audit envelopes as `list[Path]` accumulated during dispatch (not via filename glob) — old-named files unaffected |
| No migration of historical envelopes | Plan 2026-05-02-001's audit/ (e.g. `claude-implementer-i0.json`, no feature_id) still on disk verbatim post-fix; this plan's deliverable is forward-only generation, not retroactive renaming |

The fix is **scoped to filename construction at the writer + dispatch callsites + test fixtures**. The audit envelope's JSON content is byte-identical pre/post; the schema (`audit.schema.json`) is unchanged; the Audit pydantic model is unchanged.

## What this plan deliberately does NOT claim

Per operator framing constraints at close-out:

- ❌ "Audit schema semantics changed." — They didn't. Only the filename on disk changed; the Audit pydantic model + `audit.schema.json` enum/required-field set are byte-identical pre/post. D001 explicitly defers `audit_id` payload identity changes.
- ❌ "Old envelopes were migrated/renamed." — They weren't. Plan 2026-05-02-001 audit/ still has `claude-implementer-i0.json` (no feature_id); same for any other pre-fix plan. Forward-only.
- ❌ "Historical collision evidence was rewritten." — It wasn't. Plan 2026-05-01-005's preserved F002 original-volley envelopes under `evidence/f002/audit-original-volley/` (the very evidence that motivated D013 of that plan, now re-categorized as `audit_json` per Plan 005's D016 schema-conformance repair) remain verbatim. The collision evidence IS the evidence; this plan makes future collisions impossible without erasing the past.
- ❌ "Every conceivable filename-collision scenario is solved." — Only the within-plan multi-feature shape is addressed. Cross-plan collisions are impossible (different `plan_dir/audit/` paths). Same-feature multi-role-multi-iteration collisions are addressed by `{role}-i{n}` part of the existing pattern. Concurrent-dispatch-same-feature races are not in scope (no F005a-shaped concurrency primitive).

## Cross-feature outcome

| Feature | Path | Result |
|---|---|---|
| F001 — `audit_writer.write` requires `feature_id` kwarg, regex-validated; supervisor `dispatch_volley` + `dispatch_single_agent` thread `feature_id` through; 22 tests covering all 12 acceptance clauses incl. old-pattern readability fixture from Plan 005 | **Direct path (no volley)** per D003 — small mechanical writer/callsite/test change with disambiguated locked acceptance | `passes:true`. 22 targeted + 469/6 sweep (was 447 → +22). Ruff + sanitization clean. No volley dispatched per the failure-taxonomy memory's direct-path trigger conditions. |

## Cross-plan deferred-finding resolution

Plan 2026-05-01-005 (target-context-platform-fix, closed `1e06fc3`) deferred D013's "audit envelope filename collision across features within a plan" finding to a follow-up plan. **This plan IS that follow-up.** Plan 005's F002 confirmation volley overwrote F001's i0+i1 envelopes in working tree (workaround: manual copy to `evidence/f002/audit-original-volley/` before F002 dispatched). That manual workaround is now structurally unnecessary going forward — same plan can ship multiple features with feature-distinct envelope filenames without operator paperwork.

Plan 2026-05-01-005's status-flip memo (closed `1e06fc3`) already records this expected resolution path: "Audit-envelope filename collision (D013) — F002's volley overwrote committed F001 envelopes because filenames don't include feature_id. Deferred to Plan 2026-05-02-002 (still active). NOT solved by this plan." That deferred-NOT-solved-here narrative now closes here, at the owning-plan level — without retroactively modifying Plan 005's memo.

## Q2 — terminal-status classification

Trivial for this plan: **no volley dispatched per D003.** The implementation result is what counts. The 22 targeted tests' collision-free + negative + structural-integrity proofs together establish the acceptance contract. Plan 005's preserved volley envelopes serve as the old-pattern readability fixture (`test_old_pattern_envelope_remains_readable`).

No `stopped_no_progress` / `stopped_diminishing_returns` terminal to reclassify; no platform artifact masquerading as implementation defect; no auditor i2 META finding queued.

## Cross-link to closed plans depending on this work

Q1 sweep this turn (3 closed citers, 0 active):

| Citing plan (status) | Citation context |
|---|---|
| `2026-05-01-005-feat-target-context-platform-fix` (closed `1e06fc3`) | D013 deferred this filename-collision finding to a follow-up — **resolved here** |
| `2026-05-02-001-feat-resume-gate-discipline` (closed `bdb4c3e`) | Closeout-memo's non-subsumption list names this plan as the audit-envelope-filename owner of the queued discussion |
| `2026-05-02-003-feat-nested-orchestration-v1` (closed `5ddd6ae`) | plan.md cites this plan in dependency-context narrative |

Closing this plan updates "queued follow-up" → "closed" in those memos' narrative without modifying the memos themselves.

## Brand-rename note (drift forward)

Plan was authored 2026-05-02, **before** the canonical-module flip shipped at `8edd953` (Plan 2026-05-04-001, closed `ab7c7dc`). Therefore:

- **In-plan text** (plan.md, features.json, decisions, F001 memo) references legacy `scripts/jarvis_orchestrate/audit_writer.py` paths.
- **Live code** lives at `scripts/dontpanic_orchestrate/audit_writer.py` post-rename. The legacy `jarvis_orchestrate` shim still re-exports cleanly.
- **AC behavior identical** through the shim. Historical AC text intentionally NOT retro-updated.

Same drift pattern as Plans 2026-05-01-001, 2026-05-01-005, 2026-05-02-001, 2026-05-05-001. Future readers map `jarvis_orchestrate` → `dontpanic_orchestrate` at code-read time.

## What remains separately queued

Per scope discipline:

- **`audit_id` payload identity** — D001 explicitly defers any change to the JSON-internal `audit_id` field (currently uses legacy shape); a future plan that needs cross-plan audit-id uniqueness or content-addressable identity would touch the schema, not the filename. NOT in scope here.
- **Concurrent-dispatch-same-feature races** — out of scope; no F005a-shaped concurrency primitive exists yet to need this protection.
- **Historical envelope migration** — D013 of Plan 005 + this plan's motivation explicitly preserve old envelopes verbatim. If a future tool wants normalized cross-history filenames, that's a read-time view-layer concern (per Plan 005 D007 forward-only normalization principle), not a write-time migration.

## Outer plan close — exempt-flow path

```
$ dontpanic plan close docs/plans/2026-05-02-002-fix-audit-envelope-filename/
[plan close] goal_type=None is exempt from the F2 completion gate;
             status flipped active → completed without audit
```

Same exempt-flow path as the prior thirteen close-outs in this session.

## Sign-off

Plan 2026-05-02-002 ships clean. F001 `passes:true`. The audit envelope filename now includes `feature_id` regex-validated at the write boundary; collision-free across (feature, role, iteration); old-pattern envelopes remain readable verbatim; Audit schema identity is unchanged; no historical files renamed or migrated. The filename-Q answer is narrowly scoped to the writer/callsite/test boundary — schema semantics and historical evidence both preserved. Plan 2026-05-01-005's D013 deferred finding is closed at the owning-plan level without retroactively modifying that plan's historical memo.

— bayesian, 2026-05-07 UTC
