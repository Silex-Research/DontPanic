# DontPanic — In Plain English

> The safety layer between “the agent says it’s done” and “you merge it.”

DontPanic turns well-developed software plans into reviewed, tested,
commit-ready patches. Operate it directly or delegate administration to an
optional operator agent that keeps an authorized plan moving autonomously.

You start with a goal:

- "Build this feature."
- "Catch Android up to the iOS app."
- "Diagnose why this production system is broken."
- "Turn this PRD into implementation work."
- "Audit this platform and fix the gaps."

DontPanic does not immediately let an agent start coding.

You or your planning agent investigates the request and authors the plan.
The plan names the outcome, acceptance criteria, scope, environment, required
proof, and execution limits. DontPanic validates and locks that contract;
it does not provide a general natural-language brief-to-plan service.

There are narrower planning capabilities: `dontpanic config inventory
--setup-plan --format json` emits a setup/update plan skeleton from incomplete
configuration. The internal design-review loop can also revise an existing
feature decomposition when supplied a planner executor; the current `plan lock`
CLI invokes it with an auditor only. Neither is a general research-and-drafting
entry point for a new product request.

Only after the human approves the plan does DontPanic dispatch agents.

That approval can authorize continued implementation, correction, review, and
verification across the plan. An operator such as Grok Bot can manage those
steps without routine human intervention, returning for reserved decisions or
blockers it cannot resolve within the authorization. Grok Bot is optional;
other CLI/MCP callers can serve the same role. See
[autonomous operation](./AGENT_QUICKSTART.md#autonomous-operation).

One agent implements. Another (different vendor) audits. DontPanic tracks
findings, evidence, tests, gates, decisions, and signoff.

The point is simple:

> AI agents can write code. DontPanic makes the work trustworthy enough to
> ship.

The ten-word positioning:

> **OpenClaw helps agents do things across your digital life. DontPanic
> helps agents ship software safely.**

---

## What DontPanic Is

DontPanic is **the verified software-delivery layer** — the tool that
turns approved plans into reviewed, tested, commit-ready patches by
running plan-locked, cross-vendor adversarial agent volleys with human
gates and evidence trails.

DontPanic is **not** a personal-agent runtime. It does not own messaging
channels, mobile presence, chat surfaces, plugin marketplaces, or a
hosted control plane. Mature systems already solve those problems —
[OpenClaw](https://github.com/openclaw/openclaw),
[Claude Code](https://claude.com/claude-code),
[Codex CLI](https://github.com/openai/codex),
Cursor, Claude-managed agents — and DontPanic is designed to be **called
by** those systems, not to replace them. See
[`ECOSYSTEM.md`](./ECOSYSTEM.md) for the caller-pattern recipes.

DontPanic is the layer that coordinates plans, agents, memory, skills,
gates, evidence, and commits across many projects.

It can manage:

- one repo or many repos
- new projects created by DontPanic
- existing messy projects
- mobile apps
- web apps
- backend systems
- production incidents
- cross-platform parity work
- platform audits
- feature development
- root-cause investigations

Install DontPanic once. Register projects. Author and authorize the plan.
DontPanic dispatches, verifies, audits, and packages evidence. Operate the
workflow yourself or delegate its administration to an operator agent.

---

## Who Uses DontPanic

1. **A developer** — wants AI help, but does not want to blindly trust
   whatever Claude, Codex, Cursor, or another agent says is done.
2. **A founder or product-builder** — has product ideas, PRDs, bugs, and
   half-built systems; needs them turned into real implementation plans
   and verified patches.
3. **An AI coding agent** — Claude Code, Codex CLI, Cursor,
   OpenClaw-hosted skills, Clawdbot-style agents, or custom
   Claude-managed agents need a clear way to discover DontPanic, install
   it, configure it, and call it. DontPanic exposes a CLI plus (Phase B)
   a thin MCP surface; the agent's runtime owns chat / scheduling /
   reach.
4. **A remote operator** — triggers DontPanic from Claude, ChatGPT,
   OpenClaw, Clawdbot, or another managed-agent surface through that
   system's existing remote infrastructure. DontPanic ships no custom
   daemon — the caller's runtime carries the remote burden.
5. **Future non-technical users** — a UI may make this accessible to
   non-technical users later. That is not the first product.

---

## The Core Workflow

**1. Register a project**

```
dontpanic projects add spindine ~/GitHub/SpinDineSwift
```

**2. Author a plan directory**

Phase C intake (`dontpanic intake prd|issue|…`) is **abandoned**.
DontPanic does not turn a brief into a draft plan. A new operator
authors `docs/plans/<id>/` (or copies `examples/plans/hello-dontpanic`)
and locks it:

```
dontpanic plan lock docs/plans/<plan-id>/
```

See [`AUTHORING_PLANS.md`](./AUTHORING_PLANS.md) and the README
60-second start. Messy PRD / issue text stays with the operator.

**3. Sufficiency is the plan lock, not an intake loop**

`dontpanic plan lock` is the existing gate. If the plan is not
complete enough, lock refuses. There is no research/intake product
that asks follow-up questions and drafts a plan for you.

**4. Human approves**

No implementation starts until the human approves the plan.

**5. Agents execute**

- primary agent implements
- auditor agent (different vendor) reviews
- DontPanic records evidence
- gates pause when human approval is needed
- signoff happens only when acceptance is met

---

## Why This Matters

**Normal AI coding flow:**

> Ask agent → agent edits → agent says done → you hope it is right.

**DontPanic flow:**

> You or your agent researches and plans → human authorization → implementer →
> auditor → tests → evidence → signoff → commit-ready patch.

That is the difference.

DontPanic does not assume agents are reliable. It assumes agents are useful
but need structure.

---

## What Makes DontPanic Different

**Plan-first.** Agents do not start with vibes. Work is locked into a
plan with acceptance criteria.

**Operator-driven.** Your planning agent can investigate an unclear request
before writing the contract. Once authorized, an operator can manage the plan
through implementation, review, correction, and verification.

**Multi-agent verification.** One model does not grade itself. An
implementer and auditor work against the same contract.

**Local-first.** DontPanic runs where your repos live. It uses the tools
you already have.

**Project-aware.** Each repo can have its own tests, protected paths,
agents, gates, standards, and deployment rules.

**Evidence-backed.** Every decision, finding, audit, test result, and
signoff is saved.

**Adapter-aware.** DontPanic can use external tools as evidence sources
when they fit the contract. The planned Printing Press adapter work
credits [CLI Printing Press](https://github.com/mvanhorn/cli-printing-press)
and the [Printing Press Library](https://github.com/mvanhorn/printing-press-library)
for the agent-native CLI/MCP pattern: compact structured output, dry-run
flows, typed exits, local caches, and generated service adapters. DontPanic
does not own that project; it owns the allowlist, provenance, redaction,
evidence normalization, and signoff rules around any adapter it uses.

**Governed recursion.** If work needs a child plan, DontPanic bounds it
with depth limits, cycle checks, child charters, return conditions, and
human re-entry.

---

## Important Product Principle

**DontPanic should not fake certainty.**

If a user gives it:

> "Build the creator hub."

DontPanic should not immediately code.

It should ask:

- What is the creator hub?
- Who uses it?
- What is MVP?
- What is out of scope?
- What product references exist?
- What tests or QA evidence are required?
- Is this new functionality or parity with another app?
- Is there production data involved?

The human or planning agent researches and drafts the plan. If information is
missing, the caller resolves it before `dontpanic plan lock`.

That is the product discipline.

---

## What "Sufficient Enough" Means

DontPanic can start planning when it has enough to define:

- project
- desired outcome
- target surface
- constraints
- acceptance criteria
- risk level
- evidence needed
- what is out of scope

If it lacks these, `dontpanic plan lock` refuses. There is no intake loop that researches or asks.

**For a PRD, sufficient means:**

- user / persona
- problem
- desired behavior
- MVP or parity claim
- acceptance examples
- UX references if user-facing
- rollout constraints

**For a production issue, sufficient means:**

- symptom
- expected behavior
- environment
- logs / examples
- blast radius
- urgency
- permission to inspect relevant data / logs

**For parity work, sufficient means:**

- source platform
- target platform
- parity dimensions
- acceptable differences
- priority flows
- QA evidence

If the plan is insufficient, DontPanic refuses the lock. You or the planning
agent can resolve the missing information with:

- clarification questions, or
- a research plan, or
- a root-cause investigation plan.

---

## Revised Product Summary

DontPanic coordinates implementation, independent review, and evidence for
approved software plans across multiple projects.

You or an operator agent supplies the plan and manages progress. DontPanic
dispatches workers, audits their work, collects evidence, and pauses at
configured gates. Production reliability depends on the acceptance criteria,
independent review, actual proof, and release decisions in that workflow.

It does not replace developers.

It makes AI coding agents safe enough to use on serious software.

---

## See Also

- [`ECOSYSTEM.md`](./ECOSYSTEM.md) — DontPanic's place in the agent
  ecosystem: who calls DontPanic (OpenClaw, Claude Code, Codex CLI,
  Cursor, Claude-managed agents, MCP clients), what DontPanic is *not*
  trying to be, and a concrete OpenClaw-as-caller integration recipe.
- [`PLATFORM.md`](./PLATFORM.md) — the architectural thesis (5 layers,
  stakeholders, design consequences).
- [`ROADMAP.md`](./ROADMAP.md) — the phased build plan that turns the
  current substrate into the global tool described here.
- [`CONFIGURATION.md`](./CONFIGURATION.md) — every operator-facing knob
  in one place: agents/models, notification sinks, quota caps, breakers,
  per-project config, and agent-discovery surfaces.
