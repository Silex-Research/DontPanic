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

## What Should I Create?

Before writing a plan directory, classify the ask. DontPanic recognizes five
shapes of work. They share the same directory layout, but they answer different
questions and have different acceptance bars.

| Ask kind | Use it when | Ships | Dispatchable today? |
|---|---|---|---|
| Implementation plan | One concrete outcome, bounded feature set, dependencies known. | Code, tests, or docs. | Yes, once it locks. |
| Roadmap | Strategic outcome across multiple releases or milestones; some milestones are trigger-gated. | Tracking narrative plus references to child plans. | The roadmap itself is not dispatched. Only its child plans are. |
| Investigation | A question that needs evidence before scope is safe to commit. | Notes, traces, evidence files, recommendations. May propose follow-up plans. | Yes, but the feature acceptance is "evidence and recommendation produced," not "code shipped." |
| Operator setup task | A configuration, credential, registry, or environment change a human must perform once. | A documented setup step plus evidence (run logs, screenshots, registry diffs). | Yes, but the human gate is the actual work surface. |
| Design or product specification | A user-facing experience or product contract that must be agreed before implementation can be acceptance-checked. | A written spec (flows, copy, contracts, decisions) under `docs/`. May reference future implementation plans. | Yes; the acceptance is "spec is reviewed and locked," not "code shipped." |

Roadmaps track strategy. Child plans ship code and docs. A roadmap names the
future state, lists its child-plan sequence, declares non-goals, and records
trigger conditions for milestones that are not ready yet. A roadmap does not
hold the implementation that lands in a release; that work lives in a child
plan with its own `plan.md`, `features.json`, and audit trail.

### Decision rules

- If acceptance fits inside one feature set with known dependencies, write an
  implementation plan.
- If the ask spans multiple releases or audiences and some milestones are
  trigger-gated, write a roadmap plus at least one executable child plan for
  the V0 slice.
- If the next safe step is "produce evidence about X," write an investigation.
  Investigations may recommend follow-up implementation plans but should not
  embed the implementation themselves.
- If the work is "a human runs a console step, a CLI, or wires a secret," write
  an operator setup task. The feature acceptance points at evidence the work
  happened (manifest entry, registry diff, signed-off checklist).
- If the work is "agree what the experience or contract should be," write a
  design/product specification plan. Ship the spec document plus any decisions
  needed to lock it. Treat later implementation as a separate child plan.

### Anti-patterns

- Locking every future milestone as a feature in one giant plan. Use a roadmap
  with explicit trigger conditions for non-ready milestones, and one executable
  child plan for the V0 slice.
- Writing a roadmap with no executable child. A roadmap with no V0 child is a
  product brief, not a dispatchable plan.
- Calling a question an implementation plan. If the answer is unknown, write
  an investigation first and let it propose the implementation shape.
- Treating a one-time operator setup like product code. The acceptance evidence
  is registry/manifest/log proof, not a test suite.
- Treating "we need to agree what this looks like" as an implementation slice.
  Write the spec, lock it, then schedule the implementation plan.

### Trigger conditions for future milestones

A roadmap may name V1, V2, and later milestones, but it MUST also name the
condition that has to hold before each one is dispatched. Examples of valid
triggers:

- "V0 has been in use for at least two weeks and at least two operator
  decisions were missed."
- "At least three roadmap-style tracking parents are active and the lack of
  schema-level roadmap semantics caused a real dispatch failure."

Future milestones without a trigger condition are notes, not plans. DontPanic
must not dispatch a future milestone until it has been split into its own
executable child plan with locked acceptance.

### Release-impact prompt

Before locking a plan, the author answers a short release-impact prompt. The
full checklist and the path/surface pattern table live in
[`docs/RELEASE_IMPACT.md`](./RELEASE_IMPACT.md). The advisory checker shipped
with `dontpanic next` (plan 2026-05-23-007 F003) renders the same advice
automatically when it can infer the affected surfaces from the plan's
`surfaces`, `allowed_paths`, and feature step path tokens.

Plan authors still answer it inline in their plan or in `evidence/`:

- Does this change touch the root README, onboarding/getting-started, or
  `dontpanic init|doctor` behavior?
- Does it change the architecture map, dashboard UX, or dashboard state shape?
- Does it add, rename, or remove an operator-facing CLI command, flag, or
  help text?
- Does it touch a capability manifest, setup guidance, or environments
  registry?
- Does it change a schema in `claude/shared/schemas/`?
- Does it require a root `CHANGELOG.md` entry, a `claude/shared/CHANGELOG.md`
  entry, or both?
- Does it change public metadata, social preview, or repo discoverability
  assets?

If any answer is yes, list the surfaces in the plan and include the updates in
the feature acceptance. "We will remember to update the README" is not an
acceptance clause. The advisory in `dontpanic next` is a backstop — it catches
obvious omissions but does not replace this answer.

Root `CHANGELOG.md` records product-facing changes (the CLI, dashboard,
README/onboarding, capability manifests, public metadata).
`claude/shared/CHANGELOG.md` records changes to the agent-conventions subtree
(schemas, conventions, Pydantic mirrors). See
[`docs/RELEASE_IMPACT.md`](./RELEASE_IMPACT.md) for the full path → surface
table that determines which (if either) is required.

### V0 schema scope

V0 of the planning-intelligence roadmap does not add schema-level
`plan_kind`, `investigation`, or `design-spec` enforcement. The five-shape
vocabulary above is authoring guidance only. The plan schema still uses the
existing `type` enum (`feat`, `fix`, `refactor`, `migration`, `infra`), and a
roadmap continues to live as an `infra`-typed tracking plan with child plans
referenced through `orchestration.parent_plan_id`. First-class schema fields
for `plan_kind`, milestone trigger conditions, and dispatch refusal for future
milestones wait for V3 of the roadmap.

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

## Roadmap and Child Plan

Use this shape when the ask is strategic and spans multiple releases. The
roadmap is the tracking parent. It does not ship code. Its V0 child plan does.

### Roadmap (tracking parent)

<!-- dontpanic-plan-example: roadmap-tracking-parent -->
````text
=== plan.md
---
id: 2026-05-04-010-infra-onboarding-revamp-roadmap
title: Onboarding Revamp Roadmap
type: infra
tier: architectural
status: draft
date: "2026-05-04"
description: |
  Tracking parent for moving DontPanic's first-run onboarding from a single
  README walkthrough toward a guided init + doctor + capability-bound setup.
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

## Strategic Outcome

A new operator can install DontPanic, register one project, and reach a green
`dontpanic doctor` without reading the architecture map.

## Milestones

### V0 - Guided init

Executable child: 2026-05-04-011-feat-onboarding-init-guided.

Scope: replace the README walkthrough with an interactive `dontpanic init`
that writes a starter project registry and points at `dontpanic doctor`.

Status: lockable after operator review.

### V1 - Capability-bound setup

Future child.

Scope: bind init to capability manifests so missing CLIs and secrets are
called out before first dispatch.

Trigger: V0 ships and at least two operators report doctor was the first
place they noticed a missing CLI.

### V2 - Dashboard onboarding surface

Future child.

Scope: render the same init checklist inside the operator console.

Trigger: dashboard project-selector substrate is in use and operators ask for
a non-CLI onboarding entrypoint.

## Out Of Scope For V0

- Multi-project onboarding.
- Cloud-provider account creation.
- Auto-installing missing CLIs.

=== features.json
{
  "task_id": "2026-05-04-010-infra-onboarding-revamp-roadmap",
  "schema_version": "1.0",
  "features": [
    {
      "id": "F001",
      "category": "doc",
      "phase": 1,
      "description": "Track onboarding revamp milestones and dispatch V0 child plan.",
      "steps": [
        "Keep this roadmap in sync with milestone status.",
        "Spawn each child plan as a separate plan directory when its trigger fires."
      ],
      "acceptance": "The roadmap names V1 and V2 with explicit trigger conditions, links to the V0 child plan id as the current executable slice, and is not used to dispatch implementation work itself.",
      "passes": false
    }
  ]
}

=== decisions.jsonl
{"id":"D001","ts":"2026-05-04T00:00:00Z","by":"operator","title":"Roadmaps track strategy","body":"This plan is a tracking parent. Code ships from the V0 child plan, not from the roadmap."}
{"id":"D002","ts":"2026-05-04T00:05:00Z","by":"operator","title":"V1 and V2 need triggers","body":"Future milestones are named but not dispatchable. Each one declares the condition that has to hold before it is split into its own child plan."}
````

### V0 Child Plan (dispatchable work)

<!-- dontpanic-plan-example: roadmap-child-implementation -->
````text
=== plan.md
---
id: 2026-05-04-011-feat-onboarding-init-guided
title: Guided dontpanic init
type: feat
tier: local
status: draft
date: "2026-05-04"
description: |
  Replace the README onboarding walkthrough with an interactive
  `dontpanic init` that writes a starter project registry.
agents_required:
  - claude
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 2
  no_progress_threshold: 2
  wall_clock_hours: 2
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-04-010-infra-onboarding-revamp-roadmap
orchestration:
  parent_plan_id: 2026-05-04-010-infra-onboarding-revamp-roadmap
  spawn_reason: operator_manual
  depth_limit: 3
child_charter:
  kind: implementation
  parent_objective: Ship a guided init that writes a starter registry and points at doctor.
  parent_acceptance_item: "V0 onboarding revamp roadmap: guided dontpanic init."
  allowed_paths:
    - "scripts/dontpanic_orchestrate/**"
    - "docs/**/*.md"
  return_condition_summary: "`dontpanic init` writes a starter registry and links to doctor in tests and on a clean checkout."
  may_edit_product_code: true
commit_policy:
  mode: child_commit
  requires:
    - tests_pass
    - evidence_packaged
---

## Target

```yaml
target_env: dev
target_project: none
```

## Scope

Implement `dontpanic init` so a clean checkout produces a starter project
registry, a doctor-friendly state, and a printable next step.

## Out Of Scope

- Cloud-provider account setup.
- Capability-bound onboarding (V1).
- Dashboard onboarding surface (V2).

=== features.json
{
  "task_id": "2026-05-04-011-feat-onboarding-init-guided",
  "schema_version": "1.0",
  "features": [
    {
      "id": "F001",
      "category": "functional",
      "phase": 1,
      "description": "Implement dontpanic init guided flow with starter registry output.",
      "steps": [
        "Add the init subcommand with interactive prompts and a non-interactive flag set.",
        "Write a starter project registry on success.",
        "Add tests for new-checkout success, existing-registry refusal without --force, and missing-prereq failure."
      ],
      "acceptance": "`dontpanic init` produces a starter project registry on a clean checkout, refuses to overwrite without --force, and tests cover success, refusal, and missing-prerequisite paths.",
      "passes": false
    }
  ]
}

=== decisions.jsonl
{"id":"D001","ts":"2026-05-04T00:00:00Z","by":"operator","title":"Child ships code, parent tracks strategy","body":"This plan is the dispatchable child of the onboarding revamp roadmap. The roadmap parent never ships init code itself."}
````

## Investigation Plan

Use this shape when the next safe step is "produce evidence about X." The
acceptance is "evidence and a recommendation," not shipped product code.

<!-- dontpanic-plan-example: investigation -->
````text
=== plan.md
---
id: 2026-05-04-020-infra-cold-start-investigation
title: Investigate Backend Cold-Start Latency
type: infra
tier: local
status: draft
date: "2026-05-04"
description: |
  Investigate why backend cold-start latency regressed last week and recommend
  whether the next step is a config change, a code change, or no action.
agents_required:
  - claude
human_gates:
  - pre_impl
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

Reproduce the regression in dev, gather profiling evidence, and recommend a
follow-up plan if one is warranted. Do not change product code in this plan.

## Out Of Scope

- Implementing the fix.
- Production traffic experiments.

=== features.json
{
  "task_id": "2026-05-04-020-infra-cold-start-investigation",
  "schema_version": "1.0",
  "features": [
    {
      "id": "F001",
      "category": "doc",
      "phase": 1,
      "description": "Reproduce the cold-start regression in dev and gather profiling evidence.",
      "steps": [
        "Reproduce the regression against the dev backend.",
        "Capture cold-start traces and identify the dominant contributor.",
        "Save traces and notes under evidence/."
      ],
      "acceptance": "Evidence/ contains at least one reproducible cold-start trace from dev and a written summary naming the dominant contributor.",
      "passes": false
    },
    {
      "id": "F002",
      "category": "doc",
      "phase": 2,
      "description": "Recommend a follow-up plan shape or close with no action.",
      "steps": [
        "Compare candidate follow-ups: config change, code change, or no action.",
        "Write a recommendation and link it from the plan."
      ],
      "acceptance": "A written recommendation exists naming exactly one follow-up shape and why; if a follow-up plan is recommended, its proposed id and scope are listed.",
      "passes": false,
      "depends_on": ["F001"]
    }
  ]
}

=== decisions.jsonl
{"id":"D001","ts":"2026-05-04T00:00:00Z","by":"operator","title":"No product-code edits in this plan","body":"This plan produces evidence and a recommendation. Any fix lands in a separate plan."}
````

## Operator Setup Task

Use this shape when the work is a human running a console step, a CLI, or
wiring a secret. The acceptance is evidence the work happened, not a test
suite.

<!-- dontpanic-plan-example: operator-setup -->
````text
=== plan.md
---
id: 2026-05-04-030-infra-staging-registry-setup
title: Register Staging Project in DontPanic
type: infra
tier: trivial
status: draft
date: "2026-05-04"
description: |
  Add the staging project to the DontPanic project registry so dashboard and
  fleet-scope readiness can include it.
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

Register the staging project, verify it appears in `dontpanic doctor`, and
capture before/after registry diffs.

## Out Of Scope

- Production registry changes.
- Schema changes to the registry.

=== features.json
{
  "task_id": "2026-05-04-030-infra-staging-registry-setup",
  "schema_version": "1.0",
  "features": [
    {
      "id": "F001",
      "category": "doc",
      "phase": 1,
      "description": "Register the staging project and capture evidence.",
      "steps": [
        "Add the staging entry to the project registry.",
        "Run `dontpanic doctor` and capture output.",
        "Save before/after registry diffs and doctor output under evidence/."
      ],
      "acceptance": "The project registry contains a staging entry, `dontpanic doctor` lists it as healthy, and evidence/ contains before/after diffs plus doctor output.",
      "passes": false
    }
  ]
}

=== decisions.jsonl
{"id":"D001","ts":"2026-05-04T00:00:00Z","by":"operator","title":"Evidence is the acceptance surface","body":"This is an operator setup task. Pass means the registry change and doctor output are captured under evidence/, not that a test suite passed."}
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
