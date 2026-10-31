# Readable text probe

**Can you find the blocked job faster?** Old wording against new wording. Scan the left column for the blocked job, then the right.

**These records are synthetic.** The 20 command records and 20 dashboard event actions copy the shape, wording and outcome mix of real DontPanic records, but every plan name, path and project is made up and agent assignments are left out. Regenerate with `PYTHONPATH=scripts python -m dontpanic_orchestrate.readable_text_probe`.

Rows marked (unmapped; old text kept) are records the templates do not cover: calls that are not jobs (help, project listing), unknown event kinds and unknown volley outcomes. They keep their old text rather than a guessed status.

## Commands and results

| # | Old | New |
|---|-----|-----|
| 1 | plan lock --help → ok | (unmapped; old text kept) |
| 2 | plan lock /path/to/example-project/docs/plans/example-plan-a → ok | Passed: job example-plan-a — plan lock passes |
| 3 | approve --help → error | (unmapped; old text kept) |
| 4 | dispatch-from-plan --help → ok | (unmapped; old text kept) |
| 5 | approve example-plan-a pre_impl → error | Failed: job example-plan-a — approve fails |
| 6 | dispatch-from-plan /path/to/example-project/docs/plans/example-plan-a --feature F001 --max-iterations 2 → ok | Passed: job example-plan-a — dispatch-from-plan passes |
| 7 | dispatch-from-plan /path/to/example-project/docs/plans/example-plan-a --feature F001 --max-iterations 2 --confirm → error | Failed: job example-plan-a — dispatch-from-plan fails |
| 8 | approve example-plan-a on_escalation → ok | Passed: job example-plan-a — approve passes |
| 9 | dispatch-from-plan /path/to/example-project/docs/plans/example-plan-a --feature F001 --max-iterations 2 --confirm → interrupted | Stopped: job example-plan-a — dispatch-from-plan stops |
| 10 | projects add /path/to/example-project → error | (unmapped; old text kept) |
| 11 | projects list → ok | (unmapped; old text kept) |
| 12 | projects add example-project /path/to/example-project --no-hooks --dry-run → ok | (unmapped; old text kept) |
| 13 | plan lock /path/to/example-project/docs/plans/example-plan-b → error | Failed: job example-plan-b — plan lock fails |
| 14 | plan lock /path/to/example-project/docs/plans/example-plan-b → ok | Passed: job example-plan-b — plan lock passes |
| 15 | dispatch-from-plan /path/to/example-project/docs/plans/example-plan-b --feature F001 --max-iterations 3 --confirm → ok | Passed: job example-plan-b — dispatch-from-plan passes |
| 16 | resume example-plan-b --all → ok | Passed: job example-plan-b — resume passes |
| 17 | approve example-plan-c pre_merge → ok | Passed: job example-plan-c — approve passes |
| 18 | dispatch-from-plan /path/to/example-project/docs/plans/example-plan-c --feature F002 --max-iterations 2 --confirm → error | Failed: job example-plan-c — dispatch-from-plan fails |
| 19 | dispatch-from-plan /path/to/example-project/docs/plans/example-plan-d --feature F001 --max-iterations 1 --confirm → (no result) | Stopped: job example-plan-d — dispatch-from-plan stops |
| 20 | projects list → ok | (unmapped; old text kept) |

## Dashboard event actions

| # | Old | New |
|---|-----|-----|
| 1 | [info] Active AI work on example-plan-a. Volley begins (cap 2). | Running: job example-plan-a — volley starting |
| 2 | [needs_action] Approval needed on example-plan-a. Supervisor paused at gate `pre_impl`. Operator must approve before dispatch continues. | Blocked: job example-plan-a — approval needed (gate pre_impl) |
| 3 | [info] Active AI work on example-plan-a. Volley begins (cap 2). | Running: job example-plan-a — volley starting |
| 4 | [needs_action] Blocked work on example-plan-a — stopped cap. Volley terminated after 3 round(s) with status `stopped_cap`. Review the audit envelope before deciding next step. | Stopped: job example-plan-a — volley stops: cap |
| 5 | [needs_action] Blocked work on example-plan-a — breaker `iteration_cap` tripped. Circuit breaker `iteration_cap` tripped. Operator clearance required before dispatch continues. | Blocked: job example-plan-a — breaker iteration_cap blocks dispatch |
| 6 | [info] Active AI work on example-plan-b. Volley begins (cap 3). | Running: job example-plan-b — volley starting |
| 7 | [ready] AI work finished on example-plan-b. Volley completed after 2 round(s) with `signed_off`. No action needed. | Passed: job example-plan-b — audit signs off |
| 8 | [needs_action] Approval needed on example-plan-b. Supervisor paused at gate `pre_merge`. Operator must approve before dispatch continues. | Blocked: job example-plan-b — approval needed (gate pre_merge) |
| 9 | [needs_action] Blocked work on example-plan-b — merged. Volley terminated after 2 round(s) with status `merged`. Review the audit envelope before deciding next step. | Merged: job example-plan-b — merged |
| 10 | [info] Active AI work on example-plan-c. Volley begins (cap 1). | Running: job example-plan-c — volley starting |
| 11 | [needs_action] Blocked work on example-plan-c — blocked. Volley terminated after 1 round(s) with status `blocked`. Review the audit envelope before deciding next step. | Blocked: job example-plan-c — audit blocks |
| 12 | [needs_action] Approval needed on example-plan-c. Supervisor paused at gate `pre_impl`. Operator must approve before dispatch continues. | Blocked: job example-plan-c — approval needed (gate pre_impl) |
| 13 | [info] Active AI work on example-plan-c. Volley begins (cap 2). | Running: job example-plan-c — volley starting |
| 14 | [needs_action] Blocked work on example-plan-c — stopped no progress. Volley terminated after 2 round(s) with status `stopped_no_progress`. Review the audit envelope before deciding next step. | Stopped: job example-plan-c — volley stops: no progress |
| 15 | [needs_action] Verdict mismatch on example-plan-c. Auditor verdict and findings disagree. Review before dispatch continues. | (unmapped; old text kept) |
| 16 | [info] Active AI work on example-plan-d. Volley begins (cap 2). | Running: job example-plan-d — volley starting |
| 17 | [needs_action] Blocked work on example-plan-d — stopped budget. Volley terminated after 1 round(s) with status `stopped_budget`. Review the audit envelope before deciding next step. | Stopped: job example-plan-d — volley stops: budget |
| 18 | [needs_action] Blocked work on example-plan-d — breaker `global` tripped. Circuit breaker `global` tripped. Operator clearance required before dispatch continues. | Blocked: job example-plan-d — breaker global blocks dispatch |
| 19 | [needs_action] Blocked work on example-plan-d — stopped some new reason. Volley terminated after 2 round(s) with status `stopped_some_new_reason`. Review the audit envelope before deciding next step. | (unmapped; old text kept) |
| 20 | [ready] AI work finished on example-plan-d. Volley completed after 1 round(s) with `signed_off`. No action needed. | Passed: job example-plan-d — audit signs off |

## What changed

- The status word leads every line (Running, Passed, Failed, Blocked, Stopped, Merged), and its tense says whether the job is still going.
- Volley outcomes map one to one: signed off is Passed, merged is Merged, stopped_* is Stopped, blocked is Blocked. Unknown outcomes are not mapped.
- One vocabulary: a unit of work is a job and a pass/fail control is a gate; the gate name sits in a fixed trailing field.
- Failures say fails / blocks / stops, and every line has the same shape: `Status: job name — reason (fields)`.
- The dashboard event rows show the proposed wording only. The live dashboard titles are pinned by snapshot fixtures and stay unchanged until you decide to change that contract.

