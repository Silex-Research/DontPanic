"""Prompt templates for volley dispatch.

Implementer template (round 0): pure feature description.
Implementer template (round N≥1): includes prior auditor's findings, instructed
  to address each.
Auditor template: includes implementer's audit JSON path + git diff context, asks
  for findings list per audit.schema.json semantics.

F023 EC5 (Step 3): both templates require agents to declare {repo, env, project}
at the top of the response and prefix every side-effect command with `$ ` so the
supervisor can extract commands_run for post-hoc command_guard validation. The
forbidden-command list is copied into both prompts so agents pre-emptively refuse
process-global mutators (gcloud config set project, firebase use, etc.).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# F023 EC3/EC9: kept in sync with command_guard._reject patterns. Update both
# when adding a new forbidden CLI shape so prompt + post-hoc check agree.
FORBIDDEN_COMMAND_PATTERNS = [
    "gcloud config set project ...",
    "gcloud config configurations activate ...  (without isolated CLOUDSDK_CONFIG)",
    "firebase use [...]",
    "kubectl config use-context ...",
    "gh auth switch",
    "npm/yarn/pnpm config set ...",
    "npm/yarn/pnpm config set registry ...",
    "git config --global ...",
    "git push --force ... main|master  (or -f to those branches)",
    "docker context use ...",
]


# F023 EC11+EC12: positive-flag-required CLI shapes the supervisor will reject
# post-hoc if invoked without their required flags. Kept aligned with
# command_guard.check_required_flags() — update both when changing.
REQUIRED_FLAG_PATTERNS = [
    "firebase deploy ...  → must include `--project <project_id>`",
    "xcodebuild build|archive|test ...  → must include `-scheme <X> -configuration <Y> -destination <Z> -derivedDataPath <P>`",
    "gradle assemble*|bundle*|test|publish ...  → must include `--gradle-user-home <DIR>` plus an explicit flavor/buildType",
    "terraform apply|plan|destroy ...  → must include explicit `-state` or workspace selection (`terraform workspace select <NAME>` first) and explicit `-backend-config=`",
    "kubectl apply|delete|edit ...  → must include `--context <CTX>`",
]


# F003 / D005 / D010: narrow EC5 severity rule. Embedded in auditor prompts
# (no agent retraining) AND defensively re-enforced by ec5_classifier at
# finding-aggregation time, so vendors slow to internalize the rule still
# produce correct severity. Update this constant when the narrow-downgrade
# semantics change; ec5_classifier.classify_ec5_severity must agree.
TEST_DISCIPLINE_NOTE = """
## Test discipline (v3 F002 cost control)

Prefer targeted tests over full sweeps. Each subsequent agent turn re-reads
prior tool-call results from cache, so a 1800-line `pytest -q` output bloats
every later turn's input. Default cadence:
  - Iteration runs: run the targeted test file you added/changed (`pytest path/to/test_x.py -q`).
  - Before claiming completion: one full sweep if and only if acceptance
    explicitly requires it (e.g. "full orchestrate sweep stays green"). One
    sweep at the END suffices — do not re-run.
  - Never run `pytest -v` unless you need the per-test trace to debug a
    specific failure.

"""


STAGING_NOTE = """
## Stage what you write (patch-completeness gate)

Before you reply, `git add` every file you created or modified. Staging is not
committing — it does not create a commit and does not touch history.

The supervisor runs a patch-completeness gate at signoff. A new test file left
untracked, or a source module the tests import that nobody staged, blocks the
flip to `passes: true` — a fresh clone would not run your test. Nobody else can
stage for you: the operator's last action ended before your files existed, and
the gate runs after your round.

  $ git add <the files you touched>
  $ git status --short   # nothing you wrote should be left as ?? or ` M`

Do NOT `git add` unrelated pre-existing dirty files, and do NOT commit.
"""

EC5_AUDITOR_RULE = """
EC5 severity rule (target-context prelude — narrow downgrade, F003 / D005):

File a HIGH or higher EC5 (target.context.prelude) finding ONLY when one of:
  (i)  target_context is missing, has empty/invalid `env` or `project`
       alongside non-empty `commands_run`, or `commands_run` is non-empty
       without target metadata; OR
  (ii) the prose prelude is present AND its values disagree with the
       structured target_context (e.g. prelude says `Env: prod` while
       struct says `env=dev`) — this is a value-mismatch, kept as a real
       blocker.

For a missing or structurally-malformed prelude with VALID structured
target_context, file at most an `advisory` (i0-class, format-only) finding
— the platform writer (F002) auto-injects the canonical prelude on next
persist, so the format gap is transient. NEVER downgrade based on struct
validity alone; value-mismatches are real findings even when struct is
valid. The supervisor's ec5_classifier defensively reapplies this rule at
finding-aggregation, so a misclassified i1 will be downgraded to advisory
and the description preserved verbatim.
"""


def _target_block(target_env: str | None, target_project: str | None) -> str:
    """Render the F023 EC5 declaration + accountability rules used by both prompts."""
    project_line = (
        f"target_project = `{target_project}`"
        if target_project is not None
        else "target_project = (host-local — no cloud project; declare `Project: (none)`)"
    )
    forbidden = "\n".join(f"  - {p}" for p in FORBIDDEN_COMMAND_PATTERNS)
    required = "\n".join(f"  - {p}" for p in REQUIRED_FLAG_PATTERNS)
    return f"""
## Target accountability (F023 EC5)

Dispatched target:
  target_env = `{target_env}`
  {project_line}

Before any side-effect tool call, declare in your reply:
  Repo: <name>
  Env: {target_env}
  Project: {target_project if target_project is not None else "(none)"}
  Command: <the exact command you intend to run>

List every side-effect command you actually invoked, one per line, prefixed with
`$ ` (standard shell prompt). The supervisor extracts these into the audit's
target_context.commands_run for post-hoc validation. Example:

  $ gcloud services list --project={target_project or "PROJECT"}
  $ firebase deploy --project {target_project or "PROJECT"} --only hosting

Forbidden command shapes (the supervisor will downgrade or block your audit if
any of these appear in commands_run — use the explicit-flag equivalent):
{forbidden}

Required-flag command shapes (the supervisor will downgrade or block your audit
if these binaries appear in commands_run without the listed flags). EC11 cwd
discipline: the supervisor sets your cwd to the consumer repo root when an
environments.json registry resolves; rely on `--project`/`-scheme`/`--context`
flags rather than ambient state, and never re-cd inside the agent shell:
{required}
"""


def implementer_prompt(
    plan_id: str,
    plan_dir: Path,
    feature: dict[str, Any],
    iteration: int,
    prior_auditor_path: Path | None = None,
    target_env: str | None = None,
    target_project: str | None = None,
) -> str:
    steps = "\n".join(f"- {s}" for s in (feature.get("steps") or [])) or "(none specified)"
    base = f"""You are the implementer for plan {plan_id}, iteration {iteration}.

Plan directory: {plan_dir}
Feature: {feature["id"]}
Description: {feature["description"]}
Acceptance: {feature["acceptance"]}

Steps:
{steps}
"""
    target_section = _target_block(target_env, target_project) if target_env is not None else ""

    if iteration == 0 or prior_auditor_path is None:
        return (
            base
            + target_section
            + TEST_DISCIPLINE_NOTE
            + STAGING_NOTE
            + (
                "\nImplement the feature. Run any verification commands specified in steps.\n"
                "Reply with a concise paragraph (3-6 sentences) summarizing what you did and the outcome.\n"
                "Do NOT output JSON; the supervisor wraps your reply.\n"
            )
        )

    findings_block = _findings_block(prior_auditor_path)
    return (
        base
        + target_section
        + TEST_DISCIPLINE_NOTE
        + STAGING_NOTE
        + (
            f"\nPrior round's auditor produced findings (full JSON at {prior_auditor_path}):\n"
            f"{findings_block}\n"
            "Address each finding. Make code changes as needed. Run verification commands.\n"
            "Reply with a concise paragraph naming each finding ID and how you addressed it.\n"
            "Do NOT output JSON; the supervisor wraps your reply.\n"
        )
    )


def auditor_prompt(
    plan_id: str,
    plan_dir: Path,
    feature: dict[str, Any],
    iteration: int,
    implementer_audit_path: Path,
    target_env: str | None = None,
    target_project: str | None = None,
    verification_block: str = "",
) -> str:
    steps = "\n".join(f"- {s}" for s in (feature.get("steps") or [])) or "(none specified)"
    target_section = _target_block(target_env, target_project) if target_env is not None else ""
    project_line = target_project if target_project is not None else "(none)"
    return f"""You are the auditor for plan {plan_id}, iteration {iteration}.

Plan directory: {plan_dir}
Feature: {feature["id"]}
Acceptance: {feature["acceptance"]}

Steps required:
{steps}

The implementer just claimed completion. Their audit JSON is at:
  {implementer_audit_path}

Your job:
1. Read the implementer's audit summary at the path above.
2. Verify the implementer declared {{Repo, Env: {target_env}, Project: {project_line}}}
   correctly in their summary; if a declaration is missing or mismatched, raise a
   FINDING (high, correctness) — the supervisor will also catch this post-hoc.
3. Inspect target_context.commands_run in the implementer audit; flag any
   forbidden command shapes (see list below).
4. Inspect the actual code changes (run `git diff HEAD~1` or `git status` from {plan_dir.parent.parent}).
5. Judge the regression the SUPERVISOR ran for you (section below). Your sandbox is
   read-only, so you cannot execute tests — do not claim you did, and do not treat
   an absent or non-passing run as if it were green.
6. Compare what was claimed against what was actually done.
7. List concrete findings — each with severity (critical|high|medium|low|advisory),
   category (correctness|security|performance|architecture|style|test_coverage|documentation),
   issue (one sentence), evidence (what you observed), recommendation (what to fix).

{verification_block}
{target_section}
{EC5_AUDITOR_RULE}
Reply with a concise paragraph that:
- Begins with your own {{Repo, Env: {target_env}, Project: {project_line}}} declaration block.
- States overall verdict (signed_off | needs_changes | blocked).
- Lists each finding inline with severity (e.g. "FINDING (high, test_coverage): ...").
- Cites the supervisor's regression run by status, and any read-only checks you
  performed yourself with `$ ` line prefixes.

Do NOT output JSON; the supervisor extracts findings from your prose and wraps the result.
"""


def _findings_block(audit_path: Path) -> str:
    """Render auditor findings list as compact text for the next implementer's prompt."""
    try:
        data = json.loads(audit_path.read_text())
    except (OSError, json.JSONDecodeError):
        return "(could not read audit file)"
    findings = data.get("findings") or []
    if not findings:
        return f"(audit_status: {data.get('audit_status', 'unknown')}, no structured findings; see summary in audit file)"
    lines = []
    for f in findings:
        sev = f.get("severity", "?")
        cat = f.get("category", "?")
        issue = f.get("issue", "(no issue text)")
        rec = f.get("recommendation", "")
        line = f"  - [{sev}, {cat}] {issue}"
        if rec:
            line += f"  →  {rec}"
        lines.append(line)
    return "\n".join(lines)


__all__ = [
    "EC5_AUDITOR_RULE",
    "FORBIDDEN_COMMAND_PATTERNS",
    "REQUIRED_FLAG_PATTERNS",
    "TEST_DISCIPLINE_NOTE",
    "auditor_prompt",
    "implementer_prompt",
]
