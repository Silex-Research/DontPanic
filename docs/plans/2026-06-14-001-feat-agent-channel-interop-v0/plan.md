---
id: 2026-06-14-001-feat-agent-channel-interop-v0
title: Agent Channel Interop v0 — operator-surface axis, easy role choice, channel doctor, presence
type: feat
tier: cross-cutting
status: draft
date: "2026-06-14"
goal_type: new_feature
description: >
  Make DontPanic a channel + role orchestration layer for arbitrary agent
  surfaces. Add the one axis the platform does not yet model — operator_surface
  (terminal, cursor, claude_desktop, codex_app, antigravity, github_agent_hq,
  remote_vm) — with a sharp execution_locality, make every invocation record its
  full four-axis context to a sanitized concurrent presence ledger, make choosing
  roles ("Claude primary, Codex auditor, Gemini researcher") easy via a settable
  operator-role layer kept separate from worker-dispatch roles, prove each surface
  is usable via a channel doctor, and render it all in a dashboard panel. Extends
  the existing sources (agent_surface, executors, role_assignment, capabilities,
  doctor framework, worktree bindings) and adds capability-manifest shape for
  operator surfaces/runtimes rather than creating a parallel agent-channels.json
  registry.
agents_required:
  - claude
human_gates:
  - pre_impl
  - pre_merge
privacy_tier: internal
links:
  features: ./features.json
  objective_contract: ./objective_contract.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
  audits_dir: ./audit/
---

## Target

```yaml
target_env: dev
target_project: none
```

## Frame

DontPanic should be a **channel + role orchestration layer for arbitrary agent
surfaces**, not hardcoded support for today's top three CLIs. The originating
spec proposes a four-axis model the platform half-implements:

| Axis | Meaning | Status today |
|---|---|---|
| `operator_surface` | where the user/caller is engaging from | **absent** |
| `agent_runtime` | what is doing the work | **exists** — `agent_surface.py`, `executors/AGENT_REGISTRY` (claude, codex), `KNOWN_OPERATOR_AGENTS` (gemini, grok) |
| `role` | why that runtime is used | **exists, worker-only** — `roles` CLI + `agent register-worker` + `role_assignment.py` (`ROLES = implementer/auditor/goal_auditor`, guarded by `assert_registrable`) |
| `execution_locality` | where commands actually run | **exists, partial** — `environments.json`, worktree isolation, `DispatchTask.cwd` |

This v0 is **not just observation**: it adds the missing axis AND the product UX —
easy role choice and proof that each surface works — while reusing existing
substrate and adding capability-manifest shape (no new registry).

## What the first draft got right, and the recut

The reconciliation (no parallel `agent-channels.json`; derive from
`executors` + `capabilities` + `agent_surface`) is correct and kept. But the
first draft was too conservative on product UX. This revision pulls **operator-role
choice** and a **channel doctor** into v0, hardens the **presence ledger** for
concurrency/privacy, sharpens **execution_locality**, broadens **conflict
semantics** to worktree bindings, and requires the **operator-surface capability
manifest shape** so named surfaces (Cursor, Antigravity) are actually supportable,
not just enumerated.

## Features

- **F001 — `operator_surface` axis + four-axis `InvocationContext`.** Reuses
  `agent_surface` for runtime and existing `ROLES` for worker roles. Sharp
  `execution_locality` enum: `local_mac | plan_worktree | dashboard_terminal |
  code_task | remote_vm | github_vm | unknown` (the Cowork-VM-vs-Mac-code-task and
  GitHub-VM distinctions are why this axis exists). Pure model + byte-stable serialization; secret-free.
- **F002 — Channel/runtime detection (explicit-first, heuristic-second,
  unknown-last).** `DONT_PANIC_OPERATOR/_AGENT/_ROLE/_LOCALITY` → documented
  heuristics (`TERM_PROGRAM`, known-agent env markers) → explicit `unknown_*`.
  Never guesses past unknown. Pure resolver.
- **F003 — Sanitized concurrent invocation ledger.** Every CLI command appends
  one `InvocationRecord` (four-axis context + repo/worktree/branch/plan + command
  + started/finished/last_seen + result + locality) to
  `~/.dontpanic/invocations.jsonl`. **Atomic append / lock-safe under concurrent
  agents**; command-string **arg redaction** (tokens/secrets in args, not just
  field-name checks); **no raw home paths** (sanitized like audit evidence);
  **retention/compaction** policy. PID/liveness-aware.
- **F004 — Operator-role preferences (easy role choice), separate from worker
  roles.** A settable operator-role layer (`primary_operator | researcher |
  reviewer | designer | tester | release_operator`) stored under a distinct config
  namespace (`operator_roles.*`), with **no `assert_registrable` guard** (operator
  surfaces like Cursor are not executors). Easy CLI to set/list ("Claude
  primary_operator, Codex auditor, Gemini researcher") and a dashboard role-matrix
  projection. Does NOT touch the worker `roles.*` namespace or `agent
  register-worker`. **Safety invariant (D009): `operator_roles.*` are
  preferences/intent, NOT dispatch authorization — a Cursor `primary_operator`
  preference never implies DontPanic can spawn Cursor as a worker; dispatch
  authority derives solely from `AGENT_REGISTRY` via worker `roles.*`.**
- **F005 — Channel doctor + operator-surface capability manifest shape.** Extend
  the capability schema with an operator-surface/runtime manifest `kind` (no
  `agent-channels.json`) and seed manifests for real surfaces (e.g. cursor,
  claude_desktop, codex_app, antigravity). `dontpanic doctor --channel <surface>`
  (alias `--operator-surface`) reuses the existing `doctor_registry` +
  capability `verify.probes` to report PATH / home / repo / worktree-binding /
  config / MCP visibility for that surface. Answers "will this work from
  Codex/Claude/Antigravity/Cursor?".
- **F006 — Derived dashboard "Operator Channels" panel.** Joins the invocation
  ledger + capabilities (incl. the new operator-surface manifests) + worktree
  bindings + operator roles into a read-only panel, following the
  `operator-triage/v0` producer↔render boundary. Conflict/health buckets:
  `active`, `stale`, `remote_only`, **same_plan_conflict**, **same_branch**,
  **same_repo**, **unhealthy_worktree_binding**, **remote_cannot_mutate_local**,
  **operator_only_runtime_not_dispatchable**, plus the operator-role matrix.
  Enters through the real surface: real producer → real shell journey + a Python
  fixture↔producer contract test (QA-sufficiency).

## Non-goals (deferred only)

- **Fully open adapter marketplace** — a third-party adapter submission/registry
  format. New surfaces/runtimes are added by extending the existing capability
  manifests (F005), not a marketplace. (Originating F007.)
- **Remote-locality enforcement / routing** — v0 *records and surfaces*
  local-vs-remote and `remote_cannot_mutate_local`; it does not gate or route by
  locality.
- **No new `agent-channels.json` registry.** Channel/role views are derived
  (F006) from existing registries + the operator-surface manifests (F005).

## Surfaces touched

schema (`claude/shared/schemas/` — InvocationContext, operator-surface capability
kind, operator_roles), engine (`scripts/dontpanic_orchestrate/` — detection,
ledger, roles, doctor wiring, producer), CLI (`cli.py` seam + roles/doctor
subcommands), dashboard (`dashboard/lib`, `pages`, `state`, `tests`). F006 is the
only engine→dashboard pair and is split producer (engine) / render (dashboard)
with a contract test at the boundary.

## Scope-lint note (advisory)

`plan-review` flags `over_surface` on multi-touch features and `missing_prereq`
on declared symbols (env vars, record fields, role/locality/bucket names, secret
guards) — these are introduced/declared here or inherent to a detection/security
feature. F003/F006 follow the established "engine producer writes dashboard/ledger
state" pattern (cf. `operator-triage.json`), not genuine surface bleed.
Re-confirm at `pre_impl`; the implementer may split F005's manifest-shape work
from the doctor wiring if a single dispatch risks timeout.

## Decisions

See `decisions.jsonl`. Headline: D001 keep-the-four-axis-frame + no-new-registry;
D002 **operator roles are settable in v0** as a layer separate from worker roles;
D003 forbid `agent-channels.json`; D004 defer only open-adapter marketplace +
remote enforcement; D005 ledger concurrency/redaction/retention pins; D006 sharp
locality enum; D007 operator-surface capability-manifest shape so named surfaces
are supportable; D008 channel doctor pulled into v0.
