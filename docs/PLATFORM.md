# Jarvis Platform Thesis

Jarvis is portable trust infrastructure for bounded agent work.

Its job is to turn ambiguous human or agent intent into a machine-checkable
contract, execute that contract with bounded agents, and preserve enough proof
that another human or agent can understand what happened, why it happened, and
whether the outcome should be trusted.

## Simple Goal

Jarvis lets agents and humans do real work on behalf of an operator without
losing the operator's judgment, the architecture context, or the evidence trail.

The unit of trust is not a chat transcript or a single model's confidence. The
unit of trust is the contract:

- `plan.md` declares intent, scope, target environment, gates, and bounds.
- `features.json` declares machine-checkable acceptance items.
- `decisions.jsonl` records why choices were made.
- `audit/*.json`, `signoff*.json`, and `evidence/` prove what happened.

Any compatible runner should be able to read those artifacts, execute bounded
work with any vendor mix, and produce comparable evidence.

## Five Layers

1. Governance

   `SOUL.md`, `AGENTS.md`, `USER.md`, tiers, privacy levels, human gates, and
   protected paths define what work is allowed and when judgment is required.

2. Capability

   Skills, commands, `claude/RESOLVER.md`, shared conventions, and schemas turn
   repeated work into reusable procedures. Skills are not side content; they are
   the capability layer that makes the platform repeatable.

3. Memory

   Project memory, durable lessons, operator preferences, prior failures, and
   provenance explain how the system improves over time. Memory must remain
   evidence-aware: remembered lessons should point back to artifacts whenever
   possible.

4. Contracts

   Plans, features, decisions, targets, and protected paths are the commitment
   layer. This is where fuzzy intent becomes bounded work.

5. Runtime and Proof

   Executors, adversarial auditors, circuit breakers, quota checks, INBOX,
   notifications, transcripts, signoff, and dashboards run the contract and
   expose the result.

## Stakeholders

Jarvis has two first-class stakeholder shapes.

Humans need narrative summaries, visual architecture, mobile-friendly
notifications, concise gate prompts, and enough context to exercise judgment
without reading every token the agents produced.

Agents need schemas, deterministic exit codes, structured event streams,
idempotent commands, stable artifact locations, redaction guarantees, and clear
"cannot proceed" states.

These are different renderings of the same state. The platform should not invent
separate truths for humans and agents.

## What Jarvis Protects Against

- Single-model blind spots, especially one vendor approving its own work.
- Cost, quota, wall-clock, or iteration runaway.
- Hallucinated evidence and unverifiable completion claims.
- Plan drift after work starts.
- Protected-path or environment mistakes.
- Human oversight collapsing into rubber-stamping because every event looks
  equally urgent.

The defense is not more agent output. The defense is bounded contracts,
adversarial audit, structured proof, and tier-appropriate human judgment.

## Design Consequences

- Cross-model execution is a safety mechanism, not just a feature.
- Skills and memory must be portable enough for non-Claude runners to consume.
- Notifications must carry structured escalation data, not only prose.
- Autonomy must be bounded by plan contracts, loop caps, gates, and evidence.
- Architecture docs should explain the five layers and stay linked to the
  executable artifacts that prove the system's current behavior.

