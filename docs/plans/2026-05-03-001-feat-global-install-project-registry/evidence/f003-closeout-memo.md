# F003 close-out memo — 2026-05-03

Plan: `2026-05-03-001-feat-global-install-project-registry`
Feature: F003 — per-project config (`<repo>/.jarvis/jarvis.json`) + override precedence (per-project > global > fallback) + `jarvis doctor` per-project preflight + `plans_dir` resolution wiring.

## Why F003 went via volley (and F001/F002 didn't)

F001 and F002 were direct-path: small, mechanical packaging/CRUD slices with deterministic acceptance and no risk to live dispatch behavior. F003 was different — it changes resolution behavior across multiple hot paths: `dispatch_volley`, `dispatch_single_agent`, `_resolve_plan_dir`, the doctor preflight. Precedence bugs in this layer can cause Jarvis to operate on the wrong repo or dispatch the wrong agent silently. That's exactly the class of defect adversarial review catches that single-pass implementation misses.

The volley earned its keep: it surfaced an unstaged-file defect (`project_config.py` not added to git initially), a missing test file, and the ruff issues. It did not surface bugs in the override precedence chain or the resolver — those were correct on the first pass.

## What landed

| File | Change | Role |
| --- | --- | --- |
| `scripts/jarvis_orchestrate/project_config.py` (new, ~360 lines) | Pydantic `ProjectConfig` (`extra='forbid'`), `load_project_config` (missing → None, invalid JSON → WARN+None, schema-violation → WARN+None), `resolve_dispatch_defaults` (per-project > global > fallback chain), `resolve_project_path` (registry-first name vs. path disambiguation), `find_project_for_plan_dir` (deepest-match registry lookup), `scaffold_empty_config` (for `jarvis projects add --init-config`) | Core F003 module |
| `scripts/jarvis_orchestrate/cli.py` (+~180 lines) | `_resolve_plan_dir` is project-aware: literal-path → cwd-anchored project → walk registry → gated `cwd/docs/plans` smoke-test fallback. `dispatch-from-plan` consults the resolver for defaults. `projects add --init-config` scaffolds an empty per-project config | CLI surface |
| `scripts/jarvis_orchestrate/supervisor.py` (+~95 lines) | `dispatch_volley` (line 581) and `dispatch_single_agent` (line 852) both consult `resolve_dispatch_defaults` when no explicit override is passed | Both agent-picker paths wired |
| `scripts/jarvis_doctor.py` (+~340 lines) | `--include-projects` flag adds per-registered-project preflight (path exists, jarvis.json parses, plans_dir exists, agents recognized, gates valid). `--strict-codes` selects the new 0/1/2 exit-code matrix. Bare invocation keeps the legacy 0/1 contract for backward compat | Doctor + `jarvis doctor` subcommand |
| `scripts/jarvis_orchestrate/plan_loader.py` (+~37 lines) | `load()` accepts an optional `plans_dir` override path, used by the resolver | Loader plumbing |
| `scripts/jarvis_orchestrate/tests/test_f003_project_config.py` (new) | 43 tests across `TestProjectConfigLoad`, `TestPrecedenceMatrix`, `TestResolveProjectPath`, `TestPlansDirWiring`, `TestDoctorPerProject`, `TestDoctorExitCodeMatrix`, `TestSingleAgentResolverParity` | Test surface |

## Volley terminal status — non-success that we are accepting on direct review

**Terminal:** `stopped_no_progress` after 2 rounds. Auditor verdict was `needs_changes` in both iterations; the no-progress breaker tripped because the verdict pattern was identical across rounds.

**Root cause:** **Both implementer iterations hit the supervisor's hardcoded 600s subprocess timeout.** Each `claude` CLI invocation produced full F003 implementation work on disk before the wrapper killed it; only the audit envelope JSON didn't get to flush. The supervisor recorded `audit_status: blocked` with `summary: DISPATCH FAILED: TimeoutExpired`. The codex auditor then correctly flagged the broken envelopes as not being valid completion artifacts — but the implementation itself was sound.

**Why we accept the work despite the terminal status:**
1. The 43-test F003 suite is **fully green**, written by claude as part of the implementation pass.
2. The full orchestrate suite is **702 passed, 6 skipped** (baseline 659 + 43 F003).
3. `ruff check` is clean across all F003-touched files.
4. Sanitization is clean (591 files scanned, 0 findings).
5. The acceptance contract is independently verifiable from on-disk state, not dependent on the audit envelope.
6. The diff review for the 6 high-risk audit-focus areas (below) all check out.

Re-dispatching the volley to chase a clean `signed_off` envelope would not change the on-disk state — the implementation is already correct. It would only burn quota cycles to chase a platform artifact.

## Pre-flip diff review (operator-side, the 6 high-risk areas)

| # | Area | Verdict |
| --- | --- | --- |
| 1 | No unsafe `Path.cwd()` fallback | `cli._resolve_plan_dir` Step 4 (`cwd/docs/plans/<arg>`) is a **gated** smoke-test carveout — fires only when (a) registry-based resolution fails AND (b) the literal directory exists. Cannot silently pick up a stray plan from another registered project (those are caught by Step 2/3). Documented as deliberate; recorded in caveats below |
| 2 | per-project > global > fallback precedence | `resolve_dispatch_defaults` walks the chain explicitly with `or` operators. Each layer's None falls through to the next. Pinned by `TestPrecedenceMatrix` (4 cells: per-project set/unset × global set/unset, plus all-None → fallback) |
| 3 | Project name vs. path confusion | `resolve_project_path` is **structural, not heuristic**: registry-first name lookup, then path-shape detection that requires an explicit `/`, `~`, or `.` to be considered path-shaped. Bare names that aren't in the registry refuse to resolve to a coincident cwd directory. Pinned by `TestResolveProjectPath::test_registered_name_wins_over_coincident_directory` |
| 4 | None vs. missing config values | Explicit design choice documented in `resolve_dispatch_defaults`: "A field set to None (or absent) at one layer falls through to the next layer. There is intentionally no way to express 'explicitly None, don't fall through'." Pinned by `test_explicit_null_implementer_treated_as_no_override` |
| 5 | Both dispatch paths use the resolver; approve/resume parity | `dispatch_volley` (sup:581) and `dispatch_single_agent` (sup:852) both call `resolve_dispatch_defaults`. **`approve` and `resume` are deliberately NOT wired through the resolver** — they clear gates, they don't pick agents. Rationale documented in test docstring (`Audit-focus addendum (7)`) so the no-coverage-needed decision is auditable. ✓ |
| 6 | Doctor warnings/exits match locked acceptance | `compute_strict_exit` parametric matrix: all PASS → 0, any WARN → 1, any FAIL → 2. Matches the locked acceptance "exit code: 0 if all PASS, 1 if any WARN, 2 if any FAIL" literally. Bare `scripts/jarvis_doctor.py` invocation keeps the legacy 0/1 contract for backward compatibility (AC5). Pinned by `TestDoctorExitCodeMatrix` |

The auditor's i1 finding asking for WARN to NOT exit non-zero is a **spec-clarification disagreement** — the auditor disagreed with the locked spec. Per scope discipline, we honor the spec; if the spec is wrong, that's a separate ticket, not an F003 amendment.

## Caveats recorded for future plans

1. **Gate semantics: `pre_merge` is currently an upfront admission gate, not a post-implementation lifecycle gate.** F003's `human_gates: [pre_impl, pre_merge]` are evaluated as one upfront set; both had to be cleared before iteration 0 ran. The operator manually reviewed the diff post-volley before this commit, treating the operator-side review as the real merge gate for this run. **Lifecycle-staged gates remain a queued platform improvement, not part of F003's scope.**

2. **600s subprocess timeout is too short for cross-cutting features.** Both F003 implementer iterations timed out at the supervisor's hardcoded 600s deadline. Claude finished the implementation but not the audit-envelope flush. **A separate platform slice should raise this cap (perhaps to 1800s) and/or move audit-envelope writes to checkpoint-as-you-go rather than end-of-run.** The current behavior produces "work done, envelope blocked" terminals that look worse than they are.

3. **Step-4 cwd fallback in `_resolve_plan_dir`.** Deliberate smoke-test carveout for un-registered repos: if the operator runs `jarvis dispatch <plan-id>` from a repo that isn't yet in the registry, the resolver will still find `<cwd>/docs/plans/<plan-id>` if it exists. This makes the bare `jarvis` invocation usable before any registry entry exists, which keeps the F001/F002/F003 onboarding flow ergonomic. The risk is bounded: it can only pick up a real existing dir, never a stray. Documented in the function docstring.

4. **`approve` / `resume` are not wired through the resolver.** Those CLI surfaces clear gates; they don't pick agents. The resolver is for agent-picking call paths only. If a future feature adds agent-aware behavior to approve/resume (e.g., per-gate agent attribution), the resolver should be wired in then. Documented in the test file.

## Verification

- `PYTHONPATH=scripts python -m pytest scripts/jarvis_orchestrate/tests/test_f003_project_config.py` — **43 passed in 1.57s**.
- `PYTHONPATH=scripts python -m pytest scripts/jarvis_orchestrate/tests/` (full orchestrate suite) — **702 passed, 6 skipped in 11.06s**. Baseline before F003 was 659 + 6 skipped; +43 F003 tests = 702 with no regressions.
- `ruff check` on all F003-touched files — **All checks passed** (after 2 auto-fixes for I001 import-order + 1 manual fix for F841 unused variable + 1 auto-fix for B009 idiom).
- `python scripts/sanitization_check.py` — **0 findings, 591 files scanned**.
- features.json validates against `agent-conventions/schemas/v1.0/features.schema.json` Pydantic model.
- All 6 high-risk audit-focus areas reviewed and signed off (table above).

## What's NOT in this commit

- The unrelated pre-existing modifications to `CONTRIBUTING.md`, `dashboard/state/costs.json`, `claude/PORTABILITY.md`, the `2026-04-29-001-feat-changelog-skill/` plan dir's audit + INBOX + evidence files, the `2026-04-30-001-fix-quota-tracker-vendor-native/plan.md` line edit, and modifications to `test_f005b_permission_policy.py` — those are carryover from prior sessions, not F003's work.
- The untracked plan directory `docs/plans/2026-05-03-002-infra-personal-openclaw-axiom-jarvis/` and other untracked plan/skill scaffolding — those predate this volley and represent independent in-progress work.
- Doc edits to `docs/PRODUCT.md` / `docs/ROADMAP.md` / new `docs/ECOSYSTEM.md` for the OpenClaw repositioning — explicitly deferred per operator direction; they land as a separate strategic-doc plan after F003 closes.

## Pointers for follow-up plans

- **Lifecycle-staged gates plan**: change supervisor gate evaluation from "upfront set" to "lifecycle-staged" so `pre_impl` blocks before iteration 0 and `pre_merge` blocks before signoff (not both upfront). One bounded slice; tests already exist in `gate_pause` / `engagement` modules to extend.
- **Subprocess timeout + checkpoint-as-you-go plan**: raise the 600s cap (or make it configurable per plan) and refactor `audit_writer` to checkpoint partial state during long-running implementer runs so a timeout produces partial-but-readable envelopes instead of a `blocked` terminal.
- **Strategic doc edits plan** (OpenClaw repositioning): update `docs/PRODUCT.md` with the explicit positioning, rewrite `docs/ROADMAP.md` Phase B as "Agent Access Manifest + Thin MCP Surface" using the locked `~/.jarvis/agent-manifest.json` decision, add `docs/ECOSYSTEM.md` for the OpenClaw-as-caller pattern.
- **Phase B implementation plan**: agent-manifest writer module + thin MCP surface, mirroring F001/F002/F003 module patterns.
