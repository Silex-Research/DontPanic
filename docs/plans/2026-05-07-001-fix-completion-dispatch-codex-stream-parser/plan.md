---
id: 2026-05-07-001-fix-completion-dispatch-codex-stream-parser
title: F002 parser — codex streaming-output support
type: fix
tier: local
status: completed
date: "2026-05-07"
goal_type: infra
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
dependencies:
  - 2026-05-06-002-feat-post-impl-completion-audit
  - 2026-05-06-003-fix-live-cross-vendor-goal-audit-dogfood
description: |
  Narrow parser fix for the F002 ↔ codex stream-format integration
  gap surfaced by the live cross-vendor dogfood (parent plan
  `2026-05-06-003-fix-live-cross-vendor-goal-audit-dogfood`,
  closed at commit `616ad94`).

  Single feature, direct path:

  **F001 — Teach `_parse_audit_response()` to extract the final
  assistant text / JSON payload from codex's JSONL streaming output,
  while preserving the existing raw-JSON path.**

  ## Background — what the dogfood exposed

  The dogfood at commit `616ad94` invoked codex CLI through F002's
  production path (no stub, no offline mode). Codex produced a
  substantive 14-disposition payload, but emitted it inside a JSONL
  streaming envelope:

  ```
  {"type":"thread.started","thread_id":"…"}
  {"type":"turn.started"}
  {"type":"item.started","item":{…}}
  {"type":"item.completed","item":{"id":"item_5","type":"agent_message","text":"[…JSON…]"}}
  {"type":"turn.completed","usage":{…}}
  ```

  F002's `_parse_audit_response()` currently strips ``` ` ``` fences
  and parses the result as raw JSON. It can't extract the JSON
  payload from this streaming format — every parse attempt fails
  and the envelope status falls through to
  `dispatch_response_malformed`.

  The unit test
  `test_production_path_invokes_resolved_executor` (in
  `test_completion_dispatch.py`) used a stub returning clean raw
  JSON, so this gap was invisible to the test suite.

  ## Scope (narrow, per parent plan close-out + operator directive)

  In-scope:
  - Update `scripts/dontpanic_orchestrate/completion_dispatch.py`
    `_parse_audit_response()` to recognize codex's JSONL streaming
    protocol and extract the final `agent_message` item's `text`
    field as the disposition payload.
  - Preserve raw-JSON behavior — existing test stubs that return
    bare JSON arrays must continue to parse correctly. The streaming
    detection runs FIRST; on no-match it falls through to the
    existing strip-fence + parse-array logic.
  - Add a new test fixture under
    `scripts/dontpanic_orchestrate/tests/fixtures/codex_stream_*.txt`
    seeded from the captured transcript at
    `docs/plans/2026-05-06-003-fix-live-cross-vendor-goal-audit-dogfood/evidence/g-mirror/synthetic-plan/evidence/goal-governance/post_impl/audit/audit-codex-1.transcript.txt`.
    Test asserts the parser extracts the 14-disposition array
    intact.
  - Add edge-case tests: streaming envelope with no agent_message
    item; multiple agent_message items (use last); agent_message
    text that is itself fenced JSON; empty agent_message text;
    malformed line in the stream.

  Out-of-scope (queued as separate follow-ups; cross the boundary →
  abort and queue):
  - Prompt template changes. If parser tests prove the parser fix
    alone is sufficient, no prompt change is needed. If a future
    real run shows the parser still misses, that's a separate
    follow-up with its own decision (D006 of parent plan defines
    the prompt-change boundary).
  - Re-running live codex in the implementation commit. The
    fixture from the dogfood is the regression artifact. Live
    re-run lives in the next dogfood plan.
  - Changes to F002's executor wiring, dispatcher contract, or
    envelope schema. Parser-only.
  - Changes to F001 (`completion_auditor.py`) or F003
    (`completion_gate.py`) modules. F002 module + its tests only.
  - Fixture-fairness work from parent plan's other follow-ups
    (E008 + auditor-overlay-001/002). That's a separate plan.

  ## What this plan IS NOT

  - Not a v2 of the F002 dispatcher. Single function update +
    fixture-driven tests.
  - Not the place for prompt clarification. Operator may decide
    later that prompt instructions complement the parser fix; that
    decision lives in its own follow-up.
  - Not a re-run of the dogfood. The live run already happened in
    parent plan; this plan consumes its captured artifact as a
    fixture.

motivation: |
  The cross-vendor invariant (D003 / Goal Governance V1 §5) is
  load-bearing for production trust in F2's auditor pipeline. The
  parent plan proved the production path actually invokes codex
  end-to-end and produces substantive review, but every
  cross-vendor run currently terminates with
  `dispatch_response_malformed` because the parser can't consume
  codex's actual output format.

  Until this parser fix lands:
  - Every live cross-vendor close path will block on
    `dispatch_response_malformed` and require an
    `--ignore-completion-findings` override, regardless of whether
    codex's review was substantively excellent or genuinely concerning.
  - Operators can't distinguish "codex disagreed with v1" from
    "parser couldn't read codex's output," because both surface as
    the same envelope status.
  - The cross-vendor adversarial-review property is *technically*
    verified at the dispatch layer but *operationally* unusable for
    any real plan close.

  This is the highest-leverage queued follow-up because it converts
  the parent dogfood's "real cross-vendor dispatch was invoked" from
  a one-off proof into a repeatable, operationally usable surface.
  After this plan closes, future cross-vendor runs (against any
  real plan, not just the synthetic Plan G mirror) will produce
  status=`agree` or status=`disagree` envelopes that F003's close
  path can decide on without operator override-by-default.

  Re-running the parent dogfood with this fix in place would
  produce a cleaner envelope and exercise the agree/disagree
  decision branches end-to-end. That re-run lives in the
  fixture-fairness follow-up plan, not here.
---

# F002 parser — codex streaming-output support

Narrow parser fix to teach `_parse_audit_response()` to recognize
codex's JSONL streaming protocol. Adds a regression fixture seeded
from the parent dogfood's captured transcript. No live codex
invocation in the implementation commit; no prompt change unless
parser tests prove it's still needed.

Sequence position: queued follow-up after parent plan
`2026-05-06-003-fix-live-cross-vendor-goal-audit-dogfood` ✓
(closed at `616ad94`).

## Feature roadmap

| Feature | Phase | Surface |
|---|---|---|
| F001 | 1 | Teach `_parse_audit_response()` codex streaming protocol; add fixture-driven tests; preserve raw-JSON path |

Direct path. Single feature.

## Boundaries

- **D001:** Source corpus is the parent dogfood's captured codex
  transcript (`docs/plans/2026-05-06-003-…/evidence/g-mirror/synthetic-plan/evidence/goal-governance/post_impl/audit/audit-codex-1.transcript.txt`).
  Streaming protocol shape: line-delimited JSON objects with
  `type` field; the disposition payload lives at
  `item_5.text` (or wherever the final `item.completed` event with
  `item.type='agent_message'` lands).
- **D002:** Parser strategy — line-by-line scan for the LAST
  `item.completed` event with `item.type=="agent_message"`; extract
  `item.text`; on extraction success, run that text through the
  existing strip-fence + parse-array logic. On any failure (no
  agent_message found, JSONL parse error mid-stream, text is
  malformed) → fall through to the existing raw-JSON path
  unchanged. The existing path remains the default for stub /
  manual / non-streaming responses. **Tightened by D008** —
  shape-gated recognition, deterministic last-wins, raw-failure
  surface preserved.
- **D003:** Fixture file lives at
  `scripts/dontpanic_orchestrate/tests/fixtures/codex_stream_dogfood_001.txt`
  (NOT cross-plan-referenced). The fixture is a copy of the
  parent dogfood's transcript bytes; the test owns its fixture
  under the test dir so future deletes of parent plan dirs don't
  break the test.
- **D004:** Existing test
  `test_production_path_invokes_resolved_executor` keeps its
  current stub returning raw JSON — proves backward compat. The
  new tests are additive.
- **D005:** No live codex re-run in this plan's implementation
  commit. The fixture is the regression artifact. The next live
  run lives in the fixture-fairness follow-up plan, not here.
- **D006:** No prompt change unless parser tests prove the parser
  fix alone is insufficient. If parser tests pass with codex's
  natural streaming output, leave the prompt alone. If a follow-up
  plan later shows the prompt needs clarifying language for some
  other vendor or edge case, file it as its own motion.
- **D007:** Worktree boundary — diff confined to:
  - `scripts/dontpanic_orchestrate/completion_dispatch.py` (F002
    module; the only permitted module edit)
  - `scripts/dontpanic_orchestrate/tests/test_completion_dispatch.py`
    (additive tests)
  - `scripts/dontpanic_orchestrate/tests/fixtures/codex_stream_*.txt`
    (new fixture file)
  - This plan dir (plan.md / features.json / decisions.jsonl /
    evidence/)
  Forbidden writes: F001 (`completion_auditor.py`), F003
  (`completion_gate.py`), F1 surface, runtime_evidence/, executors/,
  cli.py, supervisor.py, agent-conventions schemas, parent plan
  dirs.
- **D008 (pre-lock amendment, operator-requested):** Parser must be
  format-tolerant but conservative. Four explicit acceptance
  properties added — see decisions.jsonl D008 for full text:
  - **(a) shape-gated recognition** — helper returns None unless
    at least one parsed line carries `type` ∈ {`thread.started`,
    `turn.started`, `turn.completed`, `item.started`,
    `item.completed`}. Arbitrary line-delimited JSON without any
    recognized codex event type is NOT treated as a stream — falls
    through to the existing raw-JSON path.
  - **(b) last complete assistant message wins** — extraction
    restricted to `item.completed` events with
    `item.type=='agent_message'`. Partial events (`item.started`
    without matching `item.completed`) are ignored. Other
    `item.type` values (`tool_use`, `function_call`, `reasoning`)
    are ignored.
  - **(c) deterministic ambiguity resolution** — when multiple
    `agent_message` items exist in one stream, the LAST one in
    stream order is chosen. No first-found / longest-text /
    random heuristic.
  - **(d) malformed input → raw failure path with useful error**
    — helper returning None NEVER short-circuits. Downstream raw
    path runs on the original `response`. On failure: envelope
    `status='dispatch_response_malformed'`, `raw_response`
    preserves original bytes verbatim. NO silent empty result.

## Acceptance bar

This plan's F001 acceptance:

1. `completion_dispatch._parse_audit_response()` recognizes codex's
   JSONL streaming protocol (line-delimited JSON, `type`-tagged
   events, `agent_message` item with `text` payload).
2. Streaming-format extraction runs FIRST; on no-match falls
   through to the existing raw-JSON + fence-strip path. Order
   preserved: streaming → raw → malformed.
3. Fixture
   `tests/fixtures/codex_stream_dogfood_001.txt` exists with
   the captured-from-dogfood transcript bytes.
4. New test reads the fixture; asserts parser produces the full
   14-disposition list (12 v1 + 2 auditor-overlay) with correct
   `agree` / `severity_disposition` values.
5. **D008 conservatism — format-tolerant but conservative.** New
   tests assert the four positive properties:
   - **(a) shape-gated recognition** — well-formed line-delimited
     JSON with NO recognized codex `type` field → helper returns
     None → falls through to raw-JSON path → produces
     `dispatch_response_malformed` (NOT silent empty).
   - **(b) last complete assistant message wins** — partial
     `item.started` events ignored; non-`agent_message`
     `item.type` values (`tool_use`, `reasoning`) ignored;
     extraction confined to `item.completed.agent_message.text`.
   - **(c) deterministic ambiguity** — three `agent_message`
     items in one stream → LAST one's text wins (asserted by
     identity, not by superset).
   - **(d) malformed input → raw failure path** — truncated /
     mid-event stream → helper returns None or partial → raw
     path runs on ORIGINAL response → envelope
     `status='dispatch_response_malformed'` with `raw_response`
     preserving original bytes verbatim.
   Plus existing edge-case tests: no `agent_message` in stream;
   fenced `agent_message` text; empty / whitespace-only
   `agent_message` text; mid-stream malformed JSON line skipped
   not aborted; non-streaming raw-JSON input (regression for
   backward compat).
6. Existing
   `test_production_path_invokes_resolved_executor` continues to
   pass unchanged (stub returns raw JSON).
7. Cumulative orchestrate suite green; ruff + sanitization clean.
8. Worktree boundary preserved (D007); only the four permitted
   write paths show in `git diff --name-only HEAD`.
9. NO live codex invocation in implementation commit. NO prompt
   template diff in this plan unless explicitly justified by a
   parser-test failure that no parser-only fix can resolve (D006
   release valve; default expectation: parser fix is sufficient).
10. Plan-level close via exempt-plan flow (`goal_type=infra`)
    exits 0; supervisor backstop silent on post-close state.

After this plan closes, the next motion is the fixture-fairness
follow-up plan (proposed slug:
`2026-05-XX-fix-cross-vendor-dogfood-fixture-runtime-artifacts`),
which re-runs the live cross-vendor dogfood against an enriched
fixture with the parser fix in place — proving the agree/disagree
decision branches end-to-end on a real plan.
