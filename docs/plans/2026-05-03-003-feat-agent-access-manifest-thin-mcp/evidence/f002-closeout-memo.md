# F002 close-out memo — 2026-05-04

Plan: `2026-05-03-003-feat-agent-access-manifest-thin-mcp`
Feature: F002 — Thin local MCP server: `dontpanic mcp serve`

## Volley path

F002 used the locked volley path from D010 because it exposes a new agent-callable
surface with security-sensitive defaults:

- exactly six tools, no `intake` tool (D002)
- local-only transport, no remote listener (D003)
- mutating tools dry-run by default and requiring `confirm: true` (D004)
- registry-only path validation, no CLI cwd fallback in MCP context (D005)
- stdout reserved for MCP JSON-RPC protocol, logs to stderr

The volley ended `stopped_no_progress` after two rounds. That terminal shape
does not reflect remaining F002 feature defects. Iteration 1 fixed the
substantive iteration-0 findings; the remaining iteration-1 needs_changes was
environmental and meta-envelope noise.

## Volley triage

| Iteration | Implementer state | Auditor verdict | Notes |
| --- | --- | --- | --- |
| i0 | 600s timeout / truncated envelope; real work landed on disk | `needs_changes` | 1 HIGH traversal/security finding, 2 MEDIUM test/format findings, 1 advisory untracked-file finding |
| i1 | Substantive findings fixed on disk | `needs_changes` | Auditor pytest aborted before collection because sandbox had no usable writable tempdir; stale i0 envelope inconsistency also flagged |

## Iteration-0 findings

| Finding | Class | Resolution |
| --- | --- | --- |
| HIGH security: relative `..` traversal could escape registered plan root | `feature_defect` | Fixed in `_resolve_safe_path`: relative candidates must satisfy `candidate.relative_to(root_resolved)` after resolution. |
| MEDIUM: missing traversal regression tests | `spec-clarification` | Fixed with 20 traversal refusal cases in `TestPathValidation::test_relative_path_traversal_refuses` (5 tools x 4 shapes). |
| MEDIUM: ruff format dirty files | `spec-clarification` | Fixed by running `ruff format`; format check is clean. |
| ADVISORY: F002 source/test files untracked | `already-known/env` | Fixed by staging the F002 source and test files. |

## Iteration-1 findings

The iteration-1 auditor result was not accepted as feature-blocking:

- pytest aborted before collection in the auditor sandbox with no usable
  writable tempdir. This is the known auditor-environment limitation, not a
  code defect.
- stale i0 envelope inconsistency was a meta-audit artifact from the timeout /
  truncated-envelope pattern. No audit envelope was edited post-hoc.

## What landed

| File | Change | Role |
| --- | --- | --- |
| `scripts/jarvis_orchestrate/mcp_server.py` | New JSON-RPC stdio MCP server module; exactly six tools; no `intake`; dry-run-default mutating tools; registry-only path resolver; evidence-tree confinement; stderr-only logging discipline | Core F002 module |
| `scripts/jarvis_orchestrate/cli.py` | Adds `mcp` subcommand routing and `_mcp_main()` for `dontpanic mcp serve` / tool introspection | CLI surface |
| `scripts/jarvis_orchestrate/agent_manifest.py` | `bootstrap_manifest()` detects F002 availability and populates `mcp_server: {command: "dontpanic", args: ["mcp", "serve"]}`; `supported_commands` includes `mcp` when importable | F001 manifest population required by F002 acceptance |
| `scripts/jarvis_orchestrate/tests/test_f002_mcp_server.py` | 77 F002 tests covering D002-D008 and the operator audit-focus addendum | Test surface |
| `scripts/jarvis_orchestrate/tests/test_f001_agent_manifest.py` | F001 ripple tests for manifest MCP population; 53/53 still green | Manifest regression surface |

## Verification

- Focused F001+F002 tests: **130/130 passed** (53 F001 + 77 F002).
- Full orchestrate suite excluding the known queued EC5 caveat:
  **825 passed, 6 skipped**.
- `ruff check` across F002-touched files: **All checks passed**.
- `ruff format --check` across F002-touched files: **5 files already formatted**.
- `python scripts/sanitization_check.py`: **0 findings, 614 files scanned**.
- Manifest population verified: `bootstrap_manifest()` emits
  `mcp_server: {command: "dontpanic", args: ["mcp", "serve"]}` and includes
  `mcp` in `supported_commands`.
- Tool surface verified: exactly six tools are registered and `intake` is
  absent.

## Acceptance mapping

| Acceptance | Evidence |
| --- | --- |
| exactly six tools; no `intake` | `mcp_server.tool_specs()` and `test_f002_mcp_server.py` negative tool-list assertions |
| mutating tools dry-run by default; `confirm: true` mutates | parametric tests over absent / false / true confirm values |
| local-only invariant | module exposes stdio JSON-RPC only; no HTTP/server framework import or non-loopback binding path |
| registry-only path validation | `_resolve_safe_path()` and traversal/out-of-tree tests |
| stderr-only logging | protocol tests and naked-print guard |
| manifest MCP block populated after F002 | amended F001 manifest tests |
| full suite remains green | direct-review sweep above, with known EC5 caveat excluded per D011 |

## Known caveats carried forward

The following are not F002 blockers and remain queued as separate platform
fixes:

- 600s subprocess timeout / envelope-flush risk. This recurred during the
  volley and should be addressed by a future timeout/checkpointed-envelope
  platform slice.
- `test_ec5_classifier.py::test_classifier_is_pure_no_io` remains broken
  post-directory-rename. It is excluded from the full-suite sweep per D011
  and should be fixed in its own platform slice.
- Lifecycle-staged gates are still not truly lifecycle-staged; pre_impl and
  pre_merge are evaluated upfront by the current supervisor.

## Files intentionally excluded

Pre-existing dirty files remain outside the F002 boundary, including
`CONTRIBUTING.md`, `claude/PORTABILITY.md`, changelog-skill plan artifacts,
`dashboard/state/costs.json`, and the pre-existing formatted
`scripts/jarvis_orchestrate/tests/test_f005b_permission_policy.py`.

The F002 commit boundary should include only F002 source/test changes,
F001/CLI ripples required by acceptance, volley audit artifacts for this plan,
and the close-out plan artifacts.

Generated `audit/gate-state.json` is preserved at
`evidence/f002-generated/gate-state.json` rather than under `audit/` because
the plan validator treats every non-signoff `audit/*.json` as an audit envelope.
