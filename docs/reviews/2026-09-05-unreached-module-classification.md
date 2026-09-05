# Unreached-module classification — 2026-09-05

Scope: every module under `scripts/dontpanic_orchestrate/` that the `dontpanic`
CLI never imports, statically or transitively, plus the planner slot of the
design-review volley. Static reachability was the starting filter only; each
row records the intended consumer, whether the promised behavior is enforced
or covered elsewhere, and what public-entry-point evidence exists. This is an
assessment. No runtime files were changed.

Method: AST import graph rooted at `cli.py` over 212 package modules
(191 reached, 21 not). For each unreached module: docstring, originating plan
and decisions, test files, and a grep for dynamic or non-Python callers
(Makefile, CI, skills, docs).

## Findings that bound the classification

**Dispatch safety is enforced without the guard.** Both dispatch paths call
`worker_profiles.resolve_worker`, which accepts only an executor-registry key
or a profile bound to one and raises otherwise. The supervisor calls it for
both slots before paid work (`supervisor.py:1885`); the dry-run wrapper calls
it at `cli.py:3198` and exits 3 on refusal. Config writes go through
`agent_surface.assert_registrable`, also registry-only. Nothing on that chain
reads `operator_roles`; the only readers are the roles module, the dashboard
and console renderers, and the unused guard. Public-entry evidence exists for
the config side (`roles set` and `register-worker` refusal tests) but not the
dispatch side: the four exit-3 dispatch-from-plan tests cover calibration,
config, and state blocks, none seeds an operator role for a non-executor and
then dispatches.

**The conventions CLI path misses matched-skill checks.** `plan-review` runs
the F005 disposition check over declared surfaces and the ledger only, and
skips when no surfaces are declared. Skill matching runs at `plan lock` but
only writes an advisory sidecar. No code turns a matched skill into an
expected ledger item; the ledger has no skill items. The F006 bridge in
`conventions_gate.py` is deferred integration, not redundancy.

**The audit envelope cannot support process judgments.** Commands reach the
envelope by regex over the implementer's prose summary (`$ <cmd>` lines the
prompt asks for; `audit_writer.py:139`). The supervisor's target context
carries env and project only. There is no exit status, timestamp, or link to
the harness invocation; the subprocess runner's exit code is for the harness
process, not the commands the implementer ran. The judge can at best
establish "test claimed invoked", never "completed" or "passed". It also
reads `commands_run` at the envelope top level while the writer nests it
under `target_context`, so wired unchanged it would report violations on
every envelope.

**Runtime evidence has no integrated capture trigger.** Plan G locked the
harness library-only (F005: "no MCP wrap per locked answer #2"); Plan F2
locked the completion auditor read-only (D009). Nothing in DontPanic calls
`EvidenceCollector.collect`. This does not mean the manifest is empty:
operators or external tools may write artifacts under
`evidence/goal-governance/post_impl/<source>/<journey>/`, and the auditor
reads whatever is there. The supported conclusion is only that DontPanic
lacks an integrated trigger for its own capture adapters. Wiring them into
the reader would violate the designed separation.

## Classification

| Module | Promised behavior | Intended consumer | Covered or enforced elsewhere | Public-entry evidence | Disposition |
|---|---|---|---|---|---|
| `dispatch_safety_guard` | D009: operator roles never grant dispatch (plan 2026-06-14-001 F006) | Dispatch chokepoint | Yes: `resolve_worker` and `assert_registrable` are registry-only | Config side yes; dispatch side none | Redundant / test support. Add one dispatch-from-plan test with a preference-only surface. |
| `process_behaviors` | Judge test-ran, declaration, cross-vendor, commands-recorded off envelopes (plan 2026-08-12-001 F006) | Volley consumer per that plan's D009 | No | None; fixture tests only | Deferred integration. Blocked on envelope-path fix and on command-execution evidence (identity, exit status, invocation linkage). |
| `conventions_gate` | Matched skills become expected ledger items (plan 2026-06-05-004 F006) | `plan-review` / `plan lock` | Partial: surface dispositions yes, skill items no | None | Deferred integration. D013 close-out describes the module, not the CLI. |
| `runtime_evidence/` (init, agent_sources, android, backend, harness, ios, web) | Capture journey evidence into `post_impl/<source>/<journey>/` (plan 2026-05-06-001) | A capture step upstream of the completion auditor | No integrated trigger; auditor reads whatever is on disk | None | Deferred integration, separate design. Must not be wired into the reader (F2 D009). |
| `config/doctor_registry` | Pluggable doctor checks (Plan G F006) | `dontpanic doctor` | No: doctor uses the standalone script's checks (Python, gcloud, Firebase auth), never `run_all_checks`; simctl, adb, and harness checks register only when adapters import, which never happens | None | Deferred integration. Wire `run_all_checks` into doctor and import the adapters, or drop. |
| `architecture_regen` | Debounced watch-and-regen daemon inside `dashboard serve` (plan 2026-06-04-004 F006) | Serve loop | Partial: `dashboard.py:812` regens directly on build; supervisor post-commit hook regens via `architecture.regen` | None; F006 marked passing on engine tests | Misleading completion signal. Decide serve-loop daemon or reclassify F006 as component-only. |
| `plan_review/design_review` planner slot | Planner revises decomposition on `needs_changes` (plan 2026-06-01-001 F005) | `plan lock --design-review` | No | Auditor side yes; planner none | Deferred, separate design and explicit authorization: validate returned plan, persist with diff and history, invalidate approvals and evidence, bound cost. |
| `doc_drift` | README and capability matrix never claim unshipped executors (plan 2026-07-27-001 F002) | Test suite | n/a | Test over real docs with fixed allowlist | Delivered as a test-time guard. |
| `upgrade_drift_lint` | CHANGELOG vs `releases.json` drift, advisory | Release author, ad hoc | `doctor --upgrade` does not call it; `docs/upgrade/README.md` documents `python -m` | Standalone `main` | Delivered standalone. Optional doctor integration. |
| `graders`, `smoke/suites`, `smoke/corpus` | Eval regression and capability suites | CI | n/a | `scripts/run-eval-suite.sh` in `.github/workflows/ci.yml` | Integrated via a workflow entry point. Not currently operating: GitHub Actions is disabled on the repo, so the integration exists but produces no signal until re-enabled. |
| `firebase_client`, `smoke_test_storage` | Firebase Admin wrapper; storage upload smoke | `claude/skills/revenue-check`, legacy shim | n/a | Skill and shim tests | Reusable internal component. |
| `adapters/linear_adapter` | Dogfood shim over `integrations.linear_pp_adapter` | None; CLI has no `linear` command | Canonical module reachable but also uncalled from the CLI | Smoke test only | Candidate obsolete. Confirm whether any Linear surface is still planned. |

## Completion-record status

Three rows carry misleading completion signals: the conventions gate, the
architecture daemon, and the runtime-evidence capture path. Each is marked
`passes: true` on a plan whose acceptance text names a CLI or serve-loop
behavior no test drives. The dispatch guard is the opposite case: an
invariant that holds without the module.

Recommended handling: preserve the historical decisions as written and
append a correction to each affected plan's `decisions.jsonl` distinguishing
"component complete" from "integrated capability complete". This keeps the
audit trail intact while making current status honest. Going forward, an
integrated feature should count as complete only when a test drives it
through the public entry point.

## Priority

1. Dispatch regression test: seed `operator_roles.primary_operator = cursor`
   and `roles.implementer = cursor` directly in config, run
   `dontpanic dispatch-from-plan`, assert exit 3. Establishes the missing
   proof with no new code.
2. Conventions bridge: call `conventions_gate.evaluate_plan_dispositions`
   from the `plan-review` path with the applicable-skills sidecar as
   `matched_skills`. Completes an existing promise.
3. Doctor integration: import the runtime-evidence adapters and run
   `doctor_registry.run_all_checks` from `dontpanic doctor`. Completes an
   existing promise.
4. Command-execution evidence: a harness-recorded command log with command
   identity, exit status, and volley-iteration linkage. Precedes any
   process-judgment wiring, and must distinguish test invoked, test
   completed, and test passed.
5. Capture orchestration and planner-driven plan revision: separate designs,
   separately authorized.

Related: `docs/plans/2026-06-01-001-feat-plan-review-scope-validation/decisions.jsonl`
D019 and D020 record the wiring decision and the operator-verified close that
this review revisits.
