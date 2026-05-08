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

---

## Status-flip close-out verification (added 2026-05-07)

Appended at the formal `active → completed` flip in the Tier 2/3 close-out batch. Impl-time content above is byte-untouched.

### Central correctness claim (operator-named, gate-specific)

> Does the plan preserve the distinction between clearing a specific declared gate, bulk-clearing intentionally, and bypassing/overriding a breaker?

**Answer: yes — the plan introduces all three as named, explicit, non-default modes.** Verified live this turn against `dontpanic resume --help`:

| Operation | Live CLI shape | Mechanism |
|---|---|---|
| Clear ONE specific declared gate | `dontpanic resume <plan> --gate <name>` (parity with `dontpanic approve <plan> <gate>`) | `_resume_main` argparse: `--gate <name>` clears exactly the named entry from `active_breakers` / `active_defers` / declared_gates |
| Clear ONE specific breaker (named bypass) | `dontpanic resume <plan> --gate breaker:<kind>` | Same dispatch path; `breaker:<kind>` strings are valid `--gate` targets per cli.py:203–215 (`breaker_names = {f"breaker:{k.value}" for k in cb.APPROVAL_BREAKERS}`) |
| Bulk-clear EVERYTHING (explicit) | `dontpanic resume <plan> --all` | Help text: "Explicit bulk-clear of every plan-declared gate + active breakers/defers (legacy behavior, now behind a required flag)" |
| Bare `resume` (no flag) | `usage: dontpanic resume <plan> (--gate <name> \| --all)` → **exit 2** | argparse mutually-exclusive group enforced; verified live: `dontpanic resume <plan>` → stderr usage block, `$? = 2` |
| Recommended partial clearance | `dontpanic approve <plan> <gate>` | INBOX `gate_hit` template + `--help` epilog both name `approve` as preferred for single-gate clearance |

**No silent-bypass path exists.** Every clearance operation now requires a named flag (`--gate <X>` or `--all`) and emits a structured INBOX event. The destructive bulk-clear default that the original dogfood discovered is gone.

### Q2 — three-layer terminal classification

Same shape as Plan 2026-05-01-001 (onboarding-ux, closed `e6ffa32`):

| Layer | What it is | Classification |
|---|---|---|
| 1. Initial volley terminal | `stopped_no_progress` after 2 same-verdict rounds | Platform artifact (verdict-based breaker fired on residual ruff/docstring findings; check_no_progress unaffected by Plan 2026-05-02-004's count-based fix — still queued for any future verdict-based hardening) |
| 2. Confirmation volley terminal | `stopped_diminishing_returns` with finding counts `[2, 2]` non-decreasing | **Platform artifact since fixed.** Plan 2026-05-02-004 (signature-based diminishing-returns, closed `5a0979b`) retroactively reclassifies this terminal as the false-positive shape — the [2, 2] findings between iterations were disjoint (different problems each round of similar cardinality). Under the new signature-based breaker, the volley would not have tripped here. |
| 3. F001 implementation | 9 dispatch tests + 342 full sweep + ruff/sanitization clean + 3 of 4 findings resolved manually + locked-acceptance items 1–11 verified | **Implementation result — clean.** Per Path 1 manual remediation pattern (same shape as Plans 2026-05-01-001 F002 and 2026-05-01-005 F002). |
| 4. Deferred HIGH finding (commands_run formatting) | EC5-class platform-formatting debt (bullet-prefix `- \`$ git ...\`` instead of line-start `^$ ` regex match) | **Owned by Plan 2026-05-01-005** per D006 of this plan. Plan 005 is implementation-complete (F001 + F002 + F003 all `passes:true`); plan 005's F002 ships audit_writer prelude injection that resolves this finding-class structurally; plan 005's status flip itself is pending in the close-out queue. |

### Deferred HIGH finding — substantively resolved by Plan 005's implementation, even though Plan 005's status flip is pending

Plan 005's D010 explicitly cites this plan's D006 as the same-shape case ("Same shape as plan 2026-05-02-001-feat-resume-gate-discipline's D006 close-out (HIGH command-accountability deferred to this plan)"). Plan 005's D014 says "Plan 005 fully closed after this commit (F001+F002+F003 all passes:true)" — and the plan-dir inventory confirms F001/F002/F003 all `passes:true`, with `status: active` only because the formal status flip is queued.

So the deferred HIGH finding's class is **structurally resolved** by Plan 005's shipped F002 (audit_writer prelude injection from valid struct) + F003 (EC5 severity classifier downgrade with description preservation). Closing this plan does NOT supersede that deferral — it just makes explicit that the owning plan exists, has shipped the implementation, and awaits its own status-flip close-out.

### Brand-rename drift note (CLI form)

This plan was authored 2026-05-02, **before** the canonical-module flip shipped at `8edd953` (Plan 2026-05-04-001, closed `ab7c7dc`). Therefore:

- **In-plan text** (plan.md, decisions, this impl-time memo) uses legacy `jarvis resume` invocation form.
- **Live CLI** uses post-rename canonical `dontpanic resume`. The legacy `python -m jarvis_orchestrate resume` shim still works (with a one-shot `DeprecationWarning`).
- The acceptance contract was written against `jarvis` form; the live verification this turn used `dontpanic` form. Both invoke the same `_resume_main` argparse code path. **AC behavior identical, command name updated by canonical-module-flip.**

Same drift pattern as Plan 2026-05-05-001's VERSION drift (1.3.1 → 1.4.0) and Plan 2026-05-01-001's README form drift. Historical AC text intentionally NOT retro-updated.

### What this plan does NOT solve

Per scope discipline + queued decisions:

- **`stopped_no_progress` (verdict-based) breaker hardening** — the initial volley's terminal. Plan 2026-05-02-004 fixed only the count-based `stopped_diminishing_returns` breaker. The verdict-based `check_no_progress` distinction between feature-defect vs environmental unchanged-verdict remains a separate platform discussion (named in Plan 2026-05-04-004's MAY/MUST-NOT memo + Plan 2026-05-01-001's Q2 table — same un-triggered queued discussion).
- **Auto-continue-after-clear** — D002 explicitly deferred. After clearing a gate, the supervisor still requires a separate dispatch to actually resume the volley.
- **Renaming `resume` to something less ambiguous** — D003 explicitly deferred. The verb stays; the surface is now safe-by-default via the required flag.
- **Plan 2026-05-01-005's deferred HIGH finding** — D006's deferral is preserved. Plan 005's F002+F003 implementation resolves the finding-class; Plan 005's own status-flip close-out is the canonical record of that resolution, not this plan's.
- **Audit-envelope filename collision** — Plan 005 D013 deferred this to a follow-up, which became Plan 2026-05-02-002-fix-audit-envelope-filename. Not closed by this plan.

This plan's correctness claim is narrowly scoped: the CLI surface for clearing gates / breakers / bulk now requires explicit operator intent at every level. It does NOT close adjacent platform discussions (verdict-based no-progress hardening, auto-continue, naming) or downstream finding owners (Plan 005, Plan 002).
