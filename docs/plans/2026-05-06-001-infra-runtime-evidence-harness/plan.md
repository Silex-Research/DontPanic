---
id: 2026-05-06-001-infra-runtime-evidence-harness
title: Plan G — Runtime evidence harness (Goal Governance V1 prerequisites for F2)
type: infra
tier: cross-cutting
status: active
date: "2026-05-06"
goal_type: infra
agents_required:
  - claude
  - codex
human_gates:
  - pre_impl
  - pre_merge
dependencies:
  - 2026-05-05-002-feat-goal-governance-nested-orchestration-config
  - 2026-05-05-003-feat-objective-contract-and-sufficiency-audit
description: |
  **Plan G of the Goal Governance V1 sequence** (per
  `docs/GOAL_GOVERNANCE_V1.md` §9). Capture-only runtime evidence
  prerequisites for F2's post-impl completion-test auditor. Does
  **not** ship F2; provides the harness F2 will consume.

  Five features split along independent source surfaces + one
  integrating harness layer (D003):

  - **G1 (F001)** — Web runtime evidence capture (Playwright-default
    driver, swap seam): screenshot, DOM snapshot, console errors,
    network failures, optional trace/video. Base URL operator-supplied.
  - **G2 (F002)** — iOS evidence capture: `xcrun simctl` driven
    screenshots + simulator log + crash reports. Graceful skip with
    recorded reason when no simulator runtime is available.
  - **G3 (F003)** — Android evidence capture, capture-only (D009).
    Two modes: passive-observe (`adb screencap`/`logcat`/tombstones/
    ANR against an existing device/session) and post-hoc-ingest
    (consume artifacts from existing Gradle/Espresso/Maestro/CI
    output). DontPanic does NOT own Android test orchestration in v1.
  - **G4 (F004)** — Backend observability capture, provider-adapter
    based (D010). Firebase ships first (reuses F022 SA, no new
    credential storage); Supabase as provider slot + fixture tests
    only (no live auth in v1); Generic HTTP/log-file/JSONL fallback
    with operator-supplied runtime credentials. No Firebase-specific
    assumptions in the common harness.
  - **G5 (F005)** — Common harness: `EvidenceCollector.collect(
    journey, context, sources=[...]) -> list[EvidenceRef]` composes
    G1+G2+G3+G4 adapters behind one interface; pure orchestration,
    zero source-specific logic in the core. Writes uniform artifacts
    to `evidence/goal-governance/post_impl/<source>/<journey-id>/
    <artifact>` (D003).

  G1–G4 are independent and can ship in any order; G5 lands last.
  Six commits total (4 capture + 1 harness + 1 plan-level close-out).

  **F2 is BLOCKED until G closes** (D001). The only legitimate bypass
  is a reduced-evidence D-entry recorded in F2's plan dir naming
  exactly which sources are deferred and why (D008).

  **Scope discipline (D002):** G is *capture only*, not *audit*.
  Adapters write structured `EvidenceRef` artifacts; F2 (later) reads
  them and runs completion-test logic. Any temptation to add
  assertion/scoring/journey-walk semantics here belongs in F2.

  **Project-agnostic invariant (D004, inherited from F1's D013):**
  adapters are generic. No `spin_dine_*`, `glam_*`, `creator_hub_*`
  special cases. Project-specific config (which Firebase project,
  which simulator device, which Playwright base URL, which adb
  device serial) lives in operator-edited config files, NOT in
  adapter code.

  **No new credential storage (D005):** Firebase reuses F022 SA;
  Supabase/generic adapters accept operator-supplied runtime
  credentials only.

  **Schema discipline (D007):** EvidenceRef in agent-conventions
  v1.4.0 already covers all G adapter outputs (screenshot / log /
  test_output / file / url Type values). No v1.5.0 schema bump
  needed; Plan G is single-repo (DontPanic only).

  **Library-only in v1 (locked at lock turn):** G is consumed by F2
  in-process. MCP tool wrap is a follow-up plan once the harness
  shape is stable and useful.

  **Cross-vendor dogfood dispatcher (D006):** queued as a separate
  follow-up plan, NOT in G's scope. G is capture-only; the
  cross-vendor invariant is an audit-time concern that engages when
  F2 ships.

  **Feature ID ↔ roadmap ID convention (D011):** features.json uses
  F001–F005 per agent-conventions schema. Prose may refer to G1–G5
  for roadmap clarity. Both naming surfaces are correct.

motivation: |
  Without runtime evidence capture, F2's post-impl completion-test
  auditor would be a paper-only review pattern-matching contract
  prose against features.json — exactly the failure mode F1 was
  built to prevent at pre-impl time. Plan G gives F2 a uniform
  EvidenceRef surface to walk against the contract's
  required_evidence list, anchoring the post-impl audit on real
  artifacts (screenshots, logs, traces) rather than text inspection.

  Spin & Dine surfaced as a motivating example during F1 dogfood:
  F2 needs Android coverage to produce useful audits for plans like
  Spin & Dine v2 Android parity. G3 (Android) is therefore not
  optional in v1 — bolting it on later would leave F2 producing
  `runtime_evidence_level: limited` for a major class of plans.

  The decomposition into 5 features (web / iOS / android / backend /
  harness) preserves the project-agnostic invariant: each adapter is
  a generic capture surface, the harness composes them without
  source-specific logic, and per-project configuration stays
  external. F2 then consumes the same harness for any plan
  regardless of which surfaces its journeys touch.
---

# Plan G — Runtime evidence harness

The capture-only prerequisites layer for F2 (Goal Governance V1
post-impl completion-test auditor). Five features, library-only in
v1, single-repo (no agent-conventions schema bump needed).

See `evidence/plan-g-closeout-memo.md` (written at plan-level
close-out) for the cumulative summary across G1–G5.

## Feature roadmap → schema feature ID map (D011)

| Roadmap ID | features.json ID | Surface |
|------------|------------------|---------|
| G1 | F001 | Web |
| G2 | F002 | iOS |
| G3 | F003 | Android |
| G4 | F004 | Backend |
| G5 | F005 | Common harness |

## Boundaries

- **D001:** F2 blocked until G closes (or reduced-evidence D-entry).
- **D002:** capture only, not audit.
- **D003:** evidence path `evidence/goal-governance/post_impl/<source>/<journey-id>/<artifact>`.
- **D004:** project-agnostic invariant inherited from F1 D013.
- **D005:** no new credential storage in Plan G.
- **D006:** cross-vendor dogfood dispatcher queued as follow-up.
- **D007:** EvidenceRef holds; single-repo.
- **D008:** reduced-evidence override is recorded in F2's plan dir, not G's.
- **D009:** Android v1 is capture-only; no test orchestration.
- **D010:** Backend is provider-adapter based; no Firebase-specific assumptions in the harness.
- **D011:** F001–F005 schema IDs ↔ G1–G5 roadmap names.
