# Plan F2 close-out memo

**Plan ID:** `2026-05-06-002-feat-post-impl-completion-audit`
**Sequence position:** Goal Governance V1 / F2 (per `docs/GOAL_GOVERNANCE_V1.md` §9)
**Status flip:** `active` → `completed` on 2026-05-06
**Lock checkpoint:** `97daa9a` (4 features locked, D001–D011 at lock time + D002 amendment in `38728e9`)
**Close mechanism:** `dontpanic plan close docs/plans/2026-05-06-002-feat-post-impl-completion-audit/` — F003's own close path, taking the exempt-plan flow because F2 is `goal_type=infra`.

**F2 completes the Goal Governance V1 post-impl completion-audit layer.**
The Goal Governance V1 sequence is now: F0 ✓ → F1 ✓ → G ✓ → **F2 ✓ (this close-out)**.

## What F2 shipped

Plan F2 closes the post-impl half of Goal Governance V1. F1 catches
sufficiency gaps before plan lock; Plan G's runtime adapters capture
EvidenceRef artifacts at feature close-out; F2 catches completion gaps
before plan close-out and gates the active → completed flip.

Four features, four feature-level commits, all `passes:true`:

1. **F001 — Completion auditor module + findings/envelope.** Pure
   text-only orchestration over already-shipped surfaces. Reads
   `ObjectiveContract.required_evidence`, walks each matcher against
   captured EvidenceRef artifacts (rebuilt by F001 from the on-disk
   `evidence/goal-governance/post_impl/<source>/<journey>/` tree), emits
   `CompletionFinding` objects normalized into F0's `GoalGapFinding`
   shape. Findings envelope carries `audit_kind:
   "v1_evidence_coverage_heuristic"` as a load-bearing literal so
   downstream consumers (F003, dogfood dispositions) cannot mistake
   v1 for a semantic completion proof.
2. **F002 — Cross-vendor goal-audit dispatcher.** Wires F1's
   `_resolve_goal_auditor_agent` into a real production dispatch path
   via `executors.AGENT_REGISTRY`. Closes F1's caveat that F005 dogfood
   ran with `DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR=1` set because
   production dispatch wasn't wired. `SameVendorRefused` subclasses F1's
   `SufficiencyAuditError`. Adds `DONTPANIC_GOAL_AUDITOR_OFFLINE` env
   for air-gapped close-outs.
3. **F003 — Plan close gate + CLI surface + supervisor backstop.** New
   subcommands `dontpanic plan audit <plan-id>` and `dontpanic plan
   close <plan-id> [--dry-run] [--ignore-completion-findings <reason>]`.
   Decision matrix: blocking iff (any cluster classifies to
   `child_plan`) OR (envelope status `disagree` /
   `dispatch_response_malformed`) OR (envelope `dispatch_skipped_offline`
   AND no override). Override is input-bound (D004 — four hashes).
   Supervisor backstop catches hand-edited active → completed flips that
   lack F2 evidence. Exempt-plan flow lets non-goal-gated plans (infra /
   refactor / mechanical / no goal_type) close cleanly without an audit.
4. **F004 — Dogfood proof point.** Plan-local synthetic fixture under
   `evidence/dogfood/synthetic-plan/`. Operator-judged PASS for both
   gap classes. Live cross-vendor dispatch deferred (offline mode +
   manual second-vendor sanity check serves as the cross-vendor proxy
   per F004's caveat clause); live dispatch is queued as a follow-up.

## Four feature commits

| Feature | Commit | Surface | Tests |
|---|---|---|---|
| F001 — completion auditor | `c9ccc85` | `completion_auditor.py` (606 lines) + 26 tests + D012 | +26 (zero regressions) |
| F002 — cross-vendor dispatcher | `b9e0bbb` | `completion_dispatch.py` + `prompts/completion_audit_prompt.md` + 28 tests + D013 | +28 (zero regressions) |
| F003 — close gate + CLI + backstop | `10c5ff2` | `completion_gate.py` + cli/supervisor additive + 39 tests + D014 | +39 (zero regressions) |
| F004 — dogfood | `fa1d624` | `evidence/dogfood/` tree + features.json passes flips + D015 | +0 (fixture-only) |
| Plan close-out | (this commit) | plan.md status flip + this memo + D016 | +0 |

All commits local-only; no remote pushes. Single-repo plan (D002 —
no agent-conventions schema bump needed; existing v1.4.0
`ObjectiveContract.required_evidence` carried the v1 matcher contract
directly).

## Final verification numbers (post-F004)

| Check | Result |
| --- | --- |
| Cumulative orchestrate suite | **1344 passed, 7 skipped, 0 regressions** |
| New tests added by Plan F2 | 93 (= 26 F001 + 28 F002 + 39 F003) |
| `ruff check` + `ruff format --check` (full F2 surface) | ✓ clean |
| `python3 scripts/sanitization_check.py` | ✓ 0 findings (845 files scanned) |
| Plan F2 validates against agent-conventions v1.0 schemas | ✓ |
| Project-agnostic invariant (D013 carry-forward from Plan G) | ✓ no project-name special cases in any F2 module (greppable assertions in 3 test modules) |
| Capture-only invariant (Plan G D002 / F2 D009) | ✓ no `runtime_evidence/` imports in any F2 module (greppable in `test_completion_dispatch.py` + `test_completion_gate.py`) |
| Cross-vendor invariant (D003 / Goal Governance V1 §5) | ✓ same-vendor refusal preserved by default; override env (`DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR`) untouched from F1 |
| D002 framing (load-bearing) | ✓ "v1 evidence-coverage heuristic" + "NOT a semantic completion proof" enforced by greppable regex tests in F001 module + F002 prompt template |
| F1/F002 internals untouched by F003 (D013 of Plan G — single source of truth) | ✓ F003 forwards F002 dispatch seam unchanged; F003 backstop mirrors F1's pattern without modifying F1 |
| Library-only v1 (locked at lock turn) | ✓ no MCP wrap shipped; CLI is the only operator surface |

## F004 dogfood — operator PASS disposition

The F004 dogfood is the F2 acceptance gate. Operator confirmed
**PASS** for both gap classes against the synthetic plan-local
fixture under `evidence/dogfood/synthetic-plan/`:

- **`missing_evidence/medium`**: matcher `crash-NoneObserved` correctly
  flagged as unmatched; narrative correctly enumerates the three
  operator-facing remediation paths (capture / fix matcher / drop
  requirement).
- **`journey_gap/high`**: journey `error_recovery` correctly flagged as
  orphan (zero captured refs of any kind); severity escalation to
  `high` is appropriate.

Five-step pipeline run captured under
`evidence/dogfood/transcripts/01..05`:

1. `dontpanic plan audit` → exit 3 (blocking, offline status)
2. `dontpanic plan close` (no override) → exit 3 (REFUSED, plan.md
   untouched)
3. `dontpanic plan close --ignore-completion-findings <reason>` → exit
   0 (status flipped active → completed, override.json with all four
   D004 hashes)
4. `enforce_completion_gate()` → silent on completed plan (backstop
   accepts valid override)
5. `dontpanic plan close` (re-run) → exit 0 (idempotent no-op)

Cross-vendor mode: ran in `DONTPANIC_GOAL_AUDITOR_OFFLINE=1`
deliberately. Both vendors are actually available locally (codex +
claude both on PATH), but offline mode is the design-mandated escape
hatch for air-gapped close-outs (per F002 D013); dogfooding it
exercises a strictly broader F003 decision surface (block-on-offline +
override-honor) than a live agree-path would. Live cross-vendor
dispatch is already covered by F002's production-path test
(`test_production_path_invokes_resolved_executor`). Operator
second-vendor sanity check served as the cross-vendor proxy per
F004's caveat clause.

Full disposition: `evidence/dogfood/disposition.md`.

## This close-out — F003 closes its own plan via the exempt path

Plan F2's own close-out exercises F003's **exempt-plan flow** (per
F003 design):

```
$ dontpanic plan close docs/plans/2026-05-06-002-feat-post-impl-completion-audit/
[plan close] plan_dir=docs/plans/2026-05-06-002-feat-post-impl-completion-audit
[plan close] goal_type='infra' is exempt from the F2 completion gate; status flipped active → completed without audit
[plan close] status flipped: active → completed in docs/plans/2026-05-06-002-feat-post-impl-completion-audit/plan.md
$ echo $?
0
```

F2 declared `goal_type: infra` at lock time (D002 lock-time decision +
the pre-lock condition the operator verified before locking — that
`goal_type=infra` does not require `objective_contract` and the
sufficiency gate no-ops). The completion gate symmetrically exempts
infra plans from the post-impl audit requirement: `_should_gate_completion`
returns False for goal_types outside `{parity, new_feature, migration,
incident}`. Close path takes the no-audit branch, never invokes F002,
flips status active → completed via the regex mutation, and exits 0.

Supervisor backstop verified silent on the post-close state:
`enforce_completion_gate()` correctly recognizes a completed exempt
plan as no-op (no audit was required, so no audit evidence is
required). No `BackstopError` raised.

This is **F003 dogfooding itself by self-application**: the very gate
F003 ships is the gate that closes the plan that shipped F003. The
exempt-plan flow is now empirically verified at the production
boundary, not just at the test boundary.

## Per-feature decisions

D012–D015 capture each feature's locked design choices and ship
notes; D016 (this close-out) records the plan-level flip. Quick
reference:

- **D001–D011** (lock-time decisions): goal-governance sequencing,
  single-repo + simple matcher v1, cross-vendor dispatcher in scope,
  four-hash override durability, plan-local dogfood, CLI yes / MCP no,
  F0 triage consumed unchanged, no new runtime adapters,
  capture-only carry-forward, dispatch-time backstop, schema-
  insufficiency abort.
- **D002 amendment** (commit `38728e9`, pre-lock): substring matcher
  framed explicitly as v1 evidence-coverage heuristic, NOT semantic
  completion proof; envelope `audit_kind` literal made load-bearing.
- **D012**: F001 ship — completion auditor module + 26 tests +
  schema-path correction note (`ObjectiveContract.required_evidence`
  is at top level, NOT nested under `completion_test`).
- **D013**: F002 ship — cross-vendor dispatcher + 28 tests +
  `SameVendorRefused` subclass + `DONTPANIC_GOAL_AUDITOR_OFFLINE` env
  addition.
- **D014**: F003 ship — completion gate + plan-close/audit CLI +
  supervisor backstop + 39 tests + exempt-plan flow + four-hash
  override invalidation.
- **D015**: F004 dogfood — operator PASS disposition for both gap
  classes; offline-mode + manual second-vendor sanity check serves as
  cross-vendor proxy per F004's caveat clause.
- **D016** (this close-out): plan-level flip via F003's own close
  path through the exempt-plan flow.

## Cross-vendor caveat (carried forward from F1, addressed by F2)

F1's F005 dogfood ran with `DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR=1`
because production dispatch wasn't wired (F1 deliberately stopped at
resolution + the cross-vendor refusal check; F1's `DispatchFn` was a
test seam with no production wiring).

F2/F002 closes that caveat at the post-impl boundary: the production
path now routes through `executors.AGENT_REGISTRY` via `get_executor`
when no test-injected `dispatch=` is supplied. Same-vendor refusal +
override env preserved unchanged from F1.

A queued follow-up — exercising live cross-vendor dispatch end-to-end
against a real plan (Plan G or Plan F1) — remains applicable. F004's
dogfood ran in offline mode deliberately to exercise the operator
override path; live cross-vendor is covered by F002's production-path
test. The follow-up would close the still-open question of
"end-to-end live cross-vendor against a real-plan ObjectiveContract."

## Real-plan dogfood is queued (D005)

Per F2/D005, real-plan dogfood (running F003 close against Plan G or
Plan F1 as the target) is queued as a follow-up after this static-
fixture dogfood validates the path. F004 unblocks that follow-up but
does not subsume it — real plans have richer contract shapes,
historical evidence trees, and adversarial real-world matchers that
the static fixture deliberately simplifies.

## Signoff envelope decision

Per F1 + Plan G's pattern: F2's plan-level close-out is operator-
driven (no auditor-volley reconciliation at the plan level — only
per-feature pytest + ruff + sanitization, plus the F004 dogfood
disposition). A formal `audit/signoff-*.json` envelope shaped for
auditor reconciliation would be a square-peg-round-hole. This
plan-level close-out memo + the F004 disposition are the load-bearing
artifacts instead.

Per-feature evidence:
- D012 (F001) → `decisions.jsonl` + commit `c9ccc85`.
- D013 (F002) → `decisions.jsonl` + commit `b9e0bbb`.
- D014 (F003) → `decisions.jsonl` + commit `10c5ff2`.
- D015 (F004) → `decisions.jsonl` + commit `fa1d624` + `evidence/dogfood/disposition.md`.
- D016 (this close-out) → `decisions.jsonl` + this memo.

## What's next

The Goal Governance V1 sequence is now: F0 ✓ → F1 ✓ → G ✓ → **F2 ✓
(this close-out)**. Goal Governance V1 is substantively complete.

Queued follow-ups (each its own future plan, not part of F2):

1. **Live cross-vendor end-to-end dogfood** — exercise F002's
   production path against a real plan (Plan G or F1) with both
   vendors actually invoked. Closes the remaining "live cross-vendor
   on a real ObjectiveContract" gap.
2. **Real-plan dogfood (D005)** — run F003 close against a real
   historical plan (Plan G is the natural candidate; G's own close-out
   pre-dates F003 and was operator-driven, so applying F003 to G
   retroactively would dogfood the path on a real contract shape).
3. **MCP wrap (D006)** — expose the F2 surface (`audit_plan` /
   `close_plan`) as MCP tools for external agent consumption. Locked
   out of v1 on the CLI-first principle.
4. **v2 completion-test schema** — richer per-rule shape (regex /
   structured assertions / journey-walk semantics) replacing the v1
   substring matcher. Defer until real use shows the shape; D011
   abort condition was the v1 release valve.
5. **Manifest emit at adapter-write time** — let G adapters write the
   manifest directly during feature close-out, removing F001's
   self-rebuild step. v2 follow-up; v1 self-rebuilds because adding
   manifest emit to G post-close would modify G after it shipped.

These all live in their own future plans, not Plan F2's scope.

— Goal Governance V1 layer complete. F2 close-out: 2026-05-06.
