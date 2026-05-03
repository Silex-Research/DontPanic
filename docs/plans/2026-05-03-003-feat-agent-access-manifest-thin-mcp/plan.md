---
id: 2026-05-03-003-feat-agent-access-manifest-thin-mcp
title: Phase B — Agent Access Manifest + Thin MCP Surface
type: feat
tier: cross-cutting
status: draft
date: "2026-05-03"
description: |
  Phase B of the OpenClaw-repositioned roadmap (see docs/ROADMAP.md and
  docs/ECOSYSTEM.md). Make Jarvis **callable** by ecosystem agents
  (OpenClaw skills, Claude Code, Codex CLI, Cursor, Claude-managed
  agents, MCP clients) without operator hand-holding. Four features:

  - F001 — Global agent manifest at `~/.jarvis/agent-manifest.json`:
    versioned schema; install/source metadata; CLI path; project
    registry pointer; supported commands; safety rules. Pure
    discovery, no MCP yet.
  - F002 — Thin local MCP server (`jarvis mcp serve`): localhost /
    stdio transport; thin tools `list_projects | validate_plan |
    dispatch | status | approve_gate | read_evidence`. **No intake
    tool** — Phase C owns intake, exposing it before then would lock
    in a contract we have not designed yet.
  - F003 — Agent discoverability docs: README snippets, Claude Code /
    Cursor / OpenClaw / Codex usage examples, `mcp.json` snippet,
    PyPI / GitHub topics / MCP-directory checklist as
    documentation/evidence.
  - F004 — LLM-authored plan schema docs: document the existing plan
    directory contract, minimum valid plan, examples, "sufficiency vs
    implementation" boundary. Authoring guidance, **not** the Phase C
    intake engine.

  This plan is intentionally NOT a daemon. It does not ship a chat
  surface, a hosted control plane, a custom remote daemon, or a
  plugin marketplace. The caller's runtime owns those concerns; see
  ECOSYSTEM.md for the explicit non-goals.
motivation: |
  Phase A made Jarvis globally installable and registry-aware. What's
  missing is the surface an agent can find on a machine and call
  without per-vendor integration code. The OpenClaw discovery (2026-05-03)
  sharpened the framing: Jarvis is the verified software-delivery
  layer ecosystem runtimes call, not a runtime competitor. Phase B is
  the smallest slice that delivers that calling pattern: a global
  manifest (find Jarvis), a thin MCP surface (call Jarvis), and the
  docs an agent or LLM needs to do both correctly.
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 2
  no_progress_threshold: 2
  wall_clock_hours: 3
  hard_stop: false
privacy_tier: internal
protected_paths:
  - claude/PORTABILITY.md
  - claude/scripts/sync-harness.sh
  - dashboard/state/costs.json
  - scripts/maintainer/refresh-costs.sh
  - claude/shared/
---

## Target

```yaml
target_env: dev
target_project: none
```

## Scope

Phase B is the access surface that turns Jarvis into a tool ecosystem
agents call. Four feature surfaces, intentionally narrow:

1. Global agent manifest at `~/.jarvis/agent-manifest.json` (F001).
2. Local MCP server `jarvis mcp serve` (F002).
3. Agent discoverability docs in README + repo (F003).
4. LLM-authored-plan schema documentation (F004).

The plan stays NARROW so it stays REVIEWABLE. We will pick execution
path (direct vs volley) per feature **after acceptance is locked**,
not at draft time.

## Out of scope (deliberate)

- **No `jarvis intake` MCP tool.** Phase C owns intake. Exposing an
  intake tool through MCP before Phase C exists would lock in a
  contract we have not designed yet.
- **No remote MCP transport.** Phase B is local-only (stdio +
  localhost). Remote callers go through their own runtime's remote
  surface (Clawdbot, OpenClaw Gateway, Claude dispatch, etc.) — not
  a Jarvis-hosted daemon.
- **No custom remote daemon.** Existing remote-agent infrastructure
  carries the remote-execution burden. If a daemon ever becomes
  necessary, the threat model is pre-written in
  [`docs/ROADMAP.md`](../../ROADMAP.md) Phase D notes.
- **No PyPI publish or MCP-directory submission.** Discoverability
  docs (F003) are evidence-of-readiness, not commitments to publish
  during this slice. The actual external submissions can ride a later
  release.
- **No `~/.jarvis/projects.json` schema changes.** F002's MCP tools
  read the existing registry shape that Phase A's F002 shipped.
- **No supervisor / dispatch behavior changes.** F002's `dispatch`
  MCP tool wraps the existing `supervisor.dispatch_volley` /
  `dispatch_from_plan` paths; it does not introduce new dispatch
  semantics.
- **No plugin marketplace, no chat surface, no mobile presence.**
  Those are runtime concerns owned by callers (OpenClaw, Claude Code,
  etc.). See [`docs/ECOSYSTEM.md`](../../ECOSYSTEM.md) deliberate
  non-goals.

## Cross-cutting tightenings (apply to every feature)

These are operator-supplied review priorities — not new acceptance
items, but constraints the implementer must respect and the auditor
must verify per item:

1. **MCP mutating tools must be safe by default.** `dispatch`,
   `approve_gate`, and any future state-changing tool default to
   dry-run unless the caller passes `confirm: true`. This is symmetric
   with the F002 (Phase A) `--force --yes` and `--yes` patterns:
   destructive intent is two-flag, not one-flag-with-prompt.
2. **MCP server is local-only in Phase B.** The transport is stdio
   or localhost-bound. No HTTP listener bound to non-loopback
   addresses. No authentication scaffolding (deferred to a future
   remote-MCP plan if/when it becomes necessary).
3. **MCP tools refuse arbitrary filesystem paths outside registered
   projects/plans.** A `read_evidence` call with a path outside any
   registered project's `plans_dir` hard-refuses; same for
   `validate_plan`, `dispatch`, `status`. The tool surface is
   constrained to the registry — it is not a general filesystem API.
4. **Manifest contains no secrets.** No API keys, no service-account
   paths, no auth tokens. The manifest is machine-level discovery,
   not a credential surface. Sanitization check must pass on the
   manifest writer.
5. **Manifest is regenerable and idempotent.** Operators (or a future
   `jarvis bootstrap` helper) can rewrite the manifest from scratch.
   Re-running the writer with the same inputs produces a
   byte-identical file. No accidental drift between regenerations.
6. **Agent-facing docs must say: do not dispatch without user
   approval.** Both the manifest's `safety_rules` block AND the
   discoverability docs (F003) explicitly tell agents that
   `dispatch` is a human-gated operation — they should surface the
   plan + ask the user before calling `dispatch(confirm=True)`.

## Execution path (deferred per feature)

We are NOT committing to direct-vs-volley at draft time. Lock
acceptance first; pick path per feature based on:

- F001 (manifest writer/reader) — looks like a direct slice modeled on
  F001/F002 of Phase A: Pydantic schema + writer + reader + tests.
- F002 (MCP server) — likely volley-worthy. Touches a new surface
  agents can call; precedence for "thin tool wrapping live dispatch"
  is exactly the place adversarial review catches scope-creep and
  unsafe-default bugs.
- F003 (discoverability docs) — direct, doc-only.
- F004 (LLM-plan-schema docs) — direct, doc-only.

This is recorded so future-us doesn't accidentally skip the volley on
F002 the way the close-out lessons recommend.

## Platform-context caveats inherited from F003 close-out

These platform issues exist as of plan-lock and are NOT part of Phase
B's fix scope. Implementers/auditors should be aware:

1. **Gate semantics are upfront-evaluated.** The supervisor evaluates
   declared `human_gates` as a single upfront set, not lifecycle
   checkpoints. Operators clearing `pre_impl` + `pre_merge` upfront is
   the current pattern. Lifecycle-staged gates are queued as a
   separate platform improvement (D009 of plan 2026-05-03-001).
2. **Subprocess timeout is 600s.** If an implementer iteration writes
   ~1000+ lines across multiple modules + tests, claude CLI may hit
   the wrapper deadline. The work lands on disk before the kill, but
   the audit envelope is marked `blocked`. F003 of plan 2026-05-03-001
   documents the pattern; if it recurs here, accept the work on
   direct review (per D009) rather than chasing a clean envelope.

## What "ready to lock" looks like

Before flipping `status: draft` → `status: active`, the operator
should be satisfied that:

- Acceptance criteria for all 4 features are concrete + testable.
- Cross-cutting tightenings are wired into each feature's
  acceptance, not just listed here.
- Decisions captured at lock time include: the two-file
  manifest/jarvis.json split (D001 below), the no-intake-in-MCP
  carveout (D002), the local-only constraint (D003), the
  dry-run-by-default rule (D004), the path-validation rule (D005),
  the secret-free-and-regenerable rule (D006), the
  no-dispatch-without-approval doc rule (D007), and the
  external-listings-as-evidence-not-acceptance carveout (D008).
- The MCP tool surface excludes `intake` — explicitly.
- Phase B does NOT touch the supervisor, the registry schema, or any
  Phase A code path other than wrapping it.

## See also

- [`docs/PRODUCT.md`](../../PRODUCT.md) — what Jarvis is in plain
  English; the tagline and "what Jarvis is NOT" framing.
- [`docs/ECOSYSTEM.md`](../../ECOSYSTEM.md) — caller-pattern recipes
  (OpenClaw, Claude Code, Codex CLI, Cursor, managed agents, MCP);
  the deliberate non-goals.
- [`docs/ROADMAP.md`](../../ROADMAP.md) — phase sequencing; Phase B
  is the agent-callable access surface, between Phase A (substrate,
  shipped) and Phase C (intake).
- Phase A close-out — `docs/plans/2026-05-03-001-feat-global-install-project-registry/`
  — the substrate Phase B builds on.
- Memory: `project_jarvis_agent_manifest_decision.md` — locked
  decision on the two-file split (global manifest vs project
  config), pinned before this plan was drafted.
