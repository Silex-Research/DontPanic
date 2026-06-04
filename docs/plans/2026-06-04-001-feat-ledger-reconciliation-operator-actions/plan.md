---
id: 2026-06-04-001-feat-ledger-reconciliation-operator-actions
title: Ledger reconciliation + operator-action closeouts
type: feat
tier: cross-cutting
status: draft
date: "2026-06-04"
goal_type: new_feature
description: >
  Detect plans whose capability already exists in production but whose ledger
  is still open (shipped-but-unclosed), and surface operator-friendly closeout
  decisions as dashboard ActionItems instead of leaving them as phantom backlog.
  Enforces the organizing principle: plans define capabilities (missing code →
  feature); credentials/deploys/smokes/role-or-budget choices/human approval →
  operator ActionItems, never modelled as implementation features.
motivation: >
  Auditing open plans against main on 2026-06-04 found the "open" set was a mix
  of shipped-but-unclosed (changelog skill, firebase Cloud Functions),
  operator-gated, superseded-cleanup, and conditional integrations — not a
  feature backlog. The harness let deliverables ship without flipping passes,
  so they read as work remaining. This plan makes that drift detectable and
  closeout operator-friendly, so the ledger reflects production truth.
agents_required:
  - claude
human_gates:
  - pre_impl
  - pre_merge
privacy_tier: internal

links:
  features: ./features.json
  decisions: ./decisions.jsonl
---

# Ledger reconciliation + operator-action closeouts

## Target

```yaml
target_env: dev
target_project: none
```

DontPanic-internal orchestration-engine plan. No external service setup required.

## Problem / Motivation

The plan ledger drifts from production: deliverables ship (code + tests on
`main`) without the plan's `status`/`features.passes` being flipped, so completed
capabilities read as open backlog. Separately, plans model operator-owned steps
(deploy, credentials, smoke, approval) as implementation features, which can never
"pass" through an agent volley. Both failures were observed in the 2026-06-04 audit.

## Proposed Approach

A read-only **drift detector** that flags "production evidence exists but plan is
still open," plus a set of **closeout ActionItems** (close-completed /
close-superseded / needs-deploy / needs-smoke / create-child-plan) rendered on the
dashboard with exact commands, plain consequence, reversibility, and automatic
evidence capture. No new governance primitive — it composes the shipped ActionItem
+ operator-console + `close --operator-resolved` surfaces.

## Scope (in)

- F001 Drift detector (read-only): correlate referenced files/commits + test
  signals against plan status/passes; emit a ranked list of suspected
  shipped-but-unclosed / operator-gated / superseded plans.
- F002 Closeout ActionItems: one ActionItem per drifted plan with a closeout
  disposition menu, exact `dontpanic` command, `plain_consequence`, `reversible`,
  and evidence-ref capture.
- F003 Operator-friendly closeout wiring: auto-attach the detector's evidence refs
  into the existing `close --operator-resolved` path; no agent dispatch required.

## Scope (out)

- Re-litigating any individual plan's design (handled per-plan).
- Building a new close primitive (reuse `close --operator-resolved`).
- Auto-closing without operator confirmation (always operator-gated).

## Acceptance

Detector flags the known drift cases (e.g. shipped-but-unclosed skills, deployed-
but-unflipped code) with zero false "all clear"; each flagged plan yields an
ActionItem carrying exact command + consequence + reversibility + evidence; the
operator closeout records status + evidence_refs + a decisions entry with no agent
dispatch. Full orchestrate sweep stays green.
