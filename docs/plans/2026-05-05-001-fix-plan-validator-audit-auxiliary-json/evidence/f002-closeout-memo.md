# F002 close-out memo — 2026-05-05

Plan: `2026-05-05-001-fix-plan-validator-audit-auxiliary-json`
Feature: F002 — DontPanic subtree pull (agent-conventions v1.3.1) + regression coverage against existing `gate-state.json` fixtures across DontPanic plans.

## Direct-path rationale

F002 is a mechanical subtree pull + a regression run. Acceptance is byte-equality (subtree matches upstream v1.3.1) + diff-of-validator-output (every `gate-state.json` transitions from `✗` to `⊘`). No semantic decisions for an auditor to debate. Volley quota stays unjustified. Same logic as Plans A, C-F001/F002, D.

## Two-commit boundary preserved (D006)

| Commit | Repo | SHA | Scope |
|---|---|---|---|
| 1 | agent-conventions | `cedc190` (tag `v1.3.1`) | F001: `validate.py` logic + 4 fixtures + VERSION bump + dispatch tests |
| 2a | DontPanic (subtree squash) | `f213aba` | upstream `fb5c1a3..cedc190` contents into `claude/shared/` |
| 2b | DontPanic (subtree merge) | `7c900fc` | merge of squash commit into `main` |
| 2c | DontPanic (close-out) | this commit | Plan E evidence + features.json flip |

The DontPanic-side diff for `claude/shared/**` matches upstream v1.3.1 exactly (modulo squash commit metadata). No free-form edits — D010 honored.

## Subtree-pull mechanics — git hygiene note

`git subtree pull --prefix=claude/shared <upstream> v1.3.1 --squash` initially refused to run because the DontPanic worktree had pre-existing dirty/untracked carryover (operator-acknowledged). Resolution per operator authorization:

1. `git stash push --include-untracked -m "pre-F002-stash: carryover + Plan E dir while subtree pulls v1.3.1"`
2. Verified worktree clean.
3. Ran subtree pull from `$HOME/Documents/GitHub/agent-conventions` (local-path source — no remote configured upstream, matches v1.3.0 release pattern).
4. `git stash pop` — restored carryover + Plan E dir.

The carryover (`claude/PORTABILITY.md`, `claude/scripts/sync-harness.sh`, `dashboard/state/costs.json`, untracked `claude/__init__.py`, `claude/skills/changelog/`, miscellaneous `docs/plans/*/INBOX.md` files, etc.) is preserved unchanged across the operation.

## All 11 acceptance items verified

| # | AC | Result |
|---|---|---|
| 1 | `claude/shared/VERSION` reads `1.3.1` post-pull | ✓ confirmed via `cat` |
| 2 | Subtree byte-equal to agent-conventions v1.3.1 | ✓ `diff -r` returns empty for `schemas/`, `tests/`, `scripts/`, `resolver/`, `conventions/`, `claude-md/`, `skill-standard/`, `VERSION` (only `__pycache__/*.pyc` runtime artifacts differ — untracked, irrelevant) |
| 3 | gate-state.json transitions ✗ → ⊘ | ✓ 7 of 7 plans with gate-state.json transitioned (`docs/plans/2026-05-01-001-...`, `2026-05-01-004-...`, `2026-05-01-005-...`, `2026-04-29-001-...`, `2026-05-02-001-...`, `2026-05-04-002-...`, `2026-05-04-003-...`). 8th plan in the survey (`2026-05-01-002-feat-discord-notification-sink`) doesn't have a `gate-state.json` — null fixture. |
| 4 | Real audit envelopes still validate green | ✓ `diff <(grep "claude-implementer\|codex-auditor" baseline) <(grep ... post-pull)` is empty — every `*-i\d+.json` line identical pre/post |
| 5 | Real signoffs still validate green | ✓ `diff <(grep "signoff" baseline) <(grep ... post-pull)` is empty — every `signoff*.json` line identical pre/post |
| 6 | Full DontPanic orchestrate suite passes | ✓ **979 passed, 6 skipped** in 18.18s — exactly Plan D close-out baseline. Zero regressions. |
| 7 | No free-form edits in `claude/shared/` (D010) | ✓ Subtree-pull diff exactly matches upstream v1.3.1 contents |
| 8 | Worktree boundary preserved | ✓ DontPanic commit's diff (this commit + the two subtree-pull commits) confined to `claude/shared/**` and `docs/plans/2026-05-05-001-fix-plan-validator-audit-auxiliary-json/**`. Zero diffs to historical plan dirs (Plans 001–004 close-out memos byte-identical). Zero diffs to `scripts/dontpanic_orchestrate/**`. |
| 9 | Ruff + sanitization clean | ✓ sanitization: `0 findings, 714 files scanned`. Ruff: N/A — no `scripts/` or other Python source touched in this commit (only `claude/shared/**` subtree-pull contents + plan evidence markdown/JSON). |
| 10 | F002 close-out memo present | ✓ this file at `evidence/f002-closeout-memo.md` |
| 11 | Two-commit boundary preserved (D006) | ✓ F001 sealed in agent-conventions (`cedc190`); F002's DontPanic-side commits don't touch agent-conventions. Each side is independently revertable. |

## Validator output evidence

- `evidence/baseline-validator-output.txt` — pre-fix v1.3.0 validator behavior across the 8 surveyed plans (extracted by running `git show 4632079:claude/shared/schemas/v1.0/validate.py` against current plans).
- `evidence/post-pull-validator-output.txt` — post-fix v1.3.1 validator behavior across the same 8 plans.

The diff between these two files is exactly:

- 7× `✗ audit/gate-state.json — task_id: Field required; ...` → `⊘ audit/gate-state.json — auxiliary, skipped`

All other lines (signoff, audit envelopes, plan.md frontmatter, features.json validation) are byte-identical. The remaining `features.json` validation errors that are present in both outputs (e.g. Plan B's `evidence_refs.0: Input should be a valid dictionary or instance of EvidenceRef`) are pre-existing schema drift in those historical plans, not Plan E's concern.

## Validator self-check (irony note)

The patched validator at `claude/shared/schemas/v1.0/validate.py` is the validator that should validate Plan E itself. Run against this plan's directory:

```
[plan] 2026-05-05-001-fix-plan-validator-audit-auxiliary-json
  ✓ plan.md frontmatter
  ✓ features.json
✓ All plans validate against agent-conventions v1.0 schemas
```

(The plan dir's `audit/` is empty — only `.gitkeep` — so no dispatch cases trigger here. The validator has been used to lock its own plan's frontmatter + features schema across both Plan E lock and Plan E close-out.)

## EC validator caveat — closed at this commit

Per D006, this commit is the canonical record that the audit-auxiliary-JSON validator caveat (surfaced at Plan C F003 close-out) is closed going forward. agent-conventions v1.3.1 ships the type-aware dispatch; DontPanic now consumes it via the subtree.

Future plans omit any "skip the validator under audit/" workaround. The validator is usable on every plan-dir directly. Glam and SpinDineSwift will inherit this fix the next time they pull agent-conventions.

## Files NOT in this commit

- The pre-existing dirty / untracked carryover that's been excluded from every prior plan's commit boundary (`claude/PORTABILITY.md`, `claude/scripts/sync-harness.sh`, `dashboard/state/costs.json`, untracked `claude/__init__.py`, `claude/skills/changelog/`, miscellaneous `docs/plans/*/INBOX.md` files, etc.). Carried over from before Plan A; preserved unchanged across the F002 stash/pop operation.

## Queued caveats — NOT addressed by Plan E (per D008 of plan E itself)

Three caveats remain queued, each as a future standalone slice:

1. **Per-plan `loop_caps.subprocess_timeout_seconds`** (deferred from Plan C D003).
2. **`jarvis_orchestrate` shim removal timeline** (deferred from Plan A D006).
3. **Real `gate-state.schema.json`** (deferred per Plan E D001 — v1 skips by name; v2 may validate if shape stability warrants it).

## Five-plan sequence complete

| Plan | Slice | Path | Commits |
|---|---|---|---|
| A | Canonical Python module rename | direct | `8edd953` |
| B | Lifecycle-staged human gates | volley | `dc9c6cd` |
| C | Subprocess timeout / envelope durability (F001+F002+F003) | direct + direct + volley | `3b4c0b1`, `3d47ce2`, `89061a3` |
| D | EC5 classifier purity | direct | `4632079` |
| E | Plan validator audit-auxiliary-JSON dispatch | direct (cross-repo) | agent-conventions: `cedc190`/v1.3.1; DontPanic: `f213aba`+`7c900fc`+ this close-out |
