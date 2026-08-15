# Requirements — Admitted shared state and process behaviors

Date: 2026-08-12
Status: requirements for plan `2026-08-12-001-infra-admitted-state-and-process-behaviors`
Sources: today's review of the monokern orchestration post, the real papers it mashed together, and seven capability posts (Hermes/AG-UI, anydoc, Basis behaviors, context layer, NVIDIA NOOA, harness/loop/graph, Claude workflow graphs).

This is the requirements brief. The executable contract is the plan directory. The north-star capability-surface audit is a separate document.

## Problem

DontPanic already has a deterministic supervisor and an adversarial implementer/auditor pair. What fails in production is the **handoff**: the next agent (or the operator) receives a compressed summary instead of admitted, grounded state. That is the same failure the real research names as context-handoff decay, and the same failure Basis names as "right answer, untrustworthy process."

## What we reviewed

### Not a source

- [monokern 2087466184702628235](https://x.com/monokern/status/2087466184702628235) claims a "Stanford Systems Intelligence Lab" survey (Router / Planner-Worker / Supervisor / Hierarchical; Intake → Plan → Execute → Merge → Evaluate). That pairing does not check out. The quoted article argues the opposite: kill distributed reasoning.

### Real sources we will use

| Source | Load-bearing claim |
|---|---|
| Mao & Mirhoseini, DeLM (arXiv:2606.10662) | Agents coordinate through a **verified shared context**. Compact gists. Unfold evidence. Admit only if grounded. |
| Google/MIT scaling (arXiv:2512.08296) | Multi-agent helps **parallelizable** work. It **hurts** sequential work. Independent agents amplify errors 17.2×; a central validator contains that to 4.4×. |
| Quoted control-plane article | Don't use LLMs for signal detection. One owner keeps the diagnostic chain. Sub-agents return facts. |
| Basis + Braintrust behavior specs | Grade the **process** on the trajectory, not only the outcome. Specs are **hidden from the agent**. |
| anydoc (Firecrawl) | Parse documents deterministically before any model sees them. |
| NVIDIA NOOA | Make the deterministic-vs-LLM cut visible in the source. Do not rewrite the supervisor as objects. |
| beamnxw harness / loop / graph | Diagnostic vocabulary. Not a rebuild. |
| Claude dynamic workflows | Diamonds and verifiers apply only where work is independent. Claude must not write the DontPanic control graph. |
| Hermes / AG-UI / "context layer" | Other people's products. Caller / enterprise-search concerns. |

## Product requirements we will implement

### R1 — Verified admission (must)

A finding, failed hypothesis, or binding constraint becomes a **claim** before the next worker sees it.

- Status: `proposed | admitted | rejected | stale`
- Required: `evidence_refs`, content hash, who admitted, when
- Next implementer prompt shows **admitted** claims only
- Full audit JSON remains on disk as the unfold target

### R2 — Gist + unfold (must)

The next agent gets a compact gist (verdict, claim IDs, files, constraint) plus a path. It does not get a rewritten narrative. Same pattern as DecisionBrief for humans.

### R3 — Process behaviors, hidden from workers (must)

A small closed set of behaviors judged off existing envelopes (`commands_run`, git-state, vendor pair, `{repo,env,project}` declaration). V0 judges are **deterministic**. LLM judges are out of scope.

Behaviors are not skills. They are not injected into implementer/auditor prompts.

### R4 — Schema the decisions log (must)

`decisions.jsonl` already exists. It has no schema. Add one. Highest-ROI contract because the artifact is already in every plan.

### R5 — Keep the supervisor deterministic (constraint)

No LLM router, planner, or synthesizer in the control plane. No Claude-authored orchestration script for DontPanic volleys.

### R6 — Topology by task (later, not V0)

- Sequential local feature → single agent or one volley
- Risky / user-facing → adversarial pair (validation bottleneck)
- Independent features / evidence clusters → diamond: fan-out, reduce in code, one synthesis
- Stuck bug → parallel attempts sharing admitted FAIL/FACT claims

### R7 — anydoc as intake adapter (later, blocked on Phase C)

Capability manifest + local parse to markdown + provenance. Do not vendor a parser into the orchestrator. Do not ask an LLM to "read this PDF."

## Explicit non-goals

- Hermes / AG-UI / in-app generative UI
- Vector "context platform" or knowledge graph of the repo
- NVIDIA NOOA rewrite of `supervisor.py`
- LangGraph / Claude-written supervisor graphs
- Replacing Cursor, Replit, or any harness
- Fixing DontPanic's own activation UX in this plan (separate north-star audit)

## V0 slice (this plan)

Contracts in agent-conventions + findings handoff change + three-to-five deterministic behavior judges + docs for non-goals.

## Later slices (trigger-gated)

- Independent-feature diamond in `dispatch_volley`
- anydoc capability + Phase C intake
- LLM behavior judges for semantic process (cite primary source)
- Operator-console rendering of admitted claims / behavior verdicts
