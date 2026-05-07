# Plan 003 close-out memo — live cross-vendor goal-audit dogfood

**Plan ID:** `2026-05-06-003-fix-live-cross-vendor-goal-audit-dogfood`
**Sequence position:** queued follow-up after Goal Governance V1 / F2 ✓
**Status flip:** `active` → `completed` on 2026-05-07 (UTC)
**Outcome:** **Successful dogfood; not a clean PASS.** Live cross-vendor dispatch verified end-to-end against a real ObjectiveContract; F002/F003 integration gap exposed; three follow-ups queued. Override path exercised.

## What this plan validated

The dogfood's narrow validation property — that F002's production path actually invokes the resolved non-implementer vendor against a real ObjectiveContract with both vendors actually running — was **met**.

Live cross-vendor invariant verification at envelope assertion level (D003):
- `envelope.auditor_agent = "codex"` ≠ implementer (`claude` default)
- `envelope.status = "dispatch_response_malformed"` ≠ `"dispatch_skipped_offline"` (codex actually ran; the malformed status reflects a parser-format mismatch, NOT an offline run)

Live run cost: ~2 min wall time per audit invocation; 78,948 codex input tokens (48,256 cached) + 1,911 output tokens (incl. 307 reasoning) per invocation. Dogfood incurred 3 codex invocations (initial audit + redundant Step 1 close-without-override + Step 2 close-with-override). The redundant Step 1 was an implementer-side mistake (recorded in D009 operator note).

## What the dogfood exposed

Codex produced substantively excellent adversarial review — a 14-disposition payload (12 v1 finding dispositions + 2 auditor-overlay items) that correctly classified 11 v1 findings as vocabulary mismatches, agreed-with-overlay on 1 finding, and added 2 thoughtful auditor-overlay items flagging real fixture-fairness gaps. **But F002's parser couldn't extract the disposition payload** because codex emits a JSONL streaming protocol (thread.started / item.completed / agent_message events), and `_parse_audit_response()` expects raw JSON. The unit test (`test_production_path_invokes_resolved_executor`) used a stub returning clean JSON; never exercised codex's actual streaming format.

That parser-format gap **is the most valuable outcome** of this dogfood: it's the kind of stub-vs-production divergence that real cross-vendor end-to-end runs are designed to catch. Unit tests would never have surfaced it.

Three additional fixture-fairness findings (F2C-E008 + auditor-overlay-001 + auditor-overlay-002) point at corrections this plan's mirror needs in a re-run: not every adapter source was included; the no-test-orchestration invariant requires source-level evidence not just tests; runtime-evidence harness needs runtime-like artifacts not only code/test/memo files.

## Five-step pipeline run

| Step | Command | Exit | Notes |
|---|---|---|---|
| A | `dontpanic plan audit <fixture>` | 3 (blocking) | Live codex ran; envelope status=dispatch_response_malformed; 12 v1 findings clustered as `(unknown, configure-runtime-evidence)` → child_plan classification |
| B | `dontpanic plan close <fixture>` | 3 (REFUSED) | Implementer-side mistake — redundant invocation; verified F003 refuses on blocking decision; fixture stayed active |
| C | `dontpanic plan close <fixture> --ignore-completion-findings <reason>` | 0 (PASS) | Override.json written with all four D004 hashes; fixture status flipped active → completed |
| D | `enforce_completion_gate(<fixture>)` | silent | Supervisor backstop accepts valid override on completed plan |
| E | `dontpanic plan close <plan-003-dir>` | 0 (PASS) | Outer plan close via exempt-plan flow (`goal_type=infra` → no audit) |

## Final verification numbers

| Check | Result |
| --- | --- |
| Cumulative orchestrate suite | **1344 passed, 7 skipped, 0 regressions** |
| New tests added by Plan 003 | 0 (validation wrapper; no new test code) |
| `ruff check` + `ruff format --check` | ✓ clean (113 files) |
| `sanitization_check.py` | ✓ 0 findings (874 files scanned) |
| Plan 003 validates against agent-conventions v1.0 | ✓ |
| Cross-vendor invariant (D003) verified at envelope | ✓ |
| Override path (block + honor) exercised end-to-end | ✓ |
| Worktree boundary preserved (D007) | ✓ — diff confined to `docs/plans/2026-05-06-003-…/` tree; zero diffs to Plan G plan dir, F001/F002/F003 module code, runtime_evidence/, or F1 surface |
| Plan G's plan dir untouched (D001) | ✓ |

## Cited commits

| Commit | Description |
|---|---|
| `0715bc7` | Plan G close-out (source corpus, read-only) |
| `c9ccc85` | F2 F001 — completion auditor |
| `b9e0bbb` | F2 F002 — cross-vendor dispatcher |
| `10c5ff2` | F2 F003 — completion gate + close CLI + supervisor backstop |
| `fa1d624` | F2 F004 — synthetic-fixture dogfood (offline mode) |
| `97da789` | Plan F2 close-out |
| `d868955` | Plan 003 draft |
| `18aed2d` | Plan 003 D006 amendment (line-count → behavioral boundary) |
| `a51db00` | Plan 003 lock |
| `59e55fe` | Plan 003 plan.md prose alignment + D008 |
| _(this commit)_ | Plan 003 F001 ship + outer close-out + D009 + D010 |

## Per-feature decisions

D001–D007: lock-time decisions (Plan G read-only, two-goal_type-fields, live-cross-vendor required, fixture artifacts copied not symlinked, 4-bucket finding taxonomy, behavioral-boundary D006, worktree boundary).
D008: post-lock plan.md prose alignment with D006 (no scope change).
D009: F001 ship — dogfood ran end-to-end, 11 spec-clarification findings + 3 fixture-fairness findings + 1 platform integration finding; combined per-bucket D-entry rather than per-finding.
D010: F001 ship — operator PASS/FAIL judgment (successful dogfood, not a clean PASS); F001 flips passes:true with the qualified meaning recorded in this memo.

## Follow-ups queued (NOT filed as plan dirs in this commit)

1. **F002 parser — codex streaming-output support.** Update `completion_dispatch.py` `_parse_audit_response()` to recognize codex's JSONL streaming protocol and extract `agent_message.text` as the payload. Companion unit test simulating codex's streaming format. Proposed slug: `2026-05-XX-fix-completion-dispatch-codex-stream-parser`.

2. **Fixture-fairness improvements.** Re-run this dogfood after the parser fix lands, with the fixture enriched to include: all adapter source files (`web.py`, `ios.py`, `android.py`, `backend.py`, `harness.py`); at least one synthetic runtime-like artifact per source (stub screenshots / log slices / crash dumps). Proposed slug: `2026-05-XX-fix-cross-vendor-dogfood-fixture-runtime-artifacts`.

3. **Optional prompt clarification.** Add to `completion_audit_prompt.md` something like "emit ONLY the raw JSON array; do not include exploratory shell commands or streaming events" — D006 in-scope. Defer until parser plan is scoped; if codex respects the directive, the parser fix becomes secondary; if not, parser support is the durable answer.

## Outer plan close — exempt-plan flow

This plan's outer `goal_type=infra` (D002) takes F003's exempt-plan flow at its own close-out:

```
$ dontpanic plan close docs/plans/2026-05-06-003-fix-live-cross-vendor-goal-audit-dogfood/
[plan close] goal_type='infra' is exempt from the F2 completion gate;
            status flipped active → completed without audit
$ echo $? → 0
```

Mirror of how F2 itself (`2026-05-06-002-feat-post-impl-completion-audit`, also `goal_type=infra`) closed on 2026-05-06.

## Sign-off

I (bayesian, operator) confirm: the dogfood met its narrow validation property and surfaced concrete next-hardening work. F001 of this plan flips `passes:true` with the qualified meaning recorded in D010 ("F001 passing means live cross-vendor dispatch end-to-end was exercised and produced actionable signal — NOT zero findings"). Goal Governance V1 layer is complete; this plan validates the integration boundary; follow-ups land in their own future motions.

— bayesian, 2026-05-06 / 2026-05-07 UTC
