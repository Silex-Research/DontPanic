---
id: 2026-04-25-002-infra-trivial-orchestration-test
title: Trivial test plan for F004 supervisor dispatch
type: infra
tier: trivial
status: active
date: "2026-04-25"
description: Smoke test for parent F004 — supervisor dispatches Claude on a no-op feature and produces a valid audit JSON.
agents_required:
  - claude
loop_caps:
  max_iterations: 1
  hard_stop: false
privacy_tier: internal
links:
  features: ./features.json
  audits_dir: ./audit/
---

# Trivial test plan for F004

Used as the dispatch target for `python -m jarvis_orchestrate`. The "implementation" is a single sentence the dispatched Claude must reply with — supervisor wraps it into an audit JSON that validates against `agent-conventions/schemas/v1.0/audit.schema.json`.

## Purpose

Prove the orchestration pipe end-to-end: supervisor → Claude CLI → audit JSON → schema-valid file in `audit/`.
