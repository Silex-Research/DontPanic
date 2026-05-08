# Plan 2026-05-03-003 close-out memo — Phase B (agent access manifest + thin MCP surface)

**Plan ID:** `2026-05-03-003-feat-agent-access-manifest-thin-mcp`
**Type:** `feat` · **Tier:** `cross-cutting` · **agents:** `claude` + `codex`
**goal_type:** none declared (exempt-by-absence from F2 completion gate)
**Status flip:** `active` → `completed` on 2026-05-07 (UTC).

This memo synthesizes across F001+F002+F003+F004 and connects the plan to the broader OpenClaw-repositioned roadmap. It does **not** re-cover the per-feature ship details, F002's volley triage, or the iteration-by-iteration finding analysis — those are authoritative in `evidence/f00{1,2,3,4}-closeout-memo.md` and decisions D010–D014.

## Cross-feature outcome

| Feature | Path | Result |
|---|---|---|
| F001 — Global agent manifest at `~/.dontpanic/agent-manifest.json` (versioned schema, install metadata, CLI path, supported commands, safety rules) with `~/.jarvis/` legacy read fallback | Direct (per D010) | `passes:true`. Pure discovery file; mechanical risk surface. |
| F002 — Thin local MCP server (`dontpanic mcp serve`): localhost / stdio, six tools (`list_projects \| validate_plan \| dispatch \| status \| approve_gate \| read_evidence`), no intake tool (D002) | **Volley** (per D010 — security-sensitive surface) | `passes:true`. Volley terminal `stopped_no_progress`; **operator-accepted on direct review** per D012 (i0 findings — HIGH traversal escape + 2 MEDIUM + 1 advisory — fixed in i1; remaining i1 `needs_changes` was environmental: auditor sandbox had no writable tempdir + stale i0 envelope inconsistency from the timeout pattern). |
| F003 — Discoverability docs (Claude Code / Cursor / OpenClaw / Codex usage examples, `mcp.json` snippet, publish-readiness checklist) | Direct (per D010) | `passes:true`. Docs-only; deterministic acceptance. |
| F004 — LLM-authored plan schema docs (existing plan-directory contract, minimum valid plan, sufficiency-vs-implementation boundary) | Direct (per D010) | `passes:true`. Authoring guidance; explicitly NOT the Phase C intake engine. |

The four features together deliver the calling pattern named in the OpenClaw-repositioned roadmap: a global manifest (find DontPanic), a thin MCP surface (call DontPanic), discoverability docs (per-runtime usage), and schema docs (LLMs can author plans the platform accepts). Phase B is the smallest slice that makes DontPanic callable by ecosystem agents without per-vendor integration code.

## Cross-plan pattern: `stopped_no_progress` operator-accepted (twice now)

This is the second consecutive plan whose volley feature ended `stopped_no_progress` and was operator-accepted on direct review:

| Plan | Feature | Volley terminal | Root cause | Acceptance basis |
|---|---|---|---|---|
| 2026-05-03-001 (Phase A) | F003 — per-project config + override precedence | `stopped_no_progress` after 2 rounds | 600s subprocess deadline killed envelope flush; implementation landed clean on disk | D009 — work verifiable from on-disk state, not envelope; 6-area diff review |
| **2026-05-03-003 (this plan)** | F002 — thin local MCP server | `stopped_no_progress` after 2 rounds | i0 had real findings (fixed in i1); i1 `needs_changes` was environmental (auditor sandbox tempdir + stale-envelope inconsistency from i0's timeout) | D012 — substantive findings fixed; i1 noise is not feature-defect; direct-review verification (130/130 F001+F002 tests green; 825/6 orchestrate; ruff/sanitization clean) |

Both close-outs cite each other in their D-records. Both root causes were captured as queued platform improvements. The pattern names a real platform shape worth tracking: the existing volley contract treats `stopped_no_progress` as terminal even when the underlying defect is environmental noise, not feature regression. Whether to harden the breaker (e.g., distinguish "no_progress with feature-defect findings" from "no_progress with envelope/sandbox findings") is a separate platform discussion — not scoped here.

## Cross-link to follow-up platform slices

| Caveat raised in this plan | Follow-up plan | Status |
|---|---|---|
| F001/D011 — EC5 classifier purity regression in `test_ec5_classifier.py` | `docs/plans/2026-05-04-004-fix-ec5-classifier-purity/` | F001 `passes:true`; in this Tier 1/3 close-ready batch |
| F002/D012 — i0 600s timeout-derived envelope truncation (same root cause as Phase A's F003 caveat #2) | `docs/plans/2026-05-04-003-fix-subprocess-timeout-envelope-durability/` | 3/3 features `passes:true`; close-ready |
| F002/D012 — i1 auditor sandbox tempdir absence (sandboxed read-only environment had no usable `TMPDIR`) | Captured in `feedback_orchestrator_dogfood_lessons.md` (memory) as the auditor read-only sandbox tempfile constraint; no scoped follow-up plan currently — manifests as advisory at audit time, not blocker |

The `stopped_no_progress` breaker semantics question (above) does not currently have a scoped follow-up plan; it would be its own platform slice if/when the breaker harms more than it helps in practice.

## Brand state — this plan is DontPanic-native from day zero

Unlike Plan 2026-05-03-001 (Phase A) which was authored pre-rename and references `~/.jarvis/`, this plan was authored with the canonical `~/.dontpanic/` paths from the start. F001's manifest file is `~/.dontpanic/agent-manifest.json`; the MCP server in F002 is `dontpanic mcp serve`; the docs in F003/F004 reference canonical surfaces throughout. The legacy `~/.jarvis/agent-manifest.json` is wired only as a **read fallback** in F001's manifest reader (per F001 acceptance), so existing operator setups don't break — but writes always target the canonical location.

This is the first plan where the brand is correct from the in-plan text outward; no post-rename translation needed for future readers.

## INBOX.md hygiene resolution

`INBOX.md` was untracked in the worktree (the supervisor wrote it during the F002 volley on 2026-05-04 but it never made it into git). Plan 2026-05-03-001's INBOX was tracked; the inconsistency was a hygiene gap, not a content concern — the file is normal supervisor event log content (gate_cleared events + the volley_terminal record). Picked up under git tracking with this close-out commit, so the plan-dir state is consistent with the previously-closed Phase A plan.

This is the inverse failure mode of Plan 2026-05-02-003's "tracked-but-absent decisions.jsonl" (partial-clone fallout): here the file exists but was never tracked. Both fail the eight-step `git ls-tree` discipline at step 1 if not checked. Combining the two checks: `(HEAD - worktree)` for absences, `(worktree - HEAD)` for untracked artifacts.

## Phase A → Phase B → arc state

| Phase | What it delivers | Status |
|---|---|---|
| Phase A — global install + project registry + doctor | Plan 2026-05-03-001 | Closed at `cb6d3cc` |
| **Phase B — agent manifest + MCP + docs (this plan)** | Plan 2026-05-03-003 | **Closed in this commit** |
| Phase C — intake pipeline (`dontpanic intake`, MCP intake tool) | Not drafted | Demand-driven (per nested-orch v1 D012 substrate-vs-layer discipline). MCP intake tool **explicitly excluded from F002 surface per D002** — exposing intake before Phase C designs the contract would lock in a shape we have not designed yet. |
| Phase D — agent runtime adapters / non-CLI surfaces | Not drafted | Demand-driven. |

Phase B's deliberate non-goals (per `docs/ECOSYSTEM.md`): no daemon, no chat surface, no hosted control plane, no remote MCP, no plugin marketplace. The caller's runtime owns those concerns. Future phases inherit those non-goals unless explicitly revisited.

## Outer plan close — exempt-flow path

```
$ dontpanic plan close docs/plans/2026-05-03-003-feat-agent-access-manifest-thin-mcp/
[plan close] goal_type=None is exempt from the F2 completion gate;
             status flipped active → completed without audit
```

Same exempt-flow path as the prior three Tier 1 close-outs (`2026-05-04-001`, `2026-05-02-003`, `2026-05-03-001`).

## Sign-off

Plan 2026-05-03-003 ships clean. F001+F002+F003+F004 all `passes:true`. The agent-access surface is in production: global manifest, thin MCP server with security-defaulted tool surface, discoverability docs, LLM-authored plan schema docs. F002's volley produced two findings (one HIGH security, two MEDIUM, one advisory) that were fixed in i1; the `stopped_no_progress` terminal was environmental noise, not a feature defect. Phase C/D remain demand-driven. The F002 stopped-no-progress + Phase A F003 stopped-no-progress pattern is a platform-shape signal worth tracking, not a current scope.

— bayesian, 2026-05-07 UTC
