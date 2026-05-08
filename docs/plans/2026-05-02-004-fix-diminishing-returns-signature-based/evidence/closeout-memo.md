# Plan 2026-05-02-004 — Close-out Memo

**Status:** Closed (passes: true).
**Path:** Direct (no volley). Single-feature platform correctness fix
with locked decisions D001–D004 and deterministic test cases. Operator
specified the scope; lock + execute.

## Why direct

Single function in `circuit_breakers.py` + a sibling helper in
`nested_orchestration.py` + targeted test additions. Locked decisions
already covered the design ambiguity (signature composition, severity
exclusion, no operator knob, fallback semantics). A volley would
re-verify deterministic behavior the test suite already covers.

## What shipped

### Helper — `nested_orchestration.compute_audit_finding_signature`
Signs an auditor Finding dict via the existing F001
`compute_finding_signature` primitive. Composition: `{file}:{line}`
locality (when `file` is set) + `category` + normalized `issue` text.
**Severity intentionally excluded** (D002) — high→medium downgrade is
the same finding. Returns `None` when `issue` is missing or
whitespace-only; callers degrade to fallback.

### Breaker — `circuit_breakers.check_diminishing_returns`
Replaced count-only body with signature-based convergence detection:

1. Filter audit envelopes to `agent_role=auditor` with the last N
   rounds all `audit_status=needs_changes`.
2. Per round, compute the set of finding signatures.
3. If ANY finding in any round is unsigned → fall back to the legacy
   non-decreasing-count check; reason string starts with
   `"diminishing returns (count fallback — finding signatures
   unavailable):"`.
4. Otherwise, trip when `set.intersection(*rounds_signatures)` is
   non-empty AND every round contributed at least one signed finding.
   Reason string starts with `"diminishing returns (signature-based):"`
   and lists the persisted signatures.

`_audit_findings` helper handles both schema shapes (flat `findings`
or `blocking_findings + non_blocking_findings`).

`DIMINISHING_RETURNS_MIN_ROUNDS = 2` remains a constant — no operator
config knob (D003).

### Tests — `test_f006_circuit_breakers.py`

- Existing `test_check_diminishing_returns` updated to reflect the
  new contract: same issue text trips with `"signature-based"` in the
  reason; disjoint-issue rounds at the same count do NOT trip.
- New `test_check_diminishing_returns_signature_semantics` covers the
  four operator-specified cases:
  1. Same signatures over 2 rounds → trip (signature-based reason).
  2. Different signatures with same count → no trip.
  3. Increasing count with disjoint signatures → no trip.
  4. Missing issue text → count-fallback trip with the fallback fact
     named in the reason.
- Existing `test_audit_writer_normalize.py` + `test_audit_filename_feature_id.py`
  call `check_diminishing_returns` with single audit paths
  (`len < 2` early-return); no behavioral change, no test edits needed.

## Test / lint / sanitization state

- **Targeted:** `pytest test_f006_circuit_breakers.py::test_check_diminishing_returns
  test_f006_circuit_breakers.py::test_check_diminishing_returns_signature_semantics`
  → 2 passed.
- **Full orchestrate suite:** `pytest scripts/jarvis_orchestrate/tests/`
  → 580 passed, 6 skipped (was 579 + 6 skipped before this work; +1 net
  — existing test updated, new test added).
- **Ruff:** `ruff check` on the three changed files → all checks passed.
- **Sanitization:** `python scripts/sanitization_check.py` →
  `✓ no campaign IDs or secret shapes in sanitized surface (565 files
  scanned)`.

## Concrete real-world signal validated

The SpinDine plan 2026-05-01-001 trip (`auditor finding counts [3, 3]
non-decreasing`) was the canonical false-positive shape. Under the new
heuristic that same envelope pair would only trip if the underlying 3
findings had the same signatures across both rounds — i.e., the
auditor really was stuck on the same problems. The "different problems
each round of similar count" scenario, which is the legitimate
volley-improvement workflow, no longer trips.

## Files in this commit (scoped per operator directive)

- `scripts/jarvis_orchestrate/nested_orchestration.py`
  (added `compute_audit_finding_signature`)
- `scripts/jarvis_orchestrate/circuit_breakers.py`
  (rewrote `check_diminishing_returns`; added `_audit_findings` helper)
- `scripts/jarvis_orchestrate/tests/test_f006_circuit_breakers.py`
  (updated existing test, added signature-semantics test)
- `docs/plans/2026-05-02-004-fix-diminishing-returns-signature-based/`
  (plan.md, features.json, decisions.jsonl, this memo)

No operator config knob, no schema bump, no migration of historical
audit envelopes. The fallback path makes legacy data safe to read.

---

## Cross-plan context (added 2026-05-07 at status-flip close-out)

This section was added at the formal `active → completed` flip in the Tier 2/3 close-out batch and is deliberately scoped narrower than a casual reader might expect.

### What this plan does NOT solve

This plan fixes a `diminishing_returns` false-positive class. It does **not** address the broader `stopped_no_progress` / timeout / stale-envelope class. Specifically:

- **`stopped_no_progress`** (`circuit_breakers.check_no_progress`) — fires when the auditor *verdict* (e.g. `needs_changes`) is unchanged across N consecutive rounds. That breaker is verdict-based, not count-based, and is unaffected by this plan.
- **Timeout / stale-envelope** — when an implementer subprocess hits the 600s deadline and the audit envelope JSON does not flush, downstream auditors flag the truncated envelope as a finding. This is a runtime/durability issue, not a finding-identity issue.

The Phase A F003 close-out (Plan 2026-05-03-001 D009, closed `cb6d3cc`) and the Phase B F002 close-out (Plan 2026-05-03-003 D012, closed `7ca7a23`) both terminated `stopped_no_progress` — that is the **verdict-based** breaker, not the count-based one this plan rewrites. They are adjacent failure modes, not the same one.

### What this plan does solve

The breaker now compares **persistent unresolved finding *signatures*** across the last N `needs_changes` rounds. A round-pair where the auditor flags **the same** problems still trips; a round-pair where the auditor flags *different* problems of similar cardinality (the legitimate volley-improvement shape, observed concretely as the SpinDine 2026-05-01-001 `[3, 3]` false-positive) no longer trips.

### What remains a separate question

Whether to harden `stopped_no_progress` to distinguish *feature-defect* unchanged-verdict (real implementer regression) from *environmental* unchanged-verdict (auditor sandbox tempdir absence, stale-envelope from upstream timeout, etc.) is a separate platform discussion. This plan does **not** implement that distinction, and the Phase B close-out memo's "platform-shape signal worth tracking" line was correctly framed as *adjacent* to this work, not subsumed by it.

If a future plan implements that distinction, it would touch `check_no_progress` (and possibly the auditor envelope shape), not `check_diminishing_returns`. That plan will be drafted on a real-world trigger, not on the memo cross-link alone.
