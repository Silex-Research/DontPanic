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

### Attaching a Gemini goal/experience audit (path B1)

The B1 workflow is three commands, no `register-worker`:

```bash
# 1. Render the SAME completion-audit prompt the dispatched path sends
#    and paste it into Gemini's own surface (CLI, AI Studio, …):
dontpanic plan attach-goal-audit <plan-id> --show-prompt

# 2. Save Gemini's JSON disposition array (fenced ```json is tolerated),
#    then attach it as a first-class audit envelope:
dontpanic plan attach-goal-audit <plan-id> --vendor gemini --response gemini.json

# 3. Or review the experience surface instead of the goal contract —
#    render the experience-specific prompt first (the consumer-journey
#    prompt, NOT the default goal prompt), then attach with matching kind:
dontpanic plan attach-goal-audit <plan-id> --show-prompt --kind experience
dontpanic plan attach-goal-audit <plan-id> --vendor gemini --response - --kind experience
```

The attach writes the same `audit-<vendor>-<iter>.{json,transcript.txt}`
pair the dispatched path produces — the plan-close gate and post-completion
backstop consume it directly, and a fresh `goal`-kind envelope is preferred
over a paid dispatch. Honesty rules, all refusals (exit 3, nothing written):

- a vendor **with** a registered executor (`claude`, `codex`) is refused —
  external attach must never fabricate dispatched-shape evidence for a
  dispatchable agent; use `dontpanic plan audit` there;
- the cross-vendor invariant still applies — vendor == effective
  implementer refuses without the same explicit override the dispatched
  path requires;
- a malformed or incomplete disposition array is refused — an external
  audit cannot agree by omission;
- an `experience`-kind envelope never satisfies the goal gate (and vice
  versa), and an envelope whose graded findings drift from the current v1
  findings goes stale and is ignored.

`dontpanic doctor --agent` reports this capability honestly: gemini shows as
operator-only / NOT dispatchable, with the attach path as its audit surface.

## Vocabulary: harness vs model vs profile vs role

Track D of plan 2026-07-27-001 (phase D0) splits agent identity into **four
distinct concepts**: three storage layers, plus **role** as an assignment
overlay on top of them — so that new model versions never require a new
registry key:

```text
        ┌─ ROLE ASSIGNMENT (overlay, not a layer) ──────────────────┐
        │  implementer / auditor / goal_auditor                     │
        │  roles.<slot> → profile id; capability flags gate         │
        │  which roles a profile may hold                           │
        └───────────────────────────┬───────────────────────────────┘
                                    ▼

Layer 3  WORKER PROFILES  (operator config)     ← Buzz-like agent cards
         display_name + harness + model + allowed_roles + capability overrides

                    │ binds one of each ▼

Layer 2  MODEL CATALOG    (data + discovery)    ← high churn; never registry keys
         vendor ids | openrouter/… slugs | ollama tags | aliases (grok-latest → grok-4.5)

                                    ▼

Layer 1  HARNESS REGISTRY (code, stable, few)   ← today's AGENT_REGISTRY
         claude | codex | future: gemini_cli | openrouter | ollama | …
         = how to invoke (argv, auth, sandbox, output parsing)
```

The four concepts, one by one:

1. **Harness** — the stable code adapter that knows how to invoke an agent
   runtime. `AGENT_REGISTRY` is the **harness adapter table**: its keys are
   harnesses (`claude`, `codex` today; `gemini_cli`, `openrouter`, `ollama`
   are planned), never model names. Dispatchability is earned by harness
   capabilities, not by what model runs behind the harness.
2. **Model** — data, not code: vendor model ids, `openrouter/…` slugs, Ollama
   tags, aliases. High churn; **a model id is a catalog entry, never a
   registry key**. Grok 4.5, the next Claude, or any OpenRouter OSS model
   arrive as catalog data — do not add model version strings to
   `AGENT_REGISTRY` (no Python change is involved in adopting a new model).
3. **Worker profile** — operator config binding a display name + harness +
   model + allowed roles (+ optional capability overrides). Profiles are the
   Buzz-style agent cards of D2; until they ship, config names harnesses
   directly.
4. **Role** — the slot a profile (or, today, a harness) holds:
   `implementer`, `auditor`, `goal_auditor` (see [Worker
   roles](#worker-roles)). **Capability flags gate which roles a
   harness/profile may hold** — `implementer` requires `file_edit` +
   `tool_use` + `non_interactive`; a read-only or interactive-only harness
   can at most hold audit-style roles.

**Legacy shorthand:** `roles.implementer: "claude"` in existing config names
a registry key directly. Under the Track D vocabulary, read it as shorthand
for *the default `claude_cli` worker profile* (harness `claude`, vendor
default model, all roles allowed). Legacy strings stay valid; profile ids
become an alternative, not a migration burden.

This page tracks the harness layer. Rows relax automatically as harnesses
land: the doc-drift guard reads `sorted(AGENT_REGISTRY.keys())` at test time,
so a newly registered harness makes honest wording *required*, not optional.

## Pointers

- [`README.md`](../README.md) — onboarding and the operator-vs-worker split
- [`docs/ECOSYSTEM.md`](./ECOSYSTEM.md) — who calls DontPanic (caller table, including OpenCode)
- `dontpanic agent brief` — the generated operating brief
- `dontpanic agent status --json` — machine-readable capability payload
