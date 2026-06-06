# Dashboard UX Audit — 2026-06-05

Full per-tab review of the DontPanic local operator console (7 nav tabs + shell), one
reviewer per surface against a shared rubric. Standard derived from this audit:
`docs/dashboard-design-system.md`. No code changed by this audit.

## Job-to-be-done scoreboard (1–5, higher = better)

| Tab | JTBD | Component reuse | State coverage | A11y | Headline problem |
|---|---|---|---|---|---|
| Architecture | 4 | 2 | 4 | 3 | Best-built; map buried under ~9 panels; ~110 bespoke classes; hardcoded color. |
| Health | 3 | 2 | 4 | 2 | Strong honesty; no at-a-glance roll-up; color-only status; `hlth-global-tools*` unstyled. |
| Needs Attention | 3 | 2 | 3 | 3 | Good band cards; **Global-tools block unstyled + non-copyable**; error collapses to "missing". |
| Work (mission-control) | 3 | 2 | 2 | 2 | Great to *see* work, nothing to *act*; dead "Approve/Dispatch buttons" string; no loading/error. |
| Preferences (settings) | 3 | 3 | 2 | 2 | **Fake "Save" form** looks like it writes config; **entire `sr-*` skill-recs block unstyled**. |
| Tools & Setup (capabilities) | 2 | 3 | 2 | 2 | **No copy button at all** (inert `<pre>`); ~13 card-body classes unstyled; `missing:` jargon. |
| Repair | 1 | 1 | 1 | 2 | **No stylesheet exists**; 173 items, none shown; "Repair automatically" copies (label lies). |

Shell / IA: nav order buries Needs Attention 5th; 4 orphan stylesheets bleed ~1.8k lines
onto live pages; no `<main>`/skip-link/`:focus-visible`; no spacing/type scale.

## Systemic failures (each on ≥4 tabs)

1. **No shared component layer** below `.panel`/`.status-badge`/`.empty-state`. Every tab
   reinvents cards/badges/buttons (`mc-*`, `wn-*`, `arch-*` ~110, `cap-*`, `hlth-*`,
   `stg-*`/`ci-*`/`sr-*`). Root cause.
2. **Unstyled emitted classes → broken renders** (raw text on a black canvas): Repair
   (all `repair-*`, no `repair.css`), what-now (`wn-gt-*`, `wn-status-*`, `wn-project-*`),
   capabilities (~13 `cap-card-*`), health (`hlth-global-tools*`), settings (all `sr-*`,
   `ci-layout`).
3. **Action-affordance dishonesty / inconsistency:** copy-actions labelled like execution
   (Repair); no copy affordance at all (Capabilities, what-now Global-tools, Work); fake
   write-form (Settings); copy-failure is a silent no-op everywhere.
4. **No loading/error states** — corrupt cache collapses into "not built yet" on every tab,
   masking failure as "all clear".
5. **Token drift + no scale** — 14 hex in core.css, 32 more across page CSS, mono
   re-declared ~15× (Architecture); **no spacing or type scale tokens at all**.
6. **Accessibility floor** — no landmarks/skip-link/`:focus-visible`; color-only status;
   clickable `<div>`s; no `aria-live` on copied/saved.
7. **IA + hygiene** — Needs Attention buried; 4 orphan pages still loaded + bleeding CSS.

## P0 backlog (release-blocking: visibly broken or dishonest)

- Repair: create the page (stylesheet + StatStrip + the 173-item list); relabel "Repair
  automatically" → "Copy …"; add copied/failed feedback.
- Capabilities: add the CopyCommand affordance ("Show setup steps" must copy + confirm);
  style the ~13 unstyled card-body classes; drop `missing:` jargon.
- Settings: style the `sr-*` skill-recommendations block; demote the browser-local prefs and
  stop the "Save preferences" form from looking like it writes DontPanic config.
- what-now: style + make copyable the Global-tools section.
- Health: style `hlth-global-tools*`; add a worst-status roll-up.

## P1 backlog (consistency + honesty)

- Adopt the shared component layer + page skeleton (`docs/dashboard-design-system.md` §3–4).
- Real loading + error(corrupt) states across all tabs (§7).
- Token-only colors + add spacing/type scales; kill the 32 hardcoded hex.
- Work: add a copy-command affordance in the task detail; remove the dead drag-intent string.
- Architecture: move the map above the pre-amble (collapse insights/details); persist
  selection across tab switches.

## P2 backlog (polish + hygiene)

- Retire the 4 orphan pages (cloud-costs / command-center / financial / security) + their CSS.
- Accessibility pass (landmarks, skip-link, focus-visible, non-color status, aria-live).
- Nav re-order: Needs Attention · Repair · Work · Health · Architecture · Tools & Setup · Preferences.
- De-duplicate `.mc-dot` (defined twice, divergent) and other cross-file duplicates.

## What's genuinely good (keep)

- Honesty modeling (Health's never-paint-empty-green; Architecture's "no data" tags + refusal
  to fabricate scores; the read-only contract).
- Needs Attention's four-band priority cards + value-first headings.
- Work's three-pane see-the-work layout.
- The monospace console identity (fits; reinforces "mirrors CLI truth") — evolve, don't reskin.
