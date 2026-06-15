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
The original operator-role (F004), channel-doctor (F005), and dashboard-panel
(F006) features each spanned multiple surfaces (CLI mutation + dashboard render +
orchestration safety). Per the lock-review recut (**D010**) they are split into
single-surface features so each is independently testable, auditable, and not
partially-satisfiable. The operator-role work becomes F004/F005/F006; the
channel doctor becomes F007/F008; the dashboard panel becomes F009/F010.

- **F004 — Operator-role preferences config CLI (mechanics only).** A settable
  operator-role layer (`primary_operator | researcher | reviewer | designer |
  tester | release_operator`) stored under a distinct config namespace
  (`operator_roles.*`), with **no `assert_registrable` guard** (operator surfaces
  like Cursor are not executors). Easy CLI to set/list ("Claude primary_operator,
  Codex auditor, Gemini researcher"). Does NOT touch the worker `roles.*`
  namespace or `agent register-worker`. Config mechanics only — projection (F005)
  and safety guard (F006) are split out.
- **F005 — Operator-role dashboard matrix projection.** A read-only pure
  projection that renders the `operator_roles.*` preferences as a role matrix
  consumed by the dashboard, shown separately from the worker-dispatch roles so
  the two namespaces never conflate. Projection only; no mutation.
- **F006 — Dispatch-safety guard (Safety invariant, D009).** `operator_roles.*`
  are preferences/intent, **NOT dispatch authorization** — a Cursor
  `primary_operator` preference never implies DontPanic can spawn Cursor as a
  worker; dispatch authority derives solely from `AGENT_REGISTRY` via worker
  `roles.*`. This feature pins that boundary in the dispatch path and proves a
  preference-only surface is refused at dispatch exactly as if no role were set.
- **F007 — Channel doctor CLI.** `dontpanic doctor --channel <surface>` (alias
  `--operator-surface`) reuses the existing `doctor_registry` + capability
  `verify.probes` to report PATH / home / repo / worktree-binding / config / MCP
  visibility for a named surface (per-check pass/warn/fail; unknown surface →
  non-zero; `--skip-auth` safe). Consumes the manifest kind from F008. Answers
  "will this work from Codex/Claude/Antigravity/Cursor?".
- **F008 — Operator-surface capability-manifest shape.** Extend the existing
  capability schema with an operator-surface/runtime manifest `kind` (no
  `agent-channels.json`) and seed ≥2 manifests for real surfaces (e.g. cursor,
  claude_desktop, codex_app, antigravity) with the fields doctor needs
  (`verify.probes`, `requires`, `owner_boundary`). So named surfaces are
  supportable, not just enumerated.
- **F009 — Channel-view producer + pure JS logic.** A build-time producer derives
  a channel-view object **only** from the ledger (F003) + capabilities incl.
  operator-surface manifests (F008) + worktree bindings + operator roles
  (F004), emitted as dashboard state JSON alongside `operator-triage.json` (no new
  registry). A pure JS logic module derives the buckets — `active`, `stale`,
  `remote_only`, **same_plan_conflict**, **same_branch**, **same_repo**,
  **unhealthy_worktree_binding**, **remote_cannot_mutate_local**,
  **operator_only_runtime_not_dispatchable** — plus the operator-role matrix, with
  vitest tests per bucket. `supports_*`/dispatchability derive from
  capabilities + `AGENT_REGISTRY`, not hardcoded.
- **F010 — Dashboard "Operator Channels" panel.** Renders the F009 buckets and
  role matrix in a read-only panel, following the `operator-triage/v0`
  producer↔render boundary. Renders all active + needs-attention items uncapped.
  Enters through the real surface: real producer → real shell journey + a Python
  fixture↔producer contract test (QA-sufficiency).

## Non-goals (deferred only)

- **Fully open adapter marketplace** — a third-party adapter submission/registry
  format. New surfaces/runtimes are added by extending the existing capability
  manifests (F008), not a marketplace. (Originating F007 of the spec.)
- **Remote-locality enforcement / routing** — v0 *records and surfaces*
  local-vs-remote and `remote_cannot_mutate_local`; it does not gate or route by
  locality.
- **No new `agent-channels.json` registry.** Channel/role views are derived
  (F009/F010) from existing registries + the operator-surface manifests (F008).

## Surfaces touched

schema (`claude/shared/schemas/` — InvocationContext, operator-surface capability
kind, operator_roles), engine (`scripts/dontpanic_orchestrate/` — detection,
ledger, roles, doctor wiring, producer), CLI (`cli.py` seam + roles/doctor
subcommands), dashboard (`dashboard/lib`, `pages`, `state`, `tests`). The
engine→dashboard work is split producer (F009, engine) / render (F010, dashboard)
with a Python↔JS contract test at the boundary; the operator-role projection is
likewise split engine-config (F004) / render (F005). Each feature touches a
single primary surface.

## Scope-lint note (advisory)

After the D010 single-surface recut, the multi-touch `over_surface`/`likely_timeout`
shape flags should be resolved (F004/F005/F006 split the operator-role work;
F007/F008 split the doctor from its manifest schema; F009/F010 split the producer
from the panel). Any residual `plan-review` flags are expected to be
`missing_prereq` on symbols **declared by this plan** (env vars, record fields,
role/locality/bucket names, the dispatch-safety guard) — introduced/declared in
the owning feature's `introduces[]` — or the established "engine producer writes
dashboard/ledger state" pattern (cf. `operator-triage.json`, F009→F010), not
genuine surface bleed. Re-confirm at `pre_impl`.

## Sufficiency round 1 — determinism pins (D013)

The first paid pre-impl audit returned 10 findings, all resolved by tightening
acceptance (no code, no re-lock). The shape:

- **Canonical-id + alias contract (F001).** Axis ids are lowercase
  snake/kebab-stable canonical ids; display labels are aliases only. A pure
  `normalize_identifier` maps user inputs (`Claude Code` / `claude-cli` /
  `Anthropic Claude` → `claude`) to canonical ids and every unrecognized value to
  `unknown_*` (never an invented id). The SAME id set is the single source for
  resolution (F002), `operator_roles` values (F004), capability-manifest ids
  (F008), and dashboard labels (F010). Canonical sets:
  `operator_surface = terminal, codex_app, claude_desktop, claude_dispatch,
  antigravity, cursor, github_agent_hq, remote_vm, github_vm, unknown_surface`;
  `agent_runtime = claude, codex, gemini, grok, cursor, antigravity, opencode,
  aider, unknown_runtime`; `execution_locality = local_mac, plan_worktree,
  dashboard_terminal, code_task, remote_vm, github_vm, unknown_locality`.
- **Deterministic detection (F002).** A rule table with a named cell per
  `execution_locality` member; unrecognized explicit `DONT_PANIC_*` values →
  `unknown_*`.
- **Ledger (F003).** Dual path representation — `path_display` (home-scrubbed,
  UI/evidence) + `path_key` (stable non-secret equality/conflict key; never the
  scrubbed string); exactly-one-record under argparse/import failure,
  KeyboardInterrupt, SIGTERM (`result=interrupted`); compaction preserves the
  fields F009/F010 need to reproduce active/stale/conflict buckets.
- **Operator roles (F004).** Global-vs-project precedence (project wins) +
  per-entry scope provenance + a CLI scope shape.
- **Doctor/manifest (F008).** Standard probe vocabulary + minimum probe set every
  manifest must declare; seed **exactly four** surfaces (cursor, claude_desktop,
  codex_app, antigravity); Gemini/Grok stay runtimes, not surfaces.
- **Panel (F009/F010).** A single LOCKED bucket rule matrix (active/stale
  threshold, conflict precedence, same_repo-vs-same_branch overlap, active-only
  conflicts) governs producer AND renderer.

## Decisions

See `decisions.jsonl`. Headline: D001 keep-the-four-axis-frame + no-new-registry;
D002 **operator roles are settable in v0** as a layer separate from worker roles;
D003 forbid `agent-channels.json`; D004 defer only open-adapter marketplace +
remote enforcement; D005 ledger concurrency/redaction/retention pins; D006 sharp
locality enum; D007 operator-surface capability-manifest shape so named surfaces
are supportable; D008 channel doctor pulled into v0; **D009 SAFETY INVARIANT —
`operator_roles.*` are preferences/intent, never dispatch authority**; **D010
lock-review single-surface recut** splitting the original F004/F005/F006 into the
ten-feature set (F001–F010) so each feature touches one primary surface; **D011**
records the first scope-gate `--allow-oversize` override and **D012** the second;
**D013 sufficiency round-1 determinism pins** (see section above) resolving the 10
findings with the operator's three design defaults (canonical-id/alias contract,
four seeded surfaces, dual path representation).
