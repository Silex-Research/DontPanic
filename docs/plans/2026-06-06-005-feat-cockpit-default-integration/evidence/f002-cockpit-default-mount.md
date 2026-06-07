# F002 — Cockpit default mount

## What shipped
- `dashboard/pages/cockpit/cockpit-page.js` — a page module that registers via `Jarvis.registerPage`,
  mounts `renderQueue` + `renderInspectPanel` (the F003-F007 redesign components) over the LIVE
  `state.operatorTriage` model (the F001 fleet operator-triage/v0), read-only: card click → inspect-why;
  absent model → honest empty state (`dontpanic dashboard build --project all`), never a fabricated queue.
- `dashboard/core.js` — `pages/cockpit/cockpit-page.js` is now `pageModules[0]` (the LANDING surface;
  `init` routes to `pages[0]`). Every existing tab (operator-console, what-now, repair, mission-control,
  health, architecture, capabilities, settings) stays registered + navigable — no router rewrite.
- `dashboard/components.css` — minimal token-only (`--dp-*`) legibility for the cockpit mount (two-pane
  layout, groups, cards, inspect). Full visual fidelity (per-bucket rails, density, light-mode) deferred to 008.

## Tests (real surface)
- `tests/unit/cockpit-page.test.js` (6): registers id "cockpit"; mounts renderQueue (hero count + grouped
  feed) from a live model with NO raw-JSON leak; card click opens inspect-why (render-truth basis "no basis"
  carried through); absent model → honest empty state; cockpit leads pageModules; old tabs preserved.
- Updated the two intentional nav drift-guards (core-page-modules + shell-hardening-f002) to lead with cockpit.
- Full dashboard vitest: 64 files / 1139 passed (incl. the components.css token-only conformance lint).

## Deferred (per operator scope)
Resolution affordances carry their intent on the dataset but execute nothing (gate/armed-terminal = 008);
IA regroup + Repair dissolution = 006; full state matrix (loading/stale/error) = F004; theming = 008.
