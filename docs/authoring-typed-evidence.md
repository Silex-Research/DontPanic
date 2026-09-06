# Authoring typed evidence for consumer journeys

Who this is for: anyone recording `evidence_refs` on a feature in
`features.json` for a plan whose objective contract declares a consumer
journey (`user_journeys[].consumer` set). Those refs are what
`dontpanic plan audit` and `dontpanic plan close` read to decide whether the
journey is **satisfied**, **pending**, or **unproven**. Untyped artifacts on
disk never satisfy the gate; only typed refs do.

The rules below are enforced by `experience_readiness_honesty.py` and
`completion_gate.py` (plan 2026-06-15-002; tightened 2026-09-05 after PR56
review findings r3422558988 and r3422558994).

## The three things a satisfied journey needs

1. **Typing per surface.** Every surface the journey declares needs a ref
   bound to that surface (`surface_class`), with an `evidence_class` the
   surface accepts, `data_provenance: real`, and `availability: available`.
2. **Every required family covered.** For each dependency `data_source` the
   refs name, every consumer family the journey spans (`human`, `agent`) must
   carry a typed ref. A source typed by the agent family only, on a journey
   that also has a human surface, is *pending*, never satisfied.
3. **One real journey-execution ref.** Proof that the flow actually ran, keyed
   with the reserved data source **`journey_execution`**. This is separate
   from dependency refs: a real, available `tool_call_transcript` for
   `data_source: payments` proves the payments dependency was up, not that
   the journey executed. Without a `journey_execution` ref the journey is
   *unproven*.

Accepted execution classes: `screenshot`, `recording`, `journey_walk`,
`terminal_transcript`, `tool_call_transcript`, `cli_transcript`,
`contract_check`. Seeded provenance never counts.

## Binding a ref to a journey

The gate binds a ref to a journey by path: the `uri` must contain
`/<journey-name>/`. The conventional location is
`evidence/goal-governance/post_impl/<surface_class>/<journey-name>/<file>`.

## Example

Journey in `objective_contract.json`:

```json
{
  "name": "agent-lists-tools",
  "description": "an agent lists the available tools over MCP and reads status",
  "surfaces": ["mcp_tool"],
  "consumer": "agent",
  "acceptance_signals": ["tools/list returns the fixture tool set"]
}
```

Refs on the delivering feature in `features.json`:

```json
"evidence_refs": [
  {
    "type": "log",
    "uri": "evidence/goal-governance/post_impl/agent_mcp_tool/agent-lists-tools/tools-list.json",
    "surface_class": "agent_mcp_tool",
    "data_source": "mcp:tools/list",
    "consumer_family": "agent",
    "availability": "available",
    "data_provenance": "real",
    "evidence_class": "tool_call_transcript"
  },
  {
    "type": "log",
    "uri": "evidence/goal-governance/post_impl/agent_mcp_tool/agent-lists-tools/journey-walk.json",
    "surface_class": "agent_mcp_tool",
    "data_source": "journey_execution",
    "consumer_family": "agent",
    "availability": "available",
    "data_provenance": "real",
    "evidence_class": "tool_call_transcript"
  }
]
```

The first ref types the dependency and satisfies the surface. The second is
the execution proof. With only the first, `plan audit` blocks with a reason
naming the missing `journey_execution` ref.

If the journey also declared a human surface (`"surfaces": ["web",
"mcp_tool"]`, `"consumer": "both"`), the `mcp:tools/list` source would also
need a `consumer_family: human` ref (for example a `screenshot` on
`read_only_ui`) before the journey could be satisfied.

## Honest degradation

When a dependency is down, say so: `availability: unavailable`,
`data_provenance: degraded`, and a `degraded_mode`. Every required family must
carry that honest signal. A family that stays `available` while another
reports the outage is *degraded_dishonest* and blocks. A journey whose refs
are all honest-unavailable is honest but still not a success; it needs the
execution ref once the dependency is back.

## Reading a blocking reason

`plan audit` prints, per blocked journey, the typing verdict, the honesty
verdict, and `real_execution=True|False`, followed by the specific gap:
`no real journey-execution ref (add an EvidenceRef with
data_source="journey_execution" …)` or `missing required families:
<source>:<family>`. Fix the named gap; do not add unrelated artifacts.
