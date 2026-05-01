# F002 confirmation memo

**Plan:** `2026-05-01-001-feat-onboarding-ux`
**Feature:** F002 (`dispatch-from-plan` CLI subcommand)
**Path taken:** Path 1 (manual cleanup + auditor-only confirmation, per corrected sequence v3 item 1).
**Status:** `passes: true` (operator-accepted). No implementer re-dispatch was performed; manual cleanup is preserved as `evidence/f002/manual-cleanup.diff`.

## What the close-out evidence covers

| Surface | Evidence | Captured |
|---|---|---|
| ruff check on F002 surface | inline run + log | `All checks passed!` against `cli.py` + `test_dispatch_from_plan.py` |
| ruff format on F002 surface | inline run + log | applied + verified via re-run |
| 12 dispatch tests | inline pytest log | 12 passed |
| Full orchestrate sweep | inline pytest log | 310 passed, 6 skipped |
| `--help` rendering | `evidence/f002/dispatch-from-plan-help.txt` | 42 lines, full epilog (4 readiness states + remediation pointers) visible |
| Manual cleanup diff | `evidence/f002/manual-cleanup.diff` | 379 lines |
| Sanitization | inline run | clean across 451 files |

## Auditor-only confirmation: how to read it

`audit/claude-auditor-i2.json` reports `audit_status: blocked` with one `high` finding. **This is meta, not F002 behavior.**

- The substantive verdict in the auditor's own summary: all 11 acceptance criteria verified by code reading (`cli.py:506–683` + `tests/test_dispatch_from_plan.py`); both i1 findings (ruff + help text) explicitly noted as addressed.
- The single `high` finding is an F023 EC5 prompt-format issue: the *auditor's own summary header* did not contain the `Env: dev` line that the F023 EC5 contract requires before logged side-effect commands. Same self-finding shape that codex-auditor-i1 produced. It is about the auditor prompt template, not F002 code.
- This memo is therefore the primary evidence that the auditor's blocked status is accepted as meta-only. The audit JSON remains in the repo as supporting evidence; this file is the human-authored interpretation.

## Two follow-ups recorded (not blockers)

1. **Single-agent `--role auditor` defaults to `agents_required[0]`.** That broke the cross-vendor adversarial invariant for the i2 confirmation (Claude graded Claude). The invariant only holds in `--volley` mode today. Worth a Jarvis CLI improvement so `--role auditor` defaults to `agents_required[1]`. Recorded in `decisions.jsonl` D008.
2. **F023 EC5 auditor-prompt prelude is missing the target-context block.** Both codex-i1 and claude-i2 produced the same self-finding. The auditor prompt template should auto-prepend `Repo: / Env: / Project: / Command:` before logged side-effects, just like the implementer template does. Recorded in `decisions.jsonl` D009.

## Items intentionally NOT staged with this commit

- `audit/gate-state.json` — gate-clearance state, not durable F002 evidence; mutates on every dispatch. Also currently fails the agent-conventions validator (it gets matched against the audit-record schema but it is not an audit record — pre-existing validator bug, separate concern).
- `audit/signoff-2026-05-01-001-feat-onboarding-ux.json` — currently records `signoff: false, next_action: remediate` from the volley terminal. Conflicts with `passes: true` and will confuse future readers/tools. The volley audit JSONs (`claude-implementer-i0/i1`, `codex-auditor-i0/i1`, `claude-auditor-i2`) and `transcript.md` / `INBOX.md` similarly belong to dispatch state, not durable evidence. If we want to archive the dispatch trace, do it under `evidence/f002/pre-remediation/` in a follow-up commit.
