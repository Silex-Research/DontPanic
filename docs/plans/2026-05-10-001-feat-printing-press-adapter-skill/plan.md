---
id: 2026-05-10-001-feat-printing-press-adapter-skill
title: Printing Press adapter skill — DontPanic prescribes PP for external-API wrapping
type: feat
tier: local
status: draft
date: "2026-05-10"
goal_type: infra
surfaces:
  - infra
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
  wall_clock_hours: 4
  hard_stop: false
privacy_tier: internal
protected_paths:
  - claude/shared/schemas/
dependencies:
  - 2026-05-08-002-feat-skill-applicability-v0
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
description: |
  Ship `printing-press-adapter` as a DontPanic platform skill so any
  plan whose surface is "wrap an existing API with MCP + CLI"
  auto-surfaces guidance to dispatch CLI Printing Press
  (mvanhorn/cli-printing-press) instead of hand-rolling a wrapper.
  Adds `external-api-wrap` to the agent-conventions `surfaces[]` enum
  (v1.7.0) so plan validation propagates the trigger. Dogfoods on one
  operator-picked target with a public OpenAPI spec to validate the
  pattern end-to-end.
motivation: |
  The DontPanic ↔ Printing Press boundary was sharpened during plan
  2026-05-09-003 lock (D010): PP wins for external API wrapping;
  hand-rolled wins for in-process policy-bearing surfaces (DontPanic
  itself). Without a skill, that boundary lives only in ROADMAP prose
  — operators and agents have to remember to apply it, and skill-
  applicability v0 can't surface it at lock time. Codifying the
  guidance as a skill closes the loop: plans declare `surfaces:
  [external-api-wrap]` → lock-time advisory says "consider the
  printing-press-adapter skill" → operator/agent has the pattern in
  hand instead of starting from a blank page.

  Same shape as cost-model + cost-guard (skills that codify
  cross-project guidance) and plan-artifacts (skill that codifies
  artifact discipline). The platform prescribes; the operator
  chooses.

  Scope is deliberately bounded per the demand-driven-v2 pattern:
  one skill + one schema bump + one dogfood. The dogfood teaches us
  what v1 of the adapter pattern actually needs; the next iteration
  (custom adapter governance, multi-service composition, OAuth
  rotation) opens as a v2 plan after we have lived signal.
---

# Printing Press adapter skill

## Thesis

DontPanic is a platform that orchestrates plan execution. Plans whose
goal is "wrap an existing API in a CLI/MCP surface" are a recurring
shape — Linear for intake, Sentry for incident evidence, Slack for
notification routing, GitHub Projects for cross-team status, Jira for
enterprise issue tracking. Today every such plan would mean
hand-writing argparse + MCP tool registration. CLI Printing Press
generates exactly that pair from OpenAPI in one step.

The right boundary:

- **DontPanic owns**: the projection contract (plan 2026-05-09-003),
  the adapter governance doc (F006 of that plan), redaction tiers,
  approval gates, and the platform-side guidance — i.e. **when** to
  reach for PP and **how** to wrap its output with policy.
- **Printing Press owns**: per-service CLI + MCP generation from
  OpenAPI / HAR / sniffed traffic. Auth scaffolding. Cobra-style
  flags. SQLite + FTS5. Packaging.
- **The skill is the connective tissue**: a SKILL.md DontPanic agents
  see at plan-lock time when `surfaces: [external-api-wrap]` is
  declared. It documents the decision tree, the wrapper template,
  and the registration protocol.

This is meta-substrate: a skill that recommends an external tool
for a recurring plan shape, with DontPanic's policy injection as the
seam. Not a replacement for our own CLI/MCP (plan 003 F004/F005);
that's the one explicit exception because DontPanic is policy-bearing
in-process.

## Scope

In scope:

- **F001** — Author `claude/skills/printing-press-adapter/SKILL.md`
  + `DECISION_TREE.md` + `ADAPTER_TEMPLATE.md` (thin Python wrapper
  emitting redact + approval middleware around a PP-emitted MCP
  server). `applies_to:` matcher set so `surfaces:
  [external-api-wrap]` triggers advisory surfacing.

- **F002** — Bump agent-conventions to v1.7.0. Add `external-api-wrap`
  to the `surfaces[]` enum at
  `claude/shared/schemas/v1.0/plan.schema.json`. Regenerate Pydantic
  via datamodel-codegen. Update `plan.schema.json` enum
  `description` to reference the printing-press-adapter skill.
  Subtree into DontPanic, bump local VERSION, update the v1.6.0 pin
  test to v1.7.0.

- **F003** — Dogfood. Operator picks ONE external service with public
  OpenAPI (criteria: read-only first; OAuth in `~/.dontpanic/
  adapters/<service>.json`). Run `/printing-press <service>` exactly
  once (D-entry locks budget per one-paid-call-dogfood discipline).
  Author the thin DontPanic adapter wrapper. Register in
  `~/.dontpanic/adapters.json` (new operator config file, separated
  from `discord.json` + `projects.json` per operator-config-separation
  pattern). Capture evidence: PP binary works, our redaction
  middleware works, adapter shows up in `dontpanic state snapshot`
  output once plan 003 F002 lands (or as a stub if F002 not yet
  shipped — F003 declares its own non-blocking evidence shape).

Out of scope (explicit deferrals):

- Multi-service adapter composition. v0 = one service per `adapters/`
  entry; v1 might need cross-service joins (Linear issue → Sentry
  events for that incident → GitHub PR), but defer until we have
  real demand signal from F003 dogfood.
- OAuth token rotation. v0 assumes operator manages tokens directly.
  Automated rotation is platform-substrate work and waits.
- Adapter authoring CLI (`dontpanic adapter add <service>`).
  Templates plus operator-edited JSON are enough for v0.
- Multi-host adapter coordination. v0 is single-operator.
- Approval-gate templating for mutating endpoints. F003 dogfood is
  read-only by directive; mutating-endpoint policy lives in v2.

## Target

```yaml
target_env: dev
target_project: none
```

## Acceptance Summary

- `claude/skills/printing-press-adapter/SKILL.md` exists with valid
  frontmatter (`applies_to: { surfaces: [external-api-wrap] }`).
- agent-conventions v1.7.0 published with `external-api-wrap` in the
  surfaces enum; DontPanic subtree at 1.7.0.
- A real dogfood adapter exists at `~/.dontpanic/adapters/<service>.
  json` (gitignored; example shape committed at
  `docs/plans/.../evidence/adapters-example.json` with redacted
  tokens).
- DECISION_TREE.md filters out the 4 anti-cases: in-process policy-
  bearing, < 5 endpoints, no OpenAPI available, mutating endpoint
  without an approve_gate analog.
- Full orchestrate sweep stays green (no regressions in existing
  modules).
