# State Projection — Adapter Governance Contract

DontPanic emits read-only state projections through three equivalent surfaces:

- `dontpanic state snapshot` CLI (plan 2026-05-09-003 F004)
- `state_snapshot` + `state_stream` MCP tools (F005)
- `dontpanic state export-dashboard` bundled-dashboard exporter (F007)

All three reduce to one function — `state_projection.gather()` (F002) —
emitting the **state-snapshot** envelope schema published as
agent-conventions v1.6.0 `state-snapshot.schema.json` (F001).

This document is the governance contract adapters must follow when
consuming the projection. The contract has four invariants. Plus a
worked example.

---

## The four invariants

### 1. Stable-ID discipline

Adapters MUST identify entities by the stable IDs emitted in the
projection. They MUST NOT join on internal artefacts (git SHAs, file
paths, process IDs) — those are exposed for debugging only, never as
keys.

**The stable IDs are:**

| Stream | Stable ID | Format |
|---|---|---|
| plans | `plan_id` | `YYYY-MM-DD-NNN-(feat\|fix\|infra\|refactor\|chore\|docs\|test)-<slug>` |
| features (inside plans_summary or evidence_refs) | `feature_id` | `^F\d{3}$` |
| decisions | `decision_id` | `^D\d{3}$` (unique within a plan) |
| supervisors | `supervisor_id` | `<pid>:<started_at>` composite |
| inbox events | `event_id` | `<plan_id>:<event>:<captured_at>:<feature_id-or-empty>` |
| gates | `(plan_id, gate_name)` | `gate_name` is the literal string |
| quota | `(vendor, window)` | Both come from a closed enum |

An adapter that joins by `git_sha` is wrong. An adapter that displays
"PID 12345" as the canonical identifier is wrong (PID is only present
at `full` redact_level, which MCP refuses).

### 2. Schema-version pinning

Adapters MUST pin the schema version they were written against and
emit a clear error if the snapshot's `schema_version` differs.

The current schema version is `"1.0"` (locked by F001). Any breaking
change to a stream shape requires a major bump and a deprecation
window. Additive changes (new optional fields) do not bump the major;
adapters MUST silently ignore unknown fields.

Pinning code template:

```python
SCHEMA_VERSION_SUPPORTED = "1.0"

def consume(envelope: dict) -> None:
    if envelope["schema_version"] != SCHEMA_VERSION_SUPPORTED:
        raise IncompatibleSchemaError(
            f"adapter pinned to {SCHEMA_VERSION_SUPPORTED}, "
            f"snapshot is {envelope['schema_version']}"
        )
    # ... consume normally; ignore unknown fields silently
```

### 3. Redaction respect

Adapters serving an audience MUST request the matching `redact_level`:

| Audience | redact_level | Notes |
|---|---|---|
| Unauth dashboards, CI status checks, observer roles | `public` | No quota agent breakdown, no supervisor PIDs/hosts, no body fields, no gate reasons. Safe for any third party. |
| Authenticated operator-side adapters (default) | `operator` | Full state minus secret-shape regex matches (SECRET_REGEXES in `sanitization_check.py`). |
| Local CLI debugging only | `full` | NEVER requested over MCP — the server caps `full` → `operator` silently per F003 acceptance #4. |

A team-dashboard adapter rendering for unauthenticated viewers MUST
NOT request `operator` and then hide fields client-side; that places
secrets on the wire. Request `public` server-side.

### 4. No write-back

Adapters MUST NOT write into DontPanic's local state directly
(`docs/plans/*/`, `~/.dontpanic/`, `~/.jarvis/`). Mutations go through
the MCP mutating tools (`dispatch`, `approve_gate`, `resume`) which
enforce the `confirm: true` invariant and route through the same
audit-writer / gate_pause primitives the orchestrator uses
in-process.

A Firebase-realtime team dashboard rendering a Kanban board MAY surface
a "drag to approve" gesture, but the gesture MUST call `approve_gate`
through MCP (or via a backend that calls MCP) — never `firestore.set()`
that fakes the state.

---

## Worked example — Firebase realtime team dashboard

A separate, sibling plan (`2026-05-09-004-feat-firebase-dashboard-adapter-v0`,
draft) implements a multi-operator team dashboard on top of the
projection. Skeleton:

```python
# scripts/firebase_dashboard_sync.py (lives in the adapter plan,
# not DontPanic core)

import time
from dontpanic_mcp_client import MCPClient

SCHEMA_VERSION = "1.0"

def sync_loop(mcp: MCPClient, firestore_client, *, interval_s: int = 5) -> None:
    last_cursor = None
    while True:
        # 1. Snapshot the whole world for the public surface.
        snap = mcp.call_tool("state_snapshot", {"redact_level": "public"})
        _pin_schema(snap)
        firestore_client.collection("dontpanic/state").document("snapshot").set(snap)

        # 2. Delta the inbox stream so kanban activity feels live.
        delta = mcp.call_tool("state_stream", {"since": last_cursor})
        last_cursor = delta["captured_at"]
        for event in delta["events"]:
            firestore_client.collection("dontpanic/events").add(event)

        time.sleep(interval_s)


def _pin_schema(envelope: dict) -> None:
    if envelope["schema_version"] != SCHEMA_VERSION:
        raise SystemExit(
            f"adapter pinned to {SCHEMA_VERSION}, snapshot is "
            f"{envelope['schema_version']}; bump the adapter"
        )
```

What this example DOES:
- Pulls public-redact state on a poll loop.
- Mirrors it into Firestore for browser clients.
- Pulls inbox deltas so live activity is visible.
- Pins the schema version explicitly.

What this example does NOT do:
- Write back into DontPanic. The Firestore document is one-way mirror.
- Request `operator` or `full` to a public-facing dashboard.
- Bake any internal file path or SHA into Firestore.

When an operator drags a card to "approve" in the browser, the click
handler calls a Cloud Function which (through MCP) invokes
`approve_gate` with `confirm: true`. The supervisor reacts to the
gate file change just as it does for a CLI `dontpanic approve` call.

---

## Cross-references

- USE_CASES.md — U6a (bundled static dashboard), U6b (Firebase realtime
  team dashboard), U8 (external orchestrator), U9 (CI reviewer) all
  consume the projection.
- ECOSYSTEM.md — "Concrete integration recipe" section is the broker
  pattern equivalent of this doc for OpenClaw-style relays.
- AGENT_QUICKSTART.md — caller-side surface description for
  hosted-runtime agents.
- CONFIGURATION.md — operator-facing config knobs that affect the
  projection (per-project plans_dir, quota_state_path, etc.).
- ROADMAP.md — Phase C external-SaaS adapter pattern (Printing Press)
  uses this contract as the substrate for read-only evidence
  adapters (Linear, Sentry, Slack, Notion).
- [../claude/skills/printing-press-adapter/SKILL.md](../claude/skills/printing-press-adapter/SKILL.md) —
  the lock-time advisory skill that prescribes CLI Printing Press for
  any plan declaring `surfaces: [external-api-wrap]`. The adapter
  template in that skill enforces this projection's redaction and
  sanitization invariants at the subprocess boundary; the decision
  tree filters out the four anti-cases (in-process, no contract,
  < 5 endpoints, mutating).
