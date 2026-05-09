"""F008 Item 2 — gate-pause protocol.

Plans declare `human_gates: [pre_impl, on_escalation, ...]`. Before any
dispatch begins, the supervisor checks whether each declared gate has been
cleared by the operator. Unmet gates pause the supervisor: a marker is
written, an INBOX entry is appended, terminal-notifier fires, and
dispatch_volley returns VolleyResult(final_status="paused_on_gate") without
calling any executor.

The operator clears gates via CLI:
  - `jarvis approve <plan-id> <gate>`     clears one gate
  - `jarvis resume  <plan-id> --gate <g>` clears one gate (parity with approve)
  - `jarvis resume  <plan-id> --all`      clears all declared gates

Both are no-op when state is already that way; both record the operator
action in INBOX.

State lives in <plan_dir>/audit/gate-state.json:
  {
    "plan_id": "...",
    "cleared_gates": ["pre_impl"],
    "history": [
      {"action": "approve", "gate": "pre_impl", "at": "...", "actor": "operator"}
    ],
    "paused_at": "...",          # set when supervisor last paused
    "pause_gates": ["on_escalation"]
  }

Design choice (B2): gates are checked once at the *start* of dispatch.
Mid-volley runtime checks (e.g., re-pause when auditor returns
needs_changes and on_escalation hasn't been re-cleared) are an
engagement-surface v2 concern.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GATE_STATE_FILENAME = "gate-state.json"

# Plan 2026-05-08-003 F001 — synthetic gate-name prefixes that are valid in
# persisted state without being declared in plan.human_gates. Active breakers,
# defers, and child-return gates live on the supervisor side of the lifecycle
# (transient transitions) but their names show up in cleared_gates / pause_gates
# during in-flight runs. The reconciliation helper treats any name with one of
# these prefixes as legitimate even when the plan has not declared it.
_SYNTHETIC_GATE_PREFIXES: tuple[str, ...] = (
    "breaker:",
    "defer:",
    "pre_resume_after_child:",
)

# Plan 2026-05-04-002 F001 — lifecycle stages for staged human-gate evaluation.
# Maps each canonical lifecycle stage to the human-gate names that fire there.
# Other declared human gates (e.g. on_escalation, tier_promotion) remain in the
# upfront-evaluation bucket — F001 explicitly does not stage those (D003).
LIFECYCLE_STAGES: tuple[str, ...] = ("pre_impl", "pre_merge")
_STAGE_GATES: dict[str, tuple[str, ...]] = {
    "pre_impl": ("pre_impl",),
    "pre_merge": ("pre_merge",),
}
# Inverse: the set of human-gate names handled by lifecycle staging. Used by
# the supervisor to filter out staged gates from the upfront evaluate() call.
LIFECYCLE_STAGED_GATES: frozenset[str] = frozenset(
    g for gates in _STAGE_GATES.values() for g in gates
)


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gate_state_path(plan_dir: Path) -> Path:
    return plan_dir / "audit" / GATE_STATE_FILENAME


def _stringify_gates(gates: list[Any] | None) -> list[str]:
    """Coerce a list of gate names to plain strings. Accepts plain str values
    or Pydantic-generated enum members (which expose `.value`)."""
    if not gates:
        return []
    out: list[str] = []
    for g in gates:
        if hasattr(g, "value"):
            out.append(str(g.value))
        else:
            out.append(str(g))
    return out


def _read_state(plan_dir: Path) -> dict[str, Any]:
    p = gate_state_path(plan_dir)
    if not p.is_file():
        return {"plan_id": None, "cleared_gates": [], "history": []}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        # Corrupt file — treat as fresh state but preserve the original
        # for forensics.
        backup = p.with_suffix(".corrupt.json")
        backup.write_text(p.read_text())
        return {"plan_id": None, "cleared_gates": [], "history": []}


def _coerce_cleared_gates(raw: Any) -> list[str]:
    """Plan 2026-05-04-002 F001 D004 — tolerate two legacy `cleared_gates`
    shapes plus the canonical list shape:

      - list[str]  (existing canonical shape)
      - dict[str, bool]  (illustrative legacy shape from upfront regime — a
        gate is cleared iff its mapped value is truthy)
      - None / missing  (treat as empty)

    The returned list is the de-duplicated set of gates currently considered
    cleared, preserving insertion order for the canonical list shape.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(g) for g in raw]
    if isinstance(raw, dict):
        return [str(g) for g, v in raw.items() if v]
    return []


def _write_state(plan_dir: Path, state: dict[str, Any]) -> None:
    p = gate_state_path(plan_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def is_gate_cleared(plan_dir: Path, gate: str) -> bool:
    return gate in _coerce_cleared_gates(_read_state(plan_dir).get("cleared_gates"))


def cleared_gates(plan_dir: Path) -> list[str]:
    return _coerce_cleared_gates(_read_state(plan_dir).get("cleared_gates"))


def unmet_gates(plan_dir: Path, declared_gates: list[Any]) -> list[str]:
    cleared = set(cleared_gates(plan_dir))
    declared_strs = _stringify_gates(declared_gates)
    return [g for g in declared_strs if g not in cleared]


def _stage_for_gate(gate: str) -> str | None:
    """Plan 2026-05-04-002 F001 — return the lifecycle stage the named gate
    belongs to, or None for non-lifecycle gates (e.g. on_escalation, breaker:*).
    """
    for stage, gates in _STAGE_GATES.items():
        if gate in gates:
            return stage
    return None


def is_lifecycle_gate(gate: str) -> bool:
    """Plan 2026-05-04-002 F001 — True iff ``gate`` is one of the lifecycle-
    staged human gates (``pre_impl``, ``pre_merge``). Non-lifecycle gate names
    (``on_escalation``, ``breaker:*``, ``defer:*``, ``pre_resume_after_child:*``)
    follow their existing approve/resume semantics; the staged-only constraints
    apply only to the lifecycle-gate subset."""
    return gate in LIFECYCLE_STAGED_GATES


def _append_gate_event(state: dict[str, Any], gate: str, stage: str, actor: str, when: str) -> None:
    events = list(state.get("gate_events") or [])
    events.append(
        {
            "gate": gate,
            "stage": stage,
            "cleared_at": when,
            "cleared_by": actor,
        }
    )
    state["gate_events"] = events


def _mark_stage_completed_if_done(state: dict[str, Any], stage: str) -> None:
    """Plan 2026-05-04-002 F001 — append ``stage`` to ``completed_stages``
    on the in-memory state dict iff every gate in that stage is now present
    in ``cleared_gates``. Idempotent: re-marking a completed stage is a no-op.
    The supervisor consults ``completed_stages`` to decide whether to skip
    re-evaluating the stage on subsequent dispatch iterations or on resume
    (D006 audit-focus item 8 — idempotent stage evaluation)."""
    if stage not in _STAGE_GATES:
        return
    cleared = set(_coerce_cleared_gates(state.get("cleared_gates")))
    if not all(g in cleared for g in _STAGE_GATES[stage]):
        return
    completed = list(state.get("completed_stages") or [])
    if stage in completed:
        return
    completed.append(stage)
    state["completed_stages"] = completed


def is_stage_completed(plan_dir: Path, stage: str) -> bool:
    """Plan 2026-05-04-002 F001 — True iff ``stage`` is recorded as completed
    in ``gate-state.json`` (every gate of the stage has been cleared at some
    earlier point). Used by the supervisor to short-circuit re-evaluation on
    multi-iteration loops and on resume.

    Backwards-compat: a legacy ``gate-state.json`` predating ``completed_stages``
    is also treated as "completed" for any stage whose gates are all listed in
    ``cleared_gates`` (D004 + D009 — legacy upfront-cleared plans resume
    without re-prompting)."""
    if stage not in _STAGE_GATES:
        return False
    state = _read_state(plan_dir)
    completed = state.get("completed_stages") or []
    if isinstance(completed, list) and stage in completed:
        return True
    cleared = set(_coerce_cleared_gates(state.get("cleared_gates")))
    return all(g in cleared for g in _STAGE_GATES[stage])


def is_gate_currently_pending(plan_dir: Path, gate: str) -> bool:
    """Plan 2026-05-04-002 F001 — True iff ``gate`` is currently in the
    supervisor's pending pause set (``pause_gates``). Used by the CLI's
    ``approve`` and ``resume --gate`` paths to enforce the
    "currently-pending-stage only" constraint on lifecycle gates: a lifecycle
    gate may only be cleared when it's the gate the supervisor is actually
    waiting on, never to pre-clear a future stage. Non-lifecycle gates use
    their existing relaxed semantics — see ``_approve_main`` for the wiring.
    """
    state = _read_state(plan_dir)
    pause_gates = state.get("pause_gates") or []
    if not isinstance(pause_gates, list):
        return False
    return gate in pause_gates


def pending_stage(plan_dir: Path) -> str | None:
    """Plan 2026-05-04-002 F001 — return the lifecycle stage currently paused,
    or None if no stage pause is active. Wraps the persisted ``pending_stage``
    field on ``gate-state.json``; reads via :func:`load_gate_state_compat` so
    legacy state shapes return None."""
    return load_gate_state_compat(plan_dir).pending_stage


def _maybe_clear_pause_marker(state: dict[str, Any]) -> None:
    """When the pause condition is fully resolved, drop the paused_at +
    pause_gates fields so the state file matches ground truth. Called from
    approve / resume_all / reconcile_defers after they mutate the relevant
    set.

    A gate is "resolved" by lifecycle:
      - plan-declared gate    → resolved when in cleared_gates
      - F006 breaker:<kind>   → resolved when NOT in active_breakers
      - F007 defer:<kind>     → resolved when NOT in active_defers

    Without this, transient gates (which are intentionally not added to
    cleared_gates after approval) leave paused_at / pause_gates stale —
    evaluate() ignores those fields so dispatch still proceeds, but the
    state file misrepresents ground truth.
    """
    pending = state.get("pause_gates") or []
    if not pending:
        return
    cleared = set(_coerce_cleared_gates(state.get("cleared_gates")))
    active_breakers_set = set(state.get("active_breakers") or [])
    active_defers_set = set(state.get("active_defers") or [])
    active_pre_resume_set = set(state.get("active_pre_resume_after_children") or [])

    def _is_resolved(gate: str) -> bool:
        if gate.startswith("breaker:"):
            return gate not in active_breakers_set
        if gate.startswith("defer:"):
            return gate not in active_defers_set
        if gate.startswith("pre_resume_after_child:"):
            # Plan 2026-05-02-003 F003 — same transient lifecycle as
            # breakers/defers; tracked via active_pre_resume_after_children.
            return gate not in active_pre_resume_set
        return gate in cleared

    if all(_is_resolved(g) for g in pending):
        state.pop("paused_at", None)
        state.pop("pause_gates", None)
        # Plan 2026-05-04-002 F001 — pending_stage tracks which lifecycle stage
        # the run is currently waiting on. When the corresponding gates are all
        # cleared, the run has moved past that stage; drop the marker so a
        # re-dispatch isn't misread as still-pending. The supervisor re-sets it
        # when the next staged check pauses.
        state.pop("pending_stage", None)


def approve_gate(plan_dir: Path, gate: Any, *, plan_id: str, actor: str = "operator") -> bool:
    """Mark a single gate cleared. Idempotent — re-approving is a no-op
    (no INBOX append). Returns True if state changed.

    Three lifecycles, distinguished by name prefix:

      - plan-declared gate (e.g. "pre_impl"):
        durable; tracked via `cleared_gates`. Re-approve is no-op.

      - F006 breaker:<kind>:
        transient; tracked via `active_breakers`. Approve pops it; re-trip
        re-adds. Re-approve when already cleared is no-op.

      - F007 defer:<kind>:
        transient; tracked via `active_defers`. Same approve semantics as
        breakers; the supervisor's pre-dispatch admission reconcile may
        re-add the entry on the next dispatch if the underlying condition
        is still true.
    """
    gate_str = _stringify_gates([gate])[0]
    state = _read_state(plan_dir)
    state["plan_id"] = plan_id
    is_breaker = gate_str.startswith("breaker:")
    is_defer = gate_str.startswith("defer:")
    cleared = list(state.get("cleared_gates") or [])
    active_breakers_list = list(state.get("active_breakers") or [])
    active_defers_list = list(state.get("active_defers") or [])

    if is_breaker:
        if gate_str not in active_breakers_list:
            return False
    elif is_defer:
        if gate_str not in active_defers_list:
            return False
    else:
        if gate_str in cleared:
            return False

    now = _now_iso()
    history = list(state.get("history") or [])
    history.append({"action": "approve", "gate": gate_str, "at": now, "actor": actor})
    state["history"] = history

    # Plan 2026-05-04-002 F001 D004 — record a per-clearance audit entry on
    # `gate_events` whenever a lifecycle-staged gate is cleared. Non-lifecycle
    # gates (on_escalation, breaker:*, defer:*) do not write `gate_events`.
    stage = _stage_for_gate(gate_str)
    if stage is not None:
        _append_gate_event(state, gate_str, stage, actor, now)

    if is_breaker:
        # F006 transient lifecycle: pop from active_breakers; do NOT accumulate
        # in cleared_gates so the next trip re-pauses without prior approval
        # bleeding through.
        active_breakers_list = [b for b in active_breakers_list if b != gate_str]
        if active_breakers_list:
            state["active_breakers"] = active_breakers_list
        else:
            state.pop("active_breakers", None)
        state["cleared_gates"] = [c for c in cleared if c != gate_str]
    elif is_defer:
        # F007 transient lifecycle, mirrors breakers: pop from active_defers,
        # never accumulate in cleared_gates.
        active_defers_list = [d for d in active_defers_list if d != gate_str]
        if active_defers_list:
            state["active_defers"] = active_defers_list
        else:
            state.pop("active_defers", None)
        state["cleared_gates"] = [c for c in cleared if c != gate_str]
    else:
        cleared.append(gate_str)
        state["cleared_gates"] = cleared

    # Plan 2026-05-04-002 F001 — when a lifecycle gate is cleared, mark its
    # stage completed iff every stage gate is now in cleared_gates. The
    # supervisor consults completed_stages on subsequent dispatches to skip
    # re-evaluating the stage (idempotency contract).
    if stage is not None:
        _mark_stage_completed_if_done(state, stage)

    _maybe_clear_pause_marker(state)
    _write_state(plan_dir, state)
    return True


def resume_all(
    plan_dir: Path,
    *,
    plan_id: str,
    declared_gates: list[Any],
    actor: str = "operator",
) -> list[str]:
    """Plan 2026-05-04-002 F001 — clear the gates the supervisor is currently
    paused on (``pause_gates``), narrowed to the current ``pending_stage``'s
    canonical gate set when a lifecycle stage is active, plus every active
    transient gate (breakers + F007 defers). Returns the list of names newly
    cleared in this call.

    Bulk-clear scope (D012, audit-focus item 11): under the staged regime,
    ``--all`` MUST NOT silently pre-clear future-stage gates. When the
    supervisor recorded a ``pending_stage`` (``pre_impl`` or ``pre_merge``),
    this call clears the gates of THAT stage only. Other declared lifecycle
    gates remain uncleared and re-pause at their canonical lifecycle point.
    Non-lifecycle declared gates (``on_escalation``, etc.) are also cleared
    when they're in ``pause_gates`` — they live in the upfront pause bucket.
    Active transient breakers/defers are always cleared; they never live on a
    lifecycle stage.

    ``declared_gates`` is the plan's declared human-gate list and used as a
    safety filter so the helper never invents a gate the plan doesn't declare.
    """
    declared_strs = _stringify_gates(declared_gates)
    state = _read_state(plan_dir)
    state["plan_id"] = plan_id
    cleared = set(_coerce_cleared_gates(state.get("cleared_gates")))
    pending_breakers = list(state.get("active_breakers") or [])
    pending_defers = list(state.get("active_defers") or [])
    persisted_pause_gates = state.get("pause_gates") or []
    pending_stage_value = state.get("pending_stage")

    # Compute the candidate set: current pause_gates intersected with declared
    # human gates — never widen beyond what the supervisor recorded as pending.
    declared_set = set(declared_strs)
    pause_set = set(persisted_pause_gates) & declared_set
    if pending_stage_value in _STAGE_GATES:
        # Stage active: also include the stage's canonical gates that are
        # declared but somehow not in pause_gates (defensive — covers a stale
        # pause_gates write). Excludes other-stage gates per D012.
        pause_set |= set(_STAGE_GATES[pending_stage_value]) & declared_set
    elif not persisted_pause_gates:
        # No pause active: legacy bulk-clear convenience for the case where
        # operator runs `resume --all` without an active pause (e.g. clearing
        # leftover non-lifecycle declared gates from a prior regime). Only
        # touches non-lifecycle gates so a future staged pause still fires.
        pause_set = {g for g in declared_set if not is_lifecycle_gate(g)}
    newly = sorted(pause_set - cleared)

    # Don't early-return when there's nothing in the staged scope but a
    # transient is still active — operator's "resume all" must still reach
    # breakers/defers.
    if not newly and not pending_breakers and not pending_defers:
        return []
    if newly:
        cleared.update(newly)
        state["cleared_gates"] = sorted(cleared)
    history = list(state.get("history") or [])
    now = _now_iso()
    cleared_stages: set[str] = set()
    for g in newly:
        history.append({"action": "resume_all", "gate": g, "at": now, "actor": actor})
        # Plan 2026-05-04-002 F001 — bulk-clear also records gate_events for
        # lifecycle-staged gates so the audit log reflects the clearance.
        stage = _stage_for_gate(g)
        if stage is not None:
            _append_gate_event(state, g, stage, actor, now)
            cleared_stages.add(stage)
    for b in pending_breakers:
        history.append({"action": "resume_all", "gate": b, "at": now, "actor": actor})
    for d in pending_defers:
        history.append({"action": "resume_all", "gate": d, "at": now, "actor": actor})
    if pending_breakers:
        state.pop("active_breakers", None)
    if pending_defers:
        state.pop("active_defers", None)
    if pending_breakers or pending_defers:
        # Strip transient entries from cleared_gates too (they should never
        # accumulate there).
        state["cleared_gates"] = sorted(
            c
            for c in (state.get("cleared_gates") or [])
            if not c.startswith("breaker:") and not c.startswith("defer:")
        )
    # Mark stage completion for any lifecycle stage whose gates just cleared.
    for stage_name in cleared_stages:
        _mark_stage_completed_if_done(state, stage_name)
    state["history"] = history
    _maybe_clear_pause_marker(state)
    _write_state(plan_dir, state)
    return newly + pending_breakers + pending_defers


def record_pause(
    plan_dir: Path,
    *,
    plan_id: str,
    pause_gates: list[Any],
    stage: str | None = None,
) -> None:
    """Record that the supervisor paused waiting on these gates.

    Plan 2026-05-04-002 F001 — when ``stage`` is one of ``LIFECYCLE_STAGES``,
    also records ``pending_stage`` on the state file so resume-time logic can
    tell which lifecycle stage the run is waiting on. Omitted/None ``stage``
    leaves ``pending_stage`` untouched (preserves the existing upfront-pause
    contract for transient breakers/defers and non-lifecycle human gates).
    """
    pause_strs = _stringify_gates(pause_gates)
    state = _read_state(plan_dir)
    state["plan_id"] = plan_id
    state["paused_at"] = _now_iso()
    state["pause_gates"] = pause_strs
    if stage is not None:
        if stage not in LIFECYCLE_STAGES:
            raise ValueError(f"unknown lifecycle stage {stage!r}; valid: {list(LIFECYCLE_STAGES)}")
        state["pending_stage"] = stage
        # Plan 2026-05-04-002 F001 — fresh staged pause must always materialize
        # the additive new schema (cleared_gates + gate_events + pending_stage),
        # so a round-trip read of a never-cleared staged pause shows the empty
        # event log explicitly rather than leaving the field absent. Legacy
        # state files (which never enter this branch) keep their old shape.
        if "gate_events" not in state or not isinstance(state.get("gate_events"), list):
            state["gate_events"] = []
    history = list(state.get("history") or [])
    history.append(
        {
            "action": "pause",
            "at": state["paused_at"],
            "actor": "supervisor",
            "pause_gates": pause_strs,
            **({"stage": stage} if stage is not None else {}),
        }
    )
    state["history"] = history
    _write_state(plan_dir, state)


def reset_for_test(plan_dir: Path) -> None:
    """Test helper — wipe state."""
    p = gate_state_path(plan_dir)
    if p.is_file():
        p.unlink()


@dataclass(frozen=True)
class GateCheck:
    paused: bool
    declared: list[str]
    cleared: list[str]
    unmet: list[str]


@dataclass(frozen=True)
class GatePauseInfo:
    """Plan 2026-05-04-002 F001 — staged human-gate evaluation result.

    Returned by :func:`evaluate_human_gates`. ``pending`` is the list of
    declared human-gate names mapped to ``stage`` that have NOT yet been
    cleared. Empty pending means the supervisor may proceed past that
    lifecycle stage.
    """

    stage: str
    pending: list[str]
    declared: list[str]

    @property
    def paused(self) -> bool:
        return bool(self.pending)


@dataclass(frozen=True)
class CompatGateState:
    """Plan 2026-05-04-002 F001 D004 — normalized gate-state.json view.

    `cleared_gates` is coerced from either the canonical list shape or the
    illustrative legacy dict shape (``{gate: bool}``). `gate_events` and
    `pending_stage` default to empty/None when the state file predates the
    staged-evaluation regime, so legacy in-flight plans load without error.
    """

    cleared_gates: list[str]
    gate_events: list[dict[str, Any]]
    pending_stage: str | None
    raw: dict[str, Any]


def load_gate_state_compat(plan_dir: Path) -> CompatGateState:
    """Plan 2026-05-04-002 F001 step 5 — read gate-state.json into a
    normalized object regardless of input shape.

    Tolerates absence of `gate_events` / `pending_stage` (legacy shape readable
    unchanged). Tolerates either list-shape or dict-shape `cleared_gates`. The
    raw dict is preserved for callers that need fields outside the normalized
    surface (history, active_breakers, active_defers, etc.).
    """
    state = _read_state(plan_dir)
    raw_events = state.get("gate_events")
    events = list(raw_events) if isinstance(raw_events, list) else []
    pending_stage_raw = state.get("pending_stage")
    pending_stage = (
        str(pending_stage_raw) if isinstance(pending_stage_raw, str) and pending_stage_raw else None
    )
    return CompatGateState(
        cleared_gates=_coerce_cleared_gates(state.get("cleared_gates")),
        gate_events=events,
        pending_stage=pending_stage,
        raw=state,
    )


class GateStateReconciliationError(Exception):
    """Plan 2026-05-08-003 F001 — persisted gate-state contradicts the plan
    declaration in a way the supervisor refuses to silently normalize.

    Carries the operator-facing remediation surface explicitly so callers
    (supervisor / CLI) can render INBOX evidence without re-deriving the
    fields. Per D004, no caller mutates ``gate-state.json`` before this error
    is raised; the artifact is preserved for inspection.
    """

    KIND_UNDECLARED_GATE = "undeclared_gate_name"
    KIND_INCOMPATIBLE_STAGE = "incompatible_pending_stage"
    KIND_STALE_ACTIVE_DEFER = "stale_active_defer"

    def __init__(
        self,
        *,
        kind: str,
        plan_id: str,
        gate: str | None,
        stage: str | None,
        persisted_state_path: Path,
        remediation: str,
    ) -> None:
        self.kind = kind
        self.plan_id = plan_id
        self.gate = gate
        self.stage = stage
        self.persisted_state_path = persisted_state_path
        self.remediation = remediation
        msg = (
            f"gate-state reconciliation failed [{kind}]: "
            f"plan_id={plan_id} gate={gate!r} stage={stage!r} "
            f"path={persisted_state_path}\n"
            f"remediation: {remediation}"
        )
        super().__init__(msg)


def format_reconciliation_inbox_body(err: GateStateReconciliationError) -> str:
    """Plan 2026-05-08-003 F001 — canonical INBOX body for a reconciliation
    failure. Kept module-local so every supervisor / CLI entry point emits the
    same operator-readable shape (kind + path + remediation)."""
    return (
        f"Gate-state reconciliation refused (kind={err.kind}).\n\n"
        f"Plan: {err.plan_id}\n"
        f"Persisted state: {err.persisted_state_path}\n"
        f"Offending gate: {err.gate or '(none)'}\n"
        f"Offending stage: {err.stage or '(none)'}\n\n"
        f"Remediation: {err.remediation}\n\n"
        "No gate-state.json mutation has occurred; inspect the artifact "
        "above and repair before re-running."
    )


def _is_synthetic_gate_name(name: str) -> bool:
    return any(name.startswith(p) for p in _SYNTHETIC_GATE_PREFIXES)


def _known_defer_gate_names() -> frozenset[str]:
    """Plan 2026-05-08-003 F001 — set of synthetic ``defer:<kind>`` names that
    quota_admission can legitimately add to ``active_defers``. Imported lazily
    so gate_pause stays loosely coupled to the admission module's import chain.
    """
    from dontpanic_orchestrate import quota_admission  # local to avoid cycles

    return frozenset(quota_admission.gate_name(k) for k in quota_admission.DeferKind)


def reconcile_gate_state(
    plan_dir: Path,
    *,
    plan_id: str,
    declared_gates: list[Any],
) -> CompatGateState:
    """Plan 2026-05-08-003 F001 — verify persisted gate-state is internally
    consistent with the plan declaration before any caller mutates state.

    Raises :class:`GateStateReconciliationError` on contradiction; returns the
    loaded :class:`CompatGateState` on a clean read (including the legacy
    ``cleared_gates``-only shape).

    Owned contradictions:

      1. ``undeclared_gate_name`` — ``cleared_gates`` or ``pause_gates``
         contains a non-synthetic gate name absent from ``declared_gates``.
      2. ``incompatible_pending_stage`` — ``pending_stage`` is set to a value
         outside :data:`LIFECYCLE_STAGES`, or to a stage whose canonical gates
         are not in ``declared_gates``.
      3. ``stale_active_defer`` — ``active_defers`` contains an entry that
         does not map back to any known :class:`quota_admission.DeferKind`.

    No mutation to ``gate-state.json`` regardless of outcome (D004).
    """
    state_path = gate_state_path(plan_dir)
    compat = load_gate_state_compat(plan_dir)
    if not state_path.is_file():
        # Nothing persisted yet — fresh runs cannot be in contradiction.
        return compat

    declared_set = set(_stringify_gates(declared_gates))

    # Case 1: undeclared, non-synthetic gate names in cleared_gates / pause_gates.
    raw_pause = compat.raw.get("pause_gates")
    pause_list: list[str] = []
    if isinstance(raw_pause, list):
        pause_list = [g for g in raw_pause if isinstance(g, str)]
    for source_name, gate_list in (
        ("cleared_gates", compat.cleared_gates),
        ("pause_gates", pause_list),
    ):
        for gate in gate_list:
            if gate in declared_set or _is_synthetic_gate_name(gate):
                continue
            raise GateStateReconciliationError(
                kind=GateStateReconciliationError.KIND_UNDECLARED_GATE,
                plan_id=plan_id,
                gate=gate,
                stage=None,
                persisted_state_path=state_path,
                remediation=(
                    f"Gate {gate!r} appears in {source_name} of "
                    f"{state_path} but is not declared in plan.human_gates "
                    f"({sorted(declared_set)}) and is not a synthetic "
                    f"breaker:/defer:/pre_resume_after_child: gate. "
                    "Either restore the declared gate in plan.md or remove "
                    "the stale entry from gate-state.json after operator "
                    "review."
                ),
            )

    # Case 2: incompatible pending_stage.
    if compat.pending_stage is not None:
        if compat.pending_stage not in LIFECYCLE_STAGES:
            raise GateStateReconciliationError(
                kind=GateStateReconciliationError.KIND_INCOMPATIBLE_STAGE,
                plan_id=plan_id,
                gate=None,
                stage=compat.pending_stage,
                persisted_state_path=state_path,
                remediation=(
                    f"pending_stage={compat.pending_stage!r} in "
                    f"{state_path} is not a valid lifecycle stage "
                    f"(valid: {list(LIFECYCLE_STAGES)}). After operator "
                    "review, repair gate-state.json — typically by clearing "
                    "pending_stage when no stage pause is currently active."
                ),
            )
        stage_gates = _STAGE_GATES.get(compat.pending_stage, ())
        if stage_gates and not any(g in declared_set for g in stage_gates):
            raise GateStateReconciliationError(
                kind=GateStateReconciliationError.KIND_INCOMPATIBLE_STAGE,
                plan_id=plan_id,
                gate=None,
                stage=compat.pending_stage,
                persisted_state_path=state_path,
                remediation=(
                    f"pending_stage={compat.pending_stage!r} in "
                    f"{state_path} maps to gates {list(stage_gates)} but "
                    f"the plan declares {sorted(declared_set)}, none of "
                    "which match this stage. Either declare the stage's "
                    "gate in plan.md or remove pending_stage after "
                    "operator review."
                ),
            )

    # Case 3: stale active_defer entries.
    raw_defers = compat.raw.get("active_defers")
    if isinstance(raw_defers, list) and raw_defers:
        valid_defers = _known_defer_gate_names()
        for entry in raw_defers:
            if not isinstance(entry, str):
                continue
            if entry in valid_defers:
                continue
            raise GateStateReconciliationError(
                kind=GateStateReconciliationError.KIND_STALE_ACTIVE_DEFER,
                plan_id=plan_id,
                gate=entry,
                stage=None,
                persisted_state_path=state_path,
                remediation=(
                    f"active_defers contains {entry!r} in {state_path}, "
                    f"which does not match any known defer kind "
                    f"({sorted(valid_defers)}). After operator review, "
                    "remove the stale entry from gate-state.json."
                ),
            )

    return compat


def evaluate_human_gates(
    plan_dir: Path,
    declared_gates: list[Any],
    stage: str,
) -> GatePauseInfo:
    """Plan 2026-05-04-002 F001 step 3 — evaluate declared human gates for a
    single lifecycle stage.

    Returns a :class:`GatePauseInfo` whose ``pending`` field is the list of
    declared gates mapped to ``stage`` that are NOT yet cleared. Pure read —
    does not write to gate-state.json. The caller (typically the supervisor)
    decides whether to record_pause + emit INBOX events when ``pending`` is
    non-empty.

    Stage routing (D003): ``pre_impl`` → the ``pre_impl`` human gate, fires
    before implementer iteration 0. ``pre_merge`` → the ``pre_merge`` human
    gate, fires immediately before ``signoff_writer.write_signoff(passes=True)``
    on the candidate-success path. Non-lifecycle declared gates
    (``on_escalation``, etc.) are NOT evaluated here — they remain in the
    upfront-evaluation bucket per D003.

    Backwards compat (D004 + D009): the load tolerates legacy `gate-state.json`
    shapes where `gate_events` / `pending_stage` are absent and `cleared_gates`
    may be a dict (illustrative legacy shape) or list (canonical). A plan whose
    legacy state has both gates cleared resumes cleanly under the staged code —
    every stage's pending list is empty, so no re-prompting fires.
    """
    if stage not in _STAGE_GATES:
        raise ValueError(f"unknown lifecycle stage {stage!r}; valid: {list(LIFECYCLE_STAGES)}")
    declared_strs = _stringify_gates(declared_gates)
    compat = load_gate_state_compat(plan_dir)
    cleared = set(compat.cleared_gates)
    stage_gates = _STAGE_GATES[stage]
    pending = [g for g in declared_strs if g in stage_gates and g not in cleared]
    return GatePauseInfo(stage=stage, pending=pending, declared=list(declared_strs))


def evaluate(plan_dir: Path, declared_gates: list[Any]) -> GateCheck:
    """Pure read of current gate state vs declared gates. Does not write.

    Three sources can pause dispatch:
      - plan-declared gates (durable, cleared via approve/resume)
      - F006 active_breakers (transient, set by supervisor on circuit-breaker trip)
      - F007 active_defers   (transient, set by pre-dispatch admission reconcile)

    Any unmet plan-declared gate plus any active transient gate is by-
    construction "unmet" — the supervisor pauses with paused_on_gate.
    """
    declared_strs = _stringify_gates(declared_gates)
    state = _read_state(plan_dir)
    cleared = _coerce_cleared_gates(state.get("cleared_gates"))
    active_breakers_list = list(state.get("active_breakers") or [])
    active_defers_list = list(state.get("active_defers") or [])
    # Plan 2026-05-02-003 F003 — pre_resume_after_child:* gates participate in
    # the unmet check the same way breakers/defers do. resume --all does NOT
    # clear them (the operator must use `approve <plan> pre_resume_after_child
    # --child <child_id>` with fan-in memo + child-compliance validation).
    active_pre_resume_list = list(state.get("active_pre_resume_after_children") or [])
    plan_unmet = [g for g in declared_strs if g not in cleared]
    combined_declared = (
        declared_strs + active_breakers_list + active_defers_list + active_pre_resume_list
    )
    unmet = plan_unmet + active_breakers_list + active_defers_list + active_pre_resume_list
    return GateCheck(paused=bool(unmet), declared=combined_declared, cleared=cleared, unmet=unmet)


def add_breaker(plan_dir: Path, breaker_gate: str, *, plan_id: str, reason: str = "") -> bool:
    """F006 — record that a circuit breaker tripped. Adds the synthetic
    breaker:<kind> name to active_breakers. Idempotent: re-adding is a no-op.
    Returns True if state changed.
    """
    state = _read_state(plan_dir)
    state["plan_id"] = plan_id
    breakers = list(state.get("active_breakers") or [])
    if breaker_gate in breakers:
        return False
    breakers.append(breaker_gate)
    state["active_breakers"] = breakers
    history = list(state.get("history") or [])
    history.append(
        {
            "action": "breaker_trip",
            "gate": breaker_gate,
            "at": _now_iso(),
            "actor": "supervisor",
            "reason": reason,
        }
    )
    state["history"] = history
    _write_state(plan_dir, state)
    return True


def active_breakers(plan_dir: Path) -> list[str]:
    return list(_read_state(plan_dir).get("active_breakers") or [])


def add_defer(plan_dir: Path, defer_gate: str, *, plan_id: str, reason: str = "") -> bool:
    """F007 — record that an admission-policy defer should fire. Adds the
    synthetic defer:<kind> name to active_defers. Idempotent."""
    state = _read_state(plan_dir)
    state["plan_id"] = plan_id
    defers = list(state.get("active_defers") or [])
    if defer_gate in defers:
        return False
    defers.append(defer_gate)
    state["active_defers"] = defers
    history = list(state.get("history") or [])
    history.append(
        {
            "action": "defer_trip",
            "gate": defer_gate,
            "at": _now_iso(),
            "actor": "supervisor",
            "reason": reason,
        }
    )
    state["history"] = history
    _write_state(plan_dir, state)
    return True


def active_defers(plan_dir: Path) -> list[str]:
    return list(_read_state(plan_dir).get("active_defers") or [])


# ──────────────────────────────  Plan 2026-05-02-003 F003 — pre_resume_after_child  ──────────────────────────────


def add_pre_resume_after_child(
    plan_dir: Path,
    child_plan_id: str,
    *,
    plan_id: str,
    reason: str = "",
) -> bool:
    """F003 — arm a `pre_resume_after_child:{child_plan_id}` gate on the
    parent. Tracked separately from active_breakers / active_defers because
    its clearance lifecycle is different: only `approve <parent>
    pre_resume_after_child --child <child_id>` (with fan-in memo +
    child-compliance validation) can clear it. `resume --all` and
    `resume --gate pre_resume_after_child:*` do NOT clear it.

    Idempotent: returns True on first arm, False on re-arm. Records a
    `pre_resume_after_child_arm` history entry on first arm.
    """
    gate_str = f"pre_resume_after_child:{child_plan_id}"
    state = _read_state(plan_dir)
    state["plan_id"] = plan_id
    pending = list(state.get("active_pre_resume_after_children") or [])
    if gate_str in pending:
        return False
    pending.append(gate_str)
    state["active_pre_resume_after_children"] = pending
    history = list(state.get("history") or [])
    history.append(
        {
            "action": "pre_resume_after_child_arm",
            "gate": gate_str,
            "at": _now_iso(),
            "actor": "supervisor",
            "reason": reason,
        }
    )
    state["history"] = history
    _write_state(plan_dir, state)
    return True


def clear_pre_resume_after_child(
    plan_dir: Path,
    child_plan_id: str,
    *,
    plan_id: str,
    actor: str = "operator",
    reason: str = "",
) -> bool:
    """F003 — clear a previously-armed pre_resume_after_child gate.
    Idempotent: returns True if state changed, False if the gate was
    already cleared (or never armed). `nested_orchestration.
    approve_pre_resume_after_child` is the canonical caller; direct
    calls bypass the fan-in memo + child-compliance validation."""
    gate_str = f"pre_resume_after_child:{child_plan_id}"
    state = _read_state(plan_dir)
    pending = list(state.get("active_pre_resume_after_children") or [])
    if gate_str not in pending:
        return False
    pending = [g for g in pending if g != gate_str]
    if pending:
        state["active_pre_resume_after_children"] = pending
    else:
        state.pop("active_pre_resume_after_children", None)
    state["plan_id"] = plan_id
    history = list(state.get("history") or [])
    history.append(
        {
            "action": "pre_resume_after_child_clear",
            "gate": gate_str,
            "at": _now_iso(),
            "actor": actor,
            "reason": reason,
        }
    )
    state["history"] = history
    _maybe_clear_pause_marker(state)
    _write_state(plan_dir, state)
    return True


def active_pre_resume_after_children(plan_dir: Path) -> list[str]:
    """F003 — currently-armed `pre_resume_after_child:*` gates. Each entry
    is the full gate name (`pre_resume_after_child:{child_plan_id}`).
    `resume --all` does NOT touch this list."""
    return list(_read_state(plan_dir).get("active_pre_resume_after_children") or [])


def reconcile_defers(
    plan_dir: Path,
    desired: set[str],
    *,
    plan_id: str,
    reason_for: dict[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """F007 — make active_defers match `desired` (the set computed from
    quota_admission.evaluate). Returns (added, removed) for logging.

    Transient lifecycle:
      - desired ∋ gate, not currently active → add (records defer_trip)
      - desired ∌ gate, currently active     → remove (records defer_clear,
                                                actor='supervisor', reason='condition_cleared')
      - intersection                          → leave alone

    Operator approve/resume_all between dispatches still works the same —
    they pop entries from active_defers; the next reconcile re-adds anything
    whose underlying condition is still true.
    """
    state = _read_state(plan_dir)
    state["plan_id"] = plan_id
    current = list(state.get("active_defers") or [])
    current_set = set(current)
    added: list[str] = []
    removed: list[str] = []
    history = list(state.get("history") or [])
    now_iso = _now_iso()

    for gate in sorted(desired - current_set):
        current.append(gate)
        added.append(gate)
        history.append(
            {
                "action": "defer_trip",
                "gate": gate,
                "at": now_iso,
                "actor": "supervisor",
                "reason": (reason_for or {}).get(gate, ""),
            }
        )
    for gate in sorted(current_set - desired):
        current = [g for g in current if g != gate]
        removed.append(gate)
        history.append(
            {
                "action": "defer_clear",
                "gate": gate,
                "at": now_iso,
                "actor": "supervisor",
                "reason": "condition_cleared",
            }
        )

    if added or removed:
        if current:
            state["active_defers"] = current
        else:
            state.pop("active_defers", None)
        state["history"] = history
        # Auto-clear the pause marker if every gate the supervisor recorded
        # as pending is now resolved. Reconcile may auto-drop a defer whose
        # condition resolved between dispatches; without this call, paused_at
        # / pause_gates stay stale on the state file even though dispatch
        # would proceed.
        _maybe_clear_pause_marker(state)
        _write_state(plan_dir, state)
    return added, removed


__all__ = [
    "GATE_STATE_FILENAME",
    "LIFECYCLE_STAGED_GATES",
    "LIFECYCLE_STAGES",
    "CompatGateState",
    "GateCheck",
    "GatePauseInfo",
    "GateStateReconciliationError",
    "active_breakers",
    "active_defers",
    "active_pre_resume_after_children",
    "add_breaker",
    "add_defer",
    "add_pre_resume_after_child",
    "approve_gate",
    "clear_pre_resume_after_child",
    "cleared_gates",
    "evaluate",
    "evaluate_human_gates",
    "format_reconciliation_inbox_body",
    "gate_state_path",
    "is_gate_cleared",
    "is_gate_currently_pending",
    "is_lifecycle_gate",
    "is_stage_completed",
    "load_gate_state_compat",
    "pending_stage",
    "reconcile_defers",
    "reconcile_gate_state",
    "record_pause",
    "reset_for_test",
    "resume_all",
    "unmet_gates",
]
