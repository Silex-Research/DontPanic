# Dashboard Value-Language Copy Map (V0)

Plan: `2026-05-24-001-feat-dashboard-value-language-ia-v0`

This map is the V0 contract for first-read labels and progressive technical
disclosure across the local DontPanic dashboard. It is consumed by F002 (shell
rebrand) and F003 (page rewrites), and it is the reference future surfaces
(Architecture, Review/Evidence, Configuration, Agent Sessions) must inherit.

The map is intentionally machine-readable in places — see the
[Forbidden first-read tokens](#forbidden-first-read-tokens) section, which is
the data source for the static check landed alongside this feature
(`dashboard/tests/unit/value-language-static-checks.test.js`).

---

## 1. Two-layer language rule

V0 uses a two-layer language rule:

1. **Primary labels** — user/business value, operational intent. Title, nav,
   first paragraph of a card, the line a non-technical reviewer reads first.
2. **Technical disclosure** — DontPanic internal nouns, IDs, file paths,
   timestamps, and exact CLI commands. Always present, but in metadata rows,
   tooltips, source/provenance footers, exact-command chips, or details
   sections.

> Layer 1 answers "What does this mean for me?".
> Layer 2 answers "What is this technically, and what command runs it?".

The purpose is **sequencing**, not hiding. The dashboard remains a precise
operator console; technical operators and agents must always be able to
recover the exact substrate (plan_id, feature_id, gate name, capability_id,
source file, last-updated timestamp, exact CLI command) from the same view.

---

## 2. Surface-by-surface copy map

Each row pairs a Layer 1 primary label with the Layer 2 technical disclosure
that must remain visible on the same surface.

### 2.1 Navigation shell

| V0 nav label | Backing page module | Internal noun | Required Layer 2 disclosure |
|---|---|---|---|
| **Needs Attention** (route may be `Home`) | `pages/what-now/` | What Now / action item cache | Source: `dashboard/state/what-now.json` and `dashboard/state/fleet-what-now.json` |
| **Work** | `pages/mission-control/` | Mission Control / plan + feature lifecycle | `plan_id`, `feature_id`, lifecycle gate name in metadata row |
| **Tools & Setup** (or **Connections**) | `pages/capabilities/` | Capability Center | `capability_id`, `owner_boundary`, exact setup command |
| **Health** | (new composition over status / readiness / build warnings) | Status, security, build warnings, install reconcile | Source filename + last-updated timestamp per warning |
| **Preferences** | `pages/settings/` | Settings (UI-local only) | Storage scope ("local browser only"), no DontPanic config writes |

Deferred / hidden:

| Surface | V0 disposition |
|---|---|
| Financial | Remove from core nav (Jarvis-era artifact). |
| Cloud Costs | Defer — no real cost capability manifest yet. May reappear later as a capability-backed integration card under Tools & Setup or as a Health datapoint, never as a top-level nav. |
| Security | No standalone tab; folds into Health with credible data or a missing-data state. |
| Firebase, Linear, Discord | Future `Integrations` grouping. Hidden unless capability data supports rendering. |
| Architecture | Out of scope for this plan; allowed as a muted future nav affordance pointing at the separate Architecture Explorer plan or its exact regen command. |
| Review / Evidence, Configuration editor, Agent Sessions | Future child plans. No placeholder tabs in V0. |

### 2.2 Needs Attention (Home)

Card-level copy:

| Layer 1 primary | Layer 2 technical |
|---|---|
| "Approval needed" | gate name (`pre_impl`, `pre_merge`, `on_escalation`, `breaker:*`, `defer:*`), `plan_id`, `feature_id` |
| "Blocked work" | supervisor id, last error class, gate that blocked, link to source `INBOX.md` event |
| "Setup needed" | `capability_id`, missing dependency, exact `dontpanic capabilities setup …` command |
| "Setup drift" | install reconcile snapshot path, what changed (added/removed/changed installer payload) |
| "Active AI work" | supervisor id, `feature_id`, current step, time since last heartbeat |
| "System warning" | source filename, last-updated timestamp, warning class |
| "All clear" (quiet state) | source files + last-updated timestamps for each underlying provider |

Recommended-command panel (uses `dontpanic next` substrate from
plan 2026-05-23-007):

- Layer 1: short imperative sentence describing the operator's next move.
- Layer 2: exact command chip (copyable, no auto-run), readiness explanation,
  underlying plan/feature ids.

### 2.3 Work (read-only Mission Control)

V0 Work is a read-only viewer of plan/feature lifecycle. No mutation
affordances. Drag-to-command may exist only as a non-mutating command preview
(see [§4.2 Drag-to-command decision](#42-drag-to-command-decision)).

| Layer 1 primary | Layer 2 technical |
|---|---|
| "Planned" | `plan_id`, status field, decisions log pointer |
| "Ready to run" | `dontpanic next` readiness fields, missing prerequisites |
| "Running" | supervisor id, current `feature_id`, last `INBOX.md` event, gate state |
| "Waiting on approval" | gate name (`pre_impl` / `pre_merge` / etc.), required approver, exact `dontpanic approve …` command |
| "Blocked" | breaker name, last failed audit, exact `dontpanic resume …` or remediation command |
| "Done" | last decision, evidence dir, audit envelope path |

### 2.4 Tools & Setup (Capability Center)

The page primarily groups by integration / capability category. Status comes
from the existing four-band taxonomy (§3); the optional relevance chip is
rendered orthogonally.

| Layer 1 primary | Layer 2 technical |
|---|---|
| "Connected" | `ready`; `capability_id`; last status refresh timestamp |
| "Setup required" | `needs_setup`; exact `dontpanic capabilities setup <id>` command |
| "Blocked" | `blocked`; failing precondition (`owner_boundary`, missing binary, expired credential) |
| "Not installed" | `not_installed`; exact install command (`brew install …`, `gh auth login`, etc.) |
| "Optional for this project" | `optional` relevance chip (not a status color) |
| "Needs human steps" | exact human-required reason from capability status |

### 2.5 Health

Health is the honesty surface. Every card on Health must have a credible data
source or a named missing-data state. No green checks for data we never
collected.

| Layer 1 primary | Layer 2 technical |
|---|---|
| "Install is healthy" | reconcile snapshot file, last-updated, summary of installer payload |
| "Setup drift detected" | reconcile snapshot diff, exact `dontpanic reconcile` command |
| "Recent build warnings" | source artifact (test log path, audit envelope path), warning class |
| "Budget guardrail" | quota state file, `quota_state.json` numbers, breaker name if tripped |
| "No data yet" | name of the missing file (e.g. `dashboard/state/capabilities-status.json`), exact build command (`dontpanic dashboard build`) |

Never render an empty Health card as "OK". Either the source data confirms
health (with timestamp) or the card explicitly says the data is missing.

### 2.6 Preferences

Preferences only describes UI-local behavior of *this* dashboard instance
(theme, default project, density, etc.). It must not imply that it edits
DontPanic configuration, secrets, or capability state.

| Layer 1 primary | Layer 2 technical |
|---|---|
| "Default project on open" | storage: localStorage `jarvis.selectedProject` (alias retained for cache compatibility) |
| "Refresh cadence" | client-only polling interval; never writes to disk |
| "Display density / theme" | UI-only |
| "Reset this dashboard's preferences" | clears localStorage only; does not touch `~/.dontpanic/` |

Demo project rows, Jarvis-era product rows, and any presentation that hints
at DontPanic-wide config editing must be removed.

### 2.7 Cross-surface copy primitives

These primitives appear on multiple pages and must use consistent language.

| Primitive | Layer 1 | Layer 2 |
|---|---|---|
| **Approval card** | "Approval needed — \<plain English of what gets unblocked\>" | gate name, `plan_id`, `feature_id`, exact approve command |
| **Blocked card** | "Work is blocked — \<plain English impact\>" | breaker name, source `INBOX.md` event, exact resume/remediation command |
| **Active work card** | "Running — \<plain English of what is being attempted\>" | supervisor id, current feature, time-since-heartbeat |
| **Setup needs card** | "Set up \<tool\>" | `capability_id`, exact setup command, owner_boundary |
| **Budget guardrail card** | "Budget guardrail engaged — \<plain English of why\>" | breaker name, `quota_state.json` numbers, expiry/reset time |
| **Source / provenance footer** | (no Layer 1; this *is* Layer 2 for the card) | `Source: <path> · Last updated <timeAgo>` |
| **Command chip** | (no Layer 1) | exact shell command in `<pre><code>` with a non-mutating copy button |
| **Status pill** | one of `NEEDS ACTION` / `ADVISORY` / `INFO` / `READY` | underlying provider field name in tooltip |
| **Relevance chip (`optional`)** | "Optional for this project" | `optional` capability status |

---

## 3. Status taxonomy and relevance chip

V0 keeps the existing four-band status taxonomy. **No fifth band is added.**

| Band | Label | Color token | Meaning |
|---|---|---|---|
| `needs_action` | NEEDS ACTION | red | Someone has to do something for the system to make progress. |
| `advisory` | ADVISORY | yellow | Useful warning, but no human is currently blocked. |
| `info` | INFO | accent | Contextual or running state. |
| `ready` | READY | green | The thing is healthy / ready. |

Source: `dashboard/lib/what-now-logic.js` `BANDS` / `BAND_COLORS` constants
and `dashboard/lib/capabilities-logic.js` `CAPABILITY_STATUSES` /
`STATUS_COLORS`.

### 3.1 Optional is a relevance chip, not a status

`optional` describes whether a capability or setup item applies to the
currently selected profile/project — it is not a health state. Render it as
an orthogonal chip ("Optional for this project") alongside the four-band
status pill, never as a fifth color.

This is locked by [D003](../../plans/2026-05-24-001-feat-dashboard-value-language-ia-v0/decisions.jsonl).

---

## 4. Documented decisions (read before implementation)

### 4.1 Audience expansion — non-technical reviewer persona

V0 explicitly adds a **non-technical reviewer / founder / product-owner**
audience alongside the existing operator-in-loop and agent/auditor audiences
([D008](../../plans/2026-05-24-001-feat-dashboard-value-language-ia-v0/decisions.jsonl)).

Why this matters before implementation:

- OSS and product review expose DontPanic to people who arrive without the
  internal vocabulary (gate, supervisor, volley, manifest, quota, pre_impl,
  pre_merge). If the first-read says "pre_impl gate needs approval", the
  reviewer can't tell whether anything matters.
- The audience expansion does **not** turn the dashboard into a marketing
  page. Technical substrate stays visible second, in metadata rows, source
  footers, and exact command chips. Agents and technical operators still
  recover plan_id, feature_id, capability_id, source files, and commands
  from the same view.

The success bar is "a non-technical reviewer can answer the five questions
in §2 of the plan in under one minute, and a technical operator can still
recover exact substrate from the same view".

### 4.2 Drag-to-command decision

Locked: drag-to-command is allowed **only** as a non-mutating command-preview
pattern ([D010](../../plans/2026-05-24-001-feat-dashboard-value-language-ia-v0/decisions.jsonl)).

Rules:

- Dropping a card on a target may **only** produce a preview of the exact
  command that would be run, displayed in a command chip the operator copies
  manually. The drop event itself must not call any CLI, write any state
  file, or mutate the dashboard view beyond showing the preview.
- If the implementation cannot guarantee the no-mutation rule cleanly (for
  example because Claude Design's drag affordance implies a state change),
  drag affordances must be removed entirely from V0.
- Work is read-only in V0. The previous "Mission Control" drag/drop kanban
  affordances must not survive into V0 Work unless rebuilt under the
  command-preview rule above.

Test discipline: F002 ships a test asserting Work has no drag handlers that
mutate state. If drag-to-command is implemented, the same test must assert
that the drop handler emits a command preview and does nothing else.

### 4.3 JSX-to-vanilla translation strategy

Locked: port Claude Design output into the existing vanilla static
dashboard; do not adopt React/JSX as a runtime dependency
([D012](../../plans/2026-05-24-001-feat-dashboard-value-language-ia-v0/decisions.jsonl)).

Translation rules:

| Claude Design artifact | Treatment |
|---|---|
| Design tokens (spacing, color, typography, status treatments) | Adopt as CSS custom properties / utility classes in `dashboard/core.css` and per-page CSS. |
| Small primitives — command chips, status pills, badges, provenance footers, empty states | Port to vanilla DOM helpers in `dashboard/lib/` and consume from `pages/<surface>/`. |
| Full React page components | Treat as **visual specifications**, not runtime dependencies. Implementer rewrites in vanilla JS calling existing pure logic modules. |
| Drag affordances (React) | Port only if compatible with §4.2; otherwise drop. |
| Mock data and demo state inside React components | Discarded — V0 uses real state files; missing data renders explicit missing-data states. |

Implementation must not introduce a build step (Vite/Webpack/Rollup), a JSX
runtime, or any framework dependency. The existing `dashboard/` directory
remains served as static files by `dontpanic dashboard serve`.

### 4.4 Fleet-mode expectations for Home, Work, and Health

Locked: Home (Needs Attention), Work, and Health must each ship a fleet
variant ([D013](../../plans/2026-05-24-001-feat-dashboard-value-language-ia-v0/decisions.jsonl)).

Substrate already shipped:

- `dashboard/state/fleet-summary.json` (plan 2026-05-23-005)
- `dashboard/state/fleet-what-now.json` (plan 2026-05-23-005 F004)
- `dashboard/lib/project-selector-logic.js` — `ALL_PROJECTS_VALUE`,
  `resolveSelection`, `renderScopeBadgeHTML`, `normalizeFleetSummary`

Per-surface expectations:

| Surface | Single-project view | All Projects (fleet) view |
|---|---|---|
| **Home / Needs Attention** | Cards scoped to selected project; project name visible in header. | Cards grouped by project (project name as section header); each card carries a project chip. Global blockers (no `project_name`) render in a "Global" group at the top. Stable ordering by band → project → source → id. |
| **Work** | Plan/feature lifecycle for the selected project, with `plan_id`/`feature_id` as Layer 2. | Plans/features grouped by project; project chip on each row; "All Projects" header counts plans-in-flight. Global plans (no project context) appear in a "Global" group. |
| **Health** | Health cards for the selected project's reconcile / build warnings / quota. | Three scopes visible per card: **global** (install-wide), **project-specific** (selected project rows), **fleet-level** (aggregate across projects). Each card labels which scope its warning belongs to and shows the source file for that scope. |

Fleet variants must not silently dedupe a global warning into a per-project
warning. The scope label (global / project / fleet) is required Layer 2
disclosure on every Health card.

Tools & Setup and Preferences are **not** required to ship fleet variants in
V0:

- Tools & Setup: capability status is install-wide today (one `~/.dontpanic`
  install runs the capability manifest); a per-project relevance chip is
  enough. A future plan may add per-project capability scoping.
- Preferences: UI-local only.

### 4.5 Identified Jarvis-era and internal-first labels

Before F002 starts, these are the surfaces that must be touched. F002's
acceptance is satisfied only if every item below has either been renamed
under Layer 1 or moved to Layer 2 (or, where deferred, removed from V0
core nav).

Shell:

- `<title>JARVIS — Control Dashboard</title>` in `dashboard/index.html`
  → DontPanic-branded title.
- `<h1>JARVIS</h1>` and `<span class="subtitle">Personal Control
  Dashboard</span>` in `dashboard/index.html` → DontPanic-branded shell.
- Footer "JARVIS v1.0 — Silex Research" → DontPanic-branded footer with
  version pulled from a credible source (or removed if no credible source
  exists).
- `<title>JARVIS — Firebase Mode</title>` in
  `dashboard/index-firebase.html` → DontPanic-branded title.
- localStorage / state key prefixes named `jarvis.*` may stay for cache
  compatibility, but must not appear in user-visible copy.

Tab / page labels (current → V0):

| Current label | V0 disposition |
|---|---|
| What Now | Renamed for display to **Needs Attention**. Route alias `home` acceptable per [D011](../../plans/2026-05-24-001-feat-dashboard-value-language-ia-v0/decisions.jsonl). Page module path `pages/what-now/` may remain for stability. |
| Mission Control | Renamed for display to **Work**. Read-only in V0; no drag-to-mutate. |
| Command Center | Removed from V0 core nav; functionality folds into Work and Needs Attention. Existing module `pages/command-center/` may remain on disk but must not appear as a primary tab. |
| Capabilities / Capability Center | Renamed for display to **Tools & Setup** (or **Connections**). Internal noun "Capabilities" only allowed in details rows and `capability_id` metadata. |
| Financial / Financial Analysis | Removed from core nav entirely. (Live `registerPage` label is `Financial Analysis`; both phrasings are flagged by the stale-nav-label static check.) |
| Cloud Costs | Hidden / deferred from V0. |
| Security | Folded into Health; not a standalone tab. |
| Settings | Renamed for display to **Preferences**. UI-local only. |
| Firebase / Linear / Discord | Future Integrations grouping; hidden in V0 unless capability data supports rendering. |
| Architecture | Out of scope; may appear as a muted future-nav item only ([D014](../../plans/2026-05-24-001-feat-dashboard-value-language-ia-v0/decisions.jsonl)). |

Internal-first language to lift into Layer 1 / push into Layer 2:

| Internal-first | Layer 1 rewrite | Layer 2 (kept visible) |
|---|---|---|
| "Gate" | "Approval needed" / "Approval cleared" | gate name (`pre_impl` / `pre_merge` / `on_escalation` / `breaker:*` / `defer:*`) |
| "Supervisor" / "Volley" | "Active AI work" / "Review in progress" | supervisor id, `feature_id` |
| "Capability" | "Tool" / "Integration" / "Connection" | `capability_id`, `owner_boundary` |
| "Manifest" | "Setup list" / "Install list" | manifest filename and last-updated |
| "Quota" / "Breaker" | "Budget guardrail" | `quota_state.json` numbers, breaker name |
| "Reconcile drift" | "Setup drift" | install reconcile snapshot diff |
| "What Now cache" / "render envelope" | (no first-read; this is a source name) | source: `dashboard/state/what-now.json` |
| "pre_impl" / "pre_merge" | (no first-read; this is a gate name) | gate name in details row / command chip |

### 4.6 Source / provenance pattern

Every V0 page must render a consistent source/provenance treatment without
dominating the first read. Pattern:

- Card-level: small muted footer line `Source: <relative path> · Last
  updated <timeAgo>`. Path is the dashboard state file (e.g.
  `state/what-now.json`).
- Page-level: a single footer or header strip showing the page's primary
  source file, last sync time, and the exact `dontpanic dashboard build`
  command needed to refresh.
- Missing-data states must name the file that is absent and show the exact
  command that would create it.

No secret values may appear in any state file, HTML snapshot, design doc, or
copied asset. Sanitization checks (F004) cover the relevant paths.

---

## 5. Forbidden first-read tokens

These tokens must not appear as Layer 1 / first-read labels in V0 surfaces.
They are allowed (and often required) in Layer 2 — metadata rows, tooltips,
source/provenance footers, exact-command chips, and details sections.

```
gate
supervisor
volley
manifest
quota
pre_impl
pre_merge
```

Also forbidden in user-visible shell text (header, footer, page titles,
nav labels) regardless of layer:

```
JARVIS
Jarvis
Personal Control Dashboard
Silex Research
```

The list above is the canonical input to the static check
`dashboard/tests/unit/value-language-static-checks.test.js`. If the list
changes, update both this section and that test in the same change.

> Note: `Jarvis` may legitimately appear as a JavaScript object name in
> `dashboard/core.js` (`window.Jarvis`) and as a localStorage key prefix
> (`jarvis.selectedProject`) for cache compatibility. The static check
> scans HTML/CSS shell text and skips JS identifiers and storage keys.

---

## 6. How to read this document

- **F001 (this feature)** — establishes the contract. Reviewers should be
  able to confirm every item in [§4](#4-documented-decisions-read-before-implementation)
  is locked before any code lands in F002/F003.
- **F002 (shell rebrand and nav cleanup)** — implements
  [§2.1](#21-navigation-shell), [§4.5](#45-identified-jarvis-era-and-internal-first-labels),
  and the forbidden-token check in [§5](#5-forbidden-first-read-tokens).
- **F003 (page rewrites)** — implements [§2.2–§2.6](#22-needs-attention-home)
  and the fleet-mode expectations in [§4.4](#44-fleet-mode-expectations-for-home-work-and-health).
- **F004 (provenance, accessibility, sanitization)** — verifies
  [§4.6](#46-source--provenance-pattern), the no-secret invariant, and
  the snapshots.
- **F005 (dashboard docs and closeout)** — links the dashboard README at
  this map and records which Claude Design assets were used / deferred.

Future surfaces (Architecture Explorer, Review/Evidence, Configuration,
Agent Sessions) must extend this map rather than invent new vocabulary.
