# Capability Manifests

DontPanic capabilities are optional or external integrations that need a
clear setup and ownership boundary. A capability may be an agent CLI, a
notification sink, a dashboard adapter, a PM-tool adapter, or another
external service integration.

The manifest convention answers two questions for humans and agents:

1. Is this capability part of DontPanic core, an adapter, or operator
   configuration?
2. What must be installed, configured, and verified before the
   capability can be used?

This directory is not a plugin marketplace and does not imply automatic
installation. It is the source-of-truth metadata that existing surfaces
can consume: doctor profiles, init flows, adapter registration, plan
`external_refs[]`, and documentation.

## Schema

Manifest schema version: `1.0.0`

Required fields:

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | string | Manifest schema version. Initial value: `1.0.0`. |
| `id` | string | Stable capability ID. Must match the filename stem. |
| `title` | string | Human-readable capability name. |
| `kind` | string | Broad runtime shape: `agent_cli`, `notification_sink`, `external_adapter`, `service_adapter`. |
| `category` | string | Category port, such as `agent-cli`, `notification-sink`, `dashboard-realtime`, `pm-tool`. |
| `summary` | string | One-sentence purpose. |
| `setup_required` | boolean | Whether an operator must configure anything before use. |
| `setup_doc` | string | Repo-relative documentation path. |
| `default_in_profiles` | array[string] | Doctor/init profiles that include this capability by default. Usually empty for optional adapters. |
| `use_cases` | array[string] | USE_CASES.md IDs that use this capability. |
| `requires` | object | External commands, env vars, services, files, auth, or config. |
| `verify` | object | Doctor/profile/probe metadata for readiness checks. |
| `owner_boundary` | object | What DontPanic core, the adapter, and the operator own. |
| `mutation_boundary` | object | Whether and how the capability may mutate external or DontPanic state. |
| `notes` | array[string] | Extra implementation or boundary notes. |

## Ownership Boundary

`owner_boundary` has three buckets:

- `dontpanic_core`: contracts, commands, schemas, MCP tools, projections,
  and guardrails that ship in DontPanic.
- `adapter`: service-specific runtime, mapping, sync, webhook, or
  generated wrapper behavior.
- `operator`: credentials, accounts, cloud projects, external service
  configuration, deploy choices, and local secrets.

If a future capability cannot be cleanly split across these buckets,
the architecture should be reviewed before implementation.

## Mutation Boundary

External capabilities must not write directly into DontPanic local state.
Allowed mutation paths are:

- DontPanic MCP mutating tools with explicit confirmation.
- DontPanic CLI commands that already enforce gates and evidence.
- Adapter commands that write durable evidence records and respect the
  adapter governance contract.

Read-only mirrors, dashboards, and notifications may consume state
projection output, but DontPanic remains the source of truth.

## Adding a Capability

1. Add `capabilities/<id>.json`.
2. Set `schema_version` to `1.0.0`.
3. Declare setup requirements and profile defaults honestly.
4. Fill `owner_boundary` before implementing code.
5. Reference the manifest ID from doctor/init/adapters/plan docs rather
   than duplicating setup facts in multiple places.

Do not add a new CLI or registry service just to add a manifest. The
manifest convention is the v0 contract.

## `kind` Values

Use these values consistently:

| Kind | Use When |
|---|---|
| `agent_cli` | The capability is an operator-installed agent runtime that DontPanic invokes through a governed executor, such as Claude or Codex. |
| `notification_sink` | The capability pushes DontPanic events to an external notification target and does not accept state-changing commands. |
| `service_adapter` | The capability wraps an external API or CLI without operator-deployed infrastructure. Linear through a Printing Press adapter is the reference example. |
| `external_adapter` | The capability includes operator-deployed infrastructure such as Cloud Functions, Firestore rules, hosting config, or a long-running sync process. Firebase realtime dashboard is the reference example. |

## Validation

Manifests are schema-validatable against:

```bash
python3 - <<'PY'
import json
from pathlib import Path
from jsonschema import Draft202012Validator

schema = json.loads(Path("claude/shared/schemas/v1.0/capability.schema.json").read_text())
validator = Draft202012Validator(schema)
for path in sorted(Path("capabilities").glob("*.json")):
    data = json.loads(path.read_text())
    validator.validate(data)
    assert data["id"] == path.stem, f"{path}: id must match filename stem"
print("capability manifests validate")
PY
```

The v0 schema checks manifest shape. It does not yet validate every
cross-reference. Follow-on consumer work should add checks for:

- `verify.probes[]` names against the doctor/prereq registry. Some v0
  manifests intentionally forward-declare probes that consumer-backfill
  work will add.
- `use_cases[]` IDs against `docs/USE_CASES.md`.
- `setup_doc` anchors, not only target files.

## Agent CLI Instances

`agent-claude-cli.json` is the first concrete `agent_cli` manifest
because Claude is the current default in many local flows. It is not the
only valid agent runtime. Core onboarding should eventually express
"at least one configured `agent_cli` capability" rather than requiring a
specific provider. Codex, Gemini, Grok, and Ollama manifests should
follow this shape as their setup contracts are normalized.
