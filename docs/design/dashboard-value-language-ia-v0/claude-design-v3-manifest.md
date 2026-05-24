# Claude Design v3 Manifest — Dashboard Value-Language IA v0

Canonical design pack:

```text
docs/design/dashboard-platform-roadmap-v1/claude-design-v3/
```

This child plan owns the value-language, shell, navigation, token, and core
operator-console portions of the pack.

## Assets In Scope

- `dp-shell.jsx`
  - Uses `active reviews` instead of `active volleys`.
  - Uses primary nav labels `Home`, `Work`, `Architecture`, `Tools & Setup`,
    `Health`, `Preferences`.
  - Treat `Architecture` as a real V1 item only after Architecture Explorer
    F002 begins. IA should establish shell/nav conventions without implementing
    the Architecture page.
- `dp-tokens.css`
  - Source for dark operator-console tokens, spacing, typography, command
    chips, badges, panels, and drawer styling.
- `dp-page-home.jsx`
  - Source for first-viewport Home / Needs Attention language, setup-needed
    copy, recommendation cards, and provenance treatment.
- `dp-page-work.jsx`
  - Source for read-only Work layout.
- `dp-page-work-board.jsx`
  - Contains both read-only board and drag-to-command variants.
  - IA plan must honor D010: drag may preview commands only; no mutation.
- `dp-page-caps.jsx`
  - Source for `Tools & Setup` treatment over capability data.
- `dp-page-health.jsx`
  - Source for Health/readiness layout and stale-data treatment.
- `dp-page-prefs.jsx`
  - Source for Preferences only; do not imply full DontPanic configuration
    editing in this plan.
- `dp-page-fleet.jsx`
  - Source for All Projects / fleet grouping patterns.
- `dp-page-plain.jsx`
  - Source for non-technical wording, glossary, and value-first copy.
- `dp-page-docs.jsx`
  - Source for empty states, implementation notes, provenance patterns, and
    explicit drag/drop guidance.
- `uploads/FinalDontPanic.png`
  - Product/social visual reference only; not a runtime dashboard asset unless
    separately approved for docs/README use.

## Out Of Scope For This Child

- Implementing `dp-page-architecture.jsx` or `dp-page-arch-variants.jsx`.
- Adding browser-executed mutation paths.
- Adding Firebase/realtime controls.
- Importing JSX as runtime code.

## Implementation Rule

Treat this pack as visual specification and design-token input. The shipped
dashboard remains the existing static HTML/CSS/JS implementation.
