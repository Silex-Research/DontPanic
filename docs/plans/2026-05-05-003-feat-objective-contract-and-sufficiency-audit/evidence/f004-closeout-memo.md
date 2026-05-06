# F004 close-out — Plan-lock sufficiency gate + dispatch backstop

Local-only commit in DontPanic. Operator-driven per the locked execution-mode policy: lock-path discovery + override-UX design were judgment calls owned by the operator, not auto-volley. F003's `run_sufficiency_audit()` is consumed via the new gate module; F005's dogfood remains the gating cycle for F1 close-out.

## Lock-path survey (D011 coverage)

Surveyed before any code landed. Surface as it exists today:

| # | Path | Status today | F004 coverage |
|---|---|---|---|
| (a) | `dontpanic plan lock <plan-dir>` CLI subcommand | **Did not exist** before F004 | **Created** in `cli.py` (`_plan_main` → `_plan_lock_main`). Calls `sufficiency_gate.lock_plan()`. Sole override channel (`--ignore-sufficiency-findings <reason>`). |
| (b) | Plan validator (`claude/shared/schemas/v1.0/validate.py`) | Schema-only validation; no gating | **Out of scope** per D009 cross-repo boundary. A future agent-conventions bump could surface a warning, but the load-bearing refusal stays DontPanic-side. |
| (c) | MCP `tool_dispatch` | `mcp_server.py:298` → `supervisor.dispatch_volley` | **Covered transitively** via supervisor wiring. |
| (d) | Direct status-flip helpers in `plan_loader.py` | None. `load()` is read-only (Plan model strict). | **N/A.** Documented absence — if a future helper is added, the gate must engage there too. |
| (e) | Hand-edited `plan.md` frontmatter `status: draft → active` | The de-facto lock today; how Plan F1 itself was locked. | **Backstop** at first dispatch via `supervisor.dispatch_volley` + `dispatch_single_agent` wiring (the gate refuses before the supervisor reaches `plan_loader.load`). |
| (f) | CLI dispatch entry points (`<plan-id>` single, `--volley`, `dispatch-from-plan`) | Existing; all funnel through `supervisor.dispatch_volley` | **Covered transitively** via supervisor wiring. |

## Three locked judgment calls (operator decisions, F004 design turn)

### A. Blocking severity threshold — **medium+**

`BLOCKING_SEVERITIES = frozenset({"medium", "high", "critical"})`. Pre-impl sufficiency exists to catch decomposition gaps before work starts. A medium missing journey / parity matrix / ambiguous completion test is exactly the kind of thing that should stop lock. Tune the auditor prompt later if this becomes too noisy; never relax the threshold silently.

### B. Override scope — **durable, input-bound**

`override.json` records:

- `reason`, `approved_by`, `approved_at` (ISO 8601 UTC)
- `plan_id`, `goal_type`, `objective_contract_path`
- `features_hash`, `objective_contract_hash`, `sufficiency_findings_hash` (SHA-256 of file bytes)

The gate honors the override on every subsequent call **iff** all three hashes still match the on-disk inputs. Any material change invalidates the override and the gate refuses with a structured message naming which input(s) drifted (`features_hash` / `objective_contract_hash` / `sufficiency_findings_hash`). That gives durable operator judgment without turning into a permanent bypass.

### C. Lock command — **mutating**

`dontpanic plan lock <plan-dir>` actually flips `status: draft` → `status: active` in plan.md frontmatter (single-line regex within the YAML block — preserves all other formatting). Refuses if status is not draft. Override flag (`--ignore-sufficiency-findings <reason>`) lives only here; downstream supervisor calls don't grow override surface. Hand-edited locks are caught at first dispatch via the supervisor backstop — closing the bypass without pretending it can be prevented at edit time.

## Public surface

```python
# scripts/dontpanic_orchestrate/sufficiency_gate.py

BLOCKING_SEVERITIES: frozenset[str]   # {"medium", "high", "critical"}
OVERRIDE_ARTIFACT: str                # "override.json"
SufficiencyGateError(ValueError)

enforce_sufficiency_gate(plan_dir) -> None
    # Read-only. No-op for plans without goal_type. Pure modulo file I/O.

lock_plan(plan_dir, *, override_reason=None, approved_by=None) -> Path
    # Canonical lock-command body. Mutates plan.md status on success.
```

## CLI

```bash
$ dontpanic plan lock <plan-dir>
$ dontpanic plan lock <plan-dir> --ignore-sufficiency-findings "<reason>"
```

Exit codes: `0` on success, `2` on usage errors / invalid override reason, `3` on gate refusal.

## Verification

| Check | Result |
| --- | --- |
| Pre-flight (F003 baseline) | 1019 passed, 6 skipped |
| F004 test module | 33 passed |
| **Full orchestrate suite (post-F004)** | **1052 passed, 6 skipped** (= 1019 + 33, zero regressions) |
| `ruff check` (F004 module + tests + cli + supervisor) | clean |
| `ruff format --check` | clean |
| `python3 scripts/sanitization_check.py` | 0 findings (759 files scanned) |
| `claude/shared/**` diff | none — D009 boundary preserved |
| Diff scope | `sufficiency_gate.py` (new) + `test_sufficiency_gate.py` (new) + additive `cli.py` (+84 lines, plan subcommand only) + additive `supervisor.py` (+13 lines, single gate call at top of two existing functions) |

## Test coverage map (F004 step 6 → tests)

| Step-6 case | Test(s) |
|---|---|
| (a) `_should_gate_sufficiency` only gates 4 required types | `test_should_gate_sufficiency_only_gates_four_required_types` (10 parametrized cases) |
| (b) gate is no-op for non-gated plans | `test_enforce_sufficiency_gate_no_op_when_no_goal_type`, `test_enforce_sufficiency_gate_no_op_for_mechanical` |
| (c) raises on blocking findings without override | `test_enforce_sufficiency_gate_refuses_on_high_finding`, `test_enforce_sufficiency_gate_refuses_on_medium_finding` |
| (d) override evidence written + status flipped | `test_lock_plan_with_override_records_evidence_and_flips` |
| (e) CLI integration (pass + fail paths) | `test_cli_plan_lock_pass_path_flips_status`, `test_cli_plan_lock_fail_path_returns_nonzero`, `test_cli_plan_lock_with_override_flag_records_evidence`, `test_cli_plan_lock_empty_override_reason_refused` |
| (f) backward compat — Plans A–E + F0 lock without sufficiency check | `test_lock_plan_no_goal_type_flips_status_no_gate`, `test_dispatch_volley_backstop_no_op_for_non_gated_plan` |

Plus extras locking the design judgment calls:
- `test_blocking_severities_locked_at_medium_plus` — A pin
- `test_enforce_sufficiency_gate_passes_on_low_severity_only` — A boundary
- `test_override_honored_on_subsequent_gate_calls` — B durability
- `test_override_invalidated_when_features_change` — B input-bound
- `test_override_invalidated_when_findings_change` — B input-bound
- `test_override_lists_which_inputs_drifted` — B drift attribution
- `test_lock_plan_refuses_when_status_not_draft` — C idempotency guard
- `test_lock_plan_rejects_override_for_non_gated_plan` — UX: meaningless flag refused loudly
- `test_dispatch_volley_backstop_refuses_blocked_plan` — D011 backstop coverage

## Queued for F005

- F005 dogfood drives the auditor through the new machinery against curated fixtures (Spin & Dine + Glam) under `evidence/dogfood/<project>/`. The pass/fail decision is operator-owned per D005/D010 — F005 is the hybrid execution mode locked in this turn's policy memory.
- The override flag exists; F005 should NOT use it for the dogfood cycle (any blocking finding the auditor surfaces should be addressed via re-decomposition, prompt revision, or schema revision, per D010's failure-response priority).
- Backstop coverage for the parent orchestration plan (`docs/plans/2026-04-19-001-...`) doesn't engage today because that plan declares no `goal_type`. If/when older plans get retroactive `goal_type` declarations, sufficiency findings would need to land before next dispatch (or override would be required).

## Boundary preservation

- Zero changes to `claude/shared/**` (D009 honored across F001 → F002 → F003 → F004).
- Zero changes to `nested_orchestration.py`, `plan_loader.py`, `mcp_server.py`, or any module outside the additive surface listed above.
- The supervisor wiring is two single-line gate calls — minimal blast radius for a high-impact gate placement.
