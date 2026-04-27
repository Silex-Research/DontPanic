"""F006 — 7 loop termination triggers with pause-for-approval semantics.

Six of seven triggers integrate with F008's gate-pause framework: a breaker
trip writes a synthetic `breaker:<kind>` entry into <plan_dir>/audit/gate-state.json's
`active_breakers` list. The supervisor's pre-dispatch gate-pause check unions
plan.human_gates with active_breakers; either source blocks dispatch until the
operator clears via `jarvis approve <plan-id> breaker:<kind>` or `jarvis resume
<plan-id>`.

The seventh trigger — the global circuit breaker — is hard stop, not pause.
After 3 iteration_cap hits in any 24h window across all plans (per F006 spec),
all autonomous dispatch is refused. Tracking lives in
~/.jarvis/breaker_history.jsonl and is cross-plan. Operators wait out the
window; there is intentionally no `jarvis clear-global-breaker` command.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

# F006 history path. Test isolation: set JARVIS_BREAKER_HISTORY_PATH to a
# tempfile in test setup so synthetic dispatches don't pollute the operator's
# real ~/.jarvis state. Module attribute remains assignable for legacy callers
# that monkey-patch it directly; the env var takes precedence when set.
_DEFAULT_GLOBAL_HISTORY_PATH = Path.home() / ".jarvis" / "breaker_history.jsonl"
GLOBAL_HISTORY_PATH = _DEFAULT_GLOBAL_HISTORY_PATH
QUOTA_STATE_PATH = Path.home() / ".jarvis" / "quota_state.json"


def _effective_history_path() -> Path:
    env_override = os.environ.get("JARVIS_BREAKER_HISTORY_PATH")
    if env_override:
        return Path(env_override)
    return GLOBAL_HISTORY_PATH
GLOBAL_WINDOW_SECONDS = 24 * 3600
GLOBAL_THRESHOLD_HITS = 3

DEFAULT_WALL_CLOCK_HOURS = 1.0
DIMINISHING_RETURNS_MIN_ROUNDS = 2
CONVERGENCE_COLLAPSE_WINDOW = 3
DEFAULT_BUDGET_PERCENT_CAP = 100.0  # used when plan declares no per-agent caps


class BreakerKind(str, Enum):
    ITERATION_CAP = "iteration_cap"
    BUDGET_CEILING = "budget_ceiling"
    WALL_CLOCK = "wall_clock"
    NO_PROGRESS = "no_progress"
    DIMINISHING_RETURNS = "diminishing_returns"
    CONVERGENCE_COLLAPSE = "convergence_collapse"
    GLOBAL_CIRCUIT_BREAKER = "global_circuit_breaker"


# Six of seven trip the pause-for-approval flow. The global breaker is hard
# stop and intentionally has no operator clearance.
APPROVAL_BREAKERS: frozenset[BreakerKind] = frozenset(
    {
        BreakerKind.ITERATION_CAP,
        BreakerKind.BUDGET_CEILING,
        BreakerKind.WALL_CLOCK,
        BreakerKind.NO_PROGRESS,
        BreakerKind.DIMINISHING_RETURNS,
        BreakerKind.CONVERGENCE_COLLAPSE,
    }
)

# Mapping breaker → VolleyResult.final_status the supervisor returns. Kept
# stable for log/dashboard consumers + signoff_writer's next_action mapping.
TERMINAL_STATUS: dict[BreakerKind, str] = {
    BreakerKind.ITERATION_CAP: "stopped_cap",
    BreakerKind.BUDGET_CEILING: "stopped_budget",
    BreakerKind.WALL_CLOCK: "stopped_wall_clock",
    BreakerKind.NO_PROGRESS: "stopped_no_progress",
    BreakerKind.DIMINISHING_RETURNS: "stopped_diminishing_returns",
    BreakerKind.CONVERGENCE_COLLAPSE: "stopped_convergence_collapse",
    BreakerKind.GLOBAL_CIRCUIT_BREAKER: "stopped_global_breaker",
}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def gate_name(kind: BreakerKind) -> str:
    """Synthetic gate name for the F008 gate-pause integration."""
    return f"breaker:{kind.value}"


# ──────────────────────────────  per-iteration checks  ──────────────────────────────


def _read_quota_state(path: Path | None = None) -> dict:
    """Read ~/.jarvis/quota_state.json (F020-populated). Returns empty dict on
    missing/malformed file so callers can no-op safely. Honors
    JARVIS_QUOTA_STATE_PATH for hermetic test isolation."""
    if path is None:
        env_override = os.environ.get("JARVIS_QUOTA_STATE_PATH")
        p = Path(env_override) if env_override else QUOTA_STATE_PATH
    else:
        p = path
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def check_budget_ceiling(
    audit_paths: Iterable[Path],
    per_agent_caps: dict[str, float] | None,
    *,
    quota_state_path: Path | None = None,
) -> tuple[bool, str]:
    """F006 budget breaker — read F020's ~/.jarvis/quota_state.json (the canonical
    source of percent_weekly per agent) and trip when any agent that participated
    in this volley has exceeded its plan-declared cap.

    audit_paths is used only to determine which agents participated (audit_writer
    emits agent + tokens_in/tokens_out, not percent_weekly — which is why the
    earlier implementation read a phantom field and never tripped on real data).
    Per-agent caps come from plan.quota_caps. When unset → no enforcement.

    Returns (tripped, reason).
    """
    if not per_agent_caps:
        return False, ""
    state = _read_quota_state(quota_state_path)
    if not state:
        return False, ""
    models = (state.get("models") or {}) if isinstance(state, dict) else {}

    # Restrict the cap check to agents that actually showed up in this volley's
    # audits — a global cap-overrun unrelated to the current dispatch shouldn't
    # trip the per-volley breaker.
    participating: set[str] = set()
    for ap in audit_paths:
        try:
            data = json.loads(ap.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        agent = data.get("agent")
        if agent:
            participating.add(agent)

    for agent, cap in per_agent_caps.items():
        if cap is None:
            continue
        if agent not in participating:
            continue
        info = models.get(agent) or {}
        observed = info.get("percent_weekly")
        if not isinstance(observed, (int, float)):
            continue
        if observed > cap:
            return True, (
                f"{agent} percent_weekly {float(observed):.1f}% (from "
                f"~/.jarvis/quota_state.json) exceeds plan-declared "
                f"budget {cap:.1f}%"
            )
    return False, ""


def check_wall_clock(start: dt.datetime, max_hours: float) -> tuple[bool, str]:
    elapsed = (_now() - start).total_seconds()
    if elapsed > max_hours * 3600:
        return True, f"elapsed {elapsed:.0f}s exceeds wall_clock_hours={max_hours}"
    return False, ""


def check_no_progress(
    prior_status: str | None, current_status: str, threshold_rounds: int = 2
) -> tuple[bool, str]:
    """Synthetic threshold_rounds=2 — auditor verdict identical to last round.
    Mirrors the pre-existing supervisor behavior; kept here so the breaker
    framework owns all 7 triggers symmetrically."""
    if prior_status is None:
        return False, ""
    if prior_status == current_status and current_status not in {"signed_off", "blocked"}:
        return True, (
            f"auditor verdict unchanged ({current_status}) across "
            f"{threshold_rounds} consecutive rounds"
        )
    return False, ""


def check_diminishing_returns(audit_paths: list[Path]) -> tuple[bool, str]:
    """Heuristic: across the last DIMINISHING_RETURNS_MIN_ROUNDS auditor rounds,
    finding count is non-decreasing AND status is needs_changes. Implies the
    auditor isn't converging on actionable feedback."""
    auditor_audits = []
    for ap in audit_paths:
        try:
            data = json.loads(ap.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("agent_role") == "auditor":
            auditor_audits.append(data)
    if len(auditor_audits) < DIMINISHING_RETURNS_MIN_ROUNDS:
        return False, ""
    recent = auditor_audits[-DIMINISHING_RETURNS_MIN_ROUNDS:]
    counts = [len(d.get("findings") or []) for d in recent]
    statuses = [d.get("audit_status") for d in recent]
    if all(s == "needs_changes" for s in statuses) and all(
        counts[i] <= counts[i + 1] for i in range(len(counts) - 1)
    ):
        return True, (
            f"diminishing returns: auditor finding counts {counts} non-decreasing "
            f"across {DIMINISHING_RETURNS_MIN_ROUNDS} consecutive needs_changes rounds"
        )
    return False, ""


def check_convergence_collapse(audit_paths: list[Path]) -> tuple[bool, str]:
    """Heuristic: auditor verdicts in the last CONVERGENCE_COLLAPSE_WINDOW rounds
    alternate between distinct non-terminal states (e.g., needs_changes ↔ blocked).
    Indicates the auditor is oscillating rather than progressing."""
    auditor_statuses = []
    for ap in audit_paths:
        try:
            data = json.loads(ap.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("agent_role") == "auditor":
            auditor_statuses.append(data.get("audit_status"))
    if len(auditor_statuses) < CONVERGENCE_COLLAPSE_WINDOW:
        return False, ""
    window = auditor_statuses[-CONVERGENCE_COLLAPSE_WINDOW:]
    distinct = set(window)
    if "signed_off" in distinct or "blocked" in distinct:
        # Either of those is a terminal verdict; not collapse.
        return False, ""
    if len(distinct) >= 2 and distinct.issubset({"needs_changes", "inconclusive"}):
        # Verdict ping-pongs between distinct non-terminal states within the window.
        return True, (
            f"convergence collapse: auditor verdicts {window} oscillate between "
            f"distinct non-terminal states"
        )
    return False, ""


# ──────────────────────────────  global circuit breaker  ──────────────────────────────


@dataclass(frozen=True)
class GlobalBreakerState:
    tripped: bool
    hits_in_window: int
    threshold: int = GLOBAL_THRESHOLD_HITS
    window_seconds: int = GLOBAL_WINDOW_SECONDS


def _read_history() -> list[dict]:
    path = _effective_history_path()
    if not path.is_file():
        return []
    out: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def record_global_hit(plan_id: str, kind: BreakerKind) -> None:
    """Append to ~/.jarvis/breaker_history.jsonl (or JARVIS_BREAKER_HISTORY_PATH
    override, when set). Per F006 spec only iteration_cap hits count toward the
    global threshold; other breakers are recorded for forensics but don't trip
    the global hard stop on their own."""
    path = _effective_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "plan_id": plan_id,
        "kind": kind.value,
        "at": _iso(_now()),
    }
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def evaluate_global(
    *,
    threshold: int = GLOBAL_THRESHOLD_HITS,
    window_seconds: int = GLOBAL_WINDOW_SECONDS,
    counted_kinds: Iterable[BreakerKind] = (BreakerKind.ITERATION_CAP,),
) -> GlobalBreakerState:
    """True iff iteration_cap hits in the last window_seconds reach threshold."""
    cutoff = _now() - dt.timedelta(seconds=window_seconds)
    counted_values = {k.value for k in counted_kinds}
    hits = 0
    for entry in _read_history():
        try:
            ts = dt.datetime.fromisoformat(entry["at"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if ts < cutoff:
            continue
        if entry.get("kind") in counted_values:
            hits += 1
    return GlobalBreakerState(
        tripped=hits >= threshold, hits_in_window=hits, threshold=threshold,
        window_seconds=window_seconds,
    )


__all__ = [
    "APPROVAL_BREAKERS",
    "BreakerKind",
    "CONVERGENCE_COLLAPSE_WINDOW",
    "DEFAULT_BUDGET_PERCENT_CAP",
    "DEFAULT_WALL_CLOCK_HOURS",
    "DIMINISHING_RETURNS_MIN_ROUNDS",
    "GLOBAL_HISTORY_PATH",
    "GLOBAL_THRESHOLD_HITS",
    "GLOBAL_WINDOW_SECONDS",
    "GlobalBreakerState",
    "QUOTA_STATE_PATH",
    "TERMINAL_STATUS",
    "check_budget_ceiling",
    "check_convergence_collapse",
    "check_diminishing_returns",
    "check_no_progress",
    "check_wall_clock",
    "evaluate_global",
    "gate_name",
    "record_global_hit",
]
