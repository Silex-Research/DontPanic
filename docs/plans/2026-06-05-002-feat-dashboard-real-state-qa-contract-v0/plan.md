---
id: 2026-06-05-002-feat-dashboard-real-state-qa-contract-v0
title: QA sufficiency v0 — enter through the real surface (dashboard instance + cross-surface contract)
type: feat
tier: cross-cutting
status: active
date: "2026-06-05"
goal_type: new_feature
description: >
  The 2026-06-05-001 "Global tools" miss survived every gate because DontPanic's QA
  sufficiency model is artifact-completion oriented ("are there tests, do they pass?")
  not operator-outcome oriented ("do the tests enter through the surface the human
  actually uses?"). The dashboard suite validated render helpers against synthetic
  fixtures that pre-baked the asserted shape, so the producer→served-state→shell→
  scope→page-DOM chain was never exercised end to end. This is one instance of a
  general principle: a test must enter through the same surface the user / agent /
  external system uses. This plan (a) ships the dashboard concrete instance — make
  the shell testable, de-drift the harness, add a real-state→real-shell journey test;
  (b) codifies a SURFACE-AGNOSTIC sufficiency contract (surface classes + per-class
  "entering-surface" proof) so the principle covers web, web app, iOS, Android, CLI,
  backend/API, jobs, agent/MCP tools, integrations, infra; and (c) adds a declarative,
  ADVISORY plan-review gate that warns when a surface-claiming feature names no
  entering-surface test/evidence. Heavy per-surface automation is explicitly deferred.
motivation: >
  This is a QA-sufficiency gap in the PLATFORM, not just a dashboard bug — but the
  orchestrator had no policy requiring real-surface coverage, so it correctly ran the
  plan's tests + checked acceptance and still passed a feature whose human path was
  broken. The cure is to give DontPanic that policy. Crucially, DontPanic GOVERNS and
  does not execute most surfaces (it cannot run an iOS simulator, an Android emulator,
  or a project's browser suite in its own loop) — so the contract is enforced by
  requiring the plan to NAME the entering-surface proof, verified as a reference, with
  the project's own toolchain running it. v0 stays declarative + advisory; ship one
  concrete instance to prove the pattern, then expand on demand.
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

# QA sufficiency v0 — enter through the real surface

## Target

```yaml
target_env: dev
target_project: none
```

DontPanic-internal: the dashboard test harness, a producer↔fixture contract test, a
convention doc, and a declarative plan-review heuristic. No external services; no
production deploy. DontPanic does NOT run other projects' native UI tests — it
requires plans to reference them; the project toolchain executes them.

## Problem / Motivation

Verified gaps in the dashboard suite (the worked example):

- **No real-state→real-shell test.** `npm test` is Vitest-only; Playwright covers
  only the Architecture harness. Nothing loads produced `dashboard/state/*.json` into
  the real `core.js` shell and asserts the rendered page.
- **Stale loader copy.** `core-router.test.js` copies the Jarvis literal + its own
  `loadState()` subset instead of importing `createJarvis()` — loader drift invisible.
- **Nav list drift.** `core.js` registers `pageModules` (what-now, repair,
  mission-control, architecture, capabilities, …) as a PRIVATE const; the nav test
  re-declares a SMALLER list and certifies a UI omitting Repair/Architecture/
  Mission-Control. `createJarvis()` is exported; `pageModules` is not.
- **Shell drift.** `tests/helpers/setup.js` says `JARVIS` and omits the
  project-selector container in `index.html`.

Root cause: synthetic fixtures pre-bake the asserted shape, so the producer↔render
boundary is never proven. This is **surface-class: read-only UI**. The same failure
mode exists on every surface that has a producer/consumer or a real entry point.

## The general principle

> A feature's QA proof must ENTER THROUGH THE REAL SURFACE the user, agent, or
> external system uses — not only through isolated logic. The proof matches the
> CLAIM's surface (a visual/navigational/permission/workflow claim needs a real-UI
> journey; a CLI claim needs a real command invocation; a mutation claim needs a
> side-effect/idempotency/rollback test; etc.).

DontPanic enforces this as a **declared contract**: a plan declares its surface
class(es) and NAMES the entering-surface test/evidence; DontPanic verifies the
reference exists, the project toolchain runs it. DontPanic does not itself execute
simulators/emulators/browsers for other repos (governs ≠ executes).

> **Policy vocabulary, not an execution guarantee.** DontPanic requires plans to NAME
> entering-surface proof for surface-facing claims. DontPanic does not necessarily RUN
> that proof unless the project toolchain exposes it locally; absence of execution is
> advisory in v0, not a hard failure. This keeps the contract honest — especially for
> iOS/Android, where the proof runs in the app's own CI, not DontPanic's loop.

## Proposed Approach

**Tier A — dashboard concrete instance (read-only UI surface):**
1. Export `pageModules` + shell accessors from `core.js` (keystone).
2. De-drift: `core-router.test.js` imports `createJarvis()`/real loader; `setup.js`
   becomes the real shell DOM; nav test references exported `pageModules`.
3. Real-state→real-shell journey Vitest test driven by producer-generated state +
   a Python contract test guarding fixture faithfulness (anti-synthetic by build).

**Tier B — cross-surface contract (the generalization):**
4. The dashboard sufficiency contract (the read-only-UI instance).
5. The surface-agnostic sufficiency MODEL: surface classes + per-class required
   entering-surface proof + the governs-not-executes boundary, as a convention doc.
6. A declarative, ADVISORY plan-review gate: plan/feature declares `surface_class`;
   warn when a surface-claiming feature names no entering-surface proof.

## Scope (in)

- F001 Export `pageModules` + shell accessors from `core.js` (keystone, no behavior
  change).
- F002 De-drift the dashboard harness (router import, real shell DOM, nav list).
- F003 Real-state→real-shell journey Vitest test + Python fixture-contract test.
- F004 Dashboard QA sufficiency contract (the read-only-UI surface instance).
- F005 Surface-agnostic sufficiency MODEL (convention doc): surface classes
  (read-only UI / interactive UI / mobile app / command / agent-tool / mutation /
  external-integration / service-batch) + per-class required entering-surface proof +
  the "enter through the real surface" principle + the governs-not-executes boundary,
  incl. the iOS/Android rule (user-facing mobile change → name ≥1 simulator/emulator
  UI journey).
- F006 Declarative ADVISORY plan-review gate: a feature may declare `surface_class`;
  when a feature makes a surface-facing claim and names no entering-surface
  test/evidence, plan-review WARNS (never blocks in v0). Dashboard read-only-UI is the
  seeded, exercised instance.

## Scope (out) — deferred, demand-gated

- **Full browser Playwright matrix** (console-errors, mobile overflow, real clipboard,
  layout/overlap across every tab × viewport) — the eventual dashboard tier; do after
  this v0 proves the real-state harness. Trigger: first jsdom-invisible layout/console
  regression, or operator demand.
- **DontPanic-orchestrated runners for non-CLI surfaces** (iOS simulator, Android
  emulator, browser suites for other repos) — DontPanic requires the NAMED proof; the
  project toolchain runs it. Building those runners is each project's concern.
- **Per-surface example scaffolds** for non-dashboard surfaces (XCUITest/instrumented
  templates, API contract harness, etc.) — land as each project adopts the convention.
- **Visual-regression screenshots, responsive/a11y gates, BLOCK-severity promotion,
  auto surface-class inference, and a synthetic-provenance static analyzer** — all
  later tiers; v0 is declarative + advisory.

## Acceptance

`core.js` exports `pageModules`; `core-router.test.js` exercises the real loader;
`setup.js` is the real shell DOM; the nav test would FAIL if registered pages change.
A real-state→real-shell journey test (producer-generated state, Python-guarded
fixture) asserts the All-Projects → Needs Attention "Global tools (once)" + Health
"Global tools" path and demonstrably FAILS if the producer stops emitting the
global-tools group. A written surface-agnostic sufficiency contract exists (surface
classes + per-class entering-surface proof + governs-not-executes boundary + iOS/
Android rule), and plan-review emits an advisory warning when a surface-claiming
feature names no entering-surface proof, with no false positives on non-surface
features and no blocking. Verified by the dashboard vitest suite + orchestrate sweep
staying green and the heuristic's warn/quiet fixtures.
