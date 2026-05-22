# Capability status JSON envelope (schema 1.0.0)

Plan: `2026-05-22-002-feat-capability-status-v0` F002.

`dontpanic capabilities status --format=json` (and the
`~/.dontpanic/capabilities-status.json` cache it writes) emits the
envelope documented here. The shape is pinned by a snapshot test in
`scripts/dontpanic_orchestrate/tests/test_capabilities_status_cli_f002.py`.

## Top-level envelope

```json
{
  "schema_version": "1.0.0",
  "generated_at": "2026-05-22T17:21:30Z",
  "advisory_notes": ["..."],
  "capabilities": [ { ... } ]
}
```

| Field            | Type            | Notes                                              |
|------------------|-----------------|----------------------------------------------------|
| `schema_version` | string          | Pinned constant for this envelope shape.            |
| `generated_at`   | string (ISO8601)| UTC timestamp at status-run start.                  |
| `advisory_notes` | array<string>   | Run-scoped advisories (e.g. probe binding gap).     |
| `capabilities`   | array<object>   | One entry per manifest under `capabilities/`.       |

## Per-capability object

```json
{
  "capability_id": "firebase-dashboard",
  "status": "needs_setup",
  "owner_boundary": {
    "dontpanic_core": ["..."],
    "adapter": ["..."],
    "operator": ["..."]
  },
  "configured": ["firebase", "gcloud", "environments.json"],
  "missing": ["DONTPANIC_FIREBASE_PROJECT", "..."],
  "automatable": [ { "id": "...", "what": "...", "command_template": "..." } ],
  "human_required": [
    {
      "id": "...",
      "what": "...",
      "command_template": "...",
      "human_required_reason": "..."
    }
  ],
  "pending_probes": [ { "name": "...", "reason": "..." } ],
  "next_actions": [
    {
      "id": "...",
      "what": "...",
      "automatable": true,
      "command_template": "...",
      "verify_probe": "...",
      "human_required_reason": null
    }
  ],
  "advisory_notes": []
}
```

### Fields

| Field            | Type             | Notes                                                                   |
|------------------|------------------|-------------------------------------------------------------------------|
| `capability_id`  | string           | Matches the manifest `id` (and filename stem).                          |
| `status`         | string enum      | One of `ready`, `needs_setup`, `blocked`, `not_installed`, `optional`. `pending` is NEVER a capability status. |
| `owner_boundary` | object           | Carries the manifest's three owner buckets verbatim.                    |
| `configured`     | array<string>    | Tokens from `requires.{commands,env,files}` resolved locally.           |
| `missing`        | array<string>    | Unresolved + informational tokens (`requires.{services,auth,config}`).  |
| `automatable`    | array<object>    | Subset of `setup_steps[]` with `automatable=true`.                      |
| `human_required` | array<object>    | Subset of `setup_steps[]` with `automatable=false`. Each carries `human_required_reason`. |
| `pending_probes` | array<object>    | Bound probes whose `ProbeStatus` is `pending`. Informational only.      |
| `next_actions`   | array<object>    | Full `setup_steps[]` payload preserved for agent handoff.               |
| `advisory_notes` | array<string>    | Per-capability advisories surfaced by the status run.                   |

## Status enum semantics

| `status`         | Meaning                                                                                   |
|------------------|-------------------------------------------------------------------------------------------|
| `ready`          | All non-PENDING probes pass AND every `requires.{commands,env,files}` token resolves.     |
| `needs_setup`    | Either a non-PENDING probe WARNed OR at least one require did not resolve.                |
| `blocked`        | At least one non-PENDING probe FAILed.                                                    |
| `not_installed`  | Service-adapter kind whose adapter config is absent under `~/.dontpanic/adapters/`.       |
| `optional`       | Capability is outside the requested `--profile=<name>` filter.                            |

## PENDING probe handling

`ProbeStatus.PENDING` is a probe-state only — it never propagates to
capability status. A capability whose only bound probes are PENDING and
whose `requires` resolve computes as `ready`. The PENDING set surfaces
through `pending_probes[]` (JSON) and as `probe pending: <name> — <reason>`
chips in the text renderer so the operator sees the probe-implementation
gap without it being treated as a blocker.

## Cache

`~/.dontpanic/capabilities-status.json` is written byte-identical to
the `--format=json` output after every status run unless
`--no-cache-write` is set. File mode is `0600` (operator-only).
