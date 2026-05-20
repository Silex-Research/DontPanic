# doctor `--profile=<name> --json` envelope — schema v1

Plan: `2026-05-19-002-feat-install-ux-hardening-v0`
Feature: F001
Schema version: `1.0.0`
Status: **local** schema doc. Formal promotion into
`claude/shared/schemas/` is deferred per D003 (out of v0 scope).

This document is the source of truth for the JSON envelope emitted by

```
python3 scripts/dontpanic_doctor.py --profile=<name> --json
```

when `<name>` is one of the five pure-set profiles (`core`, `discord`,
`firebase-dashboard`, `openclaw`, `ci`). The legacy no-flag JSON output
of `dontpanic doctor --json` is **unrelated** to this schema and keeps
its existing shape (backwards-compat invariant — F001 acceptance #5).

## Top-level fields

| field             | type     | required | description |
|-------------------|----------|----------|-------------|
| `schema_version`  | `string` | yes      | Pinned `"1.0.0"`. Consumers must reject any other value. Bumped only via plan + decisions log. |
| `profile`         | `string` | yes      | The profile selected on the CLI. One of `core` / `discord` / `firebase-dashboard` / `openclaw` / `ci`. |
| `generated_at`    | `string` | yes      | ISO-8601 UTC timestamp `YYYY-MM-DDTHH:MM:SSZ`. Generated at sweep start. |
| `exit_code`       | `int`    | yes      | Strict 0/1/2 matrix applied to the **probe sweep only**. `0` = all probes PASS *or* only ADVISORY (advisory-only sweeps are not a failure surface). `1` = at least one WARN. `2` = at least one FAIL. The supervisor process exit code echoes this value. Note: ADVISORY is informational (per-probe `activation_condition` did not resolve true) and never escalates exit code — see `SweepResult.exit_code()` in `prereq_registry.py`. |
| `prereq_probes`   | `array`  | yes      | Ordered array of probe items (alphabetical by `name`). Empty array when no probes match the selected profile. See "Probe item fields" below. |
| `legacy_checks`   | `array`  | yes      | Snapshot of the legacy `CheckResult` pipeline output (`{name, ok, warn, message}` shape) for diagnostic continuity. Does NOT influence `exit_code`. May be `[]` when the legacy pipeline was skipped. |

Stability contract: the set of top-level keys is fixed at v1.0.0.
Adding a new key requires bumping `schema_version` (and a corresponding
decision in `decisions.jsonl`). Removing or renaming a key is a major
bump.

## Probe item fields (`prereq_probes[i]`)

Field order is pinned for JSON snapshot tests
(`test_envelope_probe_item_field_order_is_pinned`).

| field                    | type             | required | description |
|--------------------------|------------------|----------|-------------|
| `name`                   | `string`         | yes      | Stable probe identifier (e.g. `"python-version"`, `"gh-auth-status"`, `"codex-cli"`). Lower-kebab-case. |
| `status`                 | `string`         | yes      | One of `"pass"`, `"warn"`, `"advisory"`, `"fail"`, `"omit"`. Omitted probes are dropped from the rendered array — the `"omit"` value appears only in intermediate ProbeResult records, never in serialized output. |
| `severity_reason`        | `string`         | yes      | Human-readable explanation of why the probe landed at this status (in-profile + check failed, out-of-profile + advisory escalated to FAIL, promoted WARN→FAIL by --profile-strict, etc.). |
| `version_found`          | `string \| null` | yes      | First line of the probe's stdout (callable probes return this from their second tuple element when ok=True). `null` when the probe failed or did not surface a version. |
| `fix_url`                | `string`         | yes      | Vendor documentation URL for remediation. Empty string is allowed but discouraged. |
| `fix_command`            | `array<string>`  | yes      | argv-style remediation command. Strict-argv invariant — NEVER a shell string. Example: `["brew", "install", "jq"]`. Validated at registry-build time (PrereqProbe `__post_init__`). |
| `required_for_profiles`  | `array<string>`  | yes      | Sorted list of profiles for which this probe is required (in-profile). E.g. `["ci", "openclaw"]` for `codex-cli`. Empty list is invalid. |
| `activation_condition`   | `string`         | yes      | Predicate name evaluated against the ActivationContext: one of `"always"`, `"github_remote_present"`, `"auditor_codex_selected"`, `"dispatch_requires_push"`, `"firebase_target_set"`. |
| `activation_resolved`    | `bool`           | yes      | Resolved value of `activation_condition` for this sweep. Used to interpret why a WARN/ADVISORY surfaced. |
| `elapsed_s`              | `float`          | yes      | Wall-clock seconds spent running this probe (rounded to 4 decimal places). Always `<= probe.timeout_s` for the per-probe cap, or `<= wall_clock_budget_s` for the sweep cap. |

## Status semantics matrix

| in-profile? | raw probe OK? | `severity_when_inactive` | `activation_resolved` | effective `status` |
|-------------|---------------|--------------------------|-----------------------|--------------------|
| yes         | true          | (any)                    | (any)                 | `pass`             |
| yes         | false         | (any)                    | (any)                 | `fail`             |
| no          | true          | `omit`                   | (any)                 | `omit` (dropped)   |
| no          | true          | `warn` / `advisory`      | (any)                 | `pass`             |
| no          | false         | `omit`                   | (any)                 | `omit` (dropped)   |
| no          | false         | `warn`                   | true                  | `warn`             |
| no          | false         | `warn`                   | false                 | `omit` (dropped)   |
| no          | false         | `advisory`               | true                  | `fail` (escalated) |
| no          | false         | `advisory`               | false                 | `advisory`         |

When `--profile-strict` is set, any `warn` is promoted to `fail` at the
final stage of the matrix above.

## Cross-profile inactive surfacing scope

Out-of-profile probes with `severity_when_inactive != omit` surface
only under `--profile=core`. Specialized profiles
(`discord`, `firebase-dashboard`, `openclaw`, `ci`) emit ONLY their
in-profile probe set. This avoids unrelated noise — e.g. running
`--profile=discord` no longer surfaces a WARN about a missing gh-auth
login, because gh-auth has nothing to do with Discord webhooks.

The contract is enforced by the `selected` filter inside
`prereq_registry.run_sweep` and exercised by
`test_specialized_profile_does_not_emit_codex_or_gh_auth` in
`test_doctor_profile_integration.py`.

## Example envelope

```json
{
  "schema_version": "1.0.0",
  "profile": "core",
  "generated_at": "2026-05-20T00:00:00Z",
  "exit_code": 1,
  "prereq_probes": [
    {
      "name": "anthropic-api-network",
      "status": "pass",
      "severity_reason": "in-profile + ok",
      "version_found": "api.anthropic.com reachable (HTTP 401)",
      "fix_url": "https://status.anthropic.com/",
      "fix_command": ["echo", "Check https://status.anthropic.com/ and your network egress."],
      "required_for_profiles": ["ci", "core", "discord", "firebase-dashboard", "openclaw"],
      "activation_condition": "always",
      "activation_resolved": true,
      "elapsed_s": 0.4123
    },
    {
      "name": "codex-cli",
      "status": "advisory",
      "severity_reason": "out-of-profile + advisory-by-default: codex not found on PATH",
      "version_found": null,
      "fix_url": "https://github.com/openai/codex",
      "fix_command": ["echo", "Install codex CLI from https://github.com/openai/codex"],
      "required_for_profiles": ["ci", "openclaw"],
      "activation_condition": "auditor_codex_selected",
      "activation_resolved": false,
      "elapsed_s": 0.0012
    },
    {
      "name": "gh-auth-status",
      "status": "warn",
      "severity_reason": "out-of-profile + warn-when-active + activation resolved: not authenticated",
      "version_found": null,
      "fix_url": "https://cli.github.com/manual/gh_auth_login",
      "fix_command": ["gh", "auth", "login"],
      "required_for_profiles": ["ci"],
      "activation_condition": "github_remote_present",
      "activation_resolved": true,
      "elapsed_s": 0.0871
    }
  ],
  "legacy_checks": [
    {"name": "python>=3.10", "ok": true, "warn": false, "message": "Python 3.12"}
  ]
}
```

## Versioning policy

- Patch bump (`1.0.x`) — clarifications, doc-only.
- Minor bump (`1.x.0`) — additive top-level or item field.
- Major bump (`x.0.0`) — removed/renamed field or changed semantics.

Each bump must:
1. Update the `SCHEMA_VERSION` constant in
   `scripts/dontpanic_orchestrate/prereq_registry.py`.
2. Append a decision row to this plan's `decisions.jsonl`.
3. Update this document.

Formal promotion of this schema into `claude/shared/schemas/` (with a
JSON-Schema artifact validated in CI) is tracked under Roadmap Plan 5/7
and is intentionally out of v0 scope.
