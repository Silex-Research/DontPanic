---
id: 2026-05-30-001-feat-universal-agent-repo-onboarding-v0
title: Universal agent and repo onboarding v0
description: |
  Make DontPanic simple to operate from a newly installed interactive agent
  and simple to adopt in a new target repo. Introduces a single generated
  operating brief as the source of truth, exposes it through machine and repo
  surfaces, reconciles legacy config-home drift, validates executor reality,
  makes worker role assignment, setup/configuration, and budget/iteration
  decisions explicit, and prevents dashboard process duplication.
type: feat
tier: cross-cutting
status: completed
date: "2026-05-30"
goal_type: new_feature
surfaces:
  - infra
  - ux
  - docs
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 3
  no_progress_threshold: 2
  wall_clock_hours: 12
  hard_stop: false
privacy_tier: internal
dependencies: []
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
  objective_contract: ./objective_contract.json
orchestration:
  parent_plan_id: 2026-05-23-001-infra-install-lifecycle-reconciliation-roadmap-v0
  spawn_reason: operator_manual
  depth_limit: 3
child_charter:
  kind: implementation
  parent_objective: Make DontPanic continuously reconcile an operator's local install against current platform expectations.
  parent_acceptance_item: R2/R3-style config, agent-manifest, project onboarding, and dashboard drift are discoverable and repairable by humans and interactive agents.
  allowed_paths:
    - "scripts/dontpanic_orchestrate/**"
    - "scripts/dontpanic_doctor.py"
    - "docs/**/*.md"
    - "README.md"
    - "CHANGELOG.md"
    - "docs/plans/2026-05-30-001-feat-universal-agent-repo-onboarding-v0/**"
  forbidden_decisions:
    - Do not hand-maintain multiple copies of the operating brief.
    - Do not pretend unsupported interactive agents are dispatch executors.
    - Do not overwrite existing AGENTS.md or CLAUDE.md content outside marked managed blocks.
    - Do not silently resolve contradictory ~/.dontpanic and ~/.jarvis state.
    - Do not add a Grok/Gemini/etc. executor label without a real executor implementation.
  return_condition_summary: Agent brief, orchestrate gateway, repo managed onboarding, simple worker role assignment, configuration cockpit, doctor validation, config-home reconciliation, budget/iteration action guidance, dashboard singleton guard, docs, tests, and changelog all pass.
  may_edit_product_code: true
commit_policy:
  mode: child_commit
  requires:
    - tests_pass
    - evidence_packaged
---

# Universal Agent and Repo Onboarding v0

## Motivation

DontPanic must be easy to use from two starting points:

1. A user installs a new interactive agent on the same machine or container as
   DontPanic and asks it to operate DontPanic.
2. A user registers a new target repo and expects any interactive agent working
   in that repo to understand the DontPanic workflow.

The failure mode to prevent is duplication-and-drift. The same operating facts
must not be copied by hand into a manifest, an agent brief, AGENTS.md, CLAUDE.md,
README text, and doctor output. This plan makes one generated operating brief
the source of truth for both machine onboarding and repo onboarding.

## Target

```yaml
target_env: dev
target_project: none
```

DontPanic-internal infra plan. No external service setup is required.

## Product Model

DontPanic has two distinct relationships with an AI tool:

- **Operator:** an interactive agent or human that can run local CLI commands
  and drive the workflow.
- **Worker executor:** an agent CLI that DontPanic can dispatch to through a
  registered executor implementation.

Every generated brief must make this distinction explicit:

```text
DontPanic is a local orchestration CLI, not Kubernetes, Airflow, or IT
orchestration. You can operate it if you can run its commands. You can be
dispatched as a worker only if you appear in DontPanic's executor list.
If you are Grok, Gemini, or another unsupported agent, operate DontPanic;
do not configure yourself as a worker.
```

The canonical workflow shown to both humans and agents is:

```text
project register -> plan author/lock -> orchestrate/dispatch-from-plan ->
cross-model implementation and audit -> approve/resume/close
```

## Source Of Truth

One generator produces the operating brief from live program facts:

- `agent_manifest` supported commands and version
- `executors.AGENT_REGISTRY` worker executors
- configured DontPanic home and legacy Jarvis home status
- canonical command names, including `orchestrate`
- project onboarding status when a project path is supplied

All public surfaces consume that generator:

- `dontpanic agent brief`
- `dontpanic orchestrate` teaching output
- managed block inserted into target repo `AGENTS.md`
- `CLAUDE.md` pointer/alias
- doctor freshness checks

The managed repo block carries a generator version and content hash. Re-running
onboarding updates only the marked block when the hash is stale.

## In Scope

- Generated agent operating brief module.
- `dontpanic agent brief` and optional `dontpanic agent setup` teaching surface.
- `dontpanic agent status` and guarded worker registration for implemented
  executors only, so new interactive agents can tell whether they are
  operator-only or dispatchable.
- Simple role assignment for worker executors from CLI and dashboard surfaces,
  with global and per-project scope made explicit.
- A configuration inventory/cockpit that lists all required and optional
  DontPanic setup surfaces, their status, owner scope, and safe edit/setup path.
- `dontpanic orchestrate` gateway.
- Manifest updates for `agent` and `orchestrate`.
- `projects add --onboard` with dry-run and non-clobbering managed-block writer.
- Real per-project config scaffold defaults instead of bare `{}` for onboarded
  projects.
- `doctor --agent` and `doctor --project <name-or-path>` validation.
- Validation that global and project `roles.*` resolve to registered executors.
- Dashboard and CLI role pickers for `roles.implementer`, `roles.auditor`, and
  `roles.goal_auditor`, limited to registered worker executors and showing the
  current effective source layer.
- Dashboard and CLI setup cards for capability manifests, adapters, runtime
  evidence, project gates/protected paths, notification preferences, quota caps,
  calibration, env vars, secrets/auth checks, install snapshots, and dashboard
  local/remote configuration.
- Skill invocation rubrics that turn existing skill applicability into safe
  recommendations or bounded auto-run decisions, shared by CLI and dashboard.
- A deduplicated dashboard availability affordance whenever a command produces
  human-required configuration or approval work: show the active URL or start
  command once per output, then let individual items reference that affordance.
- Reconciliation command for conflicting `~/.dontpanic` and `~/.jarvis` state,
  plus read-through compatibility after migration.
- Clear action guidance for quota/budget/cooldown and iteration-cap decisions,
  including exact wait/redispatch/raise-ceiling choices and dashboard surfacing.
- A clean no-paid finalization path for auditor `signed_off` features after
  `pre_merge` is cleared, so completion writes signoff evidence and flips only
  that feature's `passes:true` without re-dispatching workers.
- Active-run plan drift detection and reconciliation when a human or another
  interactive agent edits plan files while DontPanic is running.
- Setup recommendations that tell an operator or interactive agent when to
  register a project, onboard a repo, refresh the agent brief, or reconcile
  config homes before spending cycles.
- Dashboard singleton guard with replace/force behavior.
- README/getting-started/changelog updates.

## Out Of Scope

- Implementing worker executors for Grok, Gemini, Kimi, Qwen, or other agents.
- Remote/multi-machine coordination.
- Authenticated dashboard service mode.
- Blind automatic execution of mutating, credentialed, networked, paid, or
  indefinite-loop skills without explicit approval.
- Changing the plan schema.
- Rewriting every existing historical plan/doc that mentions Jarvis.

## Implementation Strategy

Add a small `agent_brief` module that takes typed inputs and renders stable text.
Keep the renderer deterministic so tests can hash it and repo-managed blocks can
detect staleness.

Make `orchestrate` a gateway, not just an alias. With no args, `--help`, or an
unknown shape, it prints the brief and the canonical workflow. With a plan id or
path, it forwards to `dispatch-from-plan` and preserves dry-run semantics unless
the user passes `--confirm`.

Project onboarding is additive:

- Create `.dontpanic/dontpanic.json` with explicit defaults relevant to
  onboarding.
- Create `AGENTS.md` if missing.
- If `AGENTS.md` exists, insert or replace only the marked DontPanic managed
  block.
- Create `CLAUDE.md` if missing as a short pointer to `AGENTS.md`; if present,
  insert or update a marked pointer block only.
- Provide `--dry-run` output showing exact intended writes.

Doctor becomes the validation surface for both layers. `doctor --agent` validates
the machine. `doctor --project` validates one repo. Existing `doctor
--include-projects` remains compatible but can call the same project checks.

Config-home reconciliation must not stop at detection. Add a command that
previews differences, writes missing canonical `~/.dontpanic` files, preserves
legacy `~/.jarvis` as a read-through compatibility home, and refuses destructive
merge ambiguity without `--confirm`.

Skill automation builds on the existing advisory `applies_to:` matcher instead
of replacing it with a central router. Skills declare their own invocation
rubric in `SKILL.md`; DontPanic evaluates those declarations against plan state,
config readiness, command safety, and lifecycle stage. The result is shared
SkillAction data: read-only bounded skills can be auto-run when inputs are
complete, missing-input skills ask one concise question, and risky skills are
suggested or require approval.

Auto-run requires a separate versioned allowlist, visible in doctor/reconcile
and the setup inventory. Declared skill metadata is advisory input, not enough
authority to execute. If risk signals conflict, the evaluator applies a fixed
precedence order: opt-out and unsafe properties win over a skill's requested
mode. Existing skills get a migration helper that proposes starting rubrics
without blocking normal DontPanic use.

## Acceptance Summary

A clean install plus a new target repo should support this interaction:

```bash
dontpanic doctor --agent
dontpanic agent brief
dontpanic projects add myrepo /path/to/myrepo --onboard --dry-run
dontpanic projects add myrepo /path/to/myrepo --onboard
dontpanic doctor --project myrepo
dontpanic orchestrate <plan-id>
```

An unsupported interactive agent such as Grok must be able to read the generated
brief and correctly infer that it can operate DontPanic but cannot be dispatched
as a worker executor unless a real executor exists.

When dispatch pauses on quota, cooldown, budget ceiling, or iteration state, the
operator should not have to reverse-engineer the next move from logs. DontPanic
must present a small decision set with exact tradeoffs and commands, for example:

```text
Codex budget is cooling down.
Recommended: wait until 14:35, then run dontpanic orchestrate <plan> --confirm
Alternative: raise budget_ceiling to X with dontpanic quota-caps set ...
Iteration state: one fix iteration remains under max_iterations=3.
```

The same guidance should be available in CLI output and dashboard action items.

Assigning roles should be similarly low-friction. A user or interactive agent
should be able to ask "use Codex as auditor for this project" and DontPanic
should expose a safe role-assignment surface that shows available worker
executors, current effective values, whether the edit is global or project-local,
and why unsupported operator-only agents cannot be assigned to worker roles.

Core configuration should be equally inspectable. DontPanic should be able to
answer "what do I need to configure before this plan can run well?" without a
human or interactive agent spelunking README text, environment variables, JSON
files, or dashboard state. The answer should be a grouped setup checklist with
safe edits, human-required steps, current status, and exact remediation commands
where available.

Skill usage should follow the same product rule. A human or interactive agent
should be able to ask DontPanic to run a plan and see when useful skills such as
`security-review`, `eval-harness`, `test-runner`, `autoresearch`,
`browser-use`, or `cost-model` apply, why they apply, what input is missing, and
whether DontPanic can safely run them or must ask for approval.

Whenever a decision requires a human, DontPanic should not assume the user or
interactive agent knows a dashboard exists. CLI output and agent-facing guidance
should include one dashboard affordance per response: active URL if running, or
the exact `dontpanic dashboard serve` command if not. Individual action items
should not repeat the full dashboard message; they can reference the shared
affordance when useful.

DontPanic also needs to recognize when its own plan changed during an active
run. If one interactive agent is dispatching and another edits `plan.md`,
`features.json`, `decisions.jsonl`, gates, scope, or acceptance criteria, the
running workflow must surface that drift, decide whether it is safe to continue,
and refresh downstream context before spending more budget.
