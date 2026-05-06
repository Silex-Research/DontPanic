# F002 close-out — DontPanic subtree-pull v1.4.0

**Boundary commit:** subtree pull from `$HOME/Documents/GitHub/agent-conventions` at tag `v1.4.0` (= agent-conventions commit `d5bab1b`).

**DontPanic commits:**
- `7f1d354` — `Squashed 'claude/shared/' changes from cedc190..d5bab1b`
- `08e2b26` — `Merge commit '7f1d354b4d013a7fccefe8595add05bc68755365'`

Two-commit boundary preserved (D009): F001 = `d5bab1b` lives in agent-conventions; F002 = `7f1d354` + `08e2b26` live in DontPanic. Neither commit touches the other repo.

## Acceptance evidence

1. **`claude/shared/VERSION` reads `1.4.0`** — confirmed via `cat`.

2. **Byte-equal subtree** — `diff -r --exclude='__pycache__' $HOME/Documents/GitHub/agent-conventions/schemas/v1.0/ claude/shared/schemas/v1.0/` returned exit 0 (no diffs).

3. **Backward compat verified** — baseline-vs-post-pull diff over `docs/plans/2026-05-*` returned exit 0 (byte-identical output). The two pre-existing carryover failures (`evidence_refs` structural errors in `2026-05-01-005-feat-target-context-platform-fix` and `2026-05-04-002-fix-supervisor-lifecycle-staged-gates`) are unchanged by the pull. Plan F1 itself validates green; no surveyed plan declares `goal_type`, so the new applicability rule does not engage. See `evidence/f002-baseline-validator-output.txt` and `evidence/f002-post-pull-validator-output.txt`.

4. **Full orchestrate suite passes** — `PYTHONPATH=scripts python3 -m pytest scripts/dontpanic_orchestrate/tests/ -p no:cacheprovider` reported **997 passed, 6 skipped** in 19.30s. Matches the F0 close-out baseline exactly. Zero regressions.

5. **Sanitization clean** — `python3 scripts/sanitization_check.py` reported `✓ no campaign IDs or secret shapes in sanitized surface (753 files scanned)`.

6. **Worktree boundary** — subtree commits `7f1d354` + `08e2b26` touched only `claude/shared/**`. Unrelated working-tree carryover (`claude/PORTABILITY.md`, `claude/scripts/sync-harness.sh`, `dashboard/state/costs.json`, untracked files) was stashed before the pull and popped after, with no interference. F002 evidence files (`f002-baseline-validator-output.txt`, `f002-post-pull-validator-output.txt`, this memo) are scoped under the F1 plan dir.

7. **Two-commit boundary preserved (D009)** — see commit list above.

## Follow-up commit

A separate close-out commit on the DontPanic side stages only the F002 evidence files + `features.json` flip + `decisions.jsonl` D-entry — keeping the mechanical subtree-pull commits pristine per Plan E precedent.
