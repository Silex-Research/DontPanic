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
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from jarvis_orchestrate import calibration_loader, quota_caps_loader

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


# ──────────────────────  F006a budget_ceiling structured result  ──────────────────────
#
# check_budget_ceiling returns a frozen dataclass so callers (supervisor today,
# F006b sibling consumers tomorrow) can route per-kind to different INBOX
# events without parsing the reason string. The checker is intentionally pure:
# it observes state + caps + calibration and returns a verdict; INBOX writes
# happen in the caller. Idempotence requirement: the checker can be invoked
# more than once per volley, and the same state must produce the same kind
# (the once-per-process warning de-dup is the only stateful side-effect, and
# it's reset between tests via reset_warning_cache()).


class BudgetCeilingKind(str, Enum):
    OK = "ok"  # all participating windows under cap
    TRIPPED = "tripped"  # observed * ratio > cap somewhere
    CONFIG_REQUIRED = "config_required"  # caps file absent/invalid OR participating agent has signal but no cap+signal window
    CALIBRATION_REQUIRED = "calibration_required"  # Claude percent_of_plan + uncalibrated
    UNIT_MISMATCH = "unit_mismatch"  # cap.unit != observed_unit (non-Claude)


class WindowOutcome(str, Enum):
    """Per-window evaluation result. Distinct from BudgetCeilingKind because
    a window can have outcomes (NO_SIGNAL, NO_CAP) that aren't terminal at
    the aggregate level — only the aggregator decides whether a NO_CAP window
    rises to CONFIG_REQUIRED based on whether the agent has coverage elsewhere.
    """

    NO_SIGNAL = "no_signal"  # observed_native ≤ 0 — nothing to compare; benign
    NO_CAP = "no_cap"  # has signal but no cap entry; aggregator may escalate
    OK = "ok"  # signal + cap, effective ≤ cap
    TRIPPED = "tripped"  # signal + cap, effective > cap
    CALIBRATION_REQUIRED = "calibration_required"  # Claude percent_of_plan + uncalibrated
    UNIT_MISMATCH = "unit_mismatch"  # non-Claude cap.unit ≠ observed_unit


@dataclass(frozen=True)
class WindowEvaluation:
    """Pure per-window evaluator output. Aggregator (check_budget_ceiling +
    F006b consumers) decides what to do with sets of these.

    `stale` is an advisory flag: when calibration is older than
    STALE_WARNING_DAYS the ratio still applies (no-action is more dangerous
    than slightly-aged-action — see plan 2026-04-30-001 D012). Caller emits
    a stderr warn-once so operators know to re-sample.

    `pct_of_cap` is provided so F006b consumers (supervisor soft-warn,
    quota_admission defer-threshold) can compare against their own thresholds
    (90%, 70%) without recomputing the calibration.
    """

    outcome: WindowOutcome
    agent: str
    tier: str
    window: str
    observed_native: float | None = None
    observed_unit: str | None = None
    cap: float | None = None
    cap_unit: str | None = None
    confidence: str | None = None
    ratio: float | None = None
    effective: float | None = None
    pct_of_cap: float | None = None
    stale: bool = False
    reason: str = ""


def evaluate_window(
    *,
    agent: str,
    tier: str,
    window_name: str,
    window: dict[str, Any],
    cap_block: dict[str, Any] | None,
    now: dt.datetime | None = None,
) -> WindowEvaluation:
    """Pure per-window evaluator. Applies the F006a calibration-safety + unit-
    mismatch rules to a single (agent, tier, window). No I/O, no warnings —
    aggregator handles side effects.

    Used by:
      - check_budget_ceiling._check_budget_v2 for terminal verdicts
      - F006b supervisor._quota_gate for soft-warn at 90% via .pct_of_cap
      - F006b quota_admission for defer-threshold via .pct_of_cap
    """
    base = dict(agent=agent, tier=tier, window=window_name)
    observed_native = window.get("observed_native")
    observed_unit = window.get("observed_unit")

    if not isinstance(observed_native, (int, float)) or observed_native <= 0:
        return WindowEvaluation(
            outcome=WindowOutcome.NO_SIGNAL,
            **base,
            observed_unit=observed_unit,
        )

    if cap_block is None:
        return WindowEvaluation(
            outcome=WindowOutcome.NO_CAP,
            **base,
            observed_native=float(observed_native),
            observed_unit=observed_unit,
            reason=(
                f"{agent}.{tier}.{window_name} has signal "
                f"({observed_native} {observed_unit}) but no cap entry in "
                "~/.jarvis/quota_caps.json"
            ),
        )

    cap_value = cap_block.get("cap")
    cap_unit = cap_block.get("unit")
    if not isinstance(cap_value, (int, float)) or cap_value <= 0:
        # Defensive — quota_caps_loader.validate() should reject this at load.
        return WindowEvaluation(
            outcome=WindowOutcome.NO_CAP,
            **base,
            observed_native=float(observed_native),
            observed_unit=observed_unit,
            reason=f"{agent}.{tier}.{window_name} cap value {cap_value!r} invalid",
        )

    calibration = window.get("calibration") or {}
    confidence = calibration.get("confidence") or "uncalibrated"
    ratio = calibration.get("ratio")
    stale = calibration_loader.is_stale(calibration, now=now)

    if cap_unit == "percent_of_plan":
        # Claude case: ratio required to bridge weighted_tokens → percent.
        if confidence != "manual" or not isinstance(ratio, (int, float)):
            return WindowEvaluation(
                outcome=WindowOutcome.CALIBRATION_REQUIRED,
                **base,
                observed_native=float(observed_native),
                observed_unit=observed_unit,
                cap=float(cap_value),
                cap_unit=cap_unit,
                confidence=confidence,
                stale=stale,
                reason=(
                    f"{agent}.{tier}.{window_name} cap unit is percent_of_plan "
                    f"but calibration.confidence={confidence!r}; run "
                    "`python -m jarvis_orchestrate calibrate-claude --dashboard-pct"
                    f" N --window {window_name}`"
                ),
            )
        effective = float(observed_native) * float(ratio)
        ratio_used: float | None = float(ratio)
    else:
        # Non-Claude: cap.unit must equal observed_unit.
        if cap_unit != observed_unit:
            return WindowEvaluation(
                outcome=WindowOutcome.UNIT_MISMATCH,
                **base,
                observed_native=float(observed_native),
                observed_unit=observed_unit,
                cap=float(cap_value),
                cap_unit=cap_unit,
                confidence=confidence,
                stale=stale,
                reason=(
                    f"{agent}.{tier}.{window_name} cap.unit={cap_unit!r} "
                    f"does not match observed_unit={observed_unit!r}. Fix "
                    "~/.jarvis/quota_caps.json so cap.unit matches what "
                    "quota_check.py emits."
                ),
            )
        effective = float(observed_native)
        ratio_used = None

    pct_of_cap = effective / float(cap_value)
    if effective > float(cap_value):
        return WindowEvaluation(
            outcome=WindowOutcome.TRIPPED,
            **base,
            observed_native=float(observed_native),
            observed_unit=observed_unit,
            cap=float(cap_value),
            cap_unit=cap_unit,
            confidence=confidence,
            ratio=ratio_used,
            effective=effective,
            pct_of_cap=pct_of_cap,
            stale=stale,
            reason=(
                f"{agent}.{tier}.{window_name} observed {effective:.4g} "
                f"{cap_unit} > cap {cap_value} {cap_unit} "
                f"(confidence={confidence})"
            ),
        )

    return WindowEvaluation(
        outcome=WindowOutcome.OK,
        **base,
        observed_native=float(observed_native),
        observed_unit=observed_unit,
        cap=float(cap_value),
        cap_unit=cap_unit,
        confidence=confidence,
        ratio=ratio_used,
        effective=effective,
        pct_of_cap=pct_of_cap,
        stale=stale,
    )


@dataclass(frozen=True)
class BudgetCeilingResult:
    """Structured outcome of check_budget_ceiling.

    `tripped` is True for every non-OK kind so existing callers (`if tripped:`)
    keep working unchanged. F006b will route on `kind` in the supervisor to
    emit specific INBOX events (calibration_required → operator-action-required
    pause; unit_mismatch → config-fix pause; tripped → standard breaker pause).
    """

    kind: BudgetCeilingKind
    tripped: bool
    reason: str
    agent: str | None = None
    tier: str | None = None
    window: str | None = None
    observed_native: float | None = None
    observed_unit: str | None = None
    cap: float | None = None
    cap_unit: str | None = None
    confidence: str | None = None
    fallback_used: bool = False
    details: dict[str, Any] = field(default_factory=dict)


# Once-per-process warning de-dup keyed by (consumer, agent, condition).
# Conditions used by F006a: legacy_fallback, no_cap_for_<window>, stale_<window>.
# F006b consumers (supervisor._quota_gate, quota_admission) will share this set
# under their own consumer keys.
_warned_once: set[tuple[str, str, str]] = set()


def _warn_once(consumer: str, agent: str, condition: str, message: str) -> None:
    """Emit `message` to stderr at most once per (consumer, agent, condition)
    triple per process. Test isolation: call reset_warning_cache() between
    tests (the autouse fixture in conftest.py does this)."""
    key = (consumer, agent, condition)
    if key in _warned_once:
        return
    _warned_once.add(key)
    print(message, file=sys.stderr)


def reset_warning_cache() -> None:
    """Clear the once-per-process warning de-dup state. Tests call this in an
    autouse fixture so warning assertions don't become order-dependent."""
    _warned_once.clear()


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


def _participating_agents(audit_paths: Iterable[Path]) -> set[str]:
    out: set[str] = set()
    for ap in audit_paths:
        try:
            data = json.loads(ap.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        agent = data.get("agent")
        if agent:
            out.add(agent)
    return out


_TERMINAL_OUTCOME_TO_KIND: dict[WindowOutcome, BudgetCeilingKind] = {
    WindowOutcome.TRIPPED: BudgetCeilingKind.TRIPPED,
    WindowOutcome.CALIBRATION_REQUIRED: BudgetCeilingKind.CALIBRATION_REQUIRED,
    WindowOutcome.UNIT_MISMATCH: BudgetCeilingKind.UNIT_MISMATCH,
}


def _eval_to_result(ev: WindowEvaluation) -> BudgetCeilingResult:
    """Project a terminal WindowEvaluation into a BudgetCeilingResult."""
    return BudgetCeilingResult(
        kind=_TERMINAL_OUTCOME_TO_KIND[ev.outcome],
        tripped=True,
        reason=ev.reason,
        agent=ev.agent,
        tier=ev.tier,
        window=ev.window,
        observed_native=ev.observed_native,
        observed_unit=ev.observed_unit,
        cap=ev.cap,
        cap_unit=ev.cap_unit,
        confidence=ev.confidence,
    )


def _check_budget_v2(
    state: dict,
    vendors: dict,
    participating: set[str],
    caps_path: Path | None,
) -> BudgetCeilingResult:
    """V2 path: per-vendor per-window cap lookup against operator caps file.

    Plan-level quota_caps are intentionally ignored here per plan
    2026-04-30-001 D010 + the F006a operator decision: those values are tied
    to the broken percent_weekly model and would reintroduce the bug if they
    overrode the operator caps file. Per-plan overrides remain available only
    on the legacy fallback path (state.vendors{} missing).

    Aggregation rules (F006a fix#1):
      - First terminal window outcome (TRIPPED / CALIBRATION_REQUIRED /
        UNIT_MISMATCH) returns immediately with the matching BudgetCeilingKind.
      - If no terminal outcome but a participating agent has signal in any
        window AND no cap+signal window is found anywhere for that agent,
        return CONFIG_REQUIRED. This closes the previous gap where Codex with
        signal but no cap entry returned OK silently.
      - Otherwise OK.
    """
    try:
        caps = quota_caps_loader.load(caps_path)
    except quota_caps_loader.QuotaCapsError as exc:
        return BudgetCeilingResult(
            kind=BudgetCeilingKind.CONFIG_REQUIRED,
            tripped=True,
            reason=(
                f"caps file unavailable: {exc}. Run "
                "`python -m jarvis_orchestrate quota-caps init` to seed."
            ),
            details={"error": str(exc)},
        )

    # Per-agent coverage tracking for the post-iteration CONFIG_REQUIRED check.
    agent_covered: dict[str, bool] = {a: False for a in participating}
    no_cap_evals: list[WindowEvaluation] = []

    # Iterate participating agents deterministically so first-trip window is
    # stable across test runs.
    for agent in sorted(participating):
        vblock = vendors.get(agent)
        if not isinstance(vblock, dict):
            continue
        tier = vblock.get("tier") or "unknown"
        windows = vblock.get("windows") or {}
        if not isinstance(windows, dict):
            continue
        for window_name, window in windows.items():
            if not isinstance(window, dict):
                continue
            cap_block = quota_caps_loader.get(caps, agent, tier, window_name)
            ev = evaluate_window(
                agent=agent, tier=tier, window_name=window_name,
                window=window, cap_block=cap_block,
            )

            # Stale advisory — applies whether outcome is OK or TRIPPED.
            # Plan 2026-04-30-001 D012: stale calibration is warning-only;
            # the ratio is applied because no-action is more dangerous than
            # slightly-aged-action. Operator already saw a stderr warning
            # during quota_check.py; this is a second nudge from the breaker.
            if ev.stale:
                _warn_once(
                    "budget_ceiling",
                    agent,
                    f"stale_{window_name}",
                    f"[budget_ceiling] {agent}.{window_name} calibration "
                    f"stale; applying ratio anyway. Re-run calibrate-claude "
                    f"when convenient.",
                )

            if ev.outcome in _TERMINAL_OUTCOME_TO_KIND:
                return _eval_to_result(ev)

            if ev.outcome == WindowOutcome.OK:
                agent_covered[agent] = True
            elif ev.outcome == WindowOutcome.NO_CAP:
                no_cap_evals.append(ev)
                _warn_once(
                    "budget_ceiling",
                    agent,
                    f"no_cap_for_{window_name}",
                    f"[budget_ceiling] {ev.reason}",
                )
            # NO_SIGNAL: nothing to do — agent didn't consume in this window.

    # Post-iteration: any agent with NO_CAP-with-signal AND no covering window
    # elsewhere is uncapped → CONFIG_REQUIRED. Distinct from caps-file-missing
    # CONFIG_REQUIRED above; details.cause distinguishes the two for the
    # caller's INBOX wiring (F006b).
    uncovered = sorted(
        {
            ev.agent for ev in no_cap_evals
            if not agent_covered.get(ev.agent, False)
        }
    )
    if uncovered:
        details_per_agent: list[str] = []
        for ev in no_cap_evals:
            if ev.agent in uncovered:
                details_per_agent.append(
                    f"{ev.agent}.{ev.tier}.{ev.window} "
                    f"({int(ev.observed_native or 0)} {ev.observed_unit})"
                )
        return BudgetCeilingResult(
            kind=BudgetCeilingKind.CONFIG_REQUIRED,
            tripped=True,
            reason=(
                "participating agents have signal but no cap+signal window "
                "in ~/.jarvis/quota_caps.json: "
                + "; ".join(details_per_agent)
                + ". Add the missing entries via `python -m jarvis_orchestrate"
                " quota-caps init` (samples current usage) or hand-edit."
            ),
            details={
                "cause": "no_cap_for_signal",
                "uncovered_agents": uncovered,
                "uncovered_windows": [
                    {
                        "agent": ev.agent,
                        "tier": ev.tier,
                        "window": ev.window,
                        "observed_native": ev.observed_native,
                        "observed_unit": ev.observed_unit,
                    }
                    for ev in no_cap_evals
                    if ev.agent in uncovered
                ],
            },
        )

    return BudgetCeilingResult(
        kind=BudgetCeilingKind.OK,
        tripped=False,
        reason="all participating-agent windows under operator cap",
    )


def _check_budget_legacy(
    state: dict,
    participating: set[str],
    per_agent_caps: dict[str, float] | None,
) -> BudgetCeilingResult:
    """Legacy fallback when state.vendors{} is missing.

    Preserves the F020/F006-original behavior: read state.models[agent].
    percent_weekly + plan.quota_caps[agent], trip on >cap. This is the path
    that lets cost-model + cost-guard skills keep working unchanged during
    the F002 mirror-policy cutover. Plan 2026-04-29-004 reactivation will
    drop it once those skills migrate to vendors{}.
    """
    if not per_agent_caps:
        return BudgetCeilingResult(
            kind=BudgetCeilingKind.OK,
            tripped=False,
            reason="legacy fallback: no plan.quota_caps to enforce",
            fallback_used=True,
        )
    models = (state.get("models") or {}) if isinstance(state, dict) else {}
    for agent, cap in per_agent_caps.items():
        if cap is None or agent not in participating:
            continue
        info = models.get(agent) or {}
        observed = info.get("percent_weekly")
        if not isinstance(observed, (int, float)):
            continue
        if observed > cap:
            return BudgetCeilingResult(
                kind=BudgetCeilingKind.TRIPPED,
                tripped=True,
                reason=(
                    f"{agent} percent_weekly {float(observed):.1f}% (from "
                    f"~/.jarvis/quota_state.json legacy mirror) exceeds "
                    f"plan-declared budget {cap:.1f}%"
                ),
                agent=agent,
                observed_native=float(observed),
                observed_unit="percent_weekly_legacy",
                cap=float(cap),
                cap_unit="percent_weekly_legacy",
                fallback_used=True,
            )
    return BudgetCeilingResult(
        kind=BudgetCeilingKind.OK,
        tripped=False,
        reason="legacy fallback: all participating agents under plan cap",
        fallback_used=True,
    )


def check_budget_ceiling(
    audit_paths: Iterable[Path],
    per_agent_caps: dict[str, float] | None,
    *,
    quota_state_path: Path | None = None,
    caps_path: Path | None = None,
) -> BudgetCeilingResult:
    """F006 budget breaker — v2-aware.

    Reads ~/.jarvis/quota_state.json (F020/F002). When the v2 vendors{}
    block is present, looks up per-window caps from
    ~/.jarvis/quota_caps.json (F004) and applies the F005 calibration ratio
    for Claude windows. When the v2 block is absent, falls back to the
    legacy models{}.percent_weekly path with plan.quota_caps as the
    authority (preserves pre-F002 behavior).

    Returns BudgetCeilingResult with .kind ∈ BudgetCeilingKind. The caller
    routes on .kind for INBOX events (F006b will wire this in supervisor +
    quota_admission). The function is pure w.r.t. INBOX writes; only side
    effects are stderr warnings via _warn_once for non-fatal conditions
    (no_cap_for_<window>, stale_<window>, legacy_fallback) — those are
    de-duplicated per process. Tests reset via reset_warning_cache().

    Per-plan quota_caps:
      - V2 path: IGNORED. Operator caps file is the source of truth (D010
        + F006 operator decision: plan-level values were tied to the
        broken percent_weekly model and would reintroduce the bug).
      - Legacy fallback: HONORED. Preserves the F006-original behavior
        until cost-model + cost-guard skills migrate (plan 004 reactivation).
    """
    state = _read_quota_state(quota_state_path)
    if not state:
        return BudgetCeilingResult(
            kind=BudgetCeilingKind.OK,
            tripped=False,
            reason="no quota state file (run scripts/quota_check.py)",
        )

    participating = _participating_agents(audit_paths)
    if not participating:
        return BudgetCeilingResult(
            kind=BudgetCeilingKind.OK,
            tripped=False,
            reason="no participating agents in audit_paths",
        )

    vendors = state.get("vendors")
    if isinstance(vendors, dict) and vendors:
        return _check_budget_v2(state, vendors, participating, caps_path)

    _warn_once(
        "budget_ceiling",
        "_global",
        "legacy_fallback",
        "[budget_ceiling] vendors{} block missing in quota_state.json; using "
        "legacy models{}.percent_weekly path. Re-run scripts/quota_check.py "
        "to refresh to v2 schema.",
    )
    return _check_budget_legacy(state, participating, per_agent_caps)


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
        tripped=hits >= threshold,
        hits_in_window=hits,
        threshold=threshold,
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
