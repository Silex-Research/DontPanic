"""Supervisor — orchestration entry point for F004 (single-agent dispatch).

Reads ~/.jarvis/quota_state.json before dispatch (F020 gate) and aborts/warns
based on per-vendor weekly consumption. Soft-block at >90% by default; flip
JARVIS_QUOTA_ENFORCE=hard to make it raise.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from jarvis_orchestrate import audit_writer, plan_loader
from jarvis_orchestrate.executors import ClaudeCLIExecutor
from jarvis_orchestrate.executors.base import DispatchTask

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
) -> Path:
    """F004 path: dispatch one agent (Claude), produce + validate audit JSON.

    Returns the absolute path to the persisted audit file.
    """
    loaded = plan_loader.load(plan_dir)
    feature = loaded.feature(feature_id)

    quota_pct, quota_line = _quota_gate("claude")
    print(quota_line)

    task = DispatchTask(
        plan_id=loaded.plan_id,
        plan_dir=loaded.plan_dir,
        feature_id=feature_id,
        feature_description=feature["description"],
        feature_acceptance=feature["acceptance"],
        feature_steps=feature.get("steps") or [],
        agent_role=agent_role,
        iteration=iteration,
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
        ],
    )

    return audit_writer.write(audit, loaded.plan_dir)
