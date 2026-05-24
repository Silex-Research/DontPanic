---
id: 2026-05-24-004-feat-event-messaging-v1
title: Event messaging v1 — layered notifications across Discord, INBOX, terminal, and dashboard
description: |
  Executable child of the Dashboard Platform Roadmap v1. Introduces value-first,
  layered messaging across Discord, INBOX, terminal-notifier, and dashboard
  sinks. Replaces today's technical-first single-string notifications with a
  RenderedEvent contract that maps cleanly onto the existing ActionItem shape.
  Consumes the IA value-language copy map as canonical source-of-truth for
  Layer 1 vocabulary; preserves INBOX as truth-of-record; uses a sidecar-merge
  pattern so notification flow never mutates dashboard primary artifacts.
type: feat
tier: cross-cutting
status: completed
date: "2026-05-24"
goal_type: new_feature
surfaces:
  - ux
  - infra
  - docs
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
loop_caps:
  max_iterations: 3
  no_progress_threshold: 2
  wall_clock_hours: 8
  hard_stop: false
privacy_tier: internal
dependencies:
  - 2026-05-24-003-infra-dashboard-platform-roadmap-v1
  - 2026-05-24-001-feat-dashboard-value-language-ia-v0
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  evidence_dir: ./evidence/
  objective_contract: ./objective_contract.json
orchestration:
  parent_plan_id: 2026-05-24-003-infra-dashboard-platform-roadmap-v1
  spawn_reason: operator_manual
  depth_limit: 3
child_charter:
  kind: implementation
  parent_objective: "Replace technical-first single-string notifications with a layered RenderedEvent contract rendered consistently across Discord, INBOX, terminal-notifier, and the dashboard, anchored to the IA value-language copy map and preserving INBOX as truth-of-record."
  parent_acceptance_item: "V1 event messaging: every INBOX event kind has an explicit translation disposition; rendered output is layered (headline + why + action + technical) per the copy map; brand drift fixed at render boundary; sidecar-merge bridges to dashboard ActionItems; sanitization at render boundary; honest commands (no fakes)."
  allowed_paths:
    - "scripts/dontpanic_orchestrate/**"
    - "docs/plans/2026-05-24-004-feat-event-messaging-v1/**"
    - "docs/design/dashboard-value-language-ia-v0/**"
    - "CHANGELOG.md"
  forbidden_decisions:
    - "Do not edit dashboard/** files. The sidecar pattern (D003) makes messaging changes entirely Python-side; dashboard HTML/JS/CSS edits belong to the IA plan and Architecture Explorer plan."
    - "Do not invent CLI commands. Where no canonical remediation exists, render exact_command=None per D008."
    - "Do not edit source body strings in supervisor.py to fix brand drift. Translate at the render boundary per D010."
    - "Do not change inbox.append_event() signature. INBOX truth-of-record invariant per D013."
    - "Do not push directly into ~/.dontpanic/dashboard/what-now.json from dispatch_event. Sidecar pattern per D003."
    - "Do not add capability live notification emit sites. Deferred per D014."
    - "Do not fix the volley_start double-write bug. Filed separately per D015."
    - "Do not do a full parser-factory refactor of cli.py. Token-only validator per D012."
    - "Do not externalize copy to YAML or add localization. Python translation table with snapshot tests."
  return_condition_summary: "All five features pass with translation disposition covering 27 INBOX kinds, NotifyEvent extension landed, sinks consume RenderedEvent, sidecar-merge wired, sanitization at render boundary, snapshot fixtures per kind per primary channel, brand drift verified gone, CHANGELOG updated."
  may_edit_product_code: true
commit_policy:
  mode: child_commit
  requires:
    - tests_pass
    - evidence_packaged
---

# Event Messaging v1

## Motivation

DontPanic emits notifications today via `NotifyEvent` (six kinds: `breaker_tripped`, `gate_paused`, `calibration_required`, `signoff`, `volley_terminal`, `volley_start`) and persists 27 distinct INBOX event names. Discord and terminal-notifier surface only ~22% of the operator-visible events. The rendered output is technical-first — body strings like `vol-4f1a stopped_no_progress on plan 2026-05-24-001 F002 after 3 iterations` — and contains brand drift (`jarvis approve …`, `Jarvis [{plan_id}]`).

The IA plan (`2026-05-24-001`) shipped the canonical value-language copy map at `docs/design/dashboard-value-language-ia-v0/copy-map.md`. This plan applies that vocabulary across all notification surfaces by introducing a `RenderedEvent` dataclass (subset of `ActionItem`), an `event_copy` module that produces RenderedEvents from NotifyEvents + plan/feature metadata, and per-sink renderers that consume RenderedEvent. Sanitization runs at the render boundary; INBOX remains truth-of-record; dashboard receives event-derived ActionItems via a sidecar-merge pattern that does not mutate the provider-derived `what-now.json` from dispatch flow.

The architectural commitments are locked in `decisions.jsonl` (D001–D016) and substrate inventory is at `evidence/f001-inventory-draft.md`.

## Target

```yaml
target_env: dev
target_project: none
```

DontPanic-internal infra plan. All code changes in `scripts/dontpanic_orchestrate/`. No external project, no Firebase, no remote services.

## Product Model

Four-layer message anatomy applied to every event kind that has a non-`audit_only` disposition:

1. **Headline** — one sentence, value-first label per copy map. Lands in Discord embed title, INBOX heading, dashboard card title, terminal-notifier banner.
2. **Why it matters** — one sentence, operator impact. Lands in Discord description, INBOX paragraph, dashboard card subtitle. Omitted from terminal-notifier.
3. **Action** — exact copyable CLI command OR `None` (per D008, no fakes). Lands in Discord embed field, INBOX code block, dashboard action chip.
4. **Technical details** — `plan_id`, `feature_id`, `evidence_uri`, `breaker_kind`, `iteration_count`, source path, timestamp. Lands in Discord footer/mono, INBOX collapsed `<details>`, dashboard expandable detail row.

The headline is what a stakeholder scans in two seconds. The details are what an auditor reconstructs six months later. Both are honest.

## Translation Disposition

Per D007, every INBOX event kind receives an explicit disposition in F001:

| Disposition | Meaning |
|---|---|
| `live` | Renders to Discord + terminal-notifier + dashboard sidecar. High-value operator events. |
| `dashboard_action` | Renders to dashboard sidecar only. Surfaces as ActionItem without notification noise. |
| `inbox_only` | INBOX entry only. No live notification, no dashboard surface. |
| `audit_only` | Durable INBOX record for auditor reconstruction. Not surfaced to operator at all. |

Disposition is data (a column in the translation table), reviewed and revised independent of rendering logic. Initial disposition assignments are part of F001 acceptance.

## Boundaries

In scope:

- `RenderedEvent` typed dataclass + `event_copy.render()` module
- Translation table covering all 27 INBOX event kinds with explicit disposition
- `NotifyEvent` metadata extension (8 fields per D004) + `action_link`→`evidence_uri` alias (D005)
- 6 new NotifyEvent dispatch sites for currently-silent high-value events
- Per-sink renderers consuming RenderedEvent (Discord embed upgrade, INBOX additive wrapper, terminal-notifier RenderedEvent.headline, dashboard sidecar)
- Sidecar-merge pattern: render writes to `~/.dontpanic/dashboard/event-actions.jsonl`; dashboard build merges into `what-now.json` alongside provider-derived ActionItems
- Render-boundary sanitization wiring (raise mode for sidecar; redact mode for live)
- Brand drift translated at render boundary (no source body edits)
- Token-only command validator (Approach 2 per D012) in new `command_validation.py` module
- Snapshot fixtures per `(event_kind × primary channel)`
- CHANGELOG entry (product-facing format change)
- Copy authoring guide referencing the IA copy map

Out of scope:

- Dashboard HTML/JS/CSS edits (sidecar pattern keeps changes entirely Python-side)
- New event kinds (D014, D010)
- Capability live notification emit sites (D014)
- Cross-machine pull-from-INBOX rendering (V4)
- Full per-subcommand parser-factory refactor of cli.py (D012)
- Localization / YAML externalization of copy
- New channel sinks beyond Discord/INBOX/terminal/dashboard
- Source-side fixes to brand drift in supervisor.py body strings (D010)
- Fix for volley_start double-write bug at supervisor.py:1477+1532 (D015 — separate)
- Editing `inbox.append_event()` signature (D013 — additive wrapper only)

## Implementation Strategy

`event_copy.render(event, plan_meta, feature_meta) -> RenderedEvent` is a pure function. Translation table is a Python dict keyed by `NotifyEvent.inbox_event`, the paired INBOX `event=` value from F001 inventory. Each entry provides headline template, why template, action template (or `None`), disposition, and channel-specific overrides where useful.

Per-sink renderers consume `RenderedEvent` and produce sink-specific output:

- **Discord** (`notify_discord.py`): rich embed with title (headline), description (why), action field (exact_command), footer (technical metadata), color matching the 4-band taxonomy using inline hex literals from the IA copy map.
- **INBOX** (`inbox.py`): additive `append_rendered_annotation()` wrapper appends only the rendered markdown block with `<details>` for technical metadata. Existing emit sites keep calling `append_event()` for the raw truth-of-record entry.
- **terminal-notifier** (`notify.py`): consume `RenderedEvent.headline` as message body. Fix the `Jarvis [{plan_id}]` title brand string to `DontPanic [{plan_id}]` while there.
- **dashboard sidecar** (new in `operator_console.py`): render writes ActionItems to `~/.dontpanic/dashboard/event-actions.jsonl`. Existing `write_cache` at `operator_console.py:665-687` extended to merge the sidecar into `what-now.json` alongside provider-derived items.

Sanitization at render boundary uses the existing `_assert_no_secret_shapes` (raise mode for sidecar write — operator-fixable failure before persistence) and the public `state_projection.scrub_secrets` helper (substitute mode for live Discord/terminal/INBOX paths — live notifications must not fail-hard the supervisor).

Brand drift translation happens in the renderer, not source: every `jarvis approve …` / `jarvis-orchestrate approve …` / `Jarvis [...]` string emitted by the source body is normalized to `dontpanic` at render time. Source body edits are out of scope.

## Sequencing & Parallelism

This plan is parallel-safe with the in-flight IA F002/F003 work because the sidecar pattern keeps all changes Python-side. No dashboard HTML/JS/CSS edits required. Recommended dispatch order:

1. F001 (RenderedEvent + command validator + disposition table) — pure substrate, no collision
2. F002 (NotifyEvent extension + 6 new emit sites) — additive to existing emit sites
3. F003 (event_copy module + sink renderers + sidecar pattern) — consumes F001+F002
4. F004 (sanitization wiring) — depends on F003
5. F005 (snapshots + docs + CHANGELOG) — depends on F004

F001 may begin in parallel with any active IA or Architecture work. F002+ has no `dashboard/**` collision because the sidecar pattern routes through `operator_console.py` Python only.

## Status

`completed` — all 5 features closed operator_resolved across F001–F005. Architectural commitments locked in `decisions.jsonl` (D001–D016). Inventory substrate at `evidence/f001-inventory-draft.md`. IA copy map canonical at `docs/design/dashboard-value-language-ia-v0/copy-map.md`.
