# Plan F1 close-out memo

**Plan ID:** `2026-05-05-003-feat-objective-contract-and-sufficiency-audit`
**Sequence position:** Goal Governance V1 / F1 (per `docs/GOAL_GOVERNANCE_V1.md` §9)
**Status flip:** `active` → `completed` on 2026-05-05
**Lock checkpoint:** `5761850` (5 features locked, 13 decisions D001–D013 at lock time)

## What F1 shipped

The first half of goal-completion governance:

1. **Objective-contract schema** (cross-repo, agent-conventions v1.4.0) — `goal_type` + `links.objective_contract` on Plan, `ObjectiveContract` model with user_journeys / completion_test / required_evidence / non_goals.
2. **Pre-impl sufficiency auditor** (DontPanic, text-only) — walks the contract against features.json, surfaces gap-class findings (coverage / missing_feature / wiring / parity / integration).
3. **Plan-lock sufficiency gate + dispatch backstop** — `dontpanic plan lock` CLI subcommand, supervisor wiring catches hand-edited locks, durable input-bound override (`--ignore-sufficiency-findings <reason>`), medium+ blocking threshold.
4. **Gating dogfood proof point** — Spin & Dine (parity) + Glam (integrated product surface) curated static fixtures; both confirmed PASS by operator under D010 strengthened gating.

Plan F2 (post-impl completion test + journey-walk auditor) is the next chunk in the Goal Governance V1 sequence; not part of F1.

## Five feature commits

| Feature | Commit | Boundary | Tests |
|---|---|---|---|
| F001 | `d5bab1b` (in `agent-conventions` repo, tag `v1.4.0`) | Schema/model/validator additive bump | 7 new dispatch fixtures + 4 Plan E regression — all green |
| F002 (import) | `7f1d354` + `08e2b26` | DontPanic subtree-pull squash + merge | n/a — mechanical import |
| F002 (close-out) | `842e72c` | features.json flip + D014 + 3 evidence files | 997 → 997 (zero deltas; backward compat verified) |
| F003 | `dc7d212` | sufficiency_auditor.py module + 22 tests + D015 | 997 → 1019 (+22, zero regressions) |
| F004 | `56db292` | sufficiency_gate.py module + plan lock CLI subcommand + supervisor backstop + 33 tests + D016 | 1019 → 1052 (+33, zero regressions) |
| F005 | `265c7ec` | curated dogfood fixtures + auditor outputs + dispositions + D017 | 1052 (no test changes; only fixture files) |

All commits local-only; no remote pushes. Cross-repo boundary preserved across F001 → F002 → F003 → F004 → F005 (D009 — F001 in agent-conventions, F002–F005 in DontPanic).

## Final verification numbers (post-F005)

| Check | Result |
| --- | --- |
| Cumulative orchestrate suite | **1052 passed, 6 skipped** (= 997 F002 baseline + 22 F003 + 33 F004; F005 added no tests) |
| `claude/shared/VERSION` | `1.4.0` |
| Subtree byte-equal vs upstream | ✓ (verified at F002 close-out, no changes since) |
| F1 plan validates against agent-conventions v1.4.0 | ✓ |
| Both dogfood fixtures validate | ✓ (both `objective_contract.json` + features envelope clean) |
| `ruff check` + `ruff format --check` (full F1 surface) | ✓ clean |
| `python3 scripts/sanitization_check.py` | ✓ 0 findings |
| Cross-repo boundary (D009) | ✓ F001 in agent-conventions; F002–F005 in DontPanic |
| Project-agnostic invariant (D013) | ✓ zero F1-introduced changes under `scripts/dontpanic_orchestrate/` reference project names; no top-level `dogfood/` directory; project names appear only in fixture content + close-out evidence |

## D010 gating dogfood — SATISFIED

D010 wording (strengthened at F1 lock): *"F1 close-out fails unless the sufficiency auditor surfaces at least one materially correct gap class for Spin & Dine **and** at least one materially correct gap class for Glam."*

**Spin & Dine half: PASS (confirmed 2026-05-05).**
- Target gap class: parity matrix incompleteness.
- Auditor surfaced 7 findings (3 high + 4 medium); operator confirmed 7/7 materially correct.
- Cited contract-backed gaps absent from features.json: offline voting path (`no_network_cached` + `no_network_uncached_error`), pro_grace_period (16-day buffer), returning_user_fast_path (saved-radius bypass), shared-list read-only state, no-results-after-relaxation, purchase failure UX, Pro tier voice/family delta.

**Glam half: PASS (confirmed 2026-05-05).**
- Target gap class: integrated Creator Hub journey-coverage (cross-feature integration concern, not just per-feature completeness).
- Auditor surfaced 8 findings (3 high incl. 1 integration_gap + 2 missing_feature; 5 medium); operator confirmed 8/8 materially correct.
- Cited gaps: preview journey entirely absent, post-edit journey entirely absent, no end-to-end create → edit → preview → publish → analytics → drill-down → profile acceptance, analytics drill-down wiring, publish fanout-pending UX, analytics stale state, impression-tracker init wiring, cross-device draft-resume SLO.

D010 is **SATISFIED on both halves**. Per the locked failure-response priority (sufficiency prompt → schema → decomposition), no revisions are required for v1; both PASS dispositions cite optional polish recommendations that are queued for future demand-driven evolution.

## Cross-vendor caveat (recorded)

F005 dogfood ran with `DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR=1` set — Claude served as both implementer and auditor. Acceptable for F005 dogfood specifically because it is operator-judged, not adversarial review, and the operator's confirming pass acted as the second-vendor sanity check on the artifacts. In production use of `run_sufficiency_audit()`, the cross-vendor invariant (D006 / Goal Governance V1 §5) re-engages by default — auditor will be Codex (per `project_config.resolve_dispatch_defaults`) when implementer is Claude.

A follow-up plan should wire a real cross-vendor dispatcher into F003's `dispatch=` seam once production wiring is needed, and re-run a dogfood pass to confirm the prompt + schema generalize across vendors.

## Signoff envelope decision

The formal `audit/signoff-*.json` envelope (`claude/shared/schemas/v1.0/signoff.schema.json`) is shaped for auditor-volley reconciliation: required `audits[]` minItems=1 of paths to audit JSONs, vote_summary tallies, reconciliation block. F1 close-out is operator-driven (no auditor volley at the plan level — only per-feature pytest + ruff + sanitization), so a formal signoff envelope would be a square-peg-round-hole. This plan-level close-out memo is the load-bearing artifact instead.

Per-feature evidence is in:
- `evidence/f002-closeout-memo.md`
- `evidence/f003-closeout-memo.md`
- `evidence/f004-closeout-memo.md`
- `evidence/f005-closeout-memo.md`

Plus the F002-specific validator output captures (`f002-baseline-validator-output.txt` + `f002-post-pull-validator-output.txt`) and the F005 dogfood evidence tree (`evidence/dogfood/`, `evidence/{spin-and-dine,glam}-{auditor-prompt.txt,sufficiency-findings.json,disposition.md}`).

## Decisions captured during F1

D001–D013 at lock checkpoint (locked 2026-05-05). Close-out additions:
- **D014** — F002 close-out (DontPanic subtree-pull v1.4.0 + regression sweep)
- **D015** — F003 close-out (sufficiency auditor module shipped, lock enforcement deferred to F004)
- **D016** — F004 close-out (plan-lock gate + locked threshold + input-bound override + mutating lock command)
- **D017** — F005 close-out (gating dogfood proof point; both fixtures PASS; D010 satisfied)

D018 records this plan-level close-out (status flip + verification numbers + plan-level summary).

## Boundary preservation across F1

- **D009 cross-repo boundary:** F001 lives in agent-conventions (`d5bab1b`, tag `v1.4.0`); F002–F005 live in DontPanic (`7f1d354` + `08e2b26` + `842e72c` + `dc7d212` + `56db292` + `265c7ec`). No commit touches the other repo.
- **D013 project-agnostic invariant:** zero F1-introduced project-name special cases in DontPanic product code (`scripts/dontpanic_orchestrate/`). All project names confined to F005 fixture content + close-out evidence files.
- **F1 plan dir scope:** every F1 commit's diff is confined to either `claude/shared/**` (F002 only — the subtree pull boundary) or `scripts/dontpanic_orchestrate/**` (additive only — never touches existing modules outside the F003/F004 wiring) or the F1 plan dir itself.

## Queued for the next motion (Plan G)

Plan G drafting is the next queued step **outside this commit**. Plan G is the post-impl half of Goal Governance V1 (per the sequence in `docs/GOAL_GOVERNANCE_V1.md` §9 / Plan F0's queued-work):

- F2: post-impl completion-test auditor that walks the contract against shipped patches, runs journey walks, validates required_evidence.
- Plan G: integration-audit + acceptance-evidence layer (the third Goal Governance V1 plan).
- Plan H: continuous post-impl re-evaluation loop (after Plan G ships).

This commit does NOT touch Plan G. Drafting it stays its own turn-by-turn motion, gated on operator approval.

## Plan F1 final state

- **Status:** `completed`
- **All 5 features:** `passes: true`
- **All cross-cutting boundaries (D009, D013):** preserved
- **Tests:** 1052 passed, 6 skipped (zero regressions)
- **Tooling:** ruff + sanitization clean, validator clean
- **Plan-level signoff (operator-driven, this memo):** PASS on 2026-05-05

F1 closes the first half of Goal Governance V1. The pre-impl sufficiency layer is shipped and dogfood-proven; lock-time refusals work; cross-vendor invariant is in place by default with an audit-trailed override path. Plan F2 takes over for post-impl completion testing.
