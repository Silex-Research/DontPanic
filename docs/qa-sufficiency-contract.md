# QA Sufficiency Contract — enter through the real surface

> Plan 2026-06-05-002. This is the platform's answer to "are there tests?" → **"do
> these tests prove the human/agent/external system can accomplish the intended task
> through the real surface they actually use?"**

## The principle

A feature's QA proof must **enter through the real surface** the user, agent, or
external system uses — not only through isolated logic. The proof must **match the
claim's surface**: a visual / navigational / permission / workflow claim needs a
real-UI journey; a CLI claim needs a real command invocation; a mutation claim needs
a side-effect / idempotency / rollback test; and so on.

Synthetic, render-helper-only tests that pre-bake the asserted shape are **necessary
but not sufficient** for a surface-facing claim. The canonical failure (2026-06-05-001
"Global tools"): a JS render test hand-fed fleet state *with* capability items while
the produced `fleet-what-now.json` had *zero* — the producer↔render boundary was never
exercised, so the suite passed while the operator path was broken.

## Governs ≠ executes (policy vocabulary, not an execution guarantee)

DontPanic **governs**; it does not execute most surfaces. It can run a CLI or a
Node/jsdom test, but it cannot run an iOS simulator, an Android emulator, or another
repo's browser suite in its own loop. So the contract is enforced by requiring the
plan to **NAME the entering-surface test/evidence**; DontPanic verifies the reference
exists, and the **project's own toolchain runs it**.

DontPanic does not necessarily *run* that proof unless the project toolchain exposes
it locally; **absence of execution is advisory in v0**, not a hard failure. This keeps
the contract honest — especially for iOS/Android, where the proof runs in the app's
own CI, not DontPanic's loop.

## Surface classes and required entering-surface proof

| Surface class | Required "entering-surface" proof (named in the plan) |
|---|---|
| **read-only UI** | Real generated state → real shell → real route/scope → asserted page DOM (+ empty/populated states). |
| **interactive UI** | A real interaction (click / type / select / copy / submit) with a post-interaction state/DOM assertion. |
| **mobile app (iOS/Android)** | ≥1 simulator/emulator UI journey for the affected screen (navigation / permission / workflow / visual). NOT only ViewModel/unit tests. Runs in the app's CI. |
| **command (CLI)** | A real command invocation: exit code + stdout/stderr contract + JSON schema + bad-input behavior + no secret leakage. |
| **agent / MCP tool** | Tool-schema contract + read/write boundary + permission behavior + malformed input + agent-consumable output, from the tool entrypoint. |
| **mutation** | Side-effect boundary + idempotency + rollback/verification + permission gate. |
| **external integration** | Provider-shaped fixture parity + signed-request verification + replay/idempotency + failure recovery. |
| **service / batch** (backend/API, jobs, pipelines, infra) | Contract tests + auth/permission + error envelopes + dry-run/fixture replay + observability emitted + migration/rollback compatibility. |

**Proof matches the claim.** A change with no user-facing claim (e.g. a pure
ViewModel refactor) does not require a UI journey. The trigger is the *claim*, not the
implementation language.

## Dashboard (read-only UI) — the worked, shipped instance

The DontPanic local dashboard is the read-only-UI instance of this model, shipped in
plan 2026-06-05-002:

- **Real-state → real-shell journey test** is the entering-surface proof:
  `dashboard/tests/integration/dashboard-journey.test.js` loads producer-generated
  `state/*.json` into the real `createJarvis()` shell, selects All Projects, and
  asserts the operator path (Needs Attention shows "Global tools" once; Health labels
  install state "Global tools"). It FAILS if the producer stops emitting the
  `global_tool_setup` group (anti-synthetic by construction). A Python contract test
  (`test_dashboard_fixture_contract_f003`) guards fixture↔producer faithfulness.
- **No copied harnesses.** Nav/loader tests import the real shell symbols — the
  exported `pageModules` and `createJarvis()` — never a copied router or a
  re-declared page list (which had drifted, certifying a smaller UI than the operator
  saw). See `tests/integration/core-page-modules.test.js` and the de-drifted
  `core-router.test.js`.

A dashboard-facing feature that claims "shows / displays / renders / operator sees / copy"
requires a real-state → real-shell test, not render-helper-only coverage.

## Enforcement (v0)

A plan/feature may declare its surface class. Plan-review emits an **advisory
warning** when a feature makes a surface-facing claim but names no entering-surface
test/evidence. v0 is **declarative + advisory** — no auto surface-class inference, no
synthetic-provenance static analysis, and no BLOCK. Promotion to BLOCK, per-surface
runners, visual regression, and a11y gates are deferred, demand-gated.
