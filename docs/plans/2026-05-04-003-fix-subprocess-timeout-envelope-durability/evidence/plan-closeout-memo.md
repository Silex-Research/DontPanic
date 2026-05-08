# Plan 2026-05-04-003 close-out memo — subprocess timeout handling and envelope diagnosability

**Plan ID:** `2026-05-04-003-fix-subprocess-timeout-envelope-durability`
**Type:** `fix` · **Tier:** `cross-cutting` · **agents:** `claude` + `codex`
**goal_type:** none declared (exempt-by-absence from F2 completion gate)
**Status flip:** `active` → `completed` on 2026-05-07 (UTC).

This memo synthesizes across F001 (executor), F002 (envelope persistence), and F003 (downstream classifier) — three distinct layers solving three distinct slices of the timeout-envelope-durability problem. Per-feature memos in `evidence/f00{1,2,3}-closeout-memo.md` are byte-untouched; this memo adds the cross-feature view + Q2 classification + timeout-Q answer.

## What this plan deliberately does NOT claim

Per operator framing constraints at close-out, this plan is **narrowly scoped** to timeout-envelope durability. It does NOT claim:

- ❌ "Subprocesses no longer time out." — They still do. F001's contribution is process-group cleanup, not deadline elimination. The 600s wall remains (D003 — `loop_caps.subprocess_timeout_seconds` per-plan deferred).
- ❌ "Timeout artifacts prove product failure." — The `correctness/medium` finding (F002 `_timeout_finding()`) reports an audit-completeness gap (`timed_out=true AND worktree_changed=true`), not an implementation defect. It says *"we couldn't fully verify what landed"*, not *"the implementer wrote bad code."*
- ❌ "All env timeouts are now classified correctly." — F003's classifier handles the `timeout_with_work` shape only. Other timeout shapes (`timeout_no_work`, `timed_out=true AND worktree_changed=unknown`, etc.) keep their existing classification semantics.

## The three-tier separation

The operator's timeout-Q named exactly this distinction: *"distinguish executor failure, audit envelope persistence, and downstream signoff interpretation."* Each feature lives in one tier and is independently revertable.

| Tier | Feature | Module | What it does | What it does NOT do |
|---|---|---|---|---|
| 1. Executor | F001 (direct) | `scripts/dontpanic_orchestrate/subprocess_runner.py` | `Popen(start_new_session=True)` + `os.killpg(SIGTERM)` → grace → `os.killpg(SIGKILL)` per D005. Returns structured `SubprocessResult` with `timed_out`, `worktree_changed` (optional, per D006), partial stdout/stderr. | Eliminate timeouts. Set per-plan deadlines (deferred to schema-bumped `loop_caps.subprocess_timeout_seconds`). Recover internal tool history (D001 — Claude's one-final-blob output makes per-tool checkpointing impossible cross-agent). |
| 2. Envelope persistence | F002 (direct) | `scripts/dontpanic_orchestrate/audit_writer.py` (`_layer_timeout_evidence`, `_timeout_markers`, `_timeout_finding`, `_timeout_sidecars`) | Layers timeout evidence within the existing schema-locked envelope: structured timeout block in `summary`, markers in `validation_performed`, sidecars under `audit/partials/`, structured `correctness/medium` finding **only** when `timed_out=true AND worktree_changed=true` (never false-positive per D007). Non-timeout runs are byte-stable. | Add new top-level envelope fields (`additionalProperties: false`). Add a new `audit_status` enum value (`blocked` is preserved per D002). Inline partial stdout/stderr in audit JSON (sidecars only, per D004). Mutate `target_context` or accountability metadata (preserved unchanged). |
| 3. Downstream classifier | F003 (volley → Path 1) | `scripts/dontpanic_orchestrate/circuit_breakers.py` (`_envelope_is_timeout_with_work`), `supervisor.py` | Excludes timeout-with-work envelopes from no_progress + diminishing_returns counting; doesn't advance `prior_aud_status` for skipped rounds; transcript notes via `transcript.append_note()`. 39 focused tests across the matrix. | Change thresholds. Change defaults. Change `audit_status` enum. Move signoff interpretation outside the verdict-based `check_no_progress` shape that the count-based Plan 2026-05-02-004 fix doesn't apply to. |

## Q2 — F003 volley terminal classification

F003's volley terminated `stopped_no_progress` (verdict-based — `auditor verdict unchanged (needs_changes) across 2 consecutive rounds`). This is the **verdict-based** breaker (`check_no_progress`), not the **count-based** breaker (`check_diminishing_returns`) that Plan 2026-05-02-004 (closed `5a0979b`) reclassifies. They are adjacent failure modes, not the same one — the same distinction noted in Plan 2026-05-04-004's MAY/MUST-NOT memo and Plan 2026-05-01-001's three-layer terminal table.

| Layer | What it is | Classification |
|---|---|---|
| Volley terminal | `stopped_no_progress` after 2 same-verdict rounds | Platform artifact (verdict-based; `check_no_progress` hardening remains a separate queued discussion — not solved here, not solved by 2026-05-02-004) |
| F003 implementation | 39 focused timeout-with-work classifier tests + Path 1 manual remediation of 4 volley findings (3 substantive + 1 test-coverage) | **Implementation result — clean.** All 4 findings resolved per F003 memo's Finding Disposition table. |
| Implementer i0 timeout | Itself a timeout-with-work envelope (this plan IS the fix; F003 was always going to dogfood under the old classifier) | Already-known/platform per F003 memo Finding Disposition |

The volley dogfooded F003 under the OLD classifier (since merged), exactly as designed. The closure of this plan retroactively makes future volleys' timeout-with-work envelopes diagnosable in the way F003 specifies.

## Cross-link to closed plans depending on this work

Q1 sweep this turn shows 4 closed-plan citers — all Tier 1 / Tier 2/3 plans referencing THIS plan as their timeout-caveat owner:

| Citing plan (status) | Citation context |
|---|---|
| `2026-05-03-001-feat-global-install-project-registry` (closed `cb6d3cc`) | Phase A F003 D009 + plan-closeout-memo: 600s timeout-derived envelope blocking — caveat #2; this plan's F001+F002 are the structural fix |
| `2026-05-03-003-feat-agent-access-manifest-thin-mcp` (closed `7ca7a23`) | Phase B F002 plan-closeout-memo's "Cross-link to follow-up platform slices" table: 600s timeout-derived envelope truncation; this plan ships 3/3 |
| `2026-05-04-004-fix-ec5-classifier-purity` (closed `271870c`) | EC5-purity decisions reference this plan as the parent sequence's Plan C |
| `2026-05-05-001-fix-plan-validator-audit-auxiliary-json` (closed `03cc0b9`) | Plan E decisions D008 enumerate this plan dir among the gate-state.json regression-coverage fixtures |

All citers are already closed; closing this plan does NOT supersede any active-plan narrative. It updates the cited-from-closed-memos status of "queued follow-up" → "closed", which is narrative coherence, not a wording dependency.

## Brand-rename note (no drift)

Unlike Plans 2026-05-01-001 (onboarding-ux), 2026-05-01-005 (target-context-platform-fix), or 2026-05-02-001 (resume-gate-discipline) — all of which were authored pre-rename and reference legacy `jarvis_orchestrate` invocation forms — this plan was authored 2026-05-04, **after** the canonical-module flip shipped at `8edd953` (Plan 2026-05-04-001, closed `ab7c7dc`). Plan text uses canonical `scripts/dontpanic_orchestrate/...` paths and `dontpanic` CLI form from day zero. **No drift forward; current state matches the AC text.**

## What remains separately queued

Per scope discipline + queued decisions:

- **Per-plan `loop_caps.subprocess_timeout_seconds`** — D003 explicitly defers per-plan timeout configurability via schema-backed `loop_caps`; v1 ships env-var configurability only. Still queued (also named in Plan 2026-05-05-001's deferred caveats).
- **Verdict-based `check_no_progress` hardening** (distinguishing feature-defect vs environmental unchanged-verdict) — same un-triggered queued discussion named in Plan 2026-05-04-004's MAY/MUST-NOT memo + Plan 2026-05-01-001's Q2 table + Plan 2026-05-02-001's non-subsumption list. NOT solved by this plan; this plan only addresses the timeout-with-work shape via `check_diminishing_returns` exclusion + `check_no_progress` exclusion (the latter for timeout-with-work envelopes specifically, not for the broader environmental-verdict question).
- **Per-tool checkpointing for Claude** — D001 confirms this is structurally impossible cross-agent given Claude CLI's one-final-blob output. Not on any queue; treated as architectural constraint.
- **Sidecar partials read/display tooling** — F002 writes sidecars under `audit/partials/<audit_id>.{stdout,stderr}.{txt,bin}` but does not ship a reader/display surface. If a future plan wants operator-facing partial-output rendering, that's a separate slice.

## Outer plan close — exempt-flow path

```
$ dontpanic plan close docs/plans/2026-05-04-003-fix-subprocess-timeout-envelope-durability/
[plan close] goal_type=None is exempt from the F2 completion gate;
             status flipped active → completed without audit
```

Same exempt-flow path as the prior eleven close-outs in this session.

## Sign-off

Plan 2026-05-04-003 ships clean. F001 (subprocess_runner with proper process-group cleanup) + F002 (timeout evidence within schema-locked envelope) + F003 (supervisor classifier excludes timeout-with-work) all `passes:true`. The operator-named timeout-Q is verified yes at three independent tiers — executor failure (still happens, just cleaner), audit envelope persistence (durable + truthful + schema-stable), and downstream signoff interpretation (timeout-with-work no longer mistaken for zero-progress). Subprocesses still time out; timeout artifacts do not prove product failure; the `correctness/medium` finding represents audit-completeness gap, not implementation defect.

— bayesian, 2026-05-07 UTC
