---
name: printing-press-adapter
description: Wrap an external OpenAPI-shaped service as a DontPanic-governed CLI + MCP adapter using CLI Printing Press
trigger_keywords:
  - printing press
  - external api wrap
  - openapi adapter
  - mcp adapter
  - cli generation
file_patterns: []
applicable_agents: [all]
phase: pre-impl
applies_to:
  surfaces: [external-api-wrap]
  goal_types: [new_feature, infra, parity]
  external_cli:
    provider: printing-press
    name: CLI Printing Press
    command: cli-printing-press
    version_pin: pinned-at-plan-lock
---

# printing-press-adapter

## Purpose

When a plan's goal is to wrap an existing external service (an HTTP API
that already publishes OpenAPI or has stable, sniffable traffic) as a
CLI + MCP surface for agent consumption, DontPanic prescribes **CLI
Printing Press** (https://github.com/mvanhorn/cli-printing-press, MIT)
to emit the per-service CLI/MCP pair, plus a thin DontPanic-owned
adapter that wraps the emitted MCP server with redaction, evidence-
pointer normalization, and approval-gate enforcement.

This skill is the **lock-time advisory** for that pattern: when a plan
declares `surfaces: [external-api-wrap]`, the skill-applicability
matcher (`scripts/dontpanic_orchestrate/skill_applicability.py`)
surfaces this entry in `evidence/applicable-skills.json` so the
operator and downstream agents see the recommended path before any
handler code is written.

The boundary is sharp:

- **Printing Press owns**: per-service CLI + MCP generation from
  OpenAPI / HAR / sniffed traffic, Cobra-style flags, auth scaffolding,
  packaging.
- **DontPanic owns**: the projection contract
  (`docs/STATE_PROJECTION.md`), redaction tiers, approval gates,
  evidence-refs streams, adapter registry policy
  (`~/.dontpanic/adapters.json`).
- **This skill owns**: the connective tissue — when to reach for PP,
  the decision tree that filters out anti-cases, the Python template
  for the DontPanic-side wrapper.

## When to use

Use this skill when a plan satisfies all four filters in
`DECISION_TREE.md`:

1. Target is an **external** API (not an in-process surface).
2. Target publishes **OpenAPI**, or its traffic can be reliably
   captured as HAR.
3. The plan wraps **≥ 5 endpoints** (the OpenAPI shim pays off only at
   scale; below that, just hand-write the handlers).
4. All wrapped endpoints are **read-only** in v0; mutating endpoints
   require the v2 expansion (approval-gate templating).

Canonical fits: Linear issue intake, Sentry incident evidence pulls,
GitHub Projects status, Jira issue mirroring, Notion page reads.

## When NOT to use

- **In-process, policy-bearing surfaces.** DontPanic's own CLI + MCP
  (plan 2026-05-09-003 F004 / F005) is the one explicit exception:
  redaction tiers, gate approvals, INBOX-first invariants, and
  project-registry safety must live in the same process as the
  surface. Wrapping our own API through PP would push policy into a
  subprocess boundary it cannot enforce. See `DECISION_TREE.md` Q1.
- **Fewer than five endpoints.** The PP shim + adapter wrapper +
  registry entry costs more lines than five hand-written handlers.
  See `DECISION_TREE.md` Q3.
- **No OpenAPI, no captureable traffic.** PP needs a contract or a
  reproducible HAR to generate from. SOAP-only, GraphQL-only without
  a JSON/REST shadow, or APIs behind opaque WebSocket framing fall
  outside v0. See `DECISION_TREE.md` Q2.
- **Mutating endpoints in v0.** Approval-gate templating is reserved
  for v2 of this skill; v0 wraps read-only surfaces only. If the
  target's value comes from mutation (e.g., posting to Slack), file
  the v2 expansion plan before reaching for PP. See `DECISION_TREE.md`
  Q4.

## Arguments

None — this is an advisory skill, not an executable. The matcher
surfaces it at plan-lock time when the four filters pass. Operators
invoke the actual workflow manually:

```
/printing-press <service>          # in cli-printing-press repo
python -m dontpanic_orchestrate.adapters.<service>_adapter --help
```

## Prerequisites

- `cli-printing-press` available on the operator's `$PATH` at the
  version recorded in `~/.dontpanic/adapters/<service>.json`'s
  `pp_version` field.
- The target service publishes a public OpenAPI document, or the
  operator has captured a representative HAR.
- The target supports read-only credentials (API key with read scope,
  OAuth read-only token). v0 never asks the operator for write
  scopes.
- `agent-conventions` v1.7.0 or later — the schema version that adds
  `external-api-wrap` to the canonical `surfaces[]` enum. (Without
  v1.7.0, plans cannot declare the surface and the matcher will not
  fire.)

## Steps

1. **Lock the plan with the matcher signal.** Declare `surfaces:
   [external-api-wrap]` in `plan.md`. At lock time, `dontpanic plan
   lock` writes `evidence/applicable-skills.json` with a Match for
   this skill plus the `external_cli` metadata block, so the operator
   sees the prescribed path before implementation.
2. **Pin the PP version.** Record the active CLI Printing Press
   version (the version current as of plan lock — `cli-printing-press
   --version`) in `~/.dontpanic/adapters/<service>.json` under
   `pp_version`. v1 of any given adapter MUST NOT change the pin
   without a v2 expansion plan.
3. **Generate the per-service binary.** From the `cli-printing-press`
   repo, run `/printing-press <service>` exactly once against the
   service's OpenAPI / HAR. Capture the emitted binary path and the
   tool surface count; record both as decision entries
   (`decisions.jsonl`).
4. **Author the DontPanic-side adapter.** Copy `ADAPTER_TEMPLATE.md`
   into `scripts/dontpanic_orchestrate/adapters/<service>_adapter.py`
   and fill the four blanks: `SERVICE_NAME`, the path to the PP
   binary, the redaction tier to apply, and the mutation-rejection
   policy (always reject in v0). The wrapper subprocess-spawns the
   PP-emitted MCP binary and proxies JSON-RPC tool calls + responses.
5. **Register the adapter.** Add an entry to `~/.dontpanic/adapters.
   json` pointing at the adapter module + per-service config.
   If `state_snapshot` does not yet surface registered adapters in its
   `evidence_refs` stream, the entry is inert metadata until it does.
6. **Commit a redacted example.** Place a placeholder version of
   `~/.dontpanic/adapters/<service>.json` (token fields replaced with
   `<paste-your-token>`) under the plan's `evidence/` directory.
   The real config stays gitignored at the operator's home.

## Output

This skill produces no runtime artifacts on its own. The artifacts of
the prescribed workflow are:

- A PP-emitted binary at `~/.dontpanic/adapters/<service>/<service>-
  pp-mcp` (gitignored).
- A DontPanic adapter Python module at
  `scripts/dontpanic_orchestrate/adapters/<service>_adapter.py`.
- A registry entry in `~/.dontpanic/adapters.json` and a per-service
  config at `~/.dontpanic/adapters/<service>.json` (both gitignored).
- A redacted example config under the plan's `evidence/` directory.

## Reference

- **Upstream**: CLI Printing Press
  (https://github.com/mvanhorn/cli-printing-press) and the
  Printing Press Library
  (https://github.com/mvanhorn/printing-press-library). Both are MIT
  licensed.
- **Version pinning policy**: v1 of any DontPanic adapter pins the PP
  version current at plan-lock time. The pin lives in the adapter's
  `~/.dontpanic/adapters/<service>.json` entry. Bumping the pin
  requires a v2 expansion plan with its own dogfood.
- **Decision tree**: see `DECISION_TREE.md` for the four filters and
  one worked example per anti-case.
- **Adapter skeleton**: see `ADAPTER_TEMPLATE.md` for the Python
  template every DontPanic-side adapter follows.
- **Boundary**: `docs/STATE_PROJECTION.md` documents the projection
  contract this skill enforces.
- **Roadmap entry**: `docs/ROADMAP.md` Phase C names this skill by
  path as the prescribed pattern for any external-API-wrap surface.

## Examples

A plan declares:

```yaml
surfaces: [external-api-wrap]
goal_type: new_feature
```

At lock time, `dontpanic plan lock` writes
`evidence/applicable-skills.json` containing:

```json
{
  "matches": [
    {
      "skill_name": "printing-press-adapter",
      "matched_surfaces": ["external-api-wrap"],
      "matched_goal_types": ["new_feature"],
      "provenance": "external",
      "external_cli": {
        "provider": "printing-press",
        "name": "CLI Printing Press",
        "command": "cli-printing-press",
        "version_pin": "pinned-at-plan-lock"
      }
    }
  ]
}
```

The operator reads this advisory, opens `DECISION_TREE.md`, confirms
all four filters pass for the target service, and proceeds with the
six-step workflow above. If any filter fails, the operator either
hand-rolls the handlers (Q3 fail) or files a v2 expansion plan (Q4
fail with mutating endpoints).
