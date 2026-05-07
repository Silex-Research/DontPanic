# Plan 2026-05-07-001 close-out memo — F002 parser, codex streaming-output support

**Plan ID:** `2026-05-07-001-fix-completion-dispatch-codex-stream-parser`
**Sequence position:** queued follow-up after Plan 003 ✓ (closed at `616ad94`).
**Status flip:** `active` → `completed` on 2026-05-07 (UTC).
**Outcome:** Clean PASS. F002's `_parse_audit_response()` now extracts the
final `agent_message` text from codex's JSONL streaming output while
preserving the existing raw-JSON path. D008 conservatism properties
(shape-gated recognition, last-wins ambiguity, raw-failure surface) are
all enforced and tested.

## What this plan validated

The parent dogfood (Plan 003, commit `616ad94`) exposed a stub-vs-
production divergence: F002's parser expected raw JSON but codex emits a
JSONL streaming protocol. F001 of this plan closes that gap with a
narrow parser fix:

- New helper `_extract_codex_streaming_payload(response)` walks lines,
  applies the D008(a) shape gate (returns None unless at least one
  parsed line has `type` ∈ {thread.started, turn.started, turn.completed,
  item.started, item.completed}), collects every `item.completed`
  agent_message text, and returns the LAST one (D008(c)).
- `_parse_audit_response()` calls the helper FIRST; on non-None result
  uses it as the cleaned candidate; on None (or for non-streaming
  inputs) falls through to the existing strip-fence + JSON parse logic
  unchanged.
- Helper-returns-None NEVER short-circuits the pipeline — the raw path
  runs on the original response; on failure the envelope is
  `dispatch_response_malformed` with `raw_response` preserving the
  original bytes verbatim (D008(d)).

## Final verification numbers

| Check | Result |
| --- | --- |
| Cumulative orchestrate suite (baseline) | 1344 passed, 7 skipped |
| Cumulative orchestrate suite (post-impl) | **1357 passed, 7 skipped** (+13 new tests, 0 regressions) |
| New tests in `TestCodexStreamingDecoder` | 13 |
| Existing `test_production_path_invokes_resolved_executor` | passes unchanged (D004 backward compat) |
| `ruff check` on touched files | ✓ clean |
| `ruff format --check` on touched files | ✓ clean |
| `sanitization_check.py` | ✓ 0 findings (879 files scanned) |
| Plan dir validates against agent-conventions v1.0 | ✓ |
| Worktree boundary preserved (D007) | ✓ — diff confined to `completion_dispatch.py` + `test_completion_dispatch.py` + `tests/fixtures/codex_stream_dogfood_001.txt` + this plan dir |
| NO live codex invocation in this commit (D005) | ✓ — fixture-only |
| NO prompt template diff (D006 release valve) | ✓ — `prompts/completion_audit_prompt.md` untouched |

## D008 acceptance properties — test mapping

| Property | Tests |
| --- | --- |
| (a) shape-gated recognition | `test_arbitrary_jsonl_without_codex_shape_returns_none`, `test_arbitrary_jsonl_falls_through_to_existing_raw_path`, `test_recognized_stream_with_no_agent_message_returns_none` |
| (b) last complete assistant message wins | `test_only_non_agent_message_item_types_returns_none`, `test_partial_item_started_without_completed_is_ignored` |
| (c) deterministic ambiguity (last in stream order) | `test_multiple_agent_messages_returns_last_text_identity` |
| (d) malformed input → raw failure path with useful error, NOT silent empty | `test_truncated_stream_yields_dispatch_response_malformed_with_raw`, `test_arbitrary_jsonl_falls_through_to_existing_raw_path` |
| Mid-stream malformed line tolerance | `test_mid_stream_malformed_line_is_skipped_scan_continues` |
| Empty `agent_message` text → fall through | `test_empty_agent_message_text_returns_none` |
| Fenced `agent_message` text → strip-fence still applies | `test_fenced_agent_message_text_is_strip_fenced` |
| Fixture-driven happy path | `test_fixture_dogfood_extracts_full_disposition_list` |
| Backward compat (D004) | `test_raw_json_array_input_falls_through_unchanged` + `test_production_path_invokes_resolved_executor` (existing, unchanged) |

## Fixture-truth correction

Plan F001 acceptance bar item (4) inherited a count of "14 dispositions
(12 v1 + 2 auditor-overlay)" from the parent close-out memo prose. The
captured transcript fixture actually contains 13 dispositions: 12 v1
(`F2C-E001..F2C-E012`) plus 1 `auditor-overlay-001`. The
fixture-driven test asserts 13 (fixture truth), and this discrepancy is
recorded in D009 as a citation correction — no schema, parser, or
behavioral semantic was affected.

## Cited commits

| Commit | Description |
|---|---|
| `616ad94` | Parent plan close-out (Plan 003 — dogfood transcript origin) |
| `06dafb8` | Plan 2026-05-07-001 draft |
| `66521fe` | D008 pre-lock conservatism amendment |
| `1326082` | Plan lock (status: active) |
| _(this commit)_ | F001 ship — extractor + tests + fixture + D009 + close-out memo |

## Per-feature decisions

D001–D007: lock-time decisions (codex stream protocol, parser strategy,
fixture path, backward-compat-preserved, no live re-run, no prompt
change, worktree boundary).
D008: pre-lock conservatism amendment — four explicit acceptance
properties (shape-gate, last-wins, deterministic, raw-failure surface).
D009: F001 ship — verification numbers, fixture-truth correction
(13 not 14 dispositions), commit hash, ruff/sanitization clean.

## Outer plan close — exempt-plan flow

This plan's `goal_type=infra` (D002) takes F003's exempt-plan flow:

```
$ dontpanic plan close docs/plans/2026-05-07-001-fix-completion-dispatch-codex-stream-parser/
[plan close] goal_type='infra' is exempt from the F2 completion gate;
            status flipped active → completed without audit
$ echo $? → 0
```

Mirror of how F2 itself + Plan 003 closed (both `goal_type=infra`).

## Sign-off

I (bayesian, operator) confirm: F001 of Plan 2026-05-07-001 ships clean.
The parent dogfood's exposed parser-format gap is closed; live cross-
vendor dispatch can now produce status=`agree`/`disagree` envelopes
(rather than `dispatch_response_malformed`) when codex is the auditor.
The conservatism properties (D008) ensure the parser does not drift
into accepting arbitrary JSONL — recognition is positively shape-gated.

Next queued follow-up: the fixture-fairness plan (proposed slug
`2026-05-XX-fix-cross-vendor-dogfood-fixture-runtime-artifacts`),
which re-runs the live cross-vendor dogfood against an enriched fixture
with this parser fix in place — proving the agree/disagree decision
branches end-to-end on a real plan.

— bayesian, 2026-05-07 UTC
