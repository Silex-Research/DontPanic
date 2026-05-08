# Plan 2026-05-01-005 close-out memo — target-context platform fix (F001 helpers + F002 audit_writer auto-injection + F003 EC5 classifier downgrade)

**Plan ID:** `2026-05-01-005-feat-target-context-platform-fix`
**Type:** `feat` · **Tier:** `cross-cutting` · **agents:** `claude` + `codex`
**goal_type:** none declared (exempt-by-absence from F2 completion gate)
**Status flip:** `active` → `completed` on 2026-05-07 (UTC).

This memo synthesizes across F001 (target_context_prelude helpers + fixtures), F002 (audit_writer prelude auto-injection), and F003 (EC5 severity classifier downgrade). The existing per-feature memos (`evidence/closeout-memo.md` for F001, `evidence/f003-closeout-memo.md` for F003) are byte-untouched; F002's close-out is recorded in D011/D012. This memo adds the cross-feature view, the EC5-boundary Q answer, the D016 schema-conformance repair record, and the cross-plan deferred-finding resolution.

## D016 — schema-conformance repair applied this turn

Before close-out could proceed, validator preflight surfaced one schema violation: `features.json features[1].evidence_refs[4].type='dir'` (not in v1.0 enum). The single-field repair `'dir'` → `'audit_json'` was applied this turn under operator's Path A directive. The URI points to `evidence/f002/audit-original-volley/`, a directory containing 4 preserved audit envelope JSONs from the original F002 volley — `audit_json` is the closest valid enum value matching the artifact contents. `uri`, `captured_by`, and `note` are preserved verbatim. **No acceptance claim, status, or evidence content changed** — only the schema-invalid type label was corrected. Recorded in D016 (this commit's append).

## EC5 writer/classifier boundary — what this plan does and does NOT claim

The operator-named central correctness Q at close-out:

> Does this plan close the EC5 deferred-finding class by changing the writer/classifier boundary, without claiming every future agent summary will be formatted perfectly?

**Answer: yes.** The platform's write-side (F002) and read-side (F003) compensate for the format-only case so agents are no longer required to produce perfectly-shaped prose preludes. But the platform does NOT claim to format every future agent summary perfectly — it provides defensive depth, not perfection.

| What this plan DOES at the writer/classifier boundary | What it does NOT claim |
|---|---|
| **F002 (write-side):** `audit_writer.build_audit` auto-injects the canonical D001 prelude when `target_context` struct is valid AND prose summary is missing the prelude block. Generation, not validation (D003) — the prelude is fully derivable from the structured field, so the platform produces it rather than failing the implementer for a cosmetic gap. | Force agents to always emit perfectly-formatted summaries. The platform compensates on persist; it does not retrain agents or block their output. |
| **F003 (read-side):** EC5 severity classifier downgrades severity from auditor-assigned to `i0` (advisory) when finding is detected as struct-valid + prose-missing/malformed. Narrow rule per D005 — only the format-only case downgrades. | Downgrade **all** EC5-shaped findings. **Case-g (negative control) — env=prod prose mismatching env=dev struct — stays `i1`** because that's content-correctness, not format. |
| **F003 description preservation (D008):** classifier mutates `severity` only; finding `description` survives verbatim so the auditor's reasoning is recoverable for review even when the platform overrides their severity. | Discard or rewrite auditor reasoning. Platform's severity rule is defensive, not authoritative-over-auditor. |
| **F003 backwards-compat (acceptance #10):** legacy findings without explicit `code` field detected via regex anchored on `target<sep>context...prelude` bigram. | Catch every conceivable EC5-shaped finding the auditor might invent in arbitrary text. The bigram regex matches the documented finding-prose pattern. |
| **F002 hard-fail on invalid struct (D004):** `validate_target_context` raises `TargetContextError` and the envelope file does NOT land on disk when target_context is missing/None or env/project empty when commands_run non-empty. | Silently degrade to "envelope written but flagged with warning." A persisted envelope with invalid target_context is the failure shape this plan exists to make impossible. |
| **F002 forward-only normalization (D007):** historical audit envelopes are NOT migrated to inject preludes retroactively. | Rewrite history. Historical envelopes stay verbatim; analysis tools that need canonical prelude on legacy data call `render_prelude(env.target_context)` at read time. |

**Net writer/classifier boundary**: agents produce summaries; F002 normalizes on persist; F003 classifies on read. Platform does not require agents to be perfect; it requires the structured `target_context` field to be valid, and synthesizes/classifies the prose representation around it.

## Cross-feature outcome

| Feature | Path | Result |
|---|---|---|
| F001 — `target_context_prelude.py` helpers (PRELUDE_TEMPLATE, render_prelude, validate_target_context, parse_prelude_block, TargetContextError) + 7 regression fixtures (case-{a..g}) | Volley → terminal `stopped_no_progress` after 2 rounds | `passes:true`. 65 targeted tests + 407/6 sweep. Auditor i1 produced one residual HIGH (implementer summary missing prose prelude) — exactly the meta-recursive case F002+F003 ship to fix. Deferred to F002 per D010. No audit envelope edited post-hoc. |
| F002 — `audit_writer.build_audit` auto-injects canonical prelude when struct valid + prose missing; sidecars NOT introduced (different scope from Plan 2026-05-04-003 F002); validate_target_context hard-fails on invalid struct | Volley → terminal `stopped_diminishing_returns [2, 3]` after 2 rounds → manual cross-harness remediation per D011 | `passes:true`. 20/20 F002 targeted + 427/6 sweep. Three findings from cross-harness review (HIGH case-c byte-equality, MEDIUM cli.main exit code, LOW forward-only proof) all fixed verbatim per D011 + D012 clarifications. |
| F003 — `ec5_classifier.py` (`classify_ec5_severity`, `is_ec5_finding`, `apply_ec5_classifier_to_findings`); EC5_AUDITOR_RULE prompt paragraph; aggregator wired in `build_audit` between finding-extraction and status-derivation | Direct path (no volley) per D014 — operator-approved after F002 saturated the EC5 surface adversarially | `passes:true`. 19/19 F003 targeted + 447/6 sweep. Schema unchanged per D006; abstract `i0` maps to existing `advisory` severity at aggregation boundary. |

## Q2 — three-layer terminal classification

Same shape established in prior Tier 2/3 close-outs (Plans 2026-05-01-001, 2026-05-02-001, 2026-05-04-003):

| Layer | Plan-005 instance | Classification |
|---|---|---|
| Volley breaker terminal | F001 `stopped_no_progress` (verdict-based) + F002 `stopped_diminishing_returns [2, 3]` (count-based) | F001's verdict-based terminal: separate breaker from count-based fix; verdict-based hardening remains a queued discussion (NOT solved here, NOT solved by 2026-05-02-004). F002's count-based [2, 3] terminal: **platform artifact since fixed** by Plan 2026-05-02-004 (signature-based breaker reclassifies as false-positive — disjoint findings of similar count). |
| Implementation | F001/F002/F003 all `passes:true` per features.json + per-feature memos + 447/6 full sweep at F003 close-out | **Implementation result — clean.** D013 explicitly says "Plan 005 fully closed after this commit (F001+F002+F003 all passes:true)." |
| Meta-recursive HIGH finding | F001 i1 auditor flagged implementer summary missing prelude prose | **META platform artifact, resolved within plan.** D010 deferred to F002+F003 of the same plan; F002's auto-injection + F003's downgrade structurally resolved the finding-class. The deferral chain closes inside this plan. |

## Cross-plan deferred-finding resolution

Plan 2026-05-02-001 (resume-gate-discipline, closed `bdb4c3e`) deferred a HIGH finding (commands_run formatting) to this plan per its D006. Plan 005's F002 + F003 ship the structural fix:

- **F002 audit_writer auto-injection**: when implementer's structured `target_context.commands_run` is populated but prose prelude is missing (the exact 2026-05-02-001 D006 shape), F002 injects the canonical prelude on persist.
- **F003 EC5 classifier downgrade**: even if a future auditor still flags the format-only case as HIGH, F003 downgrades to `i0` with description preservation.

**The deferred HIGH finding is closed by owning plan, not by retroactively modifying 2026-05-02-001's historical memo.** Plan 2026-05-02-001's status-flip close-out memo (the one I wrote at `bdb4c3e`) already records: "Plan 005's F002+F003 implementation resolves the finding-class; Plan 005's own status-flip close-out is the canonical record of that resolution, not this plan's." This commit is that canonical record.

## Cross-link to closed plans depending on this work

Q1 sweep this turn:

| Citing plan (status) | Citation context |
|---|---|
| `2026-05-02-001-feat-resume-gate-discipline` (closed `bdb4c3e`) | D006 + closeout-memo: deferred HIGH finding owner — **structurally resolved by this close-out** (see section above) |
| `2026-05-02-003-feat-nested-orchestration-v1` (closed `5ddd6ae`) | plan.md cites this plan in dependency context |
| `2026-05-05-001-fix-plan-validator-audit-auxiliary-json` (closed `03cc0b9`) | D008 fixture-path enumeration (mechanical) |
| `2026-05-05-003-feat-objective-contract-and-sufficiency-audit` (closed) | F002 closeout memo cites this plan as the EC5 prelude substrate |
| `2026-05-02-002-fix-audit-envelope-filename` (active) | This plan's D013 deferred audit-envelope filename collision to a follow-up; that follow-up is Plan 002, still active. Bidirectional dependency, not supersession. |

All closed citers reference this plan as already-shipped substrate; no active-plan supersession risk for the close-out itself.

## Brand-rename note (drift forward)

Plan was authored 2026-05-01, **before** the canonical-module flip shipped at `8edd953` (Plan 2026-05-04-001, closed `ab7c7dc`). Therefore:

- **In-plan text** (plan.md, features.json, decisions, F001 + F003 per-feature memos) references legacy `scripts/jarvis_orchestrate/...` paths and `jarvis_orchestrate` module names. F001 acceptance specifically names `scripts/jarvis_orchestrate/target_context_prelude.py`.
- **Live code** lives at `scripts/dontpanic_orchestrate/target_context_prelude.py` post-rename. The legacy `jarvis_orchestrate` shim still re-exports cleanly with a one-shot DeprecationWarning.
- **AC behavior identical** through the shim. Historical AC text intentionally NOT retro-updated.

Same drift pattern as Plans 2026-05-01-001 (onboarding-ux), 2026-05-02-001 (resume-gate-discipline), 2026-05-05-001 (validator-dispatch VERSION 1.3.1 → 1.4.0). Future readers map `jarvis_orchestrate` → `dontpanic_orchestrate` at code-read time.

## What this plan does NOT solve

Per scope discipline + queued decisions:

- **Verdict-based `check_no_progress` hardening** (distinguishing feature-defect vs environmental unchanged-verdict) — F001's volley tripped the verdict-based breaker. Same separate platform discussion named in Plan 2026-05-04-004's MAY/MUST-NOT memo + Plan 2026-05-01-001's Q2 + Plan 2026-05-02-001's non-subsumption + Plan 2026-05-04-003's queue. **NOT solved by this plan.**
- **Audit-envelope filename collision** (D013) — F002's volley overwrote committed F001 envelopes because `{agent}-{role}-i{n}.json` filenames don't include `feature_id`. Deferred to Plan 2026-05-02-002 (still active). **NOT solved by this plan.**
- **`summary_format_version` discriminator** (D006) — to track which envelopes have been platform-normalized vs legacy. Deferred to a separate conventions-bump plan. **NOT solved by this plan.**
- **Repo precedence schema-bump** (D002) — currently relies on cwd-fallback shim because `target_context.repo` is not yet a required field. Future schema-bump plan adds it. **NOT solved by this plan.**
- **All other-plans schema-debt sweep** — operator's explicit instruction at the D016 repair: "Do not broaden this into an all-plans schema-debt sweep inside this close-out. Plan 2026-05-04-002 or any broader legacy evidence-ref repair should stay separate." **NOT addressed here.**

## Outer plan close — exempt-flow path

```
$ dontpanic plan close docs/plans/2026-05-01-005-feat-target-context-platform-fix/
[plan close] goal_type=None is exempt from the F2 completion gate;
             status flipped active → completed without audit
```

Same exempt-flow path as the prior twelve close-outs in this session.

## Sign-off

Plan 2026-05-01-005 ships clean. F001 (helpers + 7 fixtures) + F002 (audit_writer auto-injection) + F003 (EC5 classifier downgrade with description preservation) all `passes:true`. The writer/classifier boundary is shifted: agents are no longer required to produce perfectly-formatted prose preludes (write-side platform injects on persist; read-side classifier downgrades format-only severity), but the platform does NOT claim every future summary will be formatted perfectly — it provides defensive depth, not perfection. Plan 2026-05-02-001's deferred HIGH finding is structurally resolved by this close-out's owning-plan ship of F002+F003, without retroactively modifying that plan's historical memo. The D016 schema-conformance repair (`features[1].evidence_refs[4].type` `dir` → `audit_json`) was a narrow validator-conformance fix preserving uri/captured_by/note verbatim; no acceptance claim altered.

— bayesian, 2026-05-07 UTC
