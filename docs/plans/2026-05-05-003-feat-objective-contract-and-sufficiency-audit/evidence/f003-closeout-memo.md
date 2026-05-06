# F003 close-out — Pre-impl sufficiency auditor module

Local-only commit in DontPanic. Boundary kept tight per the operator
directive: zero changes under `claude/shared/**`; consumes the v1.4.0
`ObjectiveContract` model imported from the F002 subtree pull.

## Deliverables (vs F003 acceptance)

1. **`sufficiency_auditor.py` module** at
   `scripts/dontpanic_orchestrate/sufficiency_auditor.py`. Public surface:
   - `run_sufficiency_audit(plan_dir, *, implementer_agent=None, dispatch=None) -> list[SufficiencyFinding]`
   - `SufficiencyFinding` Pydantic model
   - `SUFFICIENCY_GAP_CLASSES` taxonomy tuple
   - `SufficiencyAuditError` (subclasses `ValueError`)
   - `PRE_IMPL_FINDINGS_ARTIFACT` constant
   - `DispatchFn` Callable type
   Pure text-only — no MCP, no runtime evidence. The `dispatch` seam is
   intentionally not given a default real-dispatch implementation; F004
   wires production dispatch when the lock gate begins consuming
   findings.

2. **`SufficiencyFinding` Pydantic model** with required fields
   `severity`, `journey_id`, `gap_class`, `description`, `feature_refs`
   (+ optional `recommendation`). Severity validator reuses F0's
   `_GOAL_GAP_SEVERITY_RANK` (imported from `nested_orchestration`) so
   the sufficiency surface stays consistent with the goal-gap classifier
   downstream features will consume. `gap_class` is a `Literal` over the
   five values in `SUFFICIENCY_GAP_CLASSES`.

3. **Vendor resolution via `project_config`, NOT hardcoded.**
   `_resolve_goal_auditor_agent(plan_dir, implementer_agent=None)`:
   1. Calls `project_config.find_project_for_plan_dir(plan_dir)` to
      anchor on the plan's project.
   2. Calls `project_config.resolve_dispatch_defaults(project_path)` —
      the canonical D004 precedence walk (project config → global config
      → hardcoded fallback `claude` / `codex`).
   3. Override channel for the runtime implementer is the
      `implementer_agent` parameter (lets tests + callers drive the
      cross-vendor check without mutating config).
   4. **Cross-vendor invariant (D006 / Goal Governance V1 §5):** if
      `effective_implementer == auditor`, raises `SufficiencyAuditError`
      unless `DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR` is set truthy
      in the environment. The env var is the operator-override channel;
      the recommendation is to record the override in close-out evidence
      whenever it is set.

   Today's expected default when implementer is `claude` is `codex`
   (verified by `test_resolve_goal_auditor_returns_default_codex_when_implementer_is_claude`).

4. **Evidence written to F0's path convention.**
   `run_sufficiency_audit` writes to
   `evidence/goal-governance/pre_impl/sufficiency-findings.json`
   resolved via `nested_orchestration.goal_governance_evidence_path()`
   — the same helper F0 ships, so F003 cannot drift the prefix.

5. **Tests cover the 9 cases from F003 step 8** at
   `scripts/dontpanic_orchestrate/tests/test_sufficiency_auditor.py`
   (22 test functions total). Coverage map:

   - (a) `_load_objective_contract` happy path —
     `test_load_objective_contract_happy_path`
   - (b) `_load_objective_contract` failures (4 tests):
     `test_load_objective_contract_missing_goal_type`,
     `test_load_objective_contract_missing_links_field`,
     `test_load_objective_contract_missing_file`,
     `test_load_objective_contract_malformed_json`,
     plus an additional schema-violation case
     (`test_load_objective_contract_schema_violation`) covering
     ObjectiveContract field-level rejection.
   - (c) `_resolve_goal_auditor_agent` happy path —
     `test_resolve_goal_auditor_returns_default_codex_when_implementer_is_claude`
     and `test_resolve_goal_auditor_respects_explicit_implementer_arg`.
   - (d) Same-vendor without override raises (and with override is
     allowed) — `test_resolve_goal_auditor_same_vendor_without_override_raises`,
     `test_resolve_goal_auditor_same_vendor_with_override_allowed`.
   - (e) `_build_sufficiency_prompt` includes all required sections —
     `test_build_sufficiency_prompt_includes_all_required_sections`.
   - (f) `_parse_sufficiency_response` happy path + tolerates code
     fences + accepts empty array —
     `test_parse_sufficiency_response_happy_path`,
     `test_parse_sufficiency_response_tolerates_code_fence`,
     `test_parse_sufficiency_response_empty_array`.
   - (g) `_parse_sufficiency_response` rejects malformed JSON +
     non-array top-level —
     `test_parse_sufficiency_response_rejects_malformed_json`,
     `test_parse_sufficiency_response_rejects_non_array_top_level`.
   - (h) `_parse_sufficiency_response` rejects findings whose severity
     is below the audit envelope enum (reuses F0's pattern) plus
     unknown gap_class and short description —
     `test_parse_sufficiency_response_rejects_unknown_severity`,
     `test_parse_sufficiency_response_rejects_unknown_gap_class`,
     `test_parse_sufficiency_response_rejects_short_description`.
   - (i) `run_sufficiency_audit` end-to-end with mocked dispatch +
     synthetic plan, asserts findings file path —
     `test_run_sufficiency_audit_writes_findings_file_to_pre_impl_path`,
     plus refuse-without-dispatch
     (`test_run_sufficiency_audit_without_dispatch_raises`) and
     fail-fast-on-contract-error
     (`test_run_sufficiency_audit_propagates_contract_load_failure`).

## Verification

| Check | Result |
| --- | --- |
| Pre-flight (F002 baseline) | 997 passed, 6 skipped |
| F003 module test suite | 22 passed |
| **Full orchestrate suite (post-F003)** | **1019 passed, 6 skipped** (= 997 + 22, zero regressions) |
| `ruff check` (F003 module + tests) | clean |
| `ruff format --check` (F003 module + tests) | clean |
| `python3 scripts/sanitization_check.py` | 0 findings (756 files scanned) |
| `claude/shared/**` diff | none — boundary preserved |
| `nested_orchestration.py` diff | none — boundary preserved |
| Other module diff | none — only `sufficiency_auditor.py` + its test file added |

## Vendor-resolution path (documentation)

The module never hardcodes `"codex"` or any vendor name in its
implementation. The full call chain at runtime is:

```
sufficiency_auditor._resolve_goal_auditor_agent(plan_dir, implementer_agent=...)
    └→ project_config.find_project_for_plan_dir(plan_dir)
       └→ project_registry.load_registry()  # registered DontPanic projects
    └→ project_config.resolve_dispatch_defaults(project_path)
       ├→ project_config.load_project_config(project_path)  # <project>/.dontpanic/dontpanic.json
       ├→ global_config.load_config()                       # ~/.dontpanic/config.json
       └→ FALLBACK_IMPLEMENTER='claude' / FALLBACK_AUDITOR='codex'  # last-resort defaults
    └→ same-vendor check: refuse unless DONTPANIC_GOAL_AUDITOR_ALLOW_SAME_VENDOR is truthy
```

The `agent_manifest.AgentManifest` schema does not currently carry an
`auditor` field; routing lives in `project_config` instead. F003
deliberately uses that surface (it is the canonical D004 precedence
chain shipped with the platform) rather than extending
`agent_manifest`. If a future plan introduces an `auditor` field on
the manifest, the resolution should keep the same precedence rule
(project config → manifest → global config → fallback) so this module
stays a thin caller.

## Queued for F004

- F004 wires the lock gate that consumes the JSON written here. The
  gate invokes `run_sufficiency_audit(plan_dir, implementer_agent=...,
  dispatch=<production dispatcher>)` and refuses to lock the plan when
  the returned findings include a high/critical severity gap unless
  the operator records an `--ignore-sufficiency-findings <reason>`
  override (per D011).
- F004 also surveys every plan-lock path (CLI, validator, MCP, direct
  helpers) per D011 so the gate engages once at every point that
  transitions a plan into a locked state — never bypassed.
- The dispatch seam is generic `Callable[[agent_name, prompt], str]`
  so F004 can plug in either the existing `BaseExecutor.dispatch_*`
  surface (full executor flow) or a thinner text-only call. No
  changes to `sufficiency_auditor.py` needed.
- Operator override of the same-vendor invariant (env var path)
  should be recorded in F004's lock-time evidence whenever set, per
  D006.

F003 produces findings; F004 decides what to do with them.
