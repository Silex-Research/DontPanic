---
id: 2026-06-07-003-feat-operator-console-008-chrome-theming-state
title: Operator console 008 — armed-terminal chrome + legacy theming + full state matrix
type: feat
tier: cross-cutting
status: completed
date: "2026-06-07"
goal_type: new_feature
description: >
  Finish the operator-console usability layer deferred to 008: armed-terminal
  hazard chrome (no PTY/backend change), legacy-page theming onto the existing
  --dp-* tokens via a bridge, and the full five-state surface matrix
  (loading/missing/stale/error/ready) generalized from the cockpit classifier,
  with journey tests through the real dashboard shell. No architecture-model
  changes and no new action-execution channel.
---

## Target

```yaml
target_env: dev
target_project: none
```

## Why

The operator-console redesign (004/005/006) shipped the cockpit, IA, tokens, and
the embedded terminal, but three usability seams were deferred to 008: the armed
terminal's hazard chrome was minimal, legacy pages still render in their own
Slate hexes so a theme/density switch does not survive onto them, and the
five-state surface matrix (loading / missing / stale / error / ready) only
exists for the cockpit. With Plan A having settled the confidence/freshness
truth contract, finishing the usability layer is now safe — none of this touches
the architecture model or adds an execution channel.

## Scope (bounded)

- **Armed-terminal chrome only** — visual + a11y polish on the existing
  `dashboard/components/armed-terminal.js`. NO new PTY/backend semantics, no new
  command channel; armed stays disarm-only and OFF by default.
- **Legacy theming via the existing tokens** — bridge the legacy `core.css`
  colour variables (`--bg-primary`, `--text-*`, `--border`, …) to the `--dp-*`
  tokens under `[data-theme]`/`[data-density]` so a theme/density swap survives
  onto every legacy page. No per-page redesign.
- **Full state matrix** — generalize the cockpit's 5-state classifier into one
  reusable surface-state module applied across the key surfaces; each renders
  loading/missing/stale/error/ready consistently (render-truth: stale visibly
  demoted, error shows last-good + retry, never present stale as fresh).
- **Journey tests through the real shell** — boot `createJarvis().init()` and
  drive each key surface through the five states with producer fixtures.

## Non-goals

- No new PTY backend semantics / no new action execution channel.
- No architecture-model changes (no nodes/edges/contract edits).
- No per-page visual redesign — theming is a token bridge, not a re-layout.
- No new dashboard pages or nav changes (006 owns the IA).

## Features

- **F001** — Armed-terminal chrome: token-only hazard frame, `role="alert"`,
  scope label, disarm-only affordance; OFF by default; no backend change.
- **F002** — Legacy theme bridge: legacy `core.css` colour vars resolve to
  `--dp-*` tokens under `[data-theme]`/`[data-density]`; theme/density swap
  visibly survives onto legacy pages; no raw-hex regression on the bridge layer.
- **F003** — Surface-state matrix: reusable classifier + render contract for the
  five `surface_state` values across the key surfaces (one source, many
  renderers), aligned to `freshness.js` thresholds.
- **F004** — Real-shell journey: `createJarvis().init()` walks each key surface
  through loading/missing/stale/error/ready against producer fixtures.

## Decisions

See `decisions.jsonl`.
