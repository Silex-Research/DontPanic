# Plan 2026-05-03-001 close-out memo — Phase A (global install + project registry + doctor integration)

**Plan ID:** `2026-05-03-001-feat-global-install-project-registry`
**Type:** `feat` · **Tier:** `cross-cutting` · **agents:** `claude` + `codex`
**goal_type:** none declared (exempt-by-absence from F2 completion gate)
**Status flip:** `active` → `completed` on 2026-05-07 (UTC).

This memo synthesizes across F001+F002+F003 and connects the plan to the broader service-mode arc. It does **not** re-cover the per-feature ship details, F003's volley-terminal acceptance reasoning, the 6-area diff review, or the 4 caveats — those are authoritative in `evidence/f001-closeout-memo.md`, `evidence/f002-closeout-memo.md`, `evidence/f003-closeout-memo.md`, and decision D009.

## Cross-feature outcome

| Feature | Path | Result |
|---|---|---|
| F001 — pipx-installable + `jarvis` console script + global config | Direct (operator-authorized at lock) | `passes:true`. Packaging/bootstrap slice; deterministic. |
| F002 — `jarvis projects add\|list\|show\|remove` against `~/.jarvis/projects.json` | Direct | `passes:true`. CRUD slice; no supervisor wiring. |
| F003 — per-project `<repo>/.jarvis/jarvis.json` + override precedence + `jarvis doctor` per-project preflight + plans_dir resolution | **Volley** (claude implementer + codex auditor, max_iter=2) | `passes:true`. Volley terminal `stopped_no_progress`; **operator-accepted on direct review** per D009 — work landed clean on disk (43-test F003 suite green, 702 total passed/6 skipped, ruff/sanitization clean), only the audit envelopes blocked from flushing due to the 600s subprocess deadline. Acceptance contract independently verifiable from on-disk state. |

Phase A's three features establish the access layer: install path, multi-project registry, per-project config + preflight. Together they make `jarvis dispatch <plan>` from any registered project routine, replacing PYTHONPATH-prefixed incantations from inside the source tree.

## Phase A → service-mode arc

Phase A is the foundation; Phases B/C/D are **not drafted** and remain demand-driven (per D012 of Plan 2026-05-02-003 nested-orch v1, applied generally as substrate-vs-layer discipline):

- **Phase B — `jarvis init`** scaffolding for a fresh project. Trigger: someone wants to onboard a project and finds the manual `mkdir .jarvis && cat > jarvis.json` step painful enough to draft this.
- **Phase C — intake pipeline** (the "draft a plan from a markdown brief" surface). Trigger: a real plan-from-external-input flow that exposes the gap.
- **Phase D — MCP server** for non-CLI agent surfaces. Trigger: a real agent integration that needs it.

The historical service-mode design memo (`project_jarvis_service_mode.md` in Claude memory) catalogued a 5-plan slicing of the broader arc; Phase A subsumed slices 1 + 2 (workspace-registry + workspace-aware-dispatch) under a simpler framing. The remaining authority/intake/events.jsonl content in that memo is design scaffolding for a future Phase C, **not** current direction. The memo is marked SUPERSEDED accordingly.

## Cross-link to follow-up platform slices

F003's caveats (in D009 + the F003 memo) named two platform improvements that became their own scoped plans rather than expansions of F003:

| Caveat from F003 | Follow-up plan | Status |
|---|---|---|
| Caveat 1 — `pre_merge` is upfront admission, not lifecycle gate | `docs/plans/2026-05-04-002-fix-supervisor-lifecycle-staged-gates/` | F001 `passes:true`; awaiting close-out (validation-debt repair queued — legacy `evidence_refs` shape) |
| Caveat 2 — 600s subprocess timeout too short; envelope flush race on timeout | `docs/plans/2026-05-04-003-fix-...subprocess-timeout-envelope-durability/` | 3/3 features `passes:true`; close-ready in this same Tier 3 batch |

Both plans were drafted post-Phase A, anchored on the canonical-module name from day zero (per Plan 2026-05-04-001's lead-slice framing). Caveats 3 + 4 from F003 (the `_resolve_plan_dir` Step-4 cwd carveout + approve/resume not wired through resolver) are documented-and-bounded; no follow-up plan currently scheduled.

## Brand-rename note (read this section before extrapolating from text in this plan dir)

Plan 2026-05-03-001 was authored, locked, and shipped **before** the canonical-module rename (`jarvis_orchestrate` → `dontpanic_orchestrate`, Plan 2026-05-04-001 ship `8edd953`). Therefore:

- **In-plan text** (plan.md, features.json, F-memos, decisions) references `~/.jarvis/`, `jarvis projects`, `jarvis doctor`, etc. These are durable historical records and were intentionally NOT renamed (per the canonical-module-flip plan's D004 boundary).
- **Current canonical CLI surfaces** are `dontpanic projects`, `dontpanic doctor`, etc., backed by `dontpanic_orchestrate/*` (the canonical Python module) plus a thin `jarvis_orchestrate` shim that emits a one-shot `DeprecationWarning` per process and re-exports from canonical.
- **Global config dir** is `~/.dontpanic/` canonically; `~/.jarvis/` remains a legacy fallback for `dontpanic_home()` resolution.

Future readers inspecting this plan should mentally translate `jarvis*` → `dontpanic*` for live tooling; the on-disk per-project file `<repo>/.jarvis/jarvis.json` likewise has a current canonical name `<repo>/.dontpanic/dontpanic.json`, with the legacy filename still readable.

## Audit envelope status

The orchestration artifacts are preserved verbatim under `audit/`:
- `claude-implementer-F003-i0.json` + `i1.json` — both `audit_status: blocked`, `summary: DISPATCH FAILED: TimeoutExpired` (600s deadline)
- `codex-auditor-F003-i0.json` + `i1.json` — both `verdict: needs_changes`, correctly flagging the broken implementer envelopes as not valid completion artifacts
- `signoff-...-F003.json` — `signoff: false`, `signoff_reason: "auditor verdict unchanged (needs_changes) across 2 consecutive rounds"`, `next_action: remediate`
- `transcript.md` + `gate-state.json` — full volley trace + final gate state

Per D009 the volley work was operator-accepted despite the non-success terminal because the *implementation* was correct (the envelope blocking was a platform timing race, not a correctness defect). The audit JSONs validate cleanly against agent-conventions schemas — they're a faithful record of the volley as it ran, not amended retroactively.

## Outer plan close — exempt-flow path

```
$ dontpanic plan close docs/plans/2026-05-03-001-feat-global-install-project-registry/
[plan close] goal_type=None is exempt from the F2 completion gate;
             status flipped active → completed without audit
```

`goal_type` is undeclared (not classified as goal-governance work), so the F2 completion gate is a no-op. Same exempt path as the prior two close-outs in this Tier 1 batch (Plan 2026-05-04-001 canonical-module flip, Plan 2026-05-02-003 nested-orch v1).

## Sign-off

Plan 2026-05-03-001 ships clean. F001 + F002 + F003 all `passes:true`. The access layer is in production: pipx-installable global binary, project registry CRUD, per-project config with override precedence, doctor preflight integration. F003's audit envelopes captured a real-world test of two platform weaknesses (gate semantics + subprocess timeout) that became their own follow-up plans. Phase B/C/D remain demand-driven.

— bayesian, 2026-05-07 UTC
