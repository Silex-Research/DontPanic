# Jarvis — In Plain English

Jarvis turns messy software requests into reviewed, tested, commit-ready
patches.

You give Jarvis a goal:

- "Build this feature."
- "Catch Android up to the iOS app."
- "Diagnose why this production system is broken."
- "Turn this PRD into implementation work."
- "Audit this platform and fix the gaps."

Jarvis does not immediately let an agent start coding.

First, it figures out whether the request is clear enough. If it is not,
Jarvis uses its own research and discovery skills to inspect the repo,
docs, environment, tests, architecture, prior plans, logs, and product
context. Then it comes back with a proposed plan or follow-up questions.

Only after the human approves the plan does Jarvis dispatch agents.

One agent implements. Another (different vendor) audits. Jarvis tracks
findings, evidence, tests, gates, decisions, and signoff.

The point is simple:

> AI agents can write code. Jarvis makes the work trustworthy enough to
> ship.

---

## What Jarvis Is

Jarvis is a local AI software-delivery system.

It is not just a chat interface. It is not a SaaS. It is not "one more
agent."

Jarvis is the layer that coordinates agents, plans, memory, skills,
gates, evidence, and commits across many projects.

It can manage:

- one repo or many repos
- new projects created by Jarvis
- existing messy projects
- mobile apps
- web apps
- backend systems
- production incidents
- cross-platform parity work
- platform audits
- feature development
- root-cause investigations

Install Jarvis once. Register projects. Give it work. It plans, verifies,
dispatches, audits, and packages evidence.

---

## Who Uses Jarvis

1. **A developer** — wants AI help, but does not want to blindly trust
   whatever Claude, Codex, Cursor, or another agent says is done.
2. **A founder or product-builder** — has product ideas, PRDs, bugs, and
   half-built systems; needs them turned into real implementation plans
   and verified patches.
3. **An AI coding agent** — Claude Code, Codex CLI, Cursor, Clawdbot-style
   agents, or custom Claude-managed agents need a clear way to discover
   Jarvis, install it, configure it, and call it.
4. **A remote operator** — may want to trigger Jarvis from Claude,
   ChatGPT, Clawdbot, or another managed-agent surface without building
   a custom remote infrastructure.
5. **Future non-technical users** — a UI may make this accessible to
   non-technical users later. That is not the first product.

---

## The Core Workflow

**1. Register a project**

```
jarvis projects add spindine ~/GitHub/SpinDineSwift
```

**2. Give Jarvis a brief**

```
jarvis intake prd docs/product/creator-hub.md --project creator-hub
```

or:

```
jarvis intake issue prod-incident.md --project real-estate-analytics
```

**3. Jarvis checks sufficiency**

If the brief is good enough, Jarvis drafts a plan.

If it is not, Jarvis researches:

- repo structure
- test commands
- build system
- docs and ADRs
- prior plans
- product references
- production logs if allowed
- screenshots or examples
- parity references
- security constraints

Then it returns one of:

- "Ready for plan review."
- "I need these answers first."
- "This should be a discovery / root-cause plan, not an implementation
  plan."
- "This is too risky without human clarification."

**4. Human approves**

No implementation starts until the human approves the plan.

**5. Agents execute**

- primary agent implements
- auditor agent (different vendor) reviews
- Jarvis records evidence
- gates pause when human approval is needed
- signoff happens only when acceptance is met

---

## Why This Matters

**Normal AI coding flow:**

> Ask agent → agent edits → agent says done → you hope it is right.

**Jarvis flow:**

> Request → research if needed → plan → human approval → implementer →
> auditor → tests → evidence → signoff → commit-ready patch.

That is the difference.

Jarvis does not assume agents are reliable. It assumes agents are useful
but need structure.

---

## What Makes Jarvis Different

**Plan-first.** Agents do not start with vibes. Work is locked into a
plan with acceptance criteria.

**Research-aware.** If the request is vague, Jarvis can inspect the
project and propose what needs to be known before coding.

**Multi-agent verification.** One model does not grade itself. An
implementer and auditor work against the same contract.

**Local-first.** Jarvis runs where your repos live. It uses the tools
you already have.

**Project-aware.** Each repo can have its own tests, protected paths,
agents, gates, standards, and deployment rules.

**Evidence-backed.** Every decision, finding, audit, test result, and
signoff is saved.

**Governed recursion.** If work needs a child plan, Jarvis bounds it
with depth limits, cycle checks, child charters, return conditions, and
human re-entry.

---

## Important Product Principle

**Jarvis should not fake certainty.**

If a user gives it:

> "Build the creator hub."

Jarvis should not immediately code.

It should ask:

- What is the creator hub?
- Who uses it?
- What is MVP?
- What is out of scope?
- What product references exist?
- What tests or QA evidence are required?
- Is this new functionality or parity with another app?
- Is there production data involved?

If enough context exists in the repo, Jarvis can research and draft the
plan. If not, it asks the human.

That is the product discipline.

---

## What "Sufficient Enough" Means

Jarvis can start planning when it has enough to define:

- project
- desired outcome
- target surface
- constraints
- acceptance criteria
- risk level
- evidence needed
- what is out of scope

If it lacks these, it researches or asks.

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

If not sufficient, Jarvis should not code. It should produce:

- clarification questions, or
- a research plan, or
- a root-cause investigation plan.

---

## Revised Product Summary

Jarvis is a global local tool for turning software requests into
verified work.

It can manage many projects. It can research unclear problems. It can
draft plans. It can dispatch agents. It can audit their work. It can
pause for human decisions. It can produce evidence and commit-ready
patches.

It does not replace developers.

It makes AI coding agents safe enough to use on serious software.

---

## See Also

- [`PLATFORM.md`](./PLATFORM.md) — the architectural thesis (5 layers,
  stakeholders, design consequences).
- [`ROADMAP.md`](./ROADMAP.md) — the phased build plan that turns the
  current substrate into the global tool described here.
