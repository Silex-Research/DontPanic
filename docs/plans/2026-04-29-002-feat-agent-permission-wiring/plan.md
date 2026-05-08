---
id: 2026-04-29-002-feat-agent-permission-wiring
title: F005b — non-interactive permission policy for orchestrator-dispatched agents
type: feat
tier: local
status: completed
date: "2026-04-29"
description: |
  Add non-interactive permission policy to Claude and Codex CLI executors so the supervisor's subprocess dispatches don't deadlock on permission prompts. Currently `subprocess.run(['claude', '-p', ...])` and `subprocess.run(['codex', 'exec', '--json', ...])` pass no permission flags; with no TTY for an operator to type yes/no, any tool-use prompt blocks until the 600s timeout. Role-aware defaults: implementer can edit in cwd; auditor is read/check-only with prompts denied (not prompted) on out-of-allowlist requests. F023's resolved registry-repo cwd remains the containment boundary; the user's existing PreToolUse hooks (~/.claude/settings.json) are opportunistic defense-in-depth where present, not an OSS-boundary guarantee.
motivation: |
  This blocks #2026-04-29-001-feat-changelog-skill (the first supervised orchestrator dogfood) and every downstream dispatch that asks Claude or Codex to write files. The current orchestrator was tested on the F004 trivial plan (no real tool use) and on F005a-6 synthetic-disagreement (mocked executor) — meaning no real volley has ever been run. The first dispatch that asks an agent to write a file would hit the permission prompt and deadlock. Surfaced during #692-followup conversation 2026-04-29 when drafting the changelog dogfood lock.
agents_required:
  - claude
human_gates:
  - pre_impl
  - pre_merge
quota_caps:
  claude: 2
loop_caps:
  max_iterations: 0
  no_progress_threshold: 2
  wall_clock_hours: 4
  hard_stop: false
privacy_tier: internal
protected_paths:
  - claude/PORTABILITY.md
  - claude/scripts/sync-harness.sh
  - dashboard/state/costs.json
  - scripts/quota_check.py
  - scripts/maintainer/refresh-costs.sh
dependencies:
  - 2026-04-19-001-infra-cross-agent-orchestration
links:
  features: ./features.json
  decisions: ./decisions.jsonl
  audits_dir: ./audit/
  evidence_dir: ./evidence/
---

# F005b — non-interactive permission policy for orchestrator-dispatched agents

## Thesis

The supervisor's executors (`scripts/jarvis_orchestrate/executors/{claude_cli,codex_cli}.py`) currently invoke Claude and Codex with no permission policy. In non-interactive subprocess mode, the default permission prompts have no operator and either block until timeout or fail outright. F005b adds role-aware permission defaults wired into the executors so dispatch can actually complete on tasks that involve tool use. **No plan-level schema expansion** in this slice — defaults are hardcoded by role in the supervisor/executors. Plan-level override is deferred until a real dogfood proves we need it.

The first-class invariant: **all four (executor, role) combinations — Claude implementer, Claude auditor, Codex implementer, Codex auditor — must complete or fail-fast without prompting**, including when the agent attempts an action outside the role's allowlist.

## Design choices (locked unless noted)

1. **Role-defaults-in-executors, not plan-level allowlist (Option B+).** Schema-expanding a general allowlist before any real dogfood would be designing policy in the abstract. "Implementer can edit; auditor is read/check" is enough for the first dispatch, testable, and reversible.

2. **`DispatchTask.permission_policy` field as the contract surface.** The field is `Literal['implementer', 'auditor'] | None` (None = legacy / explicit no-policy for tests). Executors translate the role string into the right CLI flags.

3. **Don't reuse `environments.json.allowed_deploy_commands`.** That field is tier/deploy policy. Agent tool permissions are per-dispatch/per-role policy. Different lifecycles, different audiences. The two systems coexist cleanly.

4. **F023's resolved registry-repo cwd remains the containment boundary.** The supervisor sets `cwd=registry_repo_root` (verified in `supervisor.py`), not `plan_dir`. "Edit allowed within cwd" therefore means edit allowed within the resolved repo/workspace, NOT confined to the plan directory. The plan directory's protection comes from `protected_paths` declarations + command_guard's post-hoc audit, not from cwd narrowing.

5. **Hooks are opportunistic defense-in-depth, not acceptance-critical.** `~/.claude/settings.json` hooks (security-gate.sh, git-safety.sh) are inherited by `claude -p` invocations on the operator's machine, but they're workstation state. On a fresh clone or in CI they don't exist. F005b's correctness must hold without them. The real guarantees are: CLI permission flags, sandbox/cwd, executor tests, and post-hoc command_guard.

6. **Forbidden flags.** Three flags are explicitly forbidden, runtime-guarded, and tested:
   - Claude: `--dangerously-skip-permissions`
   - Claude: `--allow-dangerously-skip-permissions` (the enabling flag — also forbidden)
   - Codex: `--dangerously-bypass-approvals-and-sandbox`

   These shortcut the permission system entirely and would defeat both the role allowlist and any defense-in-depth layer. The check_forbidden_flags helper rejects them; tests assert no produced argv contains them.

7. **D001 partially resolved during lock-revise (2026-04-29):** Claude `--allowedTools` matcher syntax confirmed via `claude --help`: `"Bash(git *) Edit"` — space-asterisk inside the parentheses, not colon. My initial draft (`Bash(pytest:*)`) was wrong; correct form is `Bash(pytest *)`. The remaining sub-question (does `--permission-mode dontAsk` deny vs prompt for out-of-allowlist tools?) is verified in F002 impl smoke and recorded in decisions.

## Role specs (locked syntax; see D001 for any remaining behavioral verification)

### Claude implementer
```
claude -p --output-format json \
  --permission-mode acceptEdits \
  --allowedTools "Read Edit Write Bash"
```
- `acceptEdits` auto-allows Edit/Write inside cwd
- explicit `--allowedTools` enables Bash + Read alongside; broad Bash matcher acceptable for the first dispatch (narrowing deferred per D007)

### Claude auditor — **Read-only, no command execution**
```
claude -p --output-format json \
  --permission-mode dontAsk \
  --allowedTools "Read"
```
- **Read only.** No Bash matchers, no Edit, no Write.
- Rationale (D012): Claude has no OS-level sandbox available to the orchestrator. Allowing Bash via matcher patterns (even narrow ones like `Bash(pytest *)`) is not truly read-only — `pytest` writes caches, `python *` is arbitrary code execution, and matcher semantics may not block shell redirection. For a real read-only auditor we'd need an OS sandbox; that doesn't exist in this CLI. So Claude auditor is restricted to file-content review only. Test-execution and git-inspection auditing are Codex's job, where `--sandbox read-only` enforces at the OS level.
- Pairing implication: Claude auditor can do diff-and-content review against the implementer's output. It cannot run tests or execute commands. If a feature's acceptance requires "run tests and verify they pass," that audit must be performed by Codex, not Claude.

### Codex implementer
```
codex --ask-for-approval never --sandbox workspace-write exec --json <prompt>
```
- global flags **before** the `exec` subcommand (Codex CLI parses `-a` / `-s` globally)
- `workspace-write` sandbox = OS-level edit boundary
- `--ask-for-approval never` = no prompts; sandbox enforces

### Codex auditor — **read-only OS sandbox; can run commands that don't write**
```
codex --ask-for-approval never --sandbox read-only exec --json <prompt>
```
- `read-only` sandbox blocks any write attempt **at the OS level**, regardless of the command Codex tries
- can therefore run read-side commands (pytest --collect-only, git log/diff/status, grep, ls, cat) without write risk; the sandbox refuses any actual file mutation
- the right place for "run tests and verify they pass" auditing in the first dogfood

## Pairing recommendation for first dogfood

For the changelog dispatch (#2026-04-29-001), Claude=implementer, Codex=auditor. Reason: Codex's auditor role can actually run read-only commands (which the changelog skill's tests will need); Claude's auditor role is content-review-only and cannot exercise tests. Document this pairing in the dogfood lock as the F005b-recommended default.

## Out of scope

- Plan-level `permission_policy` override in features.json or plan.md frontmatter. Hardcoded role defaults are sufficient for the first dogfood.
- Narrowing the implementer's Bash allowlist beyond `Bash`. F023 cwd discipline + command_guard + (opportunistic) user hooks bound blast radius. Over-narrowing without dispatch evidence risks blocking legitimate operations.
- Capturing CLI version in DispatchResult. Audit_writer's current shape doesn't surface it; bolting it onto quota_consumed is a separate, smaller change. Out of scope for F005b.
- Gemini and Grok executors (don't exist yet).
- Modifying the supervisor's volley loop, INBOX, or other orchestrator components beyond setting `permission_policy` on DispatchTask.
- Replacing or modifying `~/.claude/settings.json` hooks.
- The 49 baseline resolver warnings.

## Risks

- **`dontAsk` actually prompts.** If `--permission-mode dontAsk` turns out to prompt on out-of-allowlist tools (against expectation), the auditor still hangs. Mitigation: F002 impl includes a smoke test that explicitly attempts an out-of-allowlist tool and asserts denial-without-prompt; failure here is a hard block on F005b ship.
- **Flag syntax drift between CLI versions.** The matcher syntax probed today may parse differently in older or newer releases. Mitigation: pin executor argv via test; capture CLI presence (`shutil.which`) and let the test environment determine version.
- **Codex `--full-auto` alternative.** Codex documents `--full-auto` as "low-friction sandboxed automatic execution" — a convenience alias. We're using the explicit `--ask-for-approval never --sandbox workspace-write` form for clarity (so the produced argv is self-documenting in transcripts) and for symmetric impl/auditor distinction.
- **Sandbox false positives.** `workspace-write` might block a legitimate operation we didn't anticipate (writing to /tmp, a sibling repo, etc.). Mitigation: dogfood will surface this; the failure mode is a clean dispatch error, not a security incident.
- **F005b can't be dogfooded via `jarvis orchestrate`.** Chicken-and-egg. Resolution: human-implemented this session; the changelog dogfood (#2026-04-29-001) is the first orchestrator run that exercises F005b's wiring on a real dispatch.

## Acceptance (this plan)

`signoff: true` only when:

- F001/F002/F003/F004 each `passes: true` with evidence.
- **Both dispatch paths derive permission_policy from agent_role.** `dispatch_volley` (the multi-agent build/audit loop) sets implementer/auditor on its DispatchTask constructions (lines ~1076-1083). `dispatch_single_agent` (single-shot dispatch with explicit `agent_role` parameter, lines ~246-359) derives permission_policy the same way. Unit tests cover both paths.
- **First-class invariant: all four (executor, role) paths complete or fail-fast without prompting AND assert sentinel write/no-write outcomes.** Specifically, with timeout=15s on each:
  - Claude implementer against a write-to-cwd task → exits success, sentinel file exists in cwd (proves tool use happened)
  - Claude auditor (Read-only) against a read-task asking for a file's content → exits success, response includes the read content (proves Read worked); no sentinel file created
  - Claude auditor asked to Edit → exits with denial; no TimeoutExpired; no sentinel file created
  - Codex implementer against a write-to-cwd task → exits success, sentinel file exists
  - Codex auditor against a read-task → exits success, response references read content; no sentinel file created
  - Codex auditor asked to write → exits with sandbox-deny; no TimeoutExpired; no sentinel file created
- "No timeout" alone is not sufficient — the success cases must show evidence the agent actually attempted tool use, and the deny cases must show the file was NOT created (sandbox/permission did its job).
- Unit tests assert exact argv for all 4 (executor, role) pairs against fake-binary path: 4 cases.
- Forbidden-flag guard test asserts none of the 3 forbidden flags appears in any produced argv across {implementer, auditor, None} × {Claude, Codex}, AND that `check_forbidden_flags(['claude', '--dangerously-skip-permissions'])` raises ValueError directly.
- `scripts/sanitization_check.py` + `scripts/jarvis_doctor.py --skip-auth` + resolver `validate.py` exit 0 (warnings-only baseline OK).
- All 187 existing `scripts/jarvis_orchestrate/tests/` regressions still pass.
- All 5 protected paths verified unchanged.

## Open decisions

See `decisions.jsonl`.

- **D001 (partially resolved 2026-04-29):** Claude `--allowedTools` matcher syntax confirmed as `Bash(pattern *)` (space-asterisk). Remaining sub-question: does `--permission-mode dontAsk` deny vs prompt for out-of-allowlist tools? Verified in F002 impl smoke; failure here blocks F005b ship.

## Target

```yaml
target_env: dev
target_project: <firebase-project-id>
```

## Provenance

Surfaced 2026-04-29 during #2026-04-29-001 (changelog dogfood) lock drafting. The dogfood would have deadlocked on the first tool-use prompt because no permission policy was wired. Diagnosis confirmed by reading `scripts/jarvis_orchestrate/executors/{claude_cli,codex_cli}.py` — zero matches for `permission`, `allowed`, `--ask-for-approval`, `--sandbox`. Lock revised after operator review noted (a) auditor `default` mode could still hang on out-of-allowlist tools, (b) cwd is registry_repo_root not plan_dir, (c) hooks are workstation-state not OSS guarantee, (d) D001 not yet resolved, (e) injection-test scaffolding was unnecessary, (f) acceptance was implementer-only, (g) version capture out of scope. All seven addressed in this revision.
