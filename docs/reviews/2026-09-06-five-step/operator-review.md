# Operator branch review

Reviewed source: `feat/audience-first-plan-contracts` at 438250e, eight commits
after PR67 head de0d78a. Do not bulk-merge the branch.

| Commit | Change | Review disposition |
|---|---|---|
| d1df5b6 | Global breaker preflight | Useful read-only diagnostic; retain after timing/output review. |
| faa647b | Explicit feature selection for multi-feature dispatch | Useful safety improvement. Add explicit unknown-ID rejection and compatibility checks for generated commands before promotion. |
| 53b7d4e | Cwd versus bound worktree | Useful diagnostic; unreadable registry must remain distinguishable from unbound. |
| 94b6928 | Breaker last-hit/lift time | Needs changes: oldest-hit expiry is not necessarily the breaker release time. |
| a73d7df | Ban CodeRabbit/browser login in auditor prompt | Keep independent review, but review the blanket shared forbidden-command insertion separately; it affects implementer prompts too. |
| 3eb4d75 | Explicit feature for what-now | Align with dispatch, reject unknown IDs and verify every generated invocation. |
| 49466b1 | Remaining completion requirements | Blocking evidence-honesty defect; do not merge as written. |
| 438250e | Fable prompt/skill edits | Mixed scope, including large skill deletions. Separate from operator runtime fixes and review against current main. |

## Reproduced findings

1. Four hits at 08:00, 09:00, 10:00, 11:00 with threshold three and a 24-hour
   window report release at 08:00 the next day. Three hits remain then, so the
   breaker is still tripped. The correct threshold-crossing expiry is 09:00.
   Fix using the sorted hit at index `hit_count - threshold`, while preserving
   the actual cutoff inclusivity and returning no release time when not tripped.
2. `_tests_status` returns `passed` for an existing `test_output` file containing
   `FAILED test_journey; exit status 1`. File presence is not execution success.
   It also selects plan-wide regression artifacts by mtime rather than binding
   proof to the requested feature, iteration, command and code revision.
3. `_supervisor_receipt_blocker` checks only that a plan-level receipt exists.
   It does not establish that the receipt belongs to this feature or code state.

Executable reproduction: `operator-probes.py`; output: `operator-probes.log`.
These are review probes, not changes to the parked branch. Existing branch and
cleanup recovery archive remain intact. Recommended next slice: bounded feature
selection + truthful breaker/worktree diagnostics; completion claims require the
command-evidence contract first.
