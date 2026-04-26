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
Feature: {feature['id']}
Description: {feature['description']}
Acceptance: {feature['acceptance']}

Steps:
{steps}
"""
    target_section = _target_block(target_env, target_project) if target_env is not None else ""

    if iteration == 0 or prior_auditor_path is None:
        return base + target_section + (
            "\nImplement the feature. Run any verification commands specified in steps.\n"
            "Reply with a concise paragraph (3-6 sentences) summarizing what you did and the outcome.\n"
            "Do NOT output JSON; the supervisor wraps your reply.\n"
        )

    findings_block = _findings_block(prior_auditor_path)
    return base + target_section + (
        f"\nPrior round's auditor produced findings (full JSON at {prior_auditor_path}):\n"
        f"{findings_block}\n"
        "Address each finding. Make code changes as needed. Run verification commands.\n"
        "Reply with a concise paragraph naming each finding ID and how you addressed it.\n"
        "Do NOT output JSON; the supervisor wraps your reply.\n"
    )


def auditor_prompt(
    plan_id: str,
    plan_dir: Path,
    feature: dict[str, Any],
    iteration: int,
    implementer_audit_path: Path,
    target_env: str | None = None,
    target_project: str | None = None,
) -> str:
    steps = "\n".join(f"- {s}" for s in (feature.get("steps") or [])) or "(none specified)"
    target_section = _target_block(target_env, target_project) if target_env is not None else ""
    project_line = target_project if target_project is not None else "(none)"
    return f"""You are the auditor for plan {plan_id}, iteration {iteration}.

Plan directory: {plan_dir}
Feature: {feature['id']}
Acceptance: {feature['acceptance']}

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
5. Run any tests/lints/checks the steps specify, or that you'd expect for this category of work.
6. Compare what was claimed against what was actually done.
7. List concrete findings — each with severity (critical|high|medium|low|advisory),
   category (correctness|security|performance|architecture|style|test_coverage|documentation),
   issue (one sentence), evidence (what you observed), recommendation (what to fix).
{target_section}
Reply with a concise paragraph that:
- Begins with your own {{Repo, Env: {target_env}, Project: {project_line}}} declaration block.
- States overall verdict (signed_off | needs_changes | blocked).
- Lists each finding inline with severity (e.g. "FINDING (high, test_coverage): ...").
- Mentions any tests/checks you actually ran with `$ ` line prefixes.

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
    "FORBIDDEN_COMMAND_PATTERNS",
    "REQUIRED_FLAG_PATTERNS",
    "implementer_prompt",
    "auditor_prompt",
]
