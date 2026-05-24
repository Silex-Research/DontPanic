# DontPanic Changelog

Public, product-facing changelog for DontPanic.

This file records changes that an operator or external user would notice: new
or renamed CLI commands and flags, dashboard / operator-console behavior,
README and onboarding flow shifts, capability manifests, public schemas,
public metadata (repo description, social preview, discoverability assets),
and other surfaces a fresh DontPanic user can see without reading source.

## Relationship to `claude/shared/CHANGELOG.md`

`claude/shared/CHANGELOG.md` is the **agent-conventions subtree** changelog. It
tracks `claude/shared/**` — the schemas, conventions, and Pydantic mirrors
that DontPanic shares with its `agent-conventions` upstream. Entries there
describe what a plan-authoring agent or schema-aware tool would notice.

This root file is the **DontPanic product** changelog. It tracks the
DontPanic CLI, supervisor, dashboard, README, onboarding flow, capability
manifests, and any other surface a DontPanic operator or external user touches
directly.

Some changes belong in both files: an agent-conventions schema bump that the
DontPanic CLI immediately starts enforcing produces a `claude/shared/CHANGELOG.md`
entry for the schema delta AND a root entry for the operator-visible CLI
behavior change. Most changes belong in exactly one: a pure schema/Pydantic
edit goes only to `claude/shared/CHANGELOG.md`; a CLI flag rename or dashboard
relabel goes only here. Internal supervisor refactors, test fixtures, evidence
files, and plan-ledger updates usually belong in neither.

See `docs/RELEASE_IMPACT.md` for the full path/surface pattern table that
determines which changelog (if any) a change requires.

## Format

Entries are reverse-chronological. Each entry is a single release or
behavioral surface change with the date, a short summary, and a
`Surfaces affected:` line listing the operator-visible surfaces it touched.

```
## YYYY-MM-DD — short title

### Added | Changed | Removed | Fixed
- bullet describing the change

Surfaces affected: <comma-separated list — see docs/RELEASE_IMPACT.md>
```

## 2026-05-24 — Event messaging v1 (plan 2026-05-24-004)

Layered, value-first notifications across every operator-visible sink. The
supervisor still emits the same INBOX entries (truth-of-record unchanged),
but live notifications now render through a per-event translation table
that produces a headline / why-it-matters / action / technical-details
block consistently across Discord, terminal-notifier, INBOX rendered
annotation, and a new dashboard sidecar.

### Changed
- **Discord** posts upgrade from a single content-string to a rich embed
  with a value-first title, a description, a copyable `Run:` field
  carrying the exact CLI command, a footer linking to the evidence URI,
  and a color drawn from the IA value-language 4-band taxonomy
  (`needs_action` red, `advisory` amber, `info` slate, `ready` green).
  The 2000-character payload limit is enforced by trimming description /
  footer first; `exact_command` is never truncated.
- **Terminal-notifier** banner title rebrands from `Jarvis [{plan_id}]`
  to `DontPanic [{plan_id}]`. Banner body is now the rendered headline
  (the same one-sentence value-first label every other sink uses) rather
  than the first 140 chars of the supervisor body string.
- **INBOX.md** gains an additive rendered-annotation block after every
  live or dashboard-action event — the raw header / body entry that
  `append_event()` writes is unchanged, but a follow-up block surfaces the
  same headline / why / action / technical-details a Discord embed
  carries, complete with `<details>Technical details</details>` fold.
  Operators reading INBOX.md in any editor see the layered view inline.

### Added
- **Dashboard event-actions sidecar.** Notification flow now writes one
  `ActionItem`-shaped JSON line per rendered event to
  `~/.dontpanic/dashboard/event-actions.jsonl`. The dashboard build and
  the operator-local cache writer (`operator_console.write_cache()`) both
  merge this sidecar into `what-now.json` alongside provider-derived
  items, so `dontpanic dashboard` surfaces event-driven action items
  (e.g. `gate_hit`, `breaker_tripped`, `verdict_mismatch`) alongside the
  existing gate / capability / reconcile rows.
- **Six new event surfaces.** Currently-silent INBOX events now also
  dispatch live notifications: `verdict_mismatch`,
  `no_progress_classification`, `environmental_blocker_short_circuit`,
  `verdict_blocked_reconciled`, `gate_state_reconciliation_failed`,
  `architecture_regen_failed`.
- **Brand-drift translation at the render boundary.** Legacy
  `jarvis approve …` / `jarvis-orchestrate approve …` / `Jarvis [...]`
  strings emitted by source bodies are rewritten to the `dontpanic`
  equivalents in every rendered surface. Source body strings are not
  edited — translation is pure at render time.
- **Render-boundary sanitization.** Sidecar writes raise on any
  secret-shape match (operator-fixable before persistence). Live
  notification paths (Discord, terminal, INBOX annotation) substitute
  matches with `[REDACTED]` instead of raising, so the supervisor cannot
  fail-hard on a transient ping with secret-shaped content.
- [`docs/event-messaging-authoring-guide.md`](docs/event-messaging-authoring-guide.md)
  — how to add a new event kind, set a disposition, reference the IA
  copy map, validate an exact-command via the token-only harness, and
  regenerate the cross-channel snapshot fixtures.

### Honest-commands rule
Events without a canonical CLI remediation (`verdict_mismatch`,
`gate_state_reconciliation_failed`, generic `error`) render with no
`exact_command` and an explanation-only `why` paragraph rather than a
fake command. The renderer validates every non-null command through the
token-only validator before placing it on the wire.

Surfaces affected: Discord webhook payload (single-content → rich embed,
new color taxonomy, new field layout); terminal-notifier banner title
rebrand; INBOX.md format (additive rendered block, raw entry unchanged);
dashboard `what-now.json` (new event-derived ActionItem source); operator
home `~/.dontpanic/dashboard/event-actions.jsonl` (new file).

## 2026-05-23 — Planning intelligence v0 (plan 2026-05-23-007)

### Added
- `dontpanic next` (already shipped in plan 2026-05-23-007 F002): read-only
  parallel-readiness recommender. Repo and fleet scope, JSON and text output.
- Release-impact advisory surfaced inside `dontpanic next` output: maps
  draft-time plan intent (`surfaces`, `allowed_paths`, feature step path
  tokens) to suggested docs/release update surfaces. Lock-time advice uses
  git diff when available. Advisory only — does not block dispatch or lock.
- `docs/RELEASE_IMPACT.md`: path/surface pattern table and full release-impact
  checklist covering README, onboarding/getting-started, architecture map,
  dashboard, capability manifests, CLI help, schemas, and public metadata /
  social preview.
- Root `CHANGELOG.md` (this file) plus a documented relationship to
  `claude/shared/CHANGELOG.md`.
- `docs/AUTHORING_PLANS.md`: now links to `docs/RELEASE_IMPACT.md` from the
  release-impact prompt and from the roadmap-vs-plan guidance.

### Changed
- README "What You Get" and dispatch workflow now mention `dontpanic next` and
  release-impact advisory behavior so the public docs reflect the planning
  intelligence surface.

Surfaces affected: CLI help (`dontpanic next` output), README, authoring docs,
release-impact docs, root changelog convention.
