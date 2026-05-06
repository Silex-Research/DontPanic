# F005 close-out — gating dogfood proof point

Local-only commit in DontPanic. Hybrid execution mode per the locked execution-mode policy memo: auditor runs through the F003/F004 machinery against curated static fixtures, but the PASS/FAIL judgment lives in the operator-owned dispositions. Dispositions in this commit are drafted by Claude in F005's hybrid role — the operator should review and edit before final close-out.

## Synthetic plan paths (D013 — plan-local, project-agnostic invariant)

| Fixture | Plan dir | Plan ID | Goal type |
|---|---|---|---|
| Spin & Dine | `evidence/dogfood/spin-and-dine/` | `2026-05-05-999-feat-spin-and-dine-android-parity` | `parity` |
| Glam | `evidence/dogfood/glam/` | `2026-05-05-998-feat-creator-hub-v1` | `new_feature` |

Both plan dirs are static, curated fixtures inside this F1 plan's evidence tree. Neither reads from any external repo; both are reproducible from the files committed here. Project names appear only in fixture paths/content + close-out evidence — no top-level `dogfood/` directory was created, and `scripts/dontpanic_orchestrate/` has zero F005-introduced diffs (D013 verified).

## Captured sufficiency findings (F003 machinery + F004 boundary)

| Fixture | Findings file | Total | Blocking (≥medium) | Severity mix |
|---|---|---|---|---|
| Spin & Dine | `evidence/spin-and-dine-sufficiency-findings.json` | 7 | 7 | 3 high + 4 medium |
| Glam | `evidence/glam-sufficiency-findings.json` | 8 | 8 | 3 high + 5 medium |

The auditor prompt for each fixture is preserved at `evidence/{spin-and-dine,glam}-auditor-prompt.txt` for reproducibility.

## Operator dispositions (F005's load-bearing artifact)

| Fixture | Disposition | Verdict |
|---|---|---|
| Spin & Dine | `evidence/spin-and-dine-disposition.md` | **PASS** (confirmed 2026-05-05) — 7/7 findings materially correct |
| Glam | `evidence/glam-disposition.md` | **PASS** (confirmed 2026-05-05) — 8/8 findings materially correct |

**Status: both dispositions CONFIRMED by operator + Codex/operator review on 2026-05-05.** The same-vendor caveat (Claude as both implementer and auditor with `DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR=1`) remains in place — the operator's confirming review served as the second-vendor sanity check over the artifacts. Acceptable for F005 only because dogfood is operator-judged, not adversarial review.

## D010 gate (F1 close-out)

D010 wording: *"F1 close-out fails unless the sufficiency auditor surfaces at least one materially correct gap class for Spin & Dine **and** at least one materially correct gap class for Glam."*

| Half | Gap class verified | Operator-confirmed? |
|---|---|---|
| Spin & Dine | parity matrix incompleteness (offline path, pro_grace_period, returning_user_fast_path) | **YES — confirmed 2026-05-05** |
| Glam | integrated journey-coverage / cross-feature integration concern (preview missing, edit missing, end-to-end product surface) | **YES — confirmed 2026-05-05** |

D010 **satisfied**. F1 close-out's gating dogfood proof point passes; F005 flips `passes: true`. Recorded operator note: "auditor caught the target gap class for both fixtures; the offline voting path, subscription grace period, and returning-user fast path are all contract-backed states/signals absent from the feature decomposition for Spin & Dine; missing preview, missing post-edit, and no end-to-end create → edit → preview → publish → analytics → profile acceptance for Glam — exactly the failure modes F1 exists to catch."

## Caught gap classes (auditor summary, by fixture and finding)

### Spin & Dine (parity)
| ID | Severity | Journey | Class | Anchor in contract |
|---|---|---|---|---|
| 1 | high | onboarding | parity_gap | `returning_user_fast_path` state + acceptance signal |
| 2 | high | restaurant-voting | parity_gap | `no_network_cached` + `no_network_uncached_error` states |
| 3 | high | subscription-ux | parity_gap | `pro_grace_period` state + 16-day buffer signal |
| 4 | medium | saved-lists | parity_gap | `list_detail_shared_readonly` state |
| 5 | medium | restaurant-voting | parity_gap | `no_results_after_relaxation` state |
| 6 | medium | subscription-ux | coverage_gap | `purchase_failed` / Retry CTA signal |
| 7 | medium | subscription-ux | wiring_gap | Pro-tier voice + family-sharing description |

### Glam (new_feature / integrated surface)
| ID | Severity | Journey | Class | Anchor in contract |
|---|---|---|---|---|
| 1 | high | preview | missing_feature | Entire preview journey absent |
| 2 | high | edit | missing_feature | Entire post-edit journey absent |
| 3 | high | publish | integration_gap | completion_test cross-feature flow |
| 4 | medium | analytics | wiring_gap | tile drill-down acceptance signal |
| 5 | medium | publish | wiring_gap | `publish_succeeded_fanout_pending` state |
| 6 | medium | analytics | coverage_gap | `analytics_stale` state + signal |
| 7 | medium | publish | wiring_gap | impression-tracker init signal |
| 8 | medium | create | coverage_gap | cross-device 30s draft-resume SLO |

## Cross-vendor caveat (transparency record)

**Important:** F003's `_resolve_goal_auditor_agent()` enforces a cross-vendor invariant by default (D006 / Goal Governance V1 §5). For F005 dogfood, that invariant was relaxed via the operator-override channel:

```
DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR=1
```

…and Claude served as both implementer (authoring fixtures + dispositions) and auditor (generating findings JSON). The override is recorded here per F003's design ("recorded in close-out evidence by the caller").

This is acceptable for F005 specifically because:
1. F005's load-bearing check is the operator-judged disposition, not adversarial vendor review.
2. F005 tests prompt + schema + decomposition, not vendor-pair adversarial dynamics.
3. The bias risk (Claude finds gaps Claude knew about because Claude wrote the fixtures) is mitigated by the operator review step — the operator's job is to flag findings that look "planted" vs. genuinely material.

In production usage with a wired cross-vendor dispatcher, the auditor would be Codex (per `project_config.resolve_dispatch_defaults` defaults). Future F005 re-runs (or a dedicated dogfood-dispatch test in a follow-up plan) should exercise the Codex path to confirm the prompt + schema generalize across vendors. **Recommendation:** queue a follow-up plan to wire a real cross-vendor dogfood dispatch once F003's `dispatch=` seam has a production wiring (currently F004's lock gate is the only consumer; F004 still requires an explicit dispatcher to be passed in).

## Prompt / schema tuning recommendations

Both dispositions identify the prompt as working correctly — gap classes mapped cleanly, both fixtures surfaced their target gap class. Two optional polish notes:

1. **Prompt:** explicitly instruct the auditor to consider `non_goals` as a valid mitigation for missing acceptance signals. Currently the auditor surfaced the Pro voice/family gap without considering whether it could be a non-goal; the recommendation field handled it gracefully but the prompt could nudge the consideration upfront.
2. **Schema:** ObjectiveContract.user_journeys[*].states is optional. For `parity` goal_type, requiring states (or surfacing them as recommended) would help anchor parity-gap findings on enumerated coverage. Possible v1.4.x or v1.5.0 bump — defer until a real-world plan asks for it (per the demand-driven v2 planning memory).

Neither tuning is required for F005 PASS; both are recorded for future evolution.

## F1 plan validation (acceptance #10)

`python3 claude/shared/schemas/v1.0/validate.py docs/plans/2026-05-05-003-...`: Plan F1 validates green (no `goal_type`, backward-compat path).

## Worktree boundary verification (acceptance #12)

```
git diff --name-only HEAD scripts/   # zero output — scripts/ untouched
ls dogfood/                          # No such file or directory — no top-level dogfood
```

All F005-introduced diffs scoped to `docs/plans/2026-05-05-003-feat-objective-contract-and-sufficiency-audit/evidence/`.

## Pre-existing fixture matches (D013 transparency)

`grep -ri "glam" scripts/dontpanic_orchestrate/` surfaces matches in `tests/test_environments_loader.py`. These are **F023 EC1 test fixtures**, not F005-introduced product-code special cases. The references are fixture content for a generic environments-loader test (where "Glam" happens to be the repo name in the test scenario) — same shape as a generic test using "Acme Corp" as a fictional company. D013 prohibits project-name-specific *behavior* under `scripts/`; test fixture content is data, not behavior. F005 introduced zero new matches.

## Final F1 close-out (gated on operator confirmation)

If the operator confirms both dispositions PASS:
- F005 flips `passes: true` in features.json
- D017 records the close-out
- F1 plan-level close-out memo can be authored, and `plan.md` status flips to `completed` via `dontpanic plan lock` (note: the lock command flips draft→active; F1 is already active, so close-out uses a separate plan-level mechanism that's out-of-scope here — likely a hand-edit or a future `dontpanic plan complete` subcommand).

If either disposition flips to FAIL:
- F005 stays `passes: false`
- F1 stays at status `active` (does NOT flip to completed)
- Diagnosis recorded above and triaged via the priority order in D010

## Summary

F005 produced operator-reviewable evidence for both fixtures using F003's auditor + F004's gate boundary. The findings are materially correct against the contract acceptance signals; both dispositions provisionally PASS. F1 close-out is gated on operator confirmation of the draft dispositions. Project-agnostic invariant (D013) preserved — zero F005-introduced changes under `scripts/`, no top-level `dogfood/` directory, no project-named module/class/special-case in product code.
