# F001 close-out memo — resume CLI gate discipline

**Plan:** `2026-05-02-001-feat-resume-gate-discipline`
**Feature:** F001
**Captured:** 2026-05-02 (post manual remediation + confirmation volley)

## Volley → manual fix → confirmation arc

### Initial volley (4 audit envelopes, terminal: `stopped_no_progress`)

- `audit/claude-implementer-i0.json` + `audit/codex-auditor-i0.json` — first round; auditor `needs_changes` with multiple findings; implementer addresses most.
- `audit/claude-implementer-i1.json` + `audit/codex-auditor-i1.json` — second round; auditor `needs_changes` with two residuals:
  1. **medium / correctness** — approve / `resume --gate` event bodies don't differ only by entry-path phrase (locked-acceptance step asked for normalized equality)
  2. **low / documentation** — stale `gate_pause.py:10-12` and `circuit_breakers.py:5-7` docstrings reference bare `jarvis resume <plan-id>`

Volley terminated on `breaker:no_progress` after 2 same-verdict rounds.

### Manual remediation (no audit envelope edits)

- `scripts/jarvis_orchestrate/cli.py:141` — approve INBOX body normalized from `"Operator approved gate {gate!r} via 'approve'."` to `"Operator cleared gate '{gate}' via 'approve'."`. Bodies now differ ONLY by the entry-path phrase, satisfying locked-acceptance step #9 (parity test with normalized-equality assertion).
- `scripts/jarvis_orchestrate/tests/test_cli_resume.py:284-301` — strengthened parity assertion to test byte-equality after substituting the entry-path phrase, pinning future drift.
- `scripts/jarvis_orchestrate/gate_pause.py:10-12` — updated module docstring's CLI summary: removed `jarvis resume <plan-id>` (legacy bulk form), added `--gate <g>` parity line and `--all` explicit-bulk line.
- `scripts/jarvis_orchestrate/circuit_breakers.py:5-7` — updated breaker-clearance docstring to reference `--gate breaker:<kind>` parity and `--all` explicit-bulk forms.

**No audit envelope JSON was edited.** The four envelopes from the initial volley remain on disk verbatim as audit history.

### Confirmation volley (4 more audit envelopes, terminal: `stopped_diminishing_returns`)

Re-dispatched after manual remediation; the original two residuals (event-body normalization, stale docstrings) **resolved** — they no longer appear in either iteration's findings. Two new findings surfaced:

1. **HIGH / correctness — command accountability** — `target_context.commands_run: []` because the implementer formatted side-effect commands as `- \`$ git add ...\`` (bullet + backtick) rather than the literal `^$ ` line-start format the supervisor's prose-extraction regex expects. **This is platform-formatting debt, not feature behavior.** It is the exact EC5-class issue plan `2026-05-01-005-feat-target-context-platform-fix` exists to solve at the platform layer (write-side prelude injection + auditor severity downgrade with description preservation).

2. **LOW / test_coverage — parametrize** — locked-acceptance step asked for "parametrized over seven CLI shapes"; original implementer used 7 separate `test_*` functions. **Resolved manually** via refactor: `test_cli_resume.py:115-228` now uses `@pytest.mark.parametrize` over a `_CLI_SHAPES` list, with one parametrized test driver dispatching to per-shape handler functions.

### Acceptance-miss handling

Per operator guidance ("a medium finding violating locked acceptance is still a blocker, regardless of severity label"):

| Finding | Severity | Source | Resolution |
|---|---|---|---|
| event-body parity beyond phrase | medium | initial volley i1 | manual code edit + test strengthening |
| stale `resume <plan-id>` docstrings | low | initial volley i1 | manual docstring edits |
| seven shapes not parametrized | low | confirmation volley i1 | manual refactor → @pytest.mark.parametrize |
| `target_context.commands_run: []` | high | confirmation volley i1 | **NOT addressed in this plan** — explicit dependency on plan `2026-05-01-005-feat-target-context-platform-fix` per D006 of that plan (platform writer normalization will inject prelude + extract commands from structured fields, removing this finding class entirely) |

## Test + sanitization state at close-out

```
$ PYTHONPATH=scripts python3 -m pytest scripts/jarvis_orchestrate/tests/test_cli_resume.py -v
9 passed in 0.14s

$ PYTHONPATH=scripts python3 -m pytest scripts/jarvis_orchestrate/tests/ -q
342 passed, 6 skipped in 7.40s

$ python3 scripts/sanitization_check.py
✓ no campaign IDs or secret shapes in sanitized surface (511 files scanned)
```

## Decision: flip `passes:true`

The resume CLI feature itself is complete:
- All seven CLI shapes implemented + parametrized-tested
- Approve / resume `--gate` event-body parity verified by normalized-equality assertion
- Global-breaker refusal mirrors `_approve_main`
- Idempotent re-clear is byte-stable
- INBOX `gate_hit` template recommends `approve <gate>` (preferred) and `resume --all` (explicit bulk)
- All existing 342 tests stay green

The remaining HIGH command-accountability finding is **platform-formatting debt**, not feature behavior — it would block close-out only under a stricter rule that disallowed platform-debt deferral entirely. Per operator guidance ("dogfood already did its job: it found the feature defects, then exposed a platform defect"), F001 ships with explicit deferral to plan `2026-05-01-005-feat-target-context-platform-fix`, which is the correct owner of that finding class.

## Volley-instability observation (platform evidence)

Two consecutive dogfood volleys on this plan terminated on different breakers — `stopped_no_progress` then `stopped_diminishing_returns`. Each round surfaced a different pair of findings; manual remediation resolved one pair while the next round surfaced a fresh one (the high command-accountability finding only appeared after the manual fix because by then the supervisor had no other strong findings to flag).

This is platform evidence worth preserving (not a feature defect): the volley loop's findings depth depends on what's *most* wrong, so once you fix the top issues, sub-surface issues become visible. May inform future tuning of `loop_caps` thresholds or auditor-prompt verbosity caps. Not blocking for this plan — surfacing here so the closeout trail captures it.
