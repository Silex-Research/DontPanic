# DontPanic Dashboard — Design System & UX Standard (v0)

The dashboard is a **local operator console**: a read-only window onto DontPanic's
governance state. This document is the enforceable standard every tab must meet so
the console is *consistent, scannable, honest, and actionable*. It is the design
counterpart to `docs/qa-sufficiency-contract.md` (which governs how the dashboard is
tested) — the read-only-UI surface is governed by both.

> Status: v0 standard, authored from a full 7-tab + shell UX audit (2026-06-05). It
> describes the **target**; the current dashboard does not yet conform. Migration is
> tab-by-tab, each gated by the real-state→real-shell journey test.

---

## 1. Product identity & principles

1. **Operator console, not a marketing site.** Dark, dense, terminal-adjacent. The
   monospace identity stays — it signals "this mirrors CLI truth." But monospace is
   *reserved for commands, paths, IDs, and data*; **prose (headlines, impact lines,
   empty states) uses a proportional sans** for absorption.
2. **Honesty first.** The UI never claims more than it knows or does. This is the
   platform's whole thesis — the design must not undercut it (see §6).
3. **Read-only by contract.** The dashboard mutates nothing. Every "action" *copies a
   command/bundle* you run yourself. The UI must make that unmistakable (§6).
4. **Most-urgent-first.** Layout, color, and nav order all bias the eye toward the one
   thing that needs attention now.
5. **One way to build a thing.** A card is *the* card; a button is *the* button. No
   per-page reinvention (§4 is the law).

---

## 2. Foundations (tokens)

All visual values come from tokens in `core.css :root`. **No raw hex, rgba, px font
sizes, or px spacing in page CSS** — that is a conformance failure (§11).

### 2.1 Color — semantic, not literal
Keep the existing palette tokens (`--bg-primary/secondary`, `--bg-card`,
`--bg-card-hover`, `--accent`, `--accent-glow`, `--green/red/yellow/orange/purple`
(+ `-dim`), `--text-primary/secondary/muted`, `--border`). Add **semantic aliases** so
pages reference meaning, not hue:

| Alias | Maps to | Means |
|---|---|---|
| `--surface-1/2/3` | bg-primary / bg-card / bg-card-hover | elevation layers |
| `--status-ok` | green | healthy / ready / done |
| `--status-attention` | yellow | needs setup / advisory |
| `--status-blocked` | red | blocked / needs action / error |
| `--status-info` | accent (blue) | informational / interactive |
| `--status-muted` | text-muted | inactive / no-data |

**`--accent` (blue) is reserved for interactive/active elements only** — links, the
active tab, focus, primary buttons. It must not be used for decorative headings, or the
eye loses the "this is clickable" signal.

### 2.2 Spacing scale (NEW — none exists today)
`--space-1:4px · --space-2:8px · --space-3:12px · --space-4:16px · --space-5:24px ·
--space-6:32px · --space-8:48px`. Every margin/padding/gap uses these. The current
magic-number px values (16/24/12/13/11…) are why the grid reads as inconsistent.

### 2.3 Type scale (NEW — none exists today)
`--text-xs:11px · --text-sm:12px · --text-md:13px · --text-lg:16px · --text-xl:20px ·
--text-2xl:28px`, plus `--leading-tight:1.25 · --leading-normal:1.5`. Two families:
`--font-mono` (commands/paths/IDs/data) and `--font-sans` (prose). Numbers in stat
tiles use `--text-2xl` mono.

### 2.4 Radius, border, focus
`--radius` (keep), `--border`, and a **`--focus-ring`** token (`0 0 0 2px
var(--accent)`) used by a global `:focus-visible` rule (§9).

---

## 3. Layout grammar

Every tab renders the **same page skeleton**, provided by a shared `renderPage()`
helper so no page hand-rolls its root markup:

```
.page
  .page-header     → title (mono, --text-xl) · scope badge · primary actions slot
  .page-summary    → stat strip (StatTile row) — the at-a-glance numbers
  .page-content    → the tab's body (cards / table / canvas)
  .page-footer     → provenance (source file + refresh command)   [shared pv-footer]
```

- **Title → summary → actions → content** is mandatory ordering. The summary stat-strip
  is where the operator reads the situation in <2s; the body is where they act.
- Max content width on text-heavy pages; full-bleed allowed for canvases (Architecture).
- **Shell:** header (`DontPanic · Local Operating Console` + READY pill + clock), then
  the project/scope row, then the tab bar, then `<main>` holding `.page`.
- **Nav order (recommended):** `NEEDS ATTENTION · REPAIR · WORK · HEALTH · ARCHITECTURE ·
  TOOLS & SETUP · PREFERENCES` — triage→fix→work→status→reference→setup→prefs. (Today
  Needs Attention is 5th; that's backwards for an operator console.)

---

## 4. Component library (the missing layer)

These live in `core.css` (or a `components.css`) and are the **only** approved building
blocks. A page MAY add a thin modifier; it MUST NOT reinvent the primitive.

| Component | Replaces today's… | Spec |
|---|---|---|
| **Button** `.btn` (`--primary/--secondary/--ghost`) | `repair-copy-btn`, `arch-*-btn`, `stg-save-btn`, raw `<button>` | real affordance: padding, radius, hover/active/disabled/focus states; primary uses `--accent`. |
| **CopyCommand** `.copy-cmd` | every bespoke command block + the inert `<pre>`s | a command in a mono block + a copy button; **shows "Copied ✓" on success and a visible failure hint on denial**; label always starts with **"Copy"**. THE canonical action of this console. |
| **Card** `.card` (`--ok/--attention/--blocked/--muted`) | `cost-card`, `mc-card`, `wn-card`, `arch-*-card`, `cap-card`, `hlth-card`, `ci-card`, `sr-card` | left-border status accent + header (kind chip + scope) + body + footer. |
| **StatTile** `.stat` + **StatStrip** `.stat-strip` | the Repair count sentence; `sec-stat-value`, `da-metrics-grid` | big mono number (`--text-2xl`) + label; the actionable number gets `--status-*` color + emphasis. **Data is never prose.** |
| **Badge** `.status-badge` (exists) + **Chip** `.chip` | `mc-badge`, `cap-status-badge`, `wn-*-chip`, `arch-meta-chip`, scope chips | reuse the existing `.status-badge`; one chip primitive for kind/source/role. |
| **SectionHeader** `.section-header` | bespoke `*-header` per page | title + count + optional action. |
| **Table / ListRow** `.table` / `.row` | ad-hoc card grids for list data | for scannable many-item data (e.g. Repair's 173 items). |
| **EmptyState** `.empty-state` (exists) | `wn-empty-*`, `cap-empty-*`, `mc-empty` | reuse the shared one; never reinvent. |
| **Skeleton** `.skeleton` (NEW) | (nothing) | loading placeholder; required by §7. |
| **Banner/Alert** `.banner` (`--info/--warn/--error`) (NEW) | one-off missing-fleet banner | page-level notices. |
| **ScopeBadge** `.scope-badge` (exists) | reuse | FLEET / PROJECT / GLOBAL. |

**Rule:** if a render emits a class, that class MUST have a CSS rule. "Emitted but
unstyled" (the current Repair / `sr-*` / `cap-card-*` / `wn-gt-*` / `hlth-global-tools*`
failures) is a release-blocking defect, not a polish item.

---

## 5. Patterns by data shape

- **Counts/metrics →** StatStrip of StatTiles (lead with the number that matters).
- **A prioritized list of items needing action →** banded sections (by severity), each a
  list of Cards; **always show the items**, never just a count + a copy button (Repair's
  core failure: 173 items, none shown).
- **An action the operator must run →** a CopyCommand, labelled "Copy …".
- **Config / read-only fields →** Cards with a CopyCommand for the change command. **Never
  a styled `<input>`/`<select>`/"Save" button unless it genuinely writes** (§6).
- **A graph/topology →** full-bleed canvas, with pre-amble collapsible so the canvas isn't
  buried (Architecture).

---

## 6. Action-affordance honesty (non-negotiable)

The audit's most common defect. Rules:

1. **The visible label must match what actually happens.** A control that copies a command
   is labelled **"Copy …"** — never "Repair automatically," "Run," "Apply," or any verb
   that implies the dashboard executes. (The honest verb must be *visible*, not hidden in
   an `aria-label`.)
2. **Every copy action confirms.** Success → "Copied ✓" (and an `aria-live` announcement).
   Failure (clipboard denied / sandbox) → a *visible* fallback ("select to copy"), never a
   silent no-op.
3. **Read-only must not look editable.** If the dashboard can't change a value, don't render
   it as a form field with a Save button. Show it as data + the CopyCommand that changes it.
   (Settings' "Save preferences" form is the trap — the only truly-editable thing there is
   browser-local display state, which should be visually demoted and auto-saved.)
4. **Tier the consequences.** Fleet-wide vs single-project, reversible vs not, human-required
   vs auto-safe — surface the scope/consequence *next to the action*, not buried in prose.

---

## 7. State-coverage contract

Every data surface distinguishes — visibly and differently — all five:

| State | Meaning | Treatment |
|---|---|---|
| **Loading** | cache being read | Skeleton (never a confident empty). |
| **Empty (never-ran)** | file absent | EmptyState + the exact build/create command. |
| **Zero (real)** | present, genuinely nothing | a *positive* "all clear" — not the same as never-ran. |
| **Partial** | truncated/over-limit | "+N more" affordance; never silently drop. |
| **Error (corrupt)** | file present but unparseable | a distinct error Banner — **must not** collapse into "not built yet" (the current universal bug). |

---

## 8. Content & copy

- **Value-first headline** per card ("Install has blockers") + a plain **impact line**
  ("1 tool blocked — 4 connected"). Lead with meaning, not the raw field.
- **No implementation jargon in the UI.** `missing: roles.implementer`,
  `capability_id`, raw token dumps are forbidden surface text — humanize them (Capabilities
  still leaks `missing:` tokens; that's a defect).
- **One idea per line.** Numbers belong in StatTiles, not mid-sentence (Repair).
- **Plain verbs**, present tense, operator's vocabulary.

---

## 9. Accessibility baseline (target: WCAG 2.1 AA)

- `<main>` landmark + a skip-to-content link; nav is a real `<nav>` with the tablist pattern.
- Global `:focus-visible` ring (`--focus-ring`) on every interactive element.
- **Status is never color-only** — pair the band color with an icon or text token.
- Contrast ≥ AA for body text on `--bg-primary` (audit `--text-muted`/`--yellow` at small
  sizes — several currently fail).
- Interactive elements are real `<button>`/`<a>` with labels — no clickable `<div>` without
  `role` + `tabindex` + key handler (Work's cards/agent rows, Mission-control modal triggers).
- `aria-live="polite"` for "Copied", "Saved", and auto-refresh updates.

---

## 10. Density & motion

- Density is a feature; achieve it with the spacing/type scale, not by shrinking everything
  uniformly. Hierarchy (size + weight + color) is what makes dense legible.
- Motion is minimal and functional only: the copied-flash, tab switch, skeleton shimmer.
  No decorative animation.

---

## 11. Governance & enforcement

This standard is advisory in v0 but enforced by these checks as they land:

- **No unstyled emitted class** — a build/lint check that every class a page render emits
  resolves to a CSS rule (catches the Repair/`sr-*`/`cap-card-*`/`wn-gt-*` class of bug).
- **Token-only values** — page CSS may not contain raw hex / rgba / px font-size / px
  spacing; all via tokens.
- **No orphan stylesheets** — `index.html` loads CSS only for pages in `pageModules`
  (retire cloud-costs / command-center / financial / security, which today bleed ~1.8k lines
  onto live pages).
- **Conformance is proven through the real surface** — per `docs/qa-sufficiency-contract.md`,
  a dashboard-facing change is verified by the real-state→real-shell journey test, not by a
  render-helper snapshot.
- **Component reuse** — new page markup uses §4 primitives; a bespoke card/button/stat is a
  review finding unless the primitive genuinely can't express it (then extend the primitive).

---

## 12. Aesthetic direction (the "rethink")

Keep the dark monospace operator-console identity — it's correct for a local governance
tool and every audited tab confirmed it *fits*. The evolution is **discipline, not
reskin**:

1. Introduce the type + spacing scales (§2.2–2.3) so density reads as intentional.
2. Reserve monospace for commands/paths/IDs/data; use proportional sans for prose so the
   eye absorbs headlines and impact lines faster.
3. Make `--accent` mean "interactive" only; let `--text-secondary`/`--text-muted` carry
   hierarchy so the one urgent thing pops.
4. Give every page the §3 skeleton and every action the §6 honesty treatment.

Net: same palette, same family, same console soul — but a real component system, a scale,
and honest affordances turn a flat wall of monospace into a console an operator can absorb
and act on at a glance.
