"""Prompt templates for volley dispatch.

Implementer template (round 0): pure feature description.
Implementer template (round N≥1): includes prior auditor's findings, instructed
  to address each.
Auditor template: includes implementer's audit JSON path + git diff context, asks
  for findings list per audit.schema.json semantics.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def implementer_prompt(
    plan_id: str,
    plan_dir: Path,
    feature: dict[str, Any],
    iteration: int,
    prior_auditor_path: Path | None = None,
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
    if iteration == 0 or prior_auditor_path is None:
        return base + (
            "\nImplement the feature. Run any verification commands specified in steps.\n"
            "Reply with a concise paragraph (3-6 sentences) summarizing what you did and the outcome.\n"
            "Do NOT output JSON; the supervisor wraps your reply.\n"
        )

    findings_block = _findings_block(prior_auditor_path)
    return base + (
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
) -> str:
    steps = "\n".join(f"- {s}" for s in (feature.get("steps") or [])) or "(none specified)"
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
2. Inspect the actual code changes (run `git diff HEAD~1` or `git status` from {plan_dir.parent.parent}).
3. Run any tests/lints/checks the steps specify, or that you'd expect for this category of work.
4. Compare what was claimed against what was actually done.
5. List concrete findings — each with severity (critical|high|medium|low|advisory),
   category (correctness|security|performance|architecture|style|test_coverage|documentation),
   issue (one sentence), evidence (what you observed), recommendation (what to fix).

Reply with a concise paragraph that:
- States overall verdict (signed_off | needs_changes | blocked)
- Lists each finding inline with severity (e.g. "FINDING (high, test_coverage): ...")
- Mentions any tests/checks you actually ran

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


__all__ = ["implementer_prompt", "auditor_prompt"]
