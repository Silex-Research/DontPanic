# Capability surface vs the north-star builder

Date: 2026-08-12
Status: audit (not a plan)
Companion: `docs/brainstorms/2026-08-12-admitted-state-requirements.md` and plan `2026-08-12-001-infra-admitted-state-and-process-behaviors`

This is the separate scan. It is allowed to contradict the research plan’s priority.

## North star

A person building a new system may only half-know:

- who it is for
- which journeys matter
- what “done” looks like
- what the UX should be
- which stack should deliver it

They may arrive at any point: a feeling, a journey, a stack choice, “add this capability,” or “fix this capability.”

DontPanic is not Cursor, Replit, or a harness + one model. So the only honest reason to use it is something those tools do not do.

The current experience: mediocre, hard to reach, not interactive, and you still live in another agent’s harness to turn DontPanic on.

## The one-line verdict

DontPanic is a **referee for specified work**. It is not a **studio for unspecified work**.

Cursor / Replit / Claude Code optimize generation. DontPanic optimizes whether you should merge. That is a real wedge. It is also why a builder who is still deciding what to build cannot touch the product.

PRODUCT.md already claims the studio path (`dontpanic intake prd|issue`). Those commands do not exist. That is the hole, not a documentation typo.

## Why use it at all

Use it when a confident wrong agent costs more than ceremony:

- Writer and reviewer are different vendors, graded on the **same** acceptance contract
- Human gates pause paid loops
- Evidence you can reopen in six months
- Drift, quota, protected-path, and patch-completeness refusals
- Close that demands proof, not a chat “done”
- Several repos under one registry and one state projection

Do **not** use it to choose a market, invent journeys, pick a stack, or feel a product in an afternoon. agent-conventions will not do that either. It is a fail-closed **execution grammar** for work you already named.

## Intended journey vs actual journey

**Intended (PRODUCT.md, ROADMAP Phase C):** messy intent → intake + sufficiency → draft plan → human lock → volley → gates → evidence → signoff.

**Actual (`agent_brief.CANONICAL_WORKFLOW`):**

1. Install Python + at least one dispatchable worker (Claude and/or Codex).
2. `dontpanic setup` / `projects add` / `doctor`.
3. **Leave DontPanic.** Hand-author `docs/plans/<id>/{plan.md,features.json,decisions.jsonl}` in Claude Code / Cursor / a text editor.
4. `dontpanic plan lock` — grades a contract that already exists.
5. `dontpanic dispatch-from-plan` then `--confirm`.
6. Watch INBOX / `what-now` / a **projected** dashboard.
7. `dontpanic approve`, `plan audit`, `plan close`.

Activation energy is high before any product thinking happens. The missing object is a single interactive path: messy intent → questions → draft plan → lock.

## What is great

| Asset | Why it is actually good |
|---|---|
| Plan + features + decisions + audit + evidence | The unit of trust is a contract, not a transcript. |
| Cross-vendor volley | Operational version of “never let the writer be the only approver.” |
| Deterministic supervisor | Control plane is code. Matches the research we reviewed today. |
| Gates that bite | Lock, approve, drift ack, nested resume, patch completeness, quota. Overrides leave hashed evidence. |
| `delivers[]` / `user_impact` / DecisionBrief | Outcome and impact can be declared and marked stale instead of invented. |
| MCP dry-run default | Callers cannot silently dispatch. |
| State projection | One gather feeds CLI, MCP, dashboard. DontPanic stays a substrate. |
| Honest agent classes | Dispatchable vs operator-only is live in `dontpanic agent status`. |
| Worktrees, nested orch, goal governance | Real isolation and bounded children — after a plan exists. |

## What sucks

| Pain | Reality |
|---|---|
| Not interactive | By design (`ECOSYSTEM.md`). The human lives in another harness. |
| Hard to access | Source install, two CLIs, doctor, quota, calibration, registry, hand-authored plan. |
| Dashboard is a projector | Local SPA copies commands. It does not approve or dispatch. Firebase path is optional and heavy. |
| Intake is advertised and missing | PRODUCT.md `dontpanic intake`. ROADMAP Phase C. No `dontpanic new`. MCP has no `intake`. |
| `dontpanic plan validate` advertised, not a CLI | Validation is a Python schema script or MCP `validate_plan`. |
| Docs contradict the runtime | `~/.jarvis/` still in help. `what-now` exists and is barely advertised. Skills mix platform with personal trading/video. |
| agent-conventions assumes you already know | No intake schema, no journey-discovery, no stack-choice artifact, no “where am I in product definition” state. `decisions.jsonl` is unschema’d. |
| Sufficiency does not invent | Goal governance grades a written contract. It does not interview you. |
| You still need another agent | To write the plan, to implement, to audit. DontPanic orchestrates them. It is not a place you stay. |

## Capability inventory

| Surface | Status | Usable alone? | Helps a builder who does not yet know the product? |
|---|---|---|---|
| Plan lock / sufficiency / close | Shipped | CLI yes | Only after they wrote a plan |
| Volley | Shipped | If Claude/Codex installed | Yes — this is the trust payoff |
| Goal governance | Shipped (no auto-spawn) | CLI yes | Checks a goal, does not discover one |
| Nested orchestration | Shipped | If frontmatter present | Advanced |
| Dashboard | Shipped projection; Firebase optional | View yes, act no | Situational awareness |
| MCP | Shipped, no intake | Only via an MCP host | Lets a harness drive DontPanic |
| Notify (Discord / Buzz / macOS) | Partial | If configured | Away-from-keyboard |
| Capabilities / doctor / init | Shipped | Yes | Install, not product |
| Worktrees | Shipped | Yes | Isolation after a plan |
| Linear / Printing Press | Partial | After tokens | Issue links |
| Skills | Mixed | Only inside Claude | `brainstorm-gate` / `plan-artifacts` help if you are already in Claude |
| Memory | Split / unused for volleys | No | Does not help a new idea |
| Architecture map | Shipped | Yes | This repo, not greenfield design |
| `next` / what-now / operator console | Shipped (poorly advertised) | Yes | Unblocks in-flight work |
| Intake / `dontpanic new` | Documented only | — | **This would be the north-star feature** |

## agent-conventions (v1.16.0)

What a new project actually gets after a subtree add: ten schemas, Pydantic twins, resolver, iOS+Firebase conventions, skill standard. Homework remains: write a local resolver, author a plan folder by hand.

What it answers well: “how do we know this slice is done?” and “what becomes true for whom?”

What it refuses to answer: “what should we build?”, “which journey first?”, “which stack?”, “I only have a feeling.”

`user_journeys` on the objective contract are **auditor coverage**, not a discovery interview. `capability.use_cases` are `U1` registry tags, not product exploration.

## Implication for today’s research plan

Plan `2026-08-12-001` is the right next **trust** increment once a plan exists (admitted claims, hidden behaviors, schema’d decisions).

It is the **wrong** next increment if the goal is “why would a builder start here.” That problem is Phase C: messy intent → questions → draft plan → lock, on a surface the operator can stay in.

Shipping better handoffs into a product people cannot enter will make DontPanic more correct and still unused.

## If the north star is the job

Do not start with another schema for volley internals. Start with one interactive entry that can accept a builder at any completeness:

| Arrival state | What DontPanic should do |
|---|---|
| Feeling / half-idea | Interview: audience, job, non-goal, first proof. Refuse to lock. |
| Journeys only | Draft `user_journeys` + `delivers[]`. Ask for stack only when a surface is implied. |
| Stack only | Record `environments` / surfaces. Ask what outcome that stack is for. |
| Add a capability | Child plan + `requires_capabilities` + existing-contract sufficiency. |
| Fix a capability | Investigation or fix plan; reuse `completion_test` from the parent. |
| Full PRD | Parse (anydoc later), sufficiency, draft plan dir, human lock. |

The UX bar is not “a prettier dashboard that copies `dontpanic approve`.” It is: stay in one conversation or one console long enough to go from messy intent to a locked contract **without opening a second harness just to type YAML**. Other agents can still implement and audit. They should not be required to *activate* DontPanic.
