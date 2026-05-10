---
id: 2026-05-09-003-feat-state-projection-v0
title: State projection v0 — DontPanic emits stable read-only state for adapters
type: feat
tier: local
status: active
date: "2026-05-09"
goal_type: infra
surfaces:
  - infra
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
  - 2026-04-19-001-infra-cross-agent-orchestration
  - 2026-05-03-003-feat-agent-access-manifest-thin-mcp
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
description: |
  Add a stable read-only state projection contract to DontPanic so external
  adapters (dashboards, brokers, CI runners, hosted agents) can subscribe
  to plan/gate/inbox/supervisor/quota state through one normalized surface
  instead of each adapter reading filesystem paths directly.
motivation: |
  Architectural critique (2026-05-09) identified that the dashboard-sync
  work was leaning into DontPanic core. Right boundary: DontPanic owns
  verified-delivery state and emits a stable contract; adapters consume.
  Without this projection layer, every adapter (axiom dashboard, OpenClaw
  broker, future CI runner, future Linear/Sentry integrations) ends up
  reading raw plan dirs — couples adapters to filesystem layout, breaks
  on any internal refactor, and makes redaction policy diffuse. The
  projection is the canonical caller-and-adapter contract.
---

# State Projection v0

## Thesis

DontPanic's local state lives in concrete artifacts: plan directories
under `docs/plans/<id>/`, `~/.dontpanic/active_supervisors.jsonl`,
`~/.dontpanic/quota_state.json`, `<plan>/INBOX.md`,
`<plan>/gate-state.json`, `<plan>/signoff.json`,
`<plan>/decisions.jsonl`. Every adapter that wants to render or react
to that state currently has to know which paths to read and which file
shapes to parse.

State projection v0 normalizes that into a single contract:

- **`dontpanic state snapshot --json`** CLI command — emits one JSON
  envelope with all the streams.
- **MCP tools** — `state_snapshot` (one-shot) + `state_stream`
  (long-poll for new events) + the existing `approve_gate` /
  `dispatch` / `read_evidence` mutation tools, annotated with their
  approval semantics.
- **JSON schema** in agent-conventions v1.x at
  `schemas/v1.x/state-snapshot.schema.json`.
- **Redaction-aware** — secrets, API keys, evidence file contents (only
  references), and operator-private fields excluded by default.
- **Stable IDs** — plan_id, feature_id, agent_id, gate_name. No
  internal SHAs leak through.
- **TZ-aware UTC timestamps** — every timestamp is RFC 3339 with `Z`
  suffix.

## Scope

In scope:

- New CLI subcommand: `dontpanic state snapshot [--plan <id>]
  [--include plans,gates,inbox,supervisors,quota,decisions,evidence]
  [--redact-level public|operator|full]`
- New MCP tools: `state_snapshot`, `state_stream`. Existing
  `approve_gate` / `dispatch` / `resume` / `read_evidence` /
  `validate_plan` annotated with their approval requirement.
- JSON schema published in agent-conventions (subtree).
- Redaction policy table (default: operator level — full state but
  secrets stripped; public level — extra fields stripped for unauth
  observers; full level — only available to local CLI invocations).
- Stable ID discipline (D-entry per shape; no breaking changes
  without a major schema bump).
- Tests covering every stream + redaction level + schema validation +
  empty-state edge cases.

Out of scope (explicit deferrals):

- Dashboard / Firestore sync — that's the sibling adapter plan
  `feat-team-dashboard-sync` (`2026-05-09-004`).
- Long-poll event streaming protocol details — `state_stream` v0
  returns most-recent-N events; SSE / WebSocket comes later if needed.
- Per-plan ACL beyond the redaction levels — role/action policy
  matrix from USE_CASES.md is informed by but doesn't gate v0.
- Push notifications from projection changes — adapters poll or use
  the existing NotifyEvent webhook surface.

## Target

```yaml
target_env: dev
target_project: none
```

## Acceptance Summary

- `dontpanic state snapshot --json` returns a valid envelope matching
  `state-snapshot.schema.json` for any registered project.
- Empty state (no plans yet) returns a valid envelope with empty arrays,
  not an error.
- `--redact-level public` returns a strict subset: no secrets, no
  evidence contents, no operator-private fields. Verified by sanitization
  scan against a known-secret fixture.
- MCP `state_snapshot` returns the same JSON envelope structure.
- agent-conventions schema bumped to next minor version with the new
  schema added.
- Adapter governance doc references the projection as the canonical
  contract.
- Full orchestrate sweep stays green (no regressions in existing
  modules).
