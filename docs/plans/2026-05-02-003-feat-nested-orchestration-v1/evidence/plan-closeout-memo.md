# Plan 2026-05-02-003 close-out memo — Nested orchestration v1 (safe parent/child plan nesting)

**Plan ID:** `2026-05-02-003-feat-nested-orchestration-v1`
**Type:** `feat` · **Tier:** `local` · **agents_required:** `claude` + `codex`
**goal_type:** none declared (exempt from F2 completion gate)
**Status flip:** `active` → `completed` on 2026-05-07 (UTC).
**Outcome:** Clean close. All three features (F001 + F002 + F003) shipped `passes:true` via direct delivery (no volley) and are documented in plan-local per-feature close-out memos.

## What this plan delivered

Established the minimum primitives for nested plan orchestration: a parent plan's auditor finding (or operator-manual decision) can mint a bounded child plan that runs to signoff before the parent resumes. The shipped scope is intentionally narrow — just the safety primitives needed to make nesting un-dangerous — with the broader governance-discovery layer (governance assessment, ADR proposals, standards gaps, stage-aware matrices) deferred to a future v2 plan.

The historical design memo `project_jarvis_nested_orchestration_v1.md` (memory) catalogued 8 first-class concepts; this plan shipped the 3 that are load-bearing for safe-nesting and explicitly deferred the rest.

## Acceptance — three features

### F001 — Parent/child metadata + depth/cycle/repeated-finding guards (`passes: true`)

`scripts/jarvis_orchestrate/nested_orchestration.py` (now under `dontpanic_orchestrate/` post the canonical-module flip) ships the structured `SpawnFinding` model (D001 — five required fields: `parent_audit_id`, `finding_id`, `finding_code`, `finding_class`, `finding_signature`), `Orchestration` Pydantic model with cross-field invariants (`spawn_reason='auditor_finding'` requires spawn_finding; `'operator_manual'` rejects it; D002 platform-cap enforcement: frontmatter cannot raise depth beyond `DEFAULT_DEPTH_LIMIT=3`), deterministic `compute_finding_signature()` (SHA-256 prefix of `{code}|{class}|{normalized_issue}`), `walk_parent_chain()` / `compute_depth()`, and three guards (`check_depth`, `check_cycle`, `check_repeated_finding`) — each raising `NestedOrchestrationError` on violation. CLI's `--allow-depth N` operator override threads through `override_max`, and the effective cap is the LOWER of frontmatter and override (so neither path can quietly widen).

### F002 — Child charter + commit policy (`passes: true`)

Adds `ChildCharter` (kind=`implementation` only — `governance_design` rejected at parse time with deferral message), `parent_objective` (1–500 chars), `parent_acceptance_item` (≥1), `allowed_paths` (non-empty fnmatch globs), `forbidden_decisions`, `return_condition_summary`, `may_edit_product_code` (no default per D003 — must be explicit), `may_spawn_children` (default `False`). Adds `CommitPolicy` with `mode ∈ {child_commit, evidence_only}` (default `evidence_only` per D003; `parent_squash` rejected with deferral). D003 cross-field invariant: `mode='child_commit'` requires `may_edit_product_code=True`; `mode='evidence_only'` requires `may_edit_product_code=False`. Return Condition section parser (D004) reads structured signoff text from the child's close-out memo for fan-in synthesis.

### F003 — Parent pause/fan-in protocol (`passes: true`)

New gate type `pre_resume_after_child:{child_plan_id}` in `gate_pause.py` — peer to `breaker:` and `defer:` but with a different clearance lifecycle: `resume_all()` does NOT touch it; operator must explicitly `approve <plan> pre_resume_after_child --child <child>`. Auto-arms on parent volley dispatch when active_supervisors shows a referencing child. Parent volley enters pause state at the gate; child runs to signoff under its charter; parent resumes only after explicit operator approval. Best-effort `events.jsonl` (D006 — append-only, no rollback on partial write) records: `child_spawned`, `parent_paused`, `child_signoff`, `parent_resumed`. D010 (resolved during F003): the parent fan-in memo gets its own status discipline (`fan_in_status: pending|complete`).

## Verification numbers (post-ship, pre-close)

| Check | Result |
| --- | --- |
| Plan dir validates against agent-conventions v1.0 schemas | ✓ |
| F001 features.json | `passes:true` |
| F002 features.json | `passes:true` |
| F003 features.json | `passes:true` |
| Per-feature close-out memos | ✓ — `evidence/f001-closeout-memo.md`, `f002-closeout-memo.md`, `f003-closeout-memo.md` |
| Decisions log | D001–D013 in `decisions.jsonl` (lock-time + impl-time + scoping decisions); D014 added in this commit as the close-out record |
| Delivery path | Direct (no volley) for F001/F002/F003 — all three operator-approved as direct per the F-memo "Why direct" sections (deterministic schemas + invariants + state machines; volley dogfood deferred to a real recursive-finding flow) |
| Worktree boundary at ship time | scoped to `scripts/jarvis_orchestrate/nested_orchestration.py` + `gate_pause.py` (gate-type extension) + tests + per-feature evidence memos |
| Canonical-module rename impact | post-`8edd953`, the implementation file lives at `scripts/dontpanic_orchestrate/nested_orchestration.py`; legacy import path is shim-relayed |

## Decisions log status

`decisions.jsonl` carries the full lock + impl history: D001 (structured spawn identity / finding_signature hash) → D006 (events.jsonl is best-effort, never canonical) → D007/D009/D011 (per-feature direct-path close-outs) → D012 (v2 is demand-driven, deferred until v1 has one real dogfood cycle) → D013 (v1 is the safe-nesting substrate, not the full governance layer). D014 added in this commit is the close-out record.

The per-feature memos (`f001-closeout-memo.md`, `f002-closeout-memo.md`, `f003-closeout-memo.md`) cite the relevant D-entries inline; both surfaces are kept in sync.

**Worktree note:** `decisions.jsonl` was missing from the local checkout when this close-out began (partial-clone object-store fallout — the file was tracked in HEAD but absent on disk; same shape as the side-clone restore the operator did earlier in this session for the broader plan dir). HEAD content was restored via `git checkout HEAD -- decisions.jsonl` before D014 was appended; D001–D013 are byte-identical to HEAD.

## Cited commits

| Commit | Description |
|---|---|
| (pre-`f083870`, partial-clone unreachable) | F001 ship — `nested_orchestration.py` + `SpawnFinding` + `Orchestration` model + 3 guards |
| (pre-`f083870`, partial-clone unreachable) | F002 ship — `ChildCharter` + `CommitPolicy` + cross-field invariants + Return Condition parser |
| (pre-`f083870`, partial-clone unreachable) | F003 ship — `pre_resume_after_child` gate type + auto-arm + best-effort `events.jsonl` recorder + fan-in memo discipline |
| `8edd953` | Module relocation — files moved with the canonical-module flip (Plan 2026-05-04-001) |
| _(this commit)_ | Plan close-out — plan-closeout-memo + decisions.jsonl (D001) + status flip via exempt-flow |

The pre-`f083870` ship commits are real and the work shipped (per-feature memos document each ship date + verification numbers); they're just not directly resolvable through `git log` on this checkout because of partial-clone object `1db24649` corruption that blocks ancestor traversal. A full clone would resolve the hashes; that is a known sidebar (separate plan to migrate this checkout off `promisor=true, blob:none`).

## Outer plan close — exempt-plan flow

Plan does not declare a `goal_type`, so the F2 completion gate is a no-op (`goal_type=None` is exempt from the gated set); the status flip still proceeds via the exempt path:

```
$ dontpanic plan close docs/plans/2026-05-02-003-feat-nested-orchestration-v1/ --dry-run
[plan close] plan_dir=docs/plans/2026-05-02-003-feat-nested-orchestration-v1 (dry-run)
[plan close] goal_type=None is exempt from the F2 completion gate;
             --dry-run would flip status active → completed
$ echo $? → 0
```

Same exempt-flow used by Plan 2026-05-04-001 (canonical-module flip) the previous close-out in this batch.

## Pattern adherence

This is the second close-out in the Tier 1 close-out batch, applying the pattern established by 2026-05-04-001:

1. Validate plan dir exits 0.
2. Write `evidence/plan-closeout-memo.md` (this file).
3. Append close-out D-entry to `decisions.jsonl` (D014 here).
4. Run `dontpanic plan close <plan-dir>` for status flip.
5. Re-validate.
6. Commit only this plan dir.

**Mid-flight correction noted:** an initial draft of this memo claimed the plan had no pre-existing `decisions.jsonl` and miswrote D001 as a fresh close-out entry; that draft would have overwritten the file's HEAD content (D001–D013). Caught at the staging step when `git status` flagged the file as `M` rather than `A`. Recovery: `git restore --staged` + `git checkout HEAD --` to restore byte-identical HEAD content, then a proper append of D014. Lesson for the close-out batch: when a file is "missing" from the worktree on a partial-clone checkout, run `git ls-tree HEAD -- <path>` before assuming it's never existed; the absence may be partial-clone fallout, not a plan-author choice.

**Nested orchestration is NOT used for this close-out** — close-out is mechanical paperwork (memo + D-entry + status flip + commit), not auditor-finding-driven dispatch work. The nested-orch primitives this plan ships are for future implementation volleys with implementer + auditor agents discovering recursive findings, not for paperwork operations on the very plan that ships them.

## Sign-off

I (bayesian, operator) confirm: Plan 2026-05-02-003 ships clean. Three features (F001 + F002 + F003) all `passes:true`. Safe-nesting primitives are in production: `Orchestration` + `ChildCharter` + `CommitPolicy` Pydantic models, depth/cycle/repeated-finding guards, `pre_resume_after_child` gate type with operator-only clearance, best-effort `events.jsonl` recorder, parent fan-in memo discipline. Available substrate for future v2 governance-discovery layer (governance assessment, ADR proposals, standards gaps) when that becomes load-bearing.

— bayesian, 2026-05-07 UTC
