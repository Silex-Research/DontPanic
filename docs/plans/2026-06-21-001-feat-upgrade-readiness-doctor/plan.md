---
id: 2026-06-21-001-feat-upgrade-readiness-doctor
title: Upgrade-readiness layer in `dontpanic doctor` (release manifest + probes + marker)
type: feat
tier: cross-cutting
status: active
date: "2026-06-21"
goal_type: new_feature
description: >
  Make a DontPanic instance update-aware. Today `dontpanic doctor` reports
  instance health (deps, registry, split-brain, plan schema, arch drift,
  dashboard cache) but is NOT a changelog-aware upgrade assistant: it cannot
  tell a user who just `git pull`-ed what changed, what operator actions are
  required vs advisory, which migrations (e.g. canonical-discovery backfill)
  were needed/completed, or which new CLI surfaces landed. This plan adds an
  update-readiness layer driven by a STRUCTURED release manifest
  (docs/upgrade/releases.json) — the manifest, not the prose CHANGELOG and not
  the plan ledger, is the machine contract for upgrade intent. Each release
  declares required/advisory operator actions with exact copyable commands and
  a named detection probe. A per-instance marker (~/.dontpanic/upgrade-state.json)
  records last-seen release/commit and dismissed advisories. The report is
  surfaced inside `dontpanic doctor` (concise WARN by default, full report under
  `--upgrade`, machine-readable under `--upgrade --json`) and as ActionItems for
  the operator console. v0 is DETECT + EXPLAIN + COPYABLE COMMANDS, NO MUTATION:
  it never runs a backfill/migration/config write itself.
motivation: >
  Users updating an instance currently get no coherent "what changed, what to
  run, what is advisory vs required" checklist. The recent Experience Readiness
  (2026-06-15-001/002, 2026-06-14-002) and canonical-discovery (2026-06-17-001)
  changes are enforced at plan close, not surfaced as an update path. A
  release-manifest-driven readiness layer lets future versions ship their
  operator actions as data, so doctor can guide upgrades deterministically.
agents_required:
  - claude
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 3
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-06-17-001-feat-canonical-repo-discovery
links:
  features: ./features.json
  objective_contract: ./objective_contract.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
  audits_dir: ./audit/
---

## Target

```yaml
target_env: dev
target_project: none
```

# Upgrade-readiness layer in `dontpanic doctor`

## Problem / Motivation

`dontpanic doctor` answers "is my instance healthy?" but not "am I getting the
benefit of the version I just pulled?". It does not:

- compare the installed instance against the release history,
- say "you updated across these releases — here are the operator actions",
- detect whether the canonical-discovery backfill was needed or completed,
- verify new CLI surfaces from a release are present,
- distinguish required actions from advisories with exact commands to run.

Version is effectively date-anchored (`__version__` is static `0.1.0`; the real
position of an instance is its git HEAD + the latest CHANGELOG dated section), so
"last known local version" must be a persisted per-instance marker that does not
exist today.

## Proposed Approach

1. **Release manifest as the machine contract** — `docs/upgrade/releases.json`,
   validated by a new `upgrade-releases.schema.json` + Pydantic model. Each
   release: stable `id`, `date`, `plan_refs[]`, human `summary`,
   `show_on_first_run` (first-run policy), and `actions[]`. Each action carries
   enough to tell the user WHY, WHETHER IT APPLIES, and WHAT SUCCESS LOOKS LIKE,
   not just a command: `kind` (required|advisory), `severity`, `title`,
   `detail` (the why), exact copyable `command`, `introduced_commands`,
   `applies_when` (applicability predicate), `status_probe` (satisfaction),
   `success_message`, `failure_message`, `human_next_step`, `docs_url`,
   `evidence_uri`. CHANGELOG stays prose and links to / mirrors summaries; the
   manifest owns the rest. (D001, D002, D013)

2. **Detection predicates** — a registry maps keys to callables returning
   `{satisfied, detail, evidence_uri}`, covering both `status_probe`
   (satisfaction) and `applies_when` (applicability). A required action's
   satisfied-ness comes ONLY from its `status_probe`, never from the marker
   (D004). `canonical_discovery_registered_active` reports DontPanic
   `registered_active` + backfill-evidence validity; `has_tracked_projects`
   gates the canonical action's applicability. status_probes fail-closed
   (unknown → pending); applies_when fail-open (unknown → show it).

3. **Per-instance marker + first-run policy** — `~/.dontpanic/upgrade-state.json`
   records `last_seen_release`, `last_seen_commit`, `dismissed_advisories[]`,
   `first_initialized_at`. Pure "releases since marker" diff. FIRST RUN
   bootstraps the marker to the latest release and shows only
   `show_on_first_run` advisories (no advisory flood as the manifest grows),
   while required actions stay probe-driven regardless of marker (D012).
   `--acknowledge` advances the marker and silences advisory noise ONLY; it
   never clears a probe-failing required action. (D003, D004)

4. **Surface inside doctor with a version/update summary** — plain `doctor`
   emits one concise WARN CheckResult with the pending counts and remediation
   command; `doctor --upgrade` renders the full report led by a version/update
   summary (installed_commit, latest_release_id, last_seen_release,
   pending_required, pending_advisory, update_state); `doctor --upgrade --json`
   emits that summary plus required[]/advisory[]/migration_status[]. (D005, D010)

5. **Dashboard update-status visibility** — beyond ActionItems, the dashboard
   gets a persistent version/update-readiness STATUS row (Tools & Setup / Health)
   from the same summary — "up to date" / "N upgrade actions pending" / "last
   acknowledged …" — present even in the up-to-date case. ActionItems are the
   drill-down (probe-failing required → `needs_action`, advisory → `advisory`),
   not the only signal. (D006, D011)

6. **End-to-end update journey** — a captured "after git pull" journey (fresh
   update → doctor WARN → full report → probe satisfied → action clears +
   update_state transition) is required evidence, proving the journey through the
   real CLI surface, not just unit passes. (D014)

## Scope (in)

- `upgrade-releases.schema.json` + Pydantic model + manifest loader, with the
  full per-action field set (kind, severity, applies_when, status_probe,
  success/failure copy, human_next_step, docs_url, introduced_commands) and
  release-level `show_on_first_run`.
- Seed `docs/upgrade/releases.json` with the Experience Readiness +
  canonical-discovery rollout entries exercising those fields.
- Predicate registry (status_probe + applies_when): canonical-discovery probe +
  `has_tracked_projects`.
- `~/.dontpanic/upgrade-state.json` marker read/write + releases-since-marker +
  first-run policy.
- `dontpanic doctor` integration: default WARN (with counts), `--upgrade` (with
  version/update summary), `--upgrade --json` (summary + lists), `--acknowledge`.
- Dashboard persistent update-status row + ActionItem drill-down provider.
- End-to-end "after git pull" journey test + captured evidence.
- Docs: manifest authoring guide + CHANGELOG/RELEASE_IMPACT linkage.

## Scope (out)

- No mutation: doctor never runs backfills/migrations/config writes (deferred,
  demand-gated; would need per-action safety tiers). (D007)
- No prose-grep of CHANGELOG; no derivation of upgrade actions from the plan
  ledger. (D002)
- No standalone `dontpanic upgrade` top-level command in v0 (would imply
  package management / mutation). (D005)
- No auto-version-bump / semver scheme change.

## Acceptance

- Manifest (with the full action field set) validates against schema; loader
  rejects malformed entries.
- `doctor --upgrade --json` emits `summary` (installed_commit, latest_release_id,
  last_seen_release, update_state, pending_required, pending_advisory) +
  required[]/advisory[]/migration_status[] with exact commands; required items
  reflect live status_probe results gated by applies_when.
- A required action with a failing probe stays pending across `--acknowledge`;
  an advisory is silenced by `--acknowledge`/dismissal.
- First run does not flood advisories (only `show_on_first_run`); required
  actions still surface via probes on a fresh marker.
- Dashboard shows a persistent update-status row (incl the up-to-date case);
  ActionItems are the drill-down.
- A captured end-to-end "after git pull" journey shows WARN → full report →
  action clears → update_state transition on the real CLI.
- Canonical-discovery probe reports DontPanic registered_active truthfully on a
  live run.

## Risks

- **Manifest/CHANGELOG drift** — mitigated by a lint asserting every operator-
  visible release has a manifest entry (advisory in v0). (D008)
- **Probe cost/latency** — probes that shell out (discover) must be bounded and
  degrade honestly when unavailable (fail-closed: unknown → still pending).
- **Marker portability** — marker lives under ~/.dontpanic (HOME-resolved like
  the rest of DontPanic state), never committed.
