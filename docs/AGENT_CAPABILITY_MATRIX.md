# Agent Capability Matrix

One page that answers "which agents can do what?" without reading Python
source. Everything here is derived from the runtime concepts in
`scripts/dontpanic_orchestrate/agent_surface.py` (capability booleans, worker
roles, `KNOWN_OPERATOR_AGENTS`), `executors.AGENT_REGISTRY` (the registered
executor list), and `scripts/dontpanic_orchestrate/invocation_context.py`
(the canonical agent-runtime universe, including operator surfaces such as
`opencode`).

The **live machine source of truth** is always:

```bash
dontpanic agent status           # human-readable classification
dontpanic agent status --json    # can_operate / can_be_dispatched / can_orchestrate
```

If this page and `agent status` ever disagree, `agent status` wins — and the
doc-drift guard (`doc_drift.py`, plan 2026-07-27-001 F002) fails the test
suite until this page is corrected.

## The three capability axes

DontPanic classifies every named agent on three **independent** booleans —
they are orthogonal axes, not a ladder:

| Axis | Meaning | Source of truth |
|---|---|---|
| `can_operate` | Can drive DontPanic by running its CLI commands: lock plans, approve gates, read guidance. Always true for any named agent. | Definition — any agent that can run the commands can operate |
| `can_be_dispatched` | Has a real executor registered in `executors.AGENT_REGISTRY`, so DontPanic can send it implement/audit work. | `AGENT_REGISTRY` membership |
| `can_orchestrate` | The harness can spawn sub-agents (e.g. Claude Code workflows). Reported only — DontPanic does not act on it. | `agent_surface.ORCHESTRATOR_CAPABLE_AGENTS` |

An agent with `can_operate=true` and `can_be_dispatched=false` is
**operator-only**: it should operate DontPanic, not configure itself as a
worker. `dontpanic agent register-worker` refuses such agents (exit code 3)
before writing any config.

## The matrix

| Agent | can_operate | can_be_dispatched | can_orchestrate | Notes |
|---|---|---|---|---|
| `claude` | yes | **yes** | yes | Claude Code CLI. Common implementer; its harness can spawn sub-agents. |
| `codex` | yes | **yes** | no | Codex CLI. Common cross-vendor auditor. |
| `gemini` | yes | no | no | Known operator-only runtime. Goal/experience reviews attach as operator-driven external evidence (D001 path B1); a `gemini_cli` harness restricted to `goal_auditor` is the planned follow-up (B2, F014). |
| `grok` | yes | no | no | Known operator-only runtime. Becomes a harness only when sandboxed tool-use is real (D002); the model id belongs in a model catalog, never in the registry. |
| `opencode` | yes | no | no | Operator / planning surface (D005). Runs the DontPanic CLI or MCP tools; see the [ECOSYSTEM caller table](./ECOSYSTEM.md#who-calls-dontpanic). |
| `cursor` | yes | no | no | Operator surface — IDE MCP client against `dontpanic mcp serve`. |
| `antigravity` | yes | no | no | Operator surface. |
| `aider` | yes | no | no | Operator surface. |
| `ollama` | yes | no | no | Local models used as operator-side tooling (safety probes, embeddings); not a dispatchable executor. A capability-gated `ollama` harness is planned under Track D (D002/D010). |

Any agent name **not** in this table still has `can_operate=true` and
`can_be_dispatched=false` — the classification is registry-driven, so an
unknown agent is operator-only by construction, never rejected from operating.

## Worker roles

Only agents with `can_be_dispatched=true` can hold a worker role. The three
role slots (`agent_surface.ROLES`) are:

| Role | What DontPanic sends it | Typical assignment today |
|---|---|---|
| `implementer` | Feature implementation from a locked plan | `claude` |
| `auditor` | Cross-vendor implementation audit of the implementer's work | `codex` |
| `goal_auditor` | Goal/experience audit: does the result serve the plan's stated goal? | `codex` (see the Gemini path below) |

Assigning a role to an operator-only agent (e.g. `roles.goal_auditor=gemini`)
is refused — the role holder must be in the registry. `dontpanic agent status`
shows the effective per-role assignment and each holder's classification.

## Recommended low-cost topology

The four-agent cost topology a new operator should reach for, mapped onto the
axes above (decision D001 resolved the Gemini path: B1 now, B2 when the
Gemini CLI proves non-interactive dispatch):

```text
You
  ↓
OpenCode — operator and planning surface (runs the DontPanic CLI / MCP tools)
  ↓
DontPanic — plan lock, governance, volley, evidence, signoff
  ├── Claude — implementer role
  ├── Codex  — auditor role (cross-vendor implementation review)
  └── Gemini — goal / experience review, attached by the operator as
               external evidence (operator-only today; D001 path B1)
  ↓
Human — approval, merge, deployment
```

Reading the topology against the matrix:

- **OpenCode** sits on the `can_operate` axis only: it plans, locks, and
  approves, and DontPanic never sends it work.
- **Claude and Codex** are the two agents with `can_be_dispatched=true` —
  the whole dispatched panel, until more harnesses land.
- **Gemini** participates through the operator: an operator (or OpenCode
  session) runs a Gemini goal/experience review and attaches the result as
  external evidence (path B1). When the `gemini_cli` harness ships (path B2,
  F014), the `goal_auditor` slot becomes assignable to it and the same
  topology runs fully automated.
- **The human gate** is unchanged in every variant: approval and merge stay
  with you.

## Vocabulary: harness vs model vs profile

Track D of plan 2026-07-27-001 splits agent identity into three layers so new
model versions never require a new registry key:

1. **Harness** — the stable code adapter (today's registry keys `claude`,
   `codex`; future `gemini_cli`, `openrouter`, `ollama`). Dispatchability is
   earned by harness capabilities.
2. **Model** — data, not code: vendor model ids, OpenRouter slugs, Ollama
   tags, aliases. High churn; never a registry key.
3. **Worker profile** — operator config binding a display name + harness +
   model + allowed roles.

This page tracks the harness layer. Rows relax automatically as harnesses
land: the doc-drift guard reads `sorted(AGENT_REGISTRY.keys())` at test time,
so a newly registered harness makes honest wording *required*, not optional.

## Pointers

- [`README.md`](../README.md) — onboarding and the operator-vs-worker split
- [`docs/ECOSYSTEM.md`](./ECOSYSTEM.md) — who calls DontPanic (caller table, including OpenCode)
- `dontpanic agent brief` — the generated operating brief
- `dontpanic agent status --json` — machine-readable capability payload
