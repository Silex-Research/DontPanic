"""Supervisor — orchestration entry points.

F004: dispatch_single_agent — one agent, one shot.
F005a: dispatch_volley — implementer/auditor pair, iterate until signoff or cap.

Both read ~/.jarvis/quota_state.json before each dispatch (F020 gate) and
soft-warn at >=90%; flip JARVIS_QUOTA_ENFORCE=hard to raise QuotaExceeded.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jarvis_orchestrate import audit_writer, plan_loader, prompts, transcript
from jarvis_orchestrate.execution_environment import ExecutionEnvironment
from jarvis_orchestrate.executors import ClaudeCLIExecutor, get_executor
from jarvis_orchestrate.executors.base import BaseExecutor, DispatchTask

QUOTA_STATE_PATH = Path.home() / ".jarvis" / "quota_state.json"
SOFT_THRESHOLD_PERCENT = 90.0


class QuotaExceeded(RuntimeError):
    pass


def _read_quota_state() -> dict | None:
    if not QUOTA_STATE_PATH.is_file():
        return None
    try:
        return json.loads(QUOTA_STATE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _quota_gate(agent: str) -> tuple[float | None, str]:
    """Returns (percent_weekly, decision_log_line). Raises QuotaExceeded if hard-blocked.

    F020 acceptance: 'supervisor reads ~/.jarvis/quota_state.json before every dispatch'.
    """
    state = _read_quota_state()
    if state is None:
        return None, "[quota] no state file — skipping gate (run scripts/quota_check.py)"

    info = (state.get("models") or {}).get(agent) or {}
    pct = info.get("percent_weekly")
    enforce = os.environ.get("JARVIS_QUOTA_ENFORCE", "soft").lower()

    if pct is None:
        return None, f"[quota] {agent}: unmetered or no cap ({info.get('plan', '?')})"

    line = f"[quota] {agent}: {pct}% of weekly cap ({info.get('plan', '?')})"
    if pct >= SOFT_THRESHOLD_PERCENT:
        if enforce == "hard":
            raise QuotaExceeded(
                f"{agent} weekly quota at {pct}% ≥ {SOFT_THRESHOLD_PERCENT}% — "
                f"set JARVIS_QUOTA_ENFORCE=soft (default) to log-and-proceed."
            )
        line += f"  ⚠ above {SOFT_THRESHOLD_PERCENT}% soft threshold (proceeding)"
    return pct, line


def dispatch_single_agent(
    plan_dir: Path,
    feature_id: str,
    agent_role: str = "implementer",
    iteration: int = 0,
    target_env: str | None = None,
    target_project: str | None = None,
) -> Path:
    """F004 path: dispatch one agent (Claude), produce + validate audit JSON.

    F023 Step 1 (EC9 + EC10): wraps the dispatch in an ExecutionEnvironment so
    the subprocess inherits an isolated CLI-state namespace, not ambient shell
    state. target_env / target_project remain optional until EC2 lands a plan-
    level Target contract; when unset, isolation still applies but no project
    label is injected into the subprocess env.
    """
    loaded = plan_loader.load(plan_dir)
    feature = loaded.feature(feature_id)

    quota_pct, quota_line = _quota_gate("claude")
    print(quota_line)

    with ExecutionEnvironment(
        plan_id=loaded.plan_id,
        target_env=target_env,
        target_project=target_project,
    ) as exec_env:
        task = DispatchTask(
            plan_id=loaded.plan_id,
            plan_dir=loaded.plan_dir,
            feature_id=feature_id,
            feature_description=feature["description"],
            feature_acceptance=feature["acceptance"],
            feature_steps=feature.get("steps") or [],
            agent_role=agent_role,
            iteration=iteration,
            subprocess_env=exec_env.subprocess_env(),
        )

        executor = ClaudeCLIExecutor()
        result = executor.dispatch(task)

        audit = audit_writer.build_audit(
            loaded=loaded,
            result=result,
            feature_id=feature_id,
            validation_performed=[
                f"read ~/.jarvis/quota_state.json (claude pct={quota_pct})",
                f"claude -p --output-format json (binary={executor.binary})",
                f"captured stdout {len(result.raw_response)} bytes",
                f"subprocess exit {0 if result.success else 'nonzero'}",
                f"execution_env_root={exec_env.root}",
                f"target_env={target_env or '(unset)'} target_project={target_project or '(unset)'}",
            ],
        )

        return audit_writer.write(audit, loaded.plan_dir)


# ─────────────────────────────  F005a: volley  ─────────────────────────────


@dataclass
class VolleyResult:
    final_status: str           # "signed_off" | "needs_changes" | "blocked" | "stopped_quota" | "stopped_cap" | "stopped_no_progress"
    rounds: int                 # number of (implementer, auditor) pairs completed
    reason: str                 # human-readable termination reason
    audit_paths: list[Path]     # all audit JSONs produced, in order


def dispatch_volley(
    plan_dir: Path,
    feature_id: str,
    implementer_agent: str | None = None,
    auditor_agent: str | None = None,
    max_iterations: int | None = None,
    target_env: str | None = None,
    target_project: str | None = None,
) -> VolleyResult:
    """F005a: sequential build/audit volley.

    Round 0: implementer dispatches, auditor reviews.
    Round N+1: implementer addresses auditor findings, auditor re-reviews.
    Stops on: auditor signed_off, max_iterations hit, quota soft-block,
    no-progress (auditor status unchanged across 2 consecutive rounds).

    If implementer_agent / auditor_agent are None, falls back to plan's
    `agents_required` convention: index 0 = implementer, index 1 = auditor.

    F023 Step 1 (EC9 + EC10): the volley opens a single ExecutionEnvironment
    and shares it across all rounds; tool-state mutations stay sandboxed and
    cleanup runs on volley terminate. target_env / target_project remain
    optional until EC2 lands a plan-level Target contract.
    """
    loaded = plan_loader.load(plan_dir)
    feature = loaded.feature(feature_id)

    # Resolve role pairing — F005a uses agents_required[0/1] convention
    agents_req = list(loaded.plan.agents_required or [])
    impl_name = implementer_agent or (str(agents_req[0]).split(".")[-1] if agents_req else "claude")
    aud_name = auditor_agent or (
        str(agents_req[1]).split(".")[-1] if len(agents_req) >= 2 else "codex"
    )

    # Iteration cap from plan or argument
    cap = max_iterations
    if cap is None:
        loop_caps = loaded.plan.loop_caps
        cap = (loop_caps.max_iterations if loop_caps and loop_caps.max_iterations is not None else 1)

    impl_executor = _resolve_executor(impl_name)
    aud_executor = _resolve_executor(aud_name)

    print(f"[volley] feature={feature_id} impl={impl_name} aud={aud_name} cap={cap}")

    audit_paths: list[Path] = []
    prior_aud_path: Path | None = None
    prior_aud_status: str | None = None

    with ExecutionEnvironment(
        plan_id=loaded.plan_id,
        target_env=target_env,
        target_project=target_project,
    ) as exec_env:
        print(f"[volley] execution_env_root={exec_env.root}")
        round_subprocess_env = exec_env.subprocess_env()
        round_env_log = (
            f"execution_env_root={exec_env.root} "
            f"target_env={target_env or '(unset)'} "
            f"target_project={target_project or '(unset)'}"
        )

        for iteration in range(cap + 1):
            # Implementer round
            try:
                impl_pct, impl_quota_line = _quota_gate(impl_name)
            except QuotaExceeded as exc:
                return VolleyResult("stopped_quota", iteration, str(exc), audit_paths)
            print(impl_quota_line)

            impl_audit_path = _run_round(
                loaded=loaded,
                executor=impl_executor,
                agent_name=impl_name,
                role="implementer",
                iteration=iteration,
                feature=feature,
                prompt=prompts.implementer_prompt(
                    plan_id=loaded.plan_id,
                    plan_dir=loaded.plan_dir,
                    feature=feature,
                    iteration=iteration,
                    prior_auditor_path=prior_aud_path,
                ),
                extra_validation=[
                    f"quota gate impl={impl_pct}",
                    f"prior_auditor_path={prior_aud_path or '(none)'}",
                    round_env_log,
                ],
                subprocess_env=round_subprocess_env,
            )
            audit_paths.append(impl_audit_path)

            # Auditor round
            try:
                aud_pct, aud_quota_line = _quota_gate(aud_name)
            except QuotaExceeded as exc:
                return VolleyResult("stopped_quota", iteration + 1, str(exc), audit_paths)
            print(aud_quota_line)

            aud_audit_path = _run_round(
                loaded=loaded,
                executor=aud_executor,
                agent_name=aud_name,
                role="auditor",
                iteration=iteration,
                feature=feature,
                prompt=prompts.auditor_prompt(
                    plan_id=loaded.plan_id,
                    plan_dir=loaded.plan_dir,
                    feature=feature,
                    iteration=iteration,
                    implementer_audit_path=impl_audit_path,
                ),
                extra_validation=[
                    f"quota gate aud={aud_pct}",
                    f"reviewing implementer audit at {impl_audit_path.name}",
                    round_env_log,
                ],
                subprocess_env=round_subprocess_env,
            )
            audit_paths.append(aud_audit_path)

            # Read auditor's verdict
            aud_data = json.loads(aud_audit_path.read_text())
            aud_status = aud_data.get("audit_status", "inconclusive")
            print(f"[volley] iter={iteration} auditor verdict: {aud_status}")

            if aud_status == "signed_off":
                transcript.append_terminal(
                    loaded.plan_dir, feature_id, aud_status, iteration + 1,
                    reason="auditor signed off",
                )
                return VolleyResult("signed_off", iteration + 1, "auditor signed off", audit_paths)

            if aud_status == "blocked":
                transcript.append_terminal(
                    loaded.plan_dir, feature_id, aud_status, iteration + 1,
                    reason="auditor blocked",
                )
                return VolleyResult("blocked", iteration + 1, "auditor blocked", audit_paths)

            # No-progress: auditor verdict identical to last round
            if prior_aud_status is not None and aud_status == prior_aud_status:
                transcript.append_terminal(
                    loaded.plan_dir, feature_id, "stopped_no_progress", iteration + 1,
                    reason=f"auditor verdict unchanged ({aud_status}) across 2 consecutive rounds",
                )
                return VolleyResult(
                    "stopped_no_progress",
                    iteration + 1,
                    f"auditor verdict unchanged ({aud_status}) across 2 consecutive rounds",
                    audit_paths,
                )

            prior_aud_path = aud_audit_path
            prior_aud_status = aud_status

        transcript.append_terminal(
            loaded.plan_dir, feature_id, "stopped_cap", cap + 1,
            reason=f"max_iterations={cap} reached without signoff",
        )
        return VolleyResult(
            "stopped_cap",
            cap + 1,
            f"max_iterations={cap} reached without signoff",
            audit_paths,
        )


def _resolve_executor(agent_name: str) -> BaseExecutor:
    executor = get_executor(agent_name)
    if not executor.is_available():
        raise RuntimeError(
            f"agent {agent_name!r} not available — {executor.availability_hint()}"
        )
    return executor


def _run_round(
    loaded: plan_loader.LoadedPlan,
    executor: BaseExecutor,
    agent_name: str,
    role: str,
    iteration: int,
    feature: dict[str, Any],
    prompt: str,
    extra_validation: list[str],
    subprocess_env: dict[str, str] | None = None,
) -> Path:
    task = DispatchTask(
        plan_id=loaded.plan_id,
        plan_dir=loaded.plan_dir,
        feature_id=feature["id"],
        feature_description=feature["description"],
        feature_acceptance=feature["acceptance"],
        feature_steps=feature.get("steps") or [],
        agent_role=role,
        iteration=iteration,
        extra_context={"prompt_override": prompt},
        subprocess_env=dict(subprocess_env) if subprocess_env else {},
    )
    # Override the prompt builder by monkey-patching at task level —
    # cleaner: pass prompt directly. For now, executors build their own;
    # to use volley prompts we need executors to honor extra_context["prompt_override"].
    # See codex_cli/claude_cli for the override hook below.
    result = executor.dispatch(task)

    audit = audit_writer.build_audit(
        loaded=loaded,
        result=result,
        feature_id=feature["id"],
        validation_performed=[
            f"{agent_name} {role} round (iteration {iteration})",
            *extra_validation,
            f"captured stdout {len(result.raw_response)} bytes",
        ],
    )
    audit_path = audit_writer.write(audit, loaded.plan_dir)

    transcript.append_round(
        plan_dir=loaded.plan_dir,
        feature_id=feature["id"],
        iteration=iteration,
        agent=agent_name,
        role=role,
        audit_status=audit.get("audit_status", "?"),
        tokens_in=result.quota_consumed.get("tokens_in"),
        tokens_out=result.quota_consumed.get("tokens_out"),
        audit_path=audit_path,
    )
    return audit_path
