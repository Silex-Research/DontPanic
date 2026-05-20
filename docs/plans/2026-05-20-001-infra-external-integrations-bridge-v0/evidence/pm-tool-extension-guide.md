# Adding a second PM tool to the DontPanic bridge

Plan 2026-05-20-001 F001 ships the PM-tool category contract with
Linear as the reference. This doc shows how to wire a second PM tool
(Jira, Aha, Monday, GitHub Projects, …) onto the same contract without
touching the abstract models, the mapping schema, or the sync hook
interface.

The category contract is the immovable surface:

- `scripts/dontpanic_orchestrate/integrations/pm_tool_models.py` —
  `PMIssue` / `PMProject` / `PMStatus` / `PMComment`. Service-agnostic
  by directive. If you find yourself wanting to add a field here for a
  service-specific concept (Linear cycle, Jira epic, Monday board),
  STOP — the category contract is leaking; file a v1 expansion plan
  instead.
- `pm_tool_mapping.py` — `PMToolMappingConfig`. The schema is fixed.
  Operators author per-service JSON against it; no code edits.
- `pm_tool_sync.py` — `read_issue` / `push_status` hook signatures +
  `ExternalSyncRecord` evidence shape. Implementing wrappers conform
  structurally (`runtime_checkable` Protocol); no inheritance
  required.

Adding a second PM tool is four pieces, in this order:

## 1. PP-generate the per-service MCP binary

Follow `claude/skills/printing-press-adapter/SKILL.md`. Pick a target
service that satisfies the four filters in `DECISION_TREE.md`:

- external API (not in-process),
- publishes OpenAPI or has stable HAR,
- wraps ≥5 endpoints,
- read-only in v0 (mutation gating is a v2 skill expansion).

For PM tools, the canonical fits are Linear, Jira, Aha, Monday,
GitHub Projects, ClickUp, Asana. All of these publish public
OpenAPI (or have stable enough REST surfaces to capture via HAR).

Run `/printing-press <service>` once. The emitted binary lands at
`~/.dontpanic/adapters/<service>/<service>-pp-mcp`. Pin the
PP version in the operator config (next step).

## 2. Author the per-service mapping JSON

Place it at `~/.dontpanic/adapters/<service>.json`. Schema:
`PMToolMappingConfig` in `pm_tool_mapping.py`. The Linear example
under `evidence/linear-mapping-example.json` is the reference; copy
it and edit the four sections:

```json
{
  "service_name": "<service>",
  "uri_scheme": "<service>",
  "field_name_map": {
    "PMIssue.id": "<vendor-dotted-path-to-id>",
    "PMIssue.project_id": "<vendor-dotted-path>",
    "PMIssue.title": "<vendor-dotted-path>",
    "PMIssue.status": "<vendor-dotted-path>",
    "PMIssue.uri": "<vendor-dotted-path>"
  },
  "status_enum_map": {
    "<vendor-status-label>": "backlog",
    "<vendor-status-label>": "active",
    "<vendor-status-label>": "in_progress",
    "<vendor-status-label>": "done",
    "<vendor-status-label>": "cancelled"
  },
  "push_status_tool": "<mcp-tool-name>",
  "read_issue_tool": "<mcp-tool-name>",
  "pp_version": "<pin-current-pp-version>",
  "api_key_env": "<env-var-name-holding-token>"
}
```

The validator enforces:

- Every `PMStatus` value (backlog / active / in_progress / done /
  cancelled) appears at least once in `status_enum_map.values()`.
  A partial mapping fails loud — a `push_status` outbound cannot
  silently coerce an unmapped status.
- No case-insensitive duplicate keys in `status_enum_map`. Linear's
  `In Progress` and `in progress` collapsing into one mapping entry
  is rejected at parse time so the operator notices the typo.
- Every required abstract-contract path
  (`REQUIRED_ISSUE_FIELD_PATHS`) appears in `field_name_map`.

Extra keys (`pp_version`, `api_key_env`, etc.) pass through silently —
the per-service JSON is multi-purpose and the mapping schema only
validates the mapping-specific fields.

Commit a redacted version of the JSON under your plan's `evidence/`
directory with the token-bearing fields replaced by
`<paste-your-token>` placeholders. The real config stays gitignored at
the operator's home.

## 3. Copy the Linear PP adapter to `<service>_pp_adapter.py`

`linear_pp_adapter.py` is the canonical implementation of the
`printing-press-adapter` skill's ADAPTER_TEMPLATE. It owns the trust
boundary: subprocess spawn + redact + sanitize. To add a new PM tool,
copy it to
`scripts/dontpanic_orchestrate/integrations/<service>_pp_adapter.py`
and edit only the constants block:

- `SERVICE_NAME` — service slug (also the URI scheme + registry key).
- `PP_BINARY_PATH` — usually `~/.dontpanic/adapters/<service>/<service>-pp-mcp`.
- `REDACT_LEVEL` — pick the strictest tier compatible with the
  operator's intended use (`public` / `internal` / `secret`).
- `MUTATING_TOOLS` — every tool name the vendor exposes that mutates
  the target. The generic `call_tool` proxy hard-rejects each; the
  explicit `push_status` codepath is plumbed for the bridge's
  status-flip mutation only.

The redact + sanitize boundary (`apply_redact`, `sanitize_response`,
`redact_and_sanitize`) is reusable as-is. Do not weaken
`SanitizationFailed` — it is the hard backstop on the response path.

## 4. Copy the Linear PM-tool wrapper to `<service>_pm_tool.py`

`linear_pm_tool.py` is the canonical ≤100-line wrapper that composes
the PP adapter with the mapping JSON to satisfy `PMToolSyncHook`.
Copy it to
`scripts/dontpanic_orchestrate/integrations/<service>_pm_tool.py` and
edit only:

- The class name (e.g. `class JiraPMTool` instead of `class LinearPMTool`).
- `service_name` and `uri_scheme` constants on the class.
- `DEFAULT_CONFIG_PATH` to point at
  `~/.dontpanic/adapters/<service>.json`.
- Constructor `pp_adapter` type-hint to `<Service>PPAdapter`.

The rest of the wrapper is reusable as-is because the mapping JSON
already encodes the vendor's tool names + field paths. The wrapper's
internals (`_issue_id_from_uri`, `_translate_issue`, `_resolve`) are
service-agnostic and operate against the mapping config.

If your new wrapper exceeds 100 lines, the category contract is
leaking — STOP and file a v1 expansion plan instead of stuffing
service logic into the wrapper.

## What you should NOT have to touch

- `pm_tool_models.py` — adding fields here means the category contract
  itself is expanding. Open a v1 plan.
- `pm_tool_mapping.py` — adding new mapping primitives here means the
  contract is expanding. Open a v1 plan.
- `pm_tool_sync.py` — adding new sync hooks here means the contract is
  expanding. Open a v1 plan.
- `linear_pm_tool.py` — never edit. It's the canonical reference; copy
  it for new services.

## Testing the new wrapper

Mirror `tests/test_pm_tool_contract_f001.py`:

- Round-trip the wrapper-emitted `PMIssue` through Pydantic to confirm
  the mapping translates vendor JSON correctly.
- Construct the PP adapter with a `subprocess_factory` that returns an
  in-memory `_FakeProc` (see the test file for the pattern) and assert
  `read_issue` returns a frozen `PMIssue`.
- Confirm `push_status(dry_run=True)` returns
  `ExternalSyncRecord(status=PENDING)` without the subprocess being
  touched.
- Assert the adapter's response carries `_redact_level` and
  `_sanitized_at` annotations — these prove the boundary middleware ran.

That's it. The acceptance bar for a new PM tool is: the mapping JSON
validates, the PP adapter copy compiles + passes the boundary tests,
the wrapper ≤100 lines, and the round-trip + dry-run tests pass.

## Reference

- Linear PP adapter (subprocess + redact + sanitize boundary):
  `scripts/dontpanic_orchestrate/integrations/linear_pp_adapter.py`
- Linear PM-tool wrapper:
  `scripts/dontpanic_orchestrate/integrations/linear_pm_tool.py`
- Linear mapping example:
  `docs/plans/2026-05-20-001-infra-external-integrations-bridge-v0/evidence/linear-mapping-example.json`
- Category contract tests:
  `scripts/dontpanic_orchestrate/tests/test_pm_tool_contract_f001.py`
- printing-press-adapter skill:
  `claude/skills/printing-press-adapter/SKILL.md`
