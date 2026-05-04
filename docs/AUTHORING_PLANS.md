# Authoring Plans for DontPanic

DontPanic runs work from plan directories. A human can write one by hand, and
an LLM can generate one as long as it follows the same contract. The contract is
small: a plan says what should be done, features say how completion is judged,
decisions record why the scope looks the way it does, and evidence/audit files
prove what happened.

This is authoring guidance, not the Phase C intake engine. F004 does not embed sufficiency logic, discovery rules, or cost-model decisions; those land in Phase C.

## Plan Directory Layout

The source of truth is the schema set under
[`claude/shared/schemas/v1.0/`](../claude/shared/schemas/v1.0/) and the
upstream agent-conventions schemas. This document summarizes the files; it does
not duplicate or re-derive the schemas.

Every plan directory lives under `docs/plans/<plan-id>/`:

```text
docs/plans/2026-05-04-001-feat-example/
  plan.md
  features.json
  decisions.jsonl
  audit/
  evidence/
```

| File | Role |
|---|---|
| `plan.md` | Human-readable contract: frontmatter, target environment, scope, non-goals, sequencing. |
| `features.json` | Machine-checkable feature list. This is the acceptance source of truth. |
| `decisions.jsonl` | Append-only decisions. Each line is one JSON object explaining a scope or design choice. |
| `audit/` | Machine-readable auditor/signoff envelopes written during execution. |
| `evidence/` | Human-readable close-out notes, logs, fixtures, screenshots, and other proof. |

Minimum authoring rule: do not write implementation prose until the feature
acceptance is specific enough that another agent can say pass/fail without
guessing.

## Minimum Valid Plan

This smallest example validates, but it is intentionally too small for most
real work. Use it to learn the file shape.

<!-- dontpanic-plan-example: minimum-valid -->
````text
=== plan.md
---
id: 2026-05-04-001-feat-minimum-valid-plan
title: Minimum Valid Plan Example
type: feat
tier: trivial
status: draft
date: "2026-05-04"
description: |
  Demonstrates the smallest DontPanic plan shape that still validates.
agents_required:
  - claude
human_gates:
  - pre_impl
loop_caps:
  max_iterations: 1
  no_progress_threshold: 1
  wall_clock_hours: 1
  hard_stop: false
privacy_tier: internal
---

## Target

```yaml
target_env: dev
target_project: none
```

## Scope

Write one small documentation note.

=== features.json
{
  "task_id": "2026-05-04-001-feat-minimum-valid-plan",
  "schema_version": "1.0",
  "features": [
    {
      "id": "F001",
      "category": "doc",
      "phase": 1,
      "description": "Create one small documentation note.",
      "steps": ["Add docs/example-note.md with one paragraph."],
      "acceptance": "docs/example-note.md exists and contains at least one paragraph.",
      "passes": false
    }
  ]
}

=== decisions.jsonl
{"id":"D001","ts":"2026-05-04T00:00:00Z","by":"operator","title":"Keep the example minimal","body":"This example exists to show the smallest valid plan directory shape."}
````

## Two Substantive Examples

### Feature-Add Plan

Use this shape when the request is a known feature with clear target surface and
acceptance criteria.

<!-- dontpanic-plan-example: feature-add -->
````text
=== plan.md
---
id: 2026-05-04-002-feat-export-report-button
title: Add Export Report Button
type: feat
tier: local
status: draft
date: "2026-05-04"
description: |
  Add a report-export button to the analytics dashboard without changing the
  report-generation backend.
motivation: |
  Operators can view reports today but cannot download a CSV from the dashboard.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 2
  no_progress_threshold: 2
  wall_clock_hours: 2
  hard_stop: false
privacy_tier: internal
protected_paths:
  - docs/security/
---

## Target

```yaml
target_env: dev
target_project: none
```

## Scope

Add a visible export button to the existing reports page. Reuse the existing
CSV endpoint. Do not add a new export service.

## Out of Scope

- New report formats.
- Backend schema changes.
- Authentication changes.

=== features.json
{
  "task_id": "2026-05-04-002-feat-export-report-button",
  "schema_version": "1.0",
  "features": [
    {
      "id": "F001",
      "category": "functional",
      "phase": 1,
      "description": "Add a dashboard export button that calls the existing CSV endpoint.",
      "steps": [
        "Add the button to the existing reports page.",
        "Wire it to the existing CSV endpoint without adding a new backend route.",
        "Add tests for visible enabled state, disabled loading state, and error state."
      ],
      "acceptance": "The reports page shows an Export CSV button, clicking it calls the existing CSV endpoint, loading and error states are tested, and no new backend route is added.",
      "passes": false
    }
  ]
}

=== decisions.jsonl
{"id":"D001","ts":"2026-05-04T00:00:00Z","by":"operator","title":"Reuse existing CSV endpoint","body":"The feature is UI wiring, not a backend export rewrite."}
{"id":"D002","ts":"2026-05-04T00:05:00Z","by":"operator","title":"Keep formats out of scope","body":"PDF and XLSX exports are separate product decisions and should not ride this slice."}
````

### Bug-Fix Plan

Use this shape when the request starts from a production issue or failing
behavior. The first feature should normally pin the reproducer before fixing.

<!-- dontpanic-plan-example: bug-fix -->
````text
=== plan.md
---
id: 2026-05-04-003-fix-login-retry-loop
title: Fix Login Retry Loop
type: fix
tier: local
status: draft
date: "2026-05-04"
description: |
  Fix the login page retry loop where failed token refreshes repeatedly submit
  the same request without surfacing an actionable error.
motivation: |
  Production users see a spinner loop instead of an error when token refresh
  fails. The fix needs a reproducer before implementation.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 2
  no_progress_threshold: 2
  wall_clock_hours: 2
  hard_stop: false
privacy_tier: internal
---

## Target

```yaml
target_env: dev
target_project: none
```

## Scope

Pin the retry-loop behavior with a failing test, then change the login flow so
a failed token refresh stops retrying and renders a recoverable error.

## Out of Scope

- Provider migration.
- Session-storage redesign.
- New authentication screens.

=== features.json
{
  "task_id": "2026-05-04-003-fix-login-retry-loop",
  "schema_version": "1.0",
  "features": [
    {
      "id": "F001",
      "category": "test",
      "phase": 1,
      "description": "Add a failing regression test for the login retry loop.",
      "steps": [
        "Simulate token-refresh failure.",
        "Assert the login flow attempts refresh once and surfaces an error."
      ],
      "acceptance": "A regression test fails before the implementation change and proves refresh is attempted once, not repeatedly.",
      "passes": false
    },
    {
      "id": "F002",
      "category": "functional",
      "phase": 2,
      "description": "Stop the retry loop and render a recoverable login error.",
      "steps": [
        "Update the login retry branch.",
        "Make the F001 regression test pass.",
        "Run the existing login test suite."
      ],
      "acceptance": "The login page stops retrying after token refresh failure, renders a recoverable error, and the F001 regression plus existing login tests pass.",
      "passes": false,
      "depends_on": ["F001"]
    }
  ]
}

=== decisions.jsonl
{"id":"D001","ts":"2026-05-04T00:00:00Z","by":"operator","title":"Reproducer first","body":"A production issue fix starts with a failing test so the auditor can distinguish the bug from incidental refactor."}
{"id":"D002","ts":"2026-05-04T00:05:00Z","by":"operator","title":"No auth redesign","body":"The slice fixes retry-loop behavior only; provider and session architecture are separate plans."}
````

## Sufficiency vs Implementation

A brief is plan-ready when DontPanic can identify:

- project
- desired outcome
- target surface
- constraints
- acceptance criteria
- risk level
- evidence needed
- scope boundary

If any of those are missing, the correct output is not implementation. The
correct output is a clarification request or a discovery plan. Vague input like
"make onboarding better" should not become code until the target user, current
failure, and acceptance evidence are defined.

Examples:

| Input | Sufficient? | Right next output |
|---|---|---|
| "Add a CSV export button to the existing reports page; reuse the current CSV endpoint; success is button + loading/error tests." | Yes | Draft an implementation plan. |
| "Fix login, users say it spins forever." | Partly | Draft a bug-fix plan with reproducer-first acceptance, or ask for logs if the failure surface is unknown. |
| "Make the app enterprise-ready." | No | Draft a discovery/governance plan or ask clarifying questions. |

Again: this is authoring guidance, not the Phase C intake engine. F004 does not embed sufficiency logic, discovery rules, or cost-model decisions; those land in Phase C.

## Validation

Validate a plan directory before dispatch:

```bash
python3 claude/shared/schemas/v1.0/validate.py docs/plans/<plan-id>
```

Once F002's MCP server is running, agents can call `validate_plan` through
`dontpanic mcp serve` and show the result to the user before asking whether to
dispatch.

Do not dispatch a plan just because it validates. Validation means the files
match the schema. It does not mean the plan is strategically correct, complete,
or approved by the human operator.
