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
