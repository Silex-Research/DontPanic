---
id: 2026-06-05-001-fix-capability-card-setup-clarity
title: Capability card setup clarity — surface the resolving guidance, plain-language, global-vs-project
type: fix
tier: local
status: completed
date: "2026-06-05"
goal_type: new_feature
description: >
  Make the dashboard's capability cards honest and human-legible. A `needs_setup`
  / `blocked` / `not_installed` capability card currently emits
  `dontpanic capabilities status <id>` (a read-only diagnostic) as its action,
  so an operator who runs it sees nothing change. Surface the RESOLVING guidance
  command (`dontpanic capabilities setup <id> --print-steps`, framed as "Show
  setup steps"), replace the raw `missing: …` token blob with the plain-language
  `setup_steps[].what` plus human-required reasons, and label the dashboard's
  "Global tools" (install-level capabilities) distinctly from "Tracked projects"
  (registry repos). Auto-execution of setup steps is explicitly OUT of scope.
motivation: >
  Dogfood (2026-06-05): the operator pasted the capability card's command and
  nothing happened, because `capabilities status` never resolves setup. The card
  says "setup incomplete" but offers a refresh/diagnostic command — the same
  render-truth/action-resolvability dishonesty the 001/004/005 chain exists to
  prevent, applied to `exact_command` choice. The plain-language guidance already
  exists (`capabilities setup <id> --print-steps` prints what/command/verify per
  step) — it is simply not surfaced on the card. Separately, the Health page
  conflates global tool setup with tracked projects, so "DontPanic isn't tracked"
  reads as a problem when capabilities are global and need no project at all.
agents_required:
  - claude
human_gates:
  - pre_impl
  - pre_merge
privacy_tier: internal
dependencies: []

links:
  features: ./features.json
  decisions: ./decisions.jsonl
---

# Capability card setup clarity

## Target

```yaml
target_env: dev
target_project: none
```

DontPanic-internal operator-console copy/wiring fix. No external service setup.

## Problem / Motivation

`operator_console.provide_capability_actions` correctly classifies `needs_setup` /
`blocked` as `operator_attested` (clears on evidence, not on a command) — but it
hardcodes `exact_command = "dontpanic capabilities status <id>"`, a read-only
diagnostic. The card's primary action therefore cannot resolve the card. The
operator who runs it sees no change. The `detail` is a raw `missing: linear-pp-cli,
~/.dontpanic/adapters/linear.json, …` token list — not legible to a human. And the
dashboard's Health/Capabilities surface does not distinguish install-level **global
tools** (claude-cli, discord, firebase, linear) from **tracked projects** (the
registry repos `dontpanic projects list` shows), so the two read as one concept.

The resolving guidance already exists and is honest about its own limits:
`dontpanic capabilities setup <id> --print-steps` prints per-step `what` / command /
verify and marks human-required steps; a bare `capabilities setup <id>` refuses
(exit 2) demanding `--print-steps` (plan) or `--automate-safe --confirm` (execute
allowlisted). So the correct card action is **"Show setup steps"** (guidance), not
"Repair" / "Fix".

## Proposed Approach

1. **Resolving command on the card.** For `needs_setup` / `blocked` / `not_installed`,
   set `exact_command = "dontpanic capabilities setup <id> --print-steps"` and a
   plain_consequence that says it PRINTS the setup steps (guidance), not that it
   fixes anything. Keep the existing `operator_attested` + `capability_ready`
   clears_when (resolution is still on evidence — a re-probe reporting ready).

2. **Plain-language detail.** Replace the `missing: <tokens>` blob with a short
   summary built from the capability manifest's `setup_steps[].what` plus the
   human-required reasons, so a non-technical operator can read what setup means
   and why a human is needed.

3. **Global-vs-project labelling.** On the dashboard, label install-level
   capabilities as "Global tools" and the registry repos as "Tracked projects" so
   they are visibly different concepts (a global tool needs no project; a missing
   tracked project is unrelated to capability setup).

## Scope (in)

- F001 Capability cards surface `capabilities setup <id> --print-steps` (framed
  "Show setup steps"), not `capabilities status`. Honest, guidance-only consequence.
- F002 Plain-language card detail from the manifest's setup steps + human-required
  reasons, replacing the raw `missing:` token blob.
- F003 Producer/data: capability items + exported state carry a `global_tool_setup`
  group label (the data seam; no rendering).
- F004 Dashboard rendering: Health / What Now displays "Global tools" separately
  from "Tracked projects" using the F003 label (depends_on F003).

## Scope (out)

- **Auto-executing setup steps.** `--print-steps` is GUIDANCE ONLY. NO
  `--automate-safe --confirm` wiring in this plan, and NO reuse of the
  2026-06-04-006 `--safe-derived-state` repair tier. Installing CLIs / registering
  adapters / touching credentials are NOT derived-state repairs; manifests are mixed
  (e.g. `agent-claude-cli.json`: `install_claude_cli` automatable, `authenticate_claude`
  human-credential). Any future setup automation is PER-STEP with explicit
  safety/tier metadata in a SEPARATE tier — a later, distinct plan, not this one.
- No new capability manifests; no changes to `capabilities setup` execution
  semantics. This plan changes what the card SURFACES, not what setup DOES.

## Acceptance

A `needs_setup` / `blocked` / `not_installed` capability card carries
`exact_command = "dontpanic capabilities setup <id> --print-steps"` and an honest
"shows the setup steps" consequence (never implying it auto-fixes). The card detail
reads as plain-language `setup_steps[].what` + human-required reasons rather than a
raw `missing:` token list. The dashboard visibly separates "Global tools" from
"Tracked projects". No capability is marked auto_safe and no setup step auto-runs.
Verified by producer-level tests (command + detail + class) and a dashboard render
test for the global/project labelling. Full orchestrate + dashboard sweeps stay green.
