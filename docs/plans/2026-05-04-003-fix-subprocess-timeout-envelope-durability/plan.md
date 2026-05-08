---
id: 2026-05-04-003-fix-subprocess-timeout-envelope-durability
title: Fix — Subprocess timeout handling and envelope diagnosability
type: fix
tier: cross-cutting
status: completed
date: "2026-05-04"
description: |
  Three concrete fixes that turn the volley's hardcoded 600s subprocess
  deadline from a quiet-failure mode into a diagnosable, recoverable
  one. Same scope as the symptom Plan B's volley produced (both impl
  iterations timed out, real work landed, supervisor classified the run
  as `stopped_no_progress` because the envelopes looked empty).

  Plan C does NOT recover internal tool history. It cannot — the Claude
  CLI is invoked with `claude -p --output-format json` and only emits
  one final JSON blob, so per-tool-call boundaries inside Claude are
  not externally observable (D001). Codex is more stream-friendly but
  Plan C must work cross-agent.

  The framing: **make timeout envelopes truthful, schema-valid, and
  useful enough that the supervisor no longer mistakes "work landed
  but wrapper timed out" for "zero progress."**

  Three features, three different execution paths:

  - **F001 (direct)** — shared subprocess runner with proper
    process-group handling (`Popen(start_new_session=True)` →
    SIGTERM-grace-SIGKILL via `killpg`), env-configurable timeout +
    grace, optional worktree delta detection. Replaces duplicated
    `subprocess.run(... timeout=600)` in
    `executors/{claude,codex}_cli.py`.
  - **F002 (direct)** — timeout evidence in audit envelopes.
    Schema-valid (no new `audit_status` value, no new top-level
    fields per `additionalProperties: false`); markers in
    `validation_performed`, structured `correctness/medium` finding
    when worktree changed under a timeout, partial stdout/stderr as
    sidecars under `audit/partials/`.
  - **F003 (volley)** — supervisor classifier excludes timeout-with-work
    from no-progress / diminishing-returns counting. May touch
    `circuit_breakers.py` (Plan B's zero-diff invariant is dropped
    here per D008); only timeout-with-work classification changes,
    no thresholds / defaults / statuses move.

motivation: |
  Plan B's volley (commit `dc9c6cd` in working state, then closed out
  manually) produced four `audit_status: blocked` envelopes — both
  implementer iterations and both auditor reads. The implementer
  envelopes were truncated by the 600s wrapper kill, so the supervisor
  saw no `commands_run`, no useful `summary`, and no markers indicating
  whether work landed. It then triggered `stopped_no_progress` because
  the verdict pattern was `needs_changes, needs_changes` — even though
  the implementer had modified `cli.py`, `gate_pause.py`,
  `supervisor.py`, and `test_f008_engagement_surface.py` on disk.

  The recovery — accept on direct review — has been the established
  pattern since F003 of plan 2026-05-03-001 and recurred for F002 +
  F003 of plan 2026-05-03-003. It works, but it relies on the operator
  carrying tribal memory: "if the volley terminates `stopped_no_progress`
  with timeouts, check the working tree for landed work." Plan C's
  goal is to put that signal *in the envelope itself* so the supervisor
  classifies correctly and the operator (or future automation) doesn't
  need the tribal-memory check.

  Plan A (canonical module flip, `8edd953`) and Plan B (lifecycle-staged
  gates, committed) are merged. Plan C anchors on
  `dontpanic_orchestrate` and uses Plan B's staged-gate behavior — its
  own volley (F003) will be the first dogfood of staged
  `pre_impl`/`pre_merge`.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 2
  no_progress_threshold: 2
  wall_clock_hours: 3
  hard_stop: false
privacy_tier: internal
protected_paths:
  - claude/PORTABILITY.md
  - claude/scripts/sync-harness.sh
  - dashboard/state/costs.json
  - claude/shared/
---

## Target

```yaml
target_env: dev
target_project: none
```

## Scope

Three features with explicit `depends_on` ordering:

1. **F001 — shared subprocess runner.** New module
   `scripts/dontpanic_orchestrate/subprocess_runner.py`. Both
   executors (`executors/claude_cli.py`, `executors/codex_cli.py`)
   stop calling `subprocess.run(..., timeout=600)` directly and
   delegate to the shared helper. The helper uses
   `Popen(start_new_session=True)` so the child process becomes a
   session leader (its own process group); on timeout, sends
   `SIGTERM` to the whole group via `os.killpg`, drains output for
   the grace window, then `SIGKILL`s the group if anything
   survived. Returns a structured `SubprocessResult` with
   `timed_out`, `timeout_seconds`, `grace_period_used`,
   `captured_stdout_bytes`, `captured_stderr_bytes`,
   `worktree_changed`, plus the raw stdout/stderr buffers.

2. **F002 — timeout evidence in audit envelopes.**
   `audit_writer.py` consumes the new `SubprocessResult` fields and
   populates the existing audit envelope schema with diagnostic
   markers — without adding new top-level fields (the schema has
   `additionalProperties: false`). Specifically:
   - `summary` carries structured timeout context, not the bare
     `DISPATCH FAILED: TimeoutExpired...`.
   - `validation_performed` adds string markers like
     `subprocess_timeout_seconds=600`,
     `timeout_stdout_bytes=4321`, `worktree_changed=true`,
     `grace_period_used=true`, and (when sidecars exist)
     `partial_stdout_path=audit/partials/<audit_id>.stdout.txt`.
   - `findings` gains a structured entry when
     `timed_out=true AND worktree_changed=true` —
     `severity: medium`, `category: correctness`,
     `issue: "executor timed out after observable worktree changes"`.
   - Partial stdout/stderr written to
     `audit/partials/<audit_id>.{stdout,stderr}.txt` (new sidecar
     directory; not part of the audit JSON).

3. **F003 — supervisor classifier no longer treats timeout-with-work
   as zero progress.** Real semantic change to the no-progress and
   diminishing-returns detectors in `supervisor.py` (and possibly
   `circuit_breakers.py`). When an envelope has
   `audit_status: blocked` AND `worktree_changed=true` per F002's
   markers, the supervisor:
   - excludes it from no-progress counting,
   - excludes it from diminishing-returns counting,
   - still records it in the loop history,
   - still allows the auditor to inspect the partial work,
   - emits a transcript line acknowledging "implementer timed out
     but landed work; continuing or terminating per loop caps".

   No threshold/default/status changes — no breaker enum value moves,
   no terminal-state strings change. The only behavior shift is
   classification of a specific envelope shape. Plan B's exact
   pattern (timeout both rounds, work landed, auditor flagged
   `needs_changes`) becomes diagnosable from the envelopes alone.

## Out of scope (deliberate)

- **No new `audit_status` enum value.** Schema is locked to
  `signed_off | needs_changes | blocked | inconclusive | redaction_required`.
  Adding `partial` or `timeout_with_work` would require an
  agent-conventions schema bump + generated-models regen + signoff
  aggregator changes. Plan C uses observable facts within the
  existing schema (D002).
- **No new top-level audit envelope fields.** `additionalProperties: false`
  forbids it. Sidecars + `validation_performed` markers carry the
  signal (D004).
- **No per-plan timeout via `loop_caps.subprocess_timeout_seconds`.**
  The current `loop_caps` schema has `additionalProperties: false`.
  Per-plan configurability is deferred — either via a parser-owned
  `executor_caps:` block popped before schema validation, or via a
  later agent-conventions schema bump. Plan C uses env vars
  (D003).
- **No internal-tool-call recovery for Claude.** The Claude CLI's
  one-final-blob output format means per-tool checkpointing
  inside Claude is impossible without a different invocation
  pattern. Plan C uses *external* observables only — output
  byte counts, worktree delta, exit/signal status (D001).
- **No threshold / default / status changes in
  `circuit_breakers.py`.** F003 may touch the file (Plan B's
  zero-diff invariant explicitly does NOT apply to Plan C, per
  D008), but only to thread the timeout-with-work classification
  through. No breaker enum values move; no terminal-status
  strings change.
- **Historical `docs/plans/` durability.** Same invariant as Plan
  A's D003 / Plan B's D008. Only this plan's own new directory
  touches `docs/plans/` in this commit boundary (D010).

## Cross-cutting tightenings (operator-supplied)

Per pre-draft conversation. These are absorbed into the locked
decisions D001–D008 below; restated here as a single auditor-
facing checklist:

1. Sidecar partials live under `audit/partials/<audit_id>.{stdout,stderr}.txt`,
   referenced from `validation_performed` strings — not as new
   audit JSON fields (D004).
2. F001 runner uses `Popen(start_new_session=True)` +
   `communicate(timeout=N)` + `os.killpg(SIGTERM)` →
   grace-window drain → `os.killpg(SIGKILL)` if needed. Not
   `subprocess.run`. Otherwise descendant processes survive
   the wrapper kill (D005).
3. Env vars: `DONTPANIC_SUBPROCESS_TIMEOUT_SECONDS` (default
   600, min 30, max 7200) and `DONTPANIC_SUBPROCESS_GRACE_SECONDS`
   (default 15, min 1, max 120). Invalid values fall back to
   defaults with a validation marker; never crash dispatch
   (D003).
4. F002 findings use the existing `correctness` category; no new
   category enum values. Severity `medium`. Issue text mentions
   timeout and observable worktree changes (D007).
5. Worktree detection lives in the runner, optional. If cwd is
   inside a git repo: `git status --porcelain=v1` snapshot
   before/after. If git unavailable or cwd not a repo:
   `worktree_changed=unknown`. Git failures NEVER fail dispatch
   (D006).
6. F003 may diff `circuit_breakers.py`. The "zero-diff" invariant
   from Plan B does NOT apply to Plan C. Replacement contract:
   no threshold/default/status changes; only timeout-with-work
   classification is excluded from no-progress / diminishing-
   returns counting (D008).
7. Execution paths locked per-feature: F001 direct, F002 direct,
   F003 volley (D009).

## Execution path

Per-feature, with `depends_on` ordering:

| Feature | Path | Why |
|---|---|---|
| F001 | direct | Mechanical refactor + new helper module + tests. No semantic decisions for an auditor to debate. |
| F002 | direct | Additive envelope writer changes within existing schema. AC-driven. |
| F003 | volley | Real semantic change to supervisor classifier. The exact failure mode the auditor caught in Plan B's volley — adversarial review pays off. |

F002 depends on F001 (consumes `SubprocessResult` fields); F003
depends on F002 (reads its `validation_performed` markers).

## Audit-focus addendum (F003 review priorities, NOT new ACs)

The F003 volley's auditor must touch on EACH item explicitly in
their findings paragraph (PASS/CONCERN/FAIL per item). These do
NOT add new acceptance items; they sharpen the auditor's beam:

1. **Timeout-with-work classification.** Parametric over four
   envelope shapes: `blocked + worktree_changed=true`,
   `blocked + worktree_changed=false`, `blocked + worktree_changed=unknown`,
   `signed_off`. Each must be classified correctly by the
   no-progress detector.
2. **Diminishing-returns interaction.** Same parametric coverage
   for the diminishing-returns detector.
3. **Loop-history fidelity.** Timeout-with-work envelopes still
   appear in the loop history; they're just excluded from the
   counters.
4. **No threshold / default / status changes.** Diff
   `circuit_breakers.py` against `HEAD~1`: only logic changes
   tied to the timeout-with-work classifier; no enum / threshold /
   default / terminal-status moves.
5. **Plan B retroactive diagnosability.** A stored copy of one of
   Plan B's volley envelopes (with worktree_changed manually
   added per F002's writer) classifies correctly under the new
   detector. The pattern that triggered Plan B's
   `stopped_no_progress` is now diagnosable from envelope
   evidence alone.
6. **Auditor inspection of landed work.** When the implementer
   times out with worktree-changed evidence, the auditor still
   runs and still inspects the on-disk changes. The new
   classifier doesn't gate auditor invocation.
7. **No regression of legitimate no-progress.** A
   `blocked + worktree_changed=false` (or `unknown`) envelope
   still counts toward no-progress — Plan C does not
   over-correct.
8. **Test isolation discipline.** Per the Plan A / Plan B
   learning, F003's tests must NOT delete entries from
   `sys.modules` to force re-imports. Use `record=True` warning
   capture and scoped monkeypatching instead.

## Known caveats explicitly NOT Plan C blockers

A. **Plan C's own volley (F003) may itself produce timeout-with-work
   envelopes.** F001+F002 will already be merged when F003
   dispatches, so its envelopes will carry the new evidence
   markers — but the OLD classifier (which F003 is fixing) will
   still misfire on them. If the volley terminates
   `stopped_no_progress`, accept on direct review per the
   established F002/F003-of-plan-003 + Plan-B pattern. After
   F003 merges, the next volley (Plan D, or any future plan) will
   benefit from the new classifier.

B. **`test_ec5_classifier.py` still broken** post-rename. Plan
   D's scope. Exclude from full sweep with
   `--ignore=scripts/dontpanic_orchestrate/tests/test_ec5_classifier.py`.

C. **Per-plan timeout configurability deferred.** Future plan
   adds `executor_caps:` parser carve-out or schema bump. Plan
   C ships env-var only.

## Acceptance summary

Binding contract is in `features.json` for each feature.
Highlights:

- **F001:** Popen + start_new_session + killpg pattern; structured
  `SubprocessResult`; both executors delegate; env-var parsing
  with min/max bounds and graceful fallback; worktree detection
  optional and crash-free.
- **F002:** schema-valid envelopes (no `additionalProperties`
  violations); structured `validation_performed` markers;
  `correctness/medium` finding when timeout + worktree_changed;
  sidecar partials under `audit/partials/`.
- **F003:** no-progress + diminishing-returns detectors exclude
  timeout-with-work; loop history retains all envelopes;
  auditor still inspects landed work; no threshold/default/status
  movement in breakers.
- **Cross-cutting:** Full orchestrate suite (excl.
  `test_ec5_classifier.py`) passes; ruff clean; sanitization
  clean; `git diff --name-only HEAD` for this commit shows zero
  entries under `docs/plans/` outside Plan C's own dir.
