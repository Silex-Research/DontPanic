# Checking integration readiness

`dontpanic plan-review PLAN` now checks current applicable skills as well as
surface dispositions against `conventions.json`. A goal-only skill match is
included even if the plan declares no surfaces. Matching is read-only and fresh;
the lock-time sidecar is not overwritten. Findings remain advisory. The existing
v0 JSON scope-report contract is unchanged; disposition warnings appear in text.

`dontpanic doctor --runtime-evidence --skip-auth --json` opts into the shipped
iOS, Android, backend and harness registry probes. Missing optional platforms
warn without blocking core use. Plain doctor does not run these probes. This
flag performs readiness checks, not captures; adb may start its local server.
`--skip-auth` excludes the Firebase probe before it runs. Do not combine this mode
with agent/project onboarding, channel checks, upgrade or acknowledgment modes.
Web driver/browser readiness remains capture-time; there is no new web registry
probe in this slice. A successful harness import is not evidence a journey ran.

Command recording, capture orchestration and planner revision remain proposals
under `docs/brainstorms/2026-09-06-*.md`; these commands are not implemented here.
