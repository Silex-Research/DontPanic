---
id: 2026-06-06-002-feat-governed-gui-action-channel-v1
title: Governed GUI action channel v1 — make the operator console an executor, safely
type: feat
tier: cross-cutting
status: draft
date: "2026-06-06"
goal_type: new_feature
description: >
  The operator-console workbench (plan 2026-06-06-001) is read-only: it triages, inspects,
  and HANDS OFF exact commands, but originates no mutation. This plan adds the deferred
  capability — letting the human approve/request/reject a gate and apply the safe tier
  directly from the browser — which turns the console from a projection + handoff surface
  into an EXECUTOR. That is a new trust boundary, so it gets its own threat model: a local
  action backend with auth, origin restriction, CSRF protection, and a command allowlist
  bound to operator_bucket actions; confirmation semantics and atomic evidence on every
  mutation; and integrity under failure (replay/idempotency, audit-log integrity, stale-tab
  handling). Gated on demand — only worth building once the read-only workbench proves the
  copy/handoff loop is too slow in practice.
links:
  objective_contract: ./objective_contract.json
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
---

# Governed GUI action channel v1

## Why this is a separate plan (from 2026-06-06-001 D018)
A console button that runs `dontpanic approve` or `triage apply --confirm` through a local
backend converts the dashboard from read-only into an executor. The DontPanic dashboard was
deliberately read-only so it could not be tricked into running things. Re-opening that needs
a real threat model, not a feature bullet — so v0 ships copy/handoff and this plan owns the
execution boundary.

## Threat model (the spine)
Every feature here exists to neutralize one risk of a browser-driven local executor:
- **Unauthorized invocation** — a malicious page / another local process hitting the action
  endpoint → local-server auth token + origin restriction + CSRF protection.
- **Scope creep** — the channel becoming a general shell → a command allowlist bound to the
  exact `operator_bucket` actions (approve/request/reject for a named gate; `triage apply
  --safe` for `auto_safe` only); never arbitrary commands.
- **Partial/duplicate mutation** — a click that half-applies or double-applies → confirmation
  semantics + idempotency keys + atomic evidence (the action and its evidence record commit
  together or not at all).
- **Tampered history** — an action that does not show up, or a forged one → audit-log
  integrity (append-only, hash-chained or equivalent).
- **Stale tab** — a browser showing old triage acting on a moved-on world → staleness check
  (the action carries the model fingerprint it was issued against; the backend refuses if the
  world moved).

## Demand gate
Do NOT build until the 2026-06-06-001 read-only workbench is in use and the copy/handoff loop
is demonstrably the friction. This plan is the planned next increment, not an immediate one.

## Phases -> features
1. **Channel + threat model.** F001 local action backend (auth/origin/CSRF/allowlist).
2. **Governed mutations.** F002 browser-originated gate decision; F003 browser-originated
   safe-tier apply (drives the 2026-06-06-001 F005 engine).
3. **Integrity.** F004 idempotency + atomic evidence + audit-log integrity + stale-tab refusal.

## Target

```yaml
target_env: dev
target_project: none
```
