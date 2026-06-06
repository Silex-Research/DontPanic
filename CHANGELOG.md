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

## 2026-06-06 — README rewrite for clarity and reader-first voice

### Changed
- Full editing pass on `README.md`. It now opens with a plain-language framing
  (code review, CI, and an approval queue, for the case where the author is an
  AI) so a non-engineer lands softly, then keeps the mechanics specific for
  practitioners. The before/after became one real terminal transcript, formulaic
  phrasing and symbol-as-connector usage were cut, and the section rhythm was
  varied. No command, flag, path, or capability changed.

Surfaces affected: README

## 2026-06-05 — Applicable-conventions disposition gate (plan 2026-06-05-004)

### Added
- `dontpanic plan-review` emits an advisory **conventions-disposition** block when a
  plan declares one or more surfaces whose sufficiency pack has undisposed / invalid /
  applied-without-evidence items. The plan records dispositions in a per-plan
  `conventions.json` ledger (one of `applied` / `not-applicable` / `deferred` /
  `waived`, with a reason required for the last three). Advisory only — warn-only in
  v0, never blocks the verdict or exit code, and stays silent for plans that declare
  no surface or whose ledger is complete.
- A canonical surface vocabulary + alias map turns lint tags, QA surface classes, and
  skill `applies_to` values into one of a fixed set of canonical surfaces; the matched
  applicable skills feed the ledger's expected items (awareness → accountability).

Surfaces affected: plan-review (CLI)

## 2026-06-05 — Dashboard design system v0: shared component layer + Repair rebuilt (plan 2026-06-05-003)

### Added
- A shared dashboard component layer (`dashboard/components.css` + render helpers):
  token scales (spacing, type, semantic status colors, focus ring) and the approved
  primitives — Button, CopyCommand, Card, StatTile/StatStrip, SectionHeader, Banner,
  Skeleton — so pages compose primitives instead of hand-rolling markup.
- Shell accessibility: a `<main>` landmark, a skip-to-content link, and a global
  `:focus-visible` ring.

### Changed
- The **Repair** tab is rebuilt as the worked example: it now LISTS the per-item
  repair set grouped by safety class (auto-safe / human-required / blocked-external /
  info) instead of showing only aggregate counts, every action is a copy-command with
  an honest "Copy …" label and copied/failed feedback, and it distinguishes
  populated / empty / zero / corrupt states. Still read-only — it copies commands and
  never executes.
- Nav order is task-priority: Needs Attention · Repair · Work · Health · Architecture ·
  Tools & Setup · Preferences (Health moved ahead of Architecture).

### Removed
- The four orphan dashboard pages (command-center, financial, cloud-costs, security)
  and their stylesheets, which were not in the live nav yet still loaded and silently
  restyled the live pages via last-wins cascade. A guard now keeps `index.html` loading
  page CSS only for registered pages.

Surfaces affected: dashboard

## 2026-06-05 — QA sufficiency contract + advisory surface lint (plan 2026-06-05-002)

### Added
- `docs/qa-sufficiency-contract.md` — a QA sufficiency standard: a feature's test
  must ENTER THROUGH THE REAL SURFACE the user / agent / external system uses, and
  the proof must match the claim's surface. Enumerates 8 surface classes (read-only
  UI, interactive UI, mobile iOS/Android, CLI, agent/MCP tool, mutation, external
  integration, service/batch) with each one's required entering-surface proof, the
  governs-not-executes boundary (DontPanic verifies the NAMED proof; the project's
  own toolchain runs it — no iOS simulator / Android emulator / foreign browser in
  DontPanic's loop), and the explicit iOS/Android UI-journey rule.
- `plan-review` emits an advisory `surface_proof_missing` warning when a feature
  makes a surface-facing claim but names no entering-surface test/evidence. Advisory
  only — it never blocks in v0, and is quiet on features with no surface-facing claim
  or that already name a proof.

### Changed
- The dashboard test harness is the worked instance of the contract: nav/loader
  tests now import the real shell symbols (the exported `pageModules` +
  `createJarvis()`) instead of copied routers / re-declared page lists, and a
  real-state → real-shell journey test boots the dashboard from producer-generated
  state. Test-suite hardening only — no runtime behavior change to the dashboard.

Surfaces affected: plan-review (CLI), internal standards docs

## 2026-06-05 — Capability setup cards show resolving guidance + Global tools (plan 2026-06-05-001)

### Fixed
- Capability "Setup incomplete" cards in the dashboard and `what-now` now emit the
  resolving command `dontpanic capabilities setup <id> --print-steps` (labelled
  "Show setup steps") instead of the read-only `capabilities status <id>` diagnostic,
  which only reported state and never advanced setup. Card detail now lists the
  concrete setup steps (`setup_steps[].what`) instead of `missing:` jargon.
- Install-level capabilities ("Global tools") now appear in the All-Projects / fleet
  view. They were previously dropped from `fleet-what-now.json` (the fleet build only
  aggregated per-project caches, while install-level capabilities live in the
  DontPanic repo). They are now tagged `global_tool_setup` and rendered as a dedicated
  "Global tools" section — distinct from per-project "Tracked projects" — and deduped
  so a capability is never doubled into a project group. Health labels install
  readiness "Global tools".

Surfaces affected: dashboard, operator-console / what-now

## 2026-06-04 — Agent command surface + skill guidance (plan 2026-06-03-001)

### Added
- `dontpanic agent commands` — read-only command that prints DontPanic's command
  inventory as stable JSON (path, class, audience, examples, prerequisites) so an
  outer harness or interactive agent can discover what's automatable without
  scraping `--help`.
- `dontpanic agent guide` — a version-matched, offline "start here" operating
  guide for agent/harness environments that can't reach the live brief.
- Bare `dontpanic` / `dontpanic --help` now opens with a "Start here (for AI
  agents)" block pointing at `agent brief` / `agent commands` / `agent guide`,
  and the most-touched workflow help pages (lock, dispatch, approve, …) carry
  class-specific agent guidance (read-only vs mutating vs gated).
- `doctor` gains an advisory `skill-rubrics` probe: it flags high-value skills
  that lack an invocation rubric. Advisory only — it never blocks readiness or
  escalates the doctor exit code.

### Changed
- A regression gate now refuses to ship a new top-level command (or a newly
  automatable example) without a matching entry in the command-guidance
  inventory, so the agent surface can't silently drift from the real CLI.

Surfaces affected: CLI commands, CLI help, doctor, capability/skill manifests

## 2026-06-03 — Control-plane action spine + honest agent roles (plan 2026-06-02-001)

### Added
- `ActionItem` — DontPanic's single canonical control-plane action contract —
  gains five human-facing fields: `audience[]`, `dedupe_key`, `reversible`,
  `plain_consequence`, and `dashboard_url`. `dedupe_key` (not `id`) is now the
  dedup authority across surfaces.
- `dontpanic agent status` now reports three INDEPENDENT capability booleans —
  `can_operate` (drives DontPanic), `can_be_dispatched` (worker executor), and
  `can_orchestrate` (spawns sub-agents) — instead of conflating operator and
  worker. Detection/reporting only.

### Changed
- The dashboard, CLI/JSON (`what-now`), and the onboarding agent-brief managed
  block now all render from the same `ActionItem` contract, deduped by
  `dedupe_key`, with secret-shape scrubbing enforced at the render boundary.
  This closes a gap where `what-now --format json` previously emitted an
  unsanitized legacy payload.

Surfaces affected: CLI commands, CLI/JSON output, dashboard, agent-brief / AGENTS.md

## 2026-06-03 — Operator-finish close path + convergence-delta breaker (plan 2026-06-02-002)

### Added
- `dontpanic close` accepts honest terminal classes beyond
  `stopped_no_progress` — including the operator-finish close for work an
  auditor signed off but that never reached an automated `passes:true` — so a
  legitimately-done plan no longer has to be forced through the no-progress
  path.

### Changed
- The `no_progress` circuit breaker now treats a round whose auditor findings
  change materially from the prior round as **progress**, not stagnation —
  preventing premature stops while real iteration is still happening.
- The patch-completeness gate now surfaces a new IMPLEMENTATION module that a
  dispatch imports but never tracked in git (e.g. a freshly-added helper),
  catching "it works on my machine" gaps before close.

Surfaces affected: CLI commands, supervisor close/convergence behavior

## 2026-06-03 — Plan-review scope governance + config-readiness (plan 2026-06-01-001)

### Added
- `dontpanic plan-review <plan>` — a free, deterministic scope lint over every
  feature: flags over-scoped features (too many surfaces / acceptance criteria),
  exemplar-or-weak acceptance criteria, and undeclared command/flag/symbol
  prerequisites. Read-only; `--format text|json`; exits non-zero only on a
  block-severity flag.
- `dontpanic plan-review <plan> --since <git-ref|path>` — the mid-development
  scope-delta lint: classifies each changed feature as **sharpen / expand /
  split** against a prior `features.json` snapshot and exits non-zero when the
  scope-change protocol refuses a change (a budget-busting expand of a locked
  feature, or a lossy split).
- `dontpanic plan lock --design-review` — opt-in cross-model design-review
  volley that red-teams a plan's decomposition (oversize / hidden coupling /
  underspecified AC / missing prereq / dependency order). Advisory: it prints a
  verdict and never blocks the lock. Also auto-suggested when the lint is
  uncertain.
- `dontpanic dispatch-from-plan --acknowledge-cross-feature <reason>` — records a
  rationale to pass the new cross-feature-edit check when a shared-file edit is
  intentional.

### Changed
- **Plan lock** now runs a pre-lock scope gate: a feature carrying a
  block-severity scope flag refuses the `draft → active` transition unless
  `--allow-oversize <reason>` records a rationale in `decisions.jsonl`.
- **Patch-completeness** (signoff time) now flags a `cross_feature_edit` when a
  dispatch's diff touches files owned by a *different* feature than the one being
  implemented, naming the foreign feature and paths.
- **Config readiness** is now an actionable pre-flight: a malformed/empty
  `quota_caps.json` or an invalid role value surfaces a clean failure with a
  runnable remediation command (and dashboard pointer) before any paid work —
  at dispatch *and* at the plan-close goal-completion audit — instead of a raw
  schema crash mid-run.
- README: the "Circuit breakers" line and the shipped-checklist now read **8**
  breakers (adds `environmental_blocker`, which was already in the engine); a
  new "Scope governance" capability row and a same-family-multi-agent
  (Dynamic Workflows / Managed Agents) vs. cross-vendor meta-harness contrast
  were added.

Surfaces affected: CLI commands/flags (`plan-review`, `plan lock`,
`dispatch-from-plan`), supervisor patch-completeness, plan-lock gate, README.

## 2026-06-02 — Dashboard serve singleton guard + status helper (plan 2026-05-30-001 F010)

### Added
- `dontpanic dashboard serve --replace` (alias `--force-single`): intentionally
  stop a live dashboard serving the same DontPanic home and take over. Use it to
  recover when a previous server is stuck. It waits for the old process to exit
  (escalating to SIGKILL if it ignores the graceful stop) before binding, so
  replacing a server on the same port no longer races the port release.
- A dashboard status helper that one-answers "is a dashboard running, and at what
  URL?" — returning the active URL plus recorded project/scope when live, or the
  exact `dontpanic dashboard serve` command when not. `dontpanic config
  inventory` and `dontpanic what-now` now route their dashboard discovery through
  this single helper, so the two surfaces never disagree.

### Changed
- Starting a second `dontpanic dashboard serve` for the same home is now refused
  with an actionable message naming the already-running URL (open it, or pass
  `--replace`), instead of silently stacking another local server. The guard is
  per-home, so an ordinary same-port conflict in a different home still surfaces
  as a normal bind error.
- A crashed serve leaves a stale singleton record; the next `serve` prunes the
  dead-pid record automatically and is admitted, so `--replace` is only needed
  when the old server is genuinely still alive. `--once` and Ctrl-C shutdown both
  clear the record.
- README "Onboard An Agent And A Repo" / "Dispatch Real Work" and
  `docs/GETTING_STARTED.md` now document the complete new-agent / new-repo
  onboarding flow (`agent brief`, `projects add --onboard`, role assignment,
  `config inventory`, `doctor --agent|--project`, `skills recommend`, `what-now`,
  `orchestrate`) and the operator-vs-worker distinction plus the dashboard
  decision flow. The README quickstart's `projects add` example now uses
  `--onboard` (was the stale `--init-config`).

Surfaces affected: ux, infra, readme

## 2026-05-30 — Operations guidance + no-paid finalizer (plan 2026-05-30-001 F007)

### Added
- `dontpanic what-now <plan> [--feature F] [--format text|json] [--dashboard-url URL]`:
  read-only operations guidance that turns a blocked unit of work into a short
  typed decision set — recommended action plus alternatives, an exact command
  where one is safe and validated, a rationale, a risk band, and whether a human
  must confirm. Covers quota cooldown (wait-until + redispatch + raise-ceiling
  alternative), budget ceiling, admission threshold, max_iterations
  remaining/exhausted, a signed_off feature paused at `pre_merge` (offers the
  no-paid finalize once `pre_merge` is cleared), no-progress stops, and setup
  friction (register/onboard, refresh brief, reconcile homes, unsupported worker
  role, human-required config).
- One response-level dashboard affordance per `what-now` output: the active URL
  when a dashboard is running, otherwise the `dontpanic dashboard serve` start
  command — shown once, referenced (not repeated) by individual choices.
- The same typed `ActionChoice` data backs both the CLI text and the dashboard
  ActionItems, so budget/iteration guidance never drifts between the two.

Surfaces affected: ux, infra

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
## 2026-05-24 — Dashboard Architecture Explorer v1 (plan 2026-05-24-002)

### Added
- Local dashboard now ships a first-class **Architecture** tab — an
  interactive swimlane flow map sourced from
  `docs/architecture/architecture.json`. The tab renders modules, plans,
  capabilities, dashboard pages, CLI commands, and authored / derived
  flows on a deterministic SVG canvas with a right-side flow rail,
  numbered step inspector, persistent legend, search + at-least-three
  filters, hover labels, click-to-detail provenance panel, and zoom/pan.
- `dontpanic dashboard build` writes a stable, agent-readable
  architecture view-state cache per project at
  `dashboard/state/projects/<project>/architecture-view-state.json` plus
  an All Projects fleet variant. The shape (lanes, nodes, edges, flows,
  steps, filters, insights, validation_warnings) is the canonical
  agent-facing contract — no DOM scraping required.
- Authored flow input: optional `docs/architecture/flows.json` whose
  steps reference architecture-graph node IDs. Missing references render
  as visible validation warnings on the tab rather than silent
  omissions.
- Honest stale / missing / absent / per-project-missing freshness
  states. Each renders an explicit empty card with plain-language
  explanation, source path, last `generated_at`, and the exact
  `dontpanic architecture regen --with-html` command — copyable by the
  operator. The dashboard never auto-regenerates the architecture
  artifact.
- All Projects mode renders a project-card grid with per-project
  freshness badges and "open map" affordances; DontPanic does not merge
  unrelated repo graphs into one architecture map.

### Changed
- Dashboard nav promotes Architecture from the V0 "future surfaces" row
  to a first-class tab; `dashboard/README.md` documents the tab's usage,
  command-emitter / no-auto-regen boundary, project/fleet behavior, and
  test/evidence map.

Surfaces affected: dashboard (new Architecture tab + nav), CLI help
(`dontpanic dashboard build` writes architecture view-state cache),
public dashboard documentation (`dashboard/README.md`).

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
