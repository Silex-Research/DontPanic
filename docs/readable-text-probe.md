# Readable text probe

**Can you find the blocked job faster?** The same real entries, old wording against new wording. Scan the left column for the blocked job, then the right.

Entries: 20 command records and 20 dashboard event actions (the last 20 of each; fewer means fewer exist). Paths, ids and tokens are redacted.

## Commands and results

| # | Old | New |
|---|-----|-----|
| 1 | plan lock --help → ok | Passed: job plan lock — command passes |
| 2 | plan lock ~/silex/woz/spn-057/docs/plans/2026-10-26-001-fix-spn057-mirror-chainrating → ok | Passed: job 2026-10-26-001-fix-spn057-mirror-chainrating — plan lock passes |
| 3 | approve --help → error | Failed: job approve — command fails |
| 4 | dispatch-from-plan --help → ok | Passed: job dispatch-from-plan — command passes |
| 5 | approve 2026-10-26-001-fix-spn057-mirror-chainrating pre_impl → error | Failed: job 2026-10-26-001-fix-spn057-mirror-chainrating — approve fails |
| 6 | dispatch-from-plan ~/silex/woz/spn-057/docs/plans/2026-10-26-001-fix-spn057-mirror-chainrating --feature F001 --max-iterations 2 → ok | Passed: job 2026-10-26-001-fix-spn057-mirror-chainrating — dispatch-from-plan passes |
| 7 | dispatch-from-plan ~/silex/woz/spn-057/docs/plans/2026-10-26-001-fix-spn057-mirror-chainrating --feature F001 --max-iterations 2 --confirm → error | Failed: job 2026-10-26-001-fix-spn057-mirror-chainrating — dispatch-from-plan fails |
| 8 | approve 2026-10-26-001-fix-spn057-mirror-chainrating on_escalation → ok | Passed: job 2026-10-26-001-fix-spn057-mirror-chainrating — approve passes |
| 9 | dispatch-from-plan ~/silex/woz/spn-057/docs/plans/2026-10-26-001-fix-spn057-mirror-chainrating --feature F001 --max-iterations 2 --confirm → interrupted | Stopped: job 2026-10-26-001-fix-spn057-mirror-chainrating — dispatch-from-plan stops |
| 10 | projects add ~/silex/woz/spn-057 → error | Failed: job projects add — command fails |
| 11 | projects list → ok | Passed: job projects list — command passes |
| 12 | projects add spn-057-woz ~/silex/woz/spn-057 --no-hooks --dry-run → ok | Passed: job projects add — command passes |
| 13 | projects add spn-057-woz ~/silex/woz/spn-057 --no-hooks → ok | Passed: job projects add — command passes |
| 14 | projects list → ok | Passed: job projects list — command passes |
| 15 | projects list → ok | Passed: job projects list — command passes |
| 16 | plan lock --help → ok | Passed: job plan lock — command passes |
| 17 | plan lock ~/silex/woz/spn-057/docs/plans/2026-10-26-001-fix-spn057-mirror-chainrating → error | Failed: job 2026-10-26-001-fix-spn057-mirror-chainrating — plan lock fails |
| 18 | plan lock ~/silex/woz/spn-057/docs/plans/2026-10-26-001-fix-spn057-mirror-chainrating → ok | Passed: job 2026-10-26-001-fix-spn057-mirror-chainrating — plan lock passes |
| 19 | dispatch-from-plan ~/silex/woz/spn-057/docs/plans/2026-10-26-001-fix-spn057-mirror-chainrating --feature F001 --max-iterations 2 --confirm → error | Failed: job 2026-10-26-001-fix-spn057-mirror-chainrating — dispatch-from-plan fails |
| 20 | dispatch-from-plan ~/silex/woz/spn-057/docs/plans/2026-10-26-001-fix-spn057-mirror-chainrating --feature F002 --max-iterations 2 --confirm → error | Failed: job 2026-10-26-001-fix-spn057-mirror-chainrating — dispatch-from-plan fails |

## Dashboard event actions

| # | Old | New |
|---|-----|-----|
| 1 | [needs_action] Blocked work on 2026-08-03-001-feat-cio-control-tower-v2 — stopped cap. Volley terminated after 3 round(s) with status `stopped_cap`. Review the audit envelope before deciding next step. User impact not declared for this feature. | Blocked: job 2026-08-03-001-feat-cio-control-tower-v2 — stopped cap |
| 2 | [info] Active AI work on 2026-08-03-001-feat-cio-control-tower-v2. Volley begins with implementer `claude` and auditor `codex` (cap 2). | Running: job 2026-08-03-001-feat-cio-control-tower-v2 — volley starting |
| 3 | [needs_action] Blocked work on 2026-08-03-001-feat-cio-control-tower-v2 — breaker `iteration_cap` tripped. Circuit breaker `iteration_cap` tripped. Operator clearance required before dispatch continues. User impact not declared for this feature. | Blocked: job 2026-08-03-001-feat-cio-control-tower-v2 — breaker `iteration_cap` tripped |
| 4 | [needs_action] Blocked work on 2026-08-03-001-feat-cio-control-tower-v2 — stopped cap. Volley terminated after 3 round(s) with status `stopped_cap`. Review the audit envelope before deciding next step. User impact not declared for this feature. | Blocked: job 2026-08-03-001-feat-cio-control-tower-v2 — stopped cap |
| 5 | [info] Active AI work on 2026-08-29-002-fix-today-day-wide-reuse. Volley begins with implementer `codex` and auditor `claude` (cap 1). | Running: job 2026-08-29-002-fix-today-day-wide-reuse — volley starting |
| 6 | [needs_action] Approval needed on 2026-08-29-002-fix-today-day-wide-reuse. Supervisor paused. Operator must approve before dispatch continues. User impact not declared for this feature. | Blocked: job 2026-08-29-002-fix-today-day-wide-reuse — approval needed (gate pre_merge) |
| 7 | [info] Active AI work on 2026-08-29-002-fix-today-day-wide-reuse. Volley begins with implementer `codex` and auditor `claude` (cap 1). | Running: job 2026-08-29-002-fix-today-day-wide-reuse — volley starting |
| 8 | [needs_action] Blocked work on 2026-08-29-002-fix-today-day-wide-reuse — breaker `iteration_cap` tripped. Circuit breaker `iteration_cap` tripped. Operator clearance required before dispatch continues. User impact not declared for this feature. | Blocked: job 2026-08-29-002-fix-today-day-wide-reuse — breaker `iteration_cap` tripped |
| 9 | [needs_action] Blocked work on 2026-08-29-002-fix-today-day-wide-reuse — stopped cap. Volley terminated after 2 round(s) with status `stopped_cap`. Review the audit envelope before deciding next step. User impact not declared for this feature. | Blocked: job 2026-08-29-002-fix-today-day-wide-reuse — stopped cap |
| 10 | [needs_action] Approval needed on 2026-08-29-002-fix-today-day-wide-reuse. Supervisor paused. Operator must approve before dispatch continues. User impact not declared for this feature. | Blocked: job 2026-08-29-002-fix-today-day-wide-reuse — approval needed (gate breaker:iteration_cap) |
| 11 | [needs_action] Approval needed on 2026-08-29-003-migration-user-scoped-look-receipts. Supervisor paused. Operator must approve before dispatch continues. User impact not declared for this feature. | Blocked: job 2026-08-29-003-migration-user-scoped-look-receipts — approval needed (gate on_escalation) |
| 12 | [info] Active AI work on 2026-08-29-003-migration-user-scoped-look-receipts. Volley begins with implementer `codex` and auditor `claude` (cap 2). | Running: job 2026-08-29-003-migration-user-scoped-look-receipts — volley starting |
| 13 | [needs_action] Blocked work on 2026-08-29-003-migration-user-scoped-look-receipts — breaker `iteration_cap` tripped. Circuit breaker `iteration_cap` tripped. Operator clearance required before dispatch continues. User impact not declared for this feature. | Blocked: job 2026-08-29-003-migration-user-scoped-look-receipts — breaker `iteration_cap` tripped |
| 14 | [needs_action] Blocked work on 2026-08-29-003-migration-user-scoped-look-receipts — stopped cap. Volley terminated after 3 round(s) with status `stopped_cap`. Review the audit envelope before deciding next step. User impact not declared for this feature. | Blocked: job 2026-08-29-003-migration-user-scoped-look-receipts — stopped cap |
| 15 | [needs_action] Approval needed on 2026-10-26-001-fix-spn057-mirror-chainrating. Supervisor paused. Operator must approve before dispatch continues. User impact not declared for this feature. | Blocked: job 2026-10-26-001-fix-spn057-mirror-chainrating — approval needed (gate on_escalation) |
| 16 | [info] Active AI work on 2026-10-26-001-fix-spn057-mirror-chainrating. Volley begins with implementer `claude` and auditor `codex` (cap 2). | Running: job 2026-10-26-001-fix-spn057-mirror-chainrating — volley starting |
| 17 | [info] Active AI work on 2026-10-26-001-fix-spn057-mirror-chainrating. Volley begins with implementer `claude` and auditor `codex` (cap 2). | Running: job 2026-10-26-001-fix-spn057-mirror-chainrating — volley starting |
| 18 | [needs_action] Approval needed on 2026-10-26-001-fix-spn057-mirror-chainrating. Supervisor paused. Operator must approve before dispatch continues. User impact not declared for this feature. | Blocked: job 2026-10-26-001-fix-spn057-mirror-chainrating — approval needed (gate pre_merge) |
| 19 | [info] Active AI work on 2026-10-26-001-fix-spn057-mirror-chainrating. Volley begins with implementer `claude` and auditor `codex` (cap 2). | Running: job 2026-10-26-001-fix-spn057-mirror-chainrating — volley starting |
| 20 | [needs_action] Approval needed on 2026-10-26-001-fix-spn057-mirror-chainrating. Supervisor paused. Operator must approve before dispatch continues. User impact not declared for this feature. | Blocked: job 2026-10-26-001-fix-spn057-mirror-chainrating — approval needed (gate pre_merge) |

## What changed

- The status word leads every line (Running, Passed, Failed, Blocked, Stopped), and its tense says whether the job is still going.
- One vocabulary: a unit of work is a job and a pass/fail control is a gate; the gate name sits in a fixed trailing field.
- Failures say fails / blocks / stops, and every line has the same shape: `Status: job name — reason (fields)`.
- The dashboard event rows show the proposed wording only. The live dashboard titles are pinned by snapshot fixtures and stay unchanged until you decide to change that contract.

