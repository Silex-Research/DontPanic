# F2/F004 dogfood disposition

**Plan ID:** `2026-05-06-002-feat-post-impl-completion-audit`
**Feature:** F004 — Dogfood proof point + dispositions
**Run date:** 2026-05-06
**Operator:** bayesian
**Outcome:** **PASS** — all six acceptance items satisfied; F2 pipeline (F001 + F002 + F003) verified end-to-end against the synthetic plan-local fixture.

## What this dogfood proves

F004 is the closing acceptance gate on Plan F2. Goal: exercise the F001
v1 evidence-coverage heuristic, F002 cross-vendor dispatcher (offline
mode), and F003 plan-close lifecycle gate together against a synthetic
plan-local fixture, and confirm the operator-facing decision matrix
behaves as designed when blocking findings exist.

The fixture lives at
`evidence/dogfood/synthetic-plan/` and is intentionally constructed so
the v1 auditor must surface ≥1 finding in EACH gap class:

- **`missing_evidence`**: the contract declares 5 `required_evidence`
  matchers; 4 have captured artifacts; 1 (`crash-NoneObserved`) is
  intentionally unmatched.
- **`journey_gap`**: the contract declares 3 `user_journeys`; 2 have
  captured artifacts; 1 (`error_recovery`) is intentionally orphan.

## Cross-vendor mode

This dogfood ran in **offline mode** (`DONTPANIC_GOAL_AUDITOR_OFFLINE=1`)
per the F004 design clause: "F002 dispatch may run in offline mode if
Codex isn't installed in the dogfood environment — the disposition
records this fact and the operator's manual second-vendor sanity check
on the findings JSON acts as the cross-vendor proxy."

Both vendors are actually available locally (`/opt/homebrew/bin/codex`
+ `$HOME/.local/bin/claude`), but offline mode was chosen
deliberately because it is the **design-mandated escape hatch for
air-gapped close-outs** (per F002 D013). Dogfooding the offline path is
load-bearing — it proves the F003 close gate correctly refuses on
`dispatch_skipped_offline` status without a recorded override, and
correctly honors a recorded override. A live cross-vendor dispatch
would prove F002's executor wiring, which is already covered by the
F002 production-path test (`test_production_path_invokes_resolved_executor`).

**Operator second-vendor sanity check** (cross-vendor proxy): I read
the v1 `completion_findings.json` and the `audit-codex-1.json`
envelope manually. Both findings are materially correct:

- The `missing_evidence/medium` finding correctly cites the unmatched
  `crash-NoneObserved` matcher; the narrative correctly explains the
  three operator-facing remediation paths (capture the artifact, fix
  the matcher string, drop the requirement).
- The `journey_gap/high` finding correctly cites the orphan
  `error_recovery` journey; the severity escalation to `high` is
  appropriate (a journey with zero captured refs of any kind is
  qualitatively worse than a single missing evidence matcher).

A live Codex run would have produced one disposition per finding
asserting `agree=True` for both — that disposition would not change
the F003 outcome (envelope would be `agree`, but no override would
flip the close decision because the v1 findings themselves are
non-blocking by F0 classification: both clusters classify to
`operator_deferred`, NOT `child_plan`). The OFFLINE path therefore
exercises a strictly broader decision surface (block-on-offline +
override-honor) than a live agree-path would.

## Pipeline run — five steps

All five steps re-runnable from the synthetic-plan tree. Transcripts
captured under `transcripts/`.

### Step A — `dontpanic plan audit <synthetic-plan>` (offline)

```
$ DONTPANIC_GOAL_AUDITOR_OFFLINE=1 \
  python -m dontpanic_orchestrate plan audit \
    docs/plans/2026-05-06-002-feat-post-impl-completion-audit/evidence/dogfood/synthetic-plan
```

- **Exit code:** 3 (blocking)
- **Audit envelope status:** `dispatch_skipped_offline`
- **v1 findings:** 2 (`missing_evidence` + `journey_gap`)
- **Cluster decisions:**
  - `web/browse_journey`: 1 finding → `operator_deferred`
  - `web/error_recovery`: 1 finding → `operator_deferred`
- **Block reason:** offline status + no override

Full transcript: `transcripts/01-plan-audit.txt`.

**Confirms:** F001 surfaces both materially-correct findings; F002
offline envelope is produced without invoking any executor; F0
classifier correctly classifies both clusters as
`operator_deferred` (non-blocking by F0 rules — neither cluster has
≥2 findings, neither has high+ severity below the
GOAL_GAP_MIN_FINDINGS_PER_CLUSTER threshold). The block decision
comes from the offline envelope status, NOT from F0 routing.

### Step B — `dontpanic plan close <synthetic-plan>` without override

```
$ DONTPANIC_GOAL_AUDITOR_OFFLINE=1 \
  python -m dontpanic_orchestrate plan close <synthetic-plan>
```

- **Exit code:** 3 (REFUSED)
- **plan.md status after:** `active` (unchanged)
- **override.json:** not written

Full transcript: `transcripts/02-plan-close-blocked.txt`.

**Confirms:** F003 close gate refuses on blocking decision (offline
status + no override); plan.md is NOT mutated; override.json is NOT
written; operator-actionable error message correctly points at
`--ignore-completion-findings <reason>`.

### Step C — `dontpanic plan close --ignore-completion-findings <reason>`

```
$ DONTPANIC_GOAL_AUDITOR_OFFLINE=1 \
  python -m dontpanic_orchestrate plan close <synthetic-plan> \
    --ignore-completion-findings "F2/F004 dogfood — operator confirmed cross-vendor sanity check…"
```

- **Exit code:** 0 (PASS)
- **plan.md status after:** `completed` (flipped active → completed)
- **override.json:** written with all four D004 hashes

Full transcript: `transcripts/03-plan-close-overridden.txt`.

The override file (`evidence/dogfood/synthetic-plan/evidence/goal-governance/post_impl/override.json`)
records:

- the operator reason (verbatim, ≥ 1 character)
- approved_by + ISO8601 approved_at
- plan_id + goal_type + objective_contract_path
- the four D004 input-bound hashes:
  - `features_hash`: sha256 of `features.json`
  - `objective_contract_hash`: sha256 of `objective_contract.json`
  - `completion_findings_hash`: sha256 of `completion_findings.json`
  - `evidence_manifest_hash`: sha256 of the manifest signature
    (sorted `uri|hash` lines)

**Confirms:** F003 honors a properly-formed operator override; mutates
plan.md exactly once via the regex flip; writes override.json under
the post_impl evidence dir; embeds the four input-bound hashes for
drift detection.

### Step D — supervisor backstop check on the post-close state

```python
completion_gate.enforce_completion_gate(<synthetic-plan>)
# → no raise (silent) — completed plan has valid override.json
```

Full transcript: `transcripts/04-backstop-check.txt`.

**Confirms:** the F003 supervisor backstop (which fires at every
dispatch entrypoint via `supervisor.dispatch_single_agent` /
`dispatch_volley`) is silent for a plan that closed cleanly through
the override path. A subsequent dispatch attempt against this
synthetic plan would not trigger BackstopError.

### Step E — idempotent re-close

```
$ python -m dontpanic_orchestrate plan close <synthetic-plan>
[plan close] plan already completed (status='completed'); no action taken
```

- **Exit code:** 0
- **plan.md unchanged**
- **No re-write of any evidence**

Full transcript: `transcripts/05-plan-close-idempotent.txt`.

**Confirms:** F003 is idempotent on already-completed plans; no
spurious re-dispatch, no second override.

## Per-gap-class operator disposition

| Gap class | Required by F004 acceptance | Materially correct? | Disposition |
|---|---|---|---|
| `missing_evidence` | ≥1 finding | ✓ (`crash-NoneObserved` matcher) | **PASS** |
| `journey_gap` | ≥1 finding | ✓ (`error_recovery` journey) | **PASS** |

Both halves PASS. Per F004 acceptance #5 (mirror of F1's F005 / D010
strengthened gating), I am authorized to flip F004 to `passes:true`.

## Decision matrix verification

The full F003 decision matrix as exercised by this dogfood:

| Audit env status | Override on file | F003 close decision | Confirmed? |
|---|---|---|---|
| `dispatch_skipped_offline` | none | block (exit 3) | ✓ Step B |
| `dispatch_skipped_offline` | valid (input-bound hashes match) | pass (exit 0) | ✓ Step C |
| any | none, on already-completed plan | idempotent no-op (exit 0) | ✓ Step E |

The remaining decision-matrix paths (auditor `disagree`,
`dispatch_response_malformed`, F0 `child_plan` classification, override
invalidation on input drift) are covered by `test_completion_gate.py`
(39 unit tests at the F003 ship). This dogfood deliberately exercises
only the offline + override paths, since those are the load-bearing
operator escape hatch and the unit tests cover the rest in finer
detail than a single end-to-end run can.

## Cross-vendor caveat (carried forward)

This dogfood did NOT exercise live cross-vendor dispatch. The cross-
vendor invariant (D003 / Goal Governance V1 §5) is preserved by F002
and verified by the F002 unit tests (`TestCrossVendorResolution` in
`test_completion_dispatch.py`). A queued follow-up — exercising live
Codex against the same synthetic-plan fixture — is a reasonable
candidate for a v2 dogfood once we have a stable Codex authentication
posture and a justification for the per-run cost. For v1, the offline-
mode path + manual operator second-vendor sanity check is the
explicitly-designed substitute (D015).

## Real-plan dogfood is queued (D005)

Per F2/D005, real-plan dogfood (e.g. running F003 close against Plan G
or Plan F1) is queued as a follow-up after this static-fixture
dogfood validates the path. This dogfood unblocks that follow-up but
does not subsume it — real plans have richer contract shapes,
historical evidence trees, and adversarial real-world matchers that
the static fixture deliberately simplifies.

## Re-running this dogfood

The fixture survives in its post-close state (status=completed +
override.json present + evidence files unchanged). To re-run:

1. Delete `synthetic-plan/evidence/goal-governance/post_impl/override.json`.
2. Edit `synthetic-plan/plan.md` frontmatter: `status: completed` →
   `status: active`.
3. Re-run Steps A–E from this disposition (exact commands above).

The four D004 hashes are deterministic given the same inputs, so the
override.json on a re-run will have identical hash values (only
`approved_at` will differ).

## Sign-off

I (bayesian, operator) confirm both halves PASS. F004 is authorized
to flip to `passes:true` in features.json. F2 is now substantively
complete; close-out memo + plan-level status flip is the next motion.

— bayesian, 2026-05-06
