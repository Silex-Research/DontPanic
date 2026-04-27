"""F008 Item 2 — gate-pause protocol.

Plans declare `human_gates: [pre_impl, on_escalation, ...]`. Before any
dispatch begins, the supervisor checks whether each declared gate has been
cleared by the operator. Unmet gates pause the supervisor: a marker is
written, an INBOX entry is appended, terminal-notifier fires, and
dispatch_volley returns VolleyResult(final_status="paused_on_gate") without
calling any executor.

The operator clears gates via CLI:
  - `jarvis approve <plan-id> <gate>` clears one gate
  - `jarvis resume  <plan-id>`         clears all declared gates

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


def _write_state(plan_dir: Path, state: dict[str, Any]) -> None:
    p = gate_state_path(plan_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def is_gate_cleared(plan_dir: Path, gate: str) -> bool:
    return gate in (_read_state(plan_dir).get("cleared_gates") or [])


def cleared_gates(plan_dir: Path) -> list[str]:
    return list(_read_state(plan_dir).get("cleared_gates") or [])


def unmet_gates(plan_dir: Path, declared_gates: list[Any]) -> list[str]:
    cleared = set(cleared_gates(plan_dir))
    declared_strs = _stringify_gates(declared_gates)
    return [g for g in declared_strs if g not in cleared]


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
    cleared = set(state.get("cleared_gates") or [])
    active_breakers_set = set(state.get("active_breakers") or [])
    active_defers_set = set(state.get("active_defers") or [])

    def _is_resolved(gate: str) -> bool:
        if gate.startswith("breaker:"):
            return gate not in active_breakers_set
        if gate.startswith("defer:"):
            return gate not in active_defers_set
        return gate in cleared

    if all(_is_resolved(g) for g in pending):
        state.pop("paused_at", None)
        state.pop("pause_gates", None)


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

    history = list(state.get("history") or [])
    history.append(
        {"action": "approve", "gate": gate_str, "at": _now_iso(), "actor": actor}
    )
    state["history"] = history

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

    _maybe_clear_pause_marker(state)
    _write_state(plan_dir, state)
    return True


def resume_all(plan_dir: Path, *, plan_id: str, declared_gates: list[Any], actor: str = "operator") -> list[str]:
    """Clear every declared gate AND every active transient gate (breakers +
    F007 defers). Returns the list of names newly cleared in this call."""
    declared_strs = _stringify_gates(declared_gates)
    state = _read_state(plan_dir)
    state["plan_id"] = plan_id
    cleared = set(state.get("cleared_gates") or [])
    newly = [g for g in declared_strs if g not in cleared]
    pending_breakers = list(state.get("active_breakers") or [])
    pending_defers = list(state.get("active_defers") or [])
    # Don't early-return when declared_gates were already cleared if any
    # transient gate still exists — operator's "resume all" must reach those.
    if not newly and not pending_breakers and not pending_defers:
        return []
    if newly:
        cleared.update(newly)
        state["cleared_gates"] = sorted(cleared)
    history = list(state.get("history") or [])
    for g in newly:
        history.append(
            {"action": "resume_all", "gate": g, "at": _now_iso(), "actor": actor}
        )
    for b in pending_breakers:
        history.append(
            {"action": "resume_all", "gate": b, "at": _now_iso(), "actor": actor}
        )
    for d in pending_defers:
        history.append(
            {"action": "resume_all", "gate": d, "at": _now_iso(), "actor": actor}
        )
    if pending_breakers:
        state.pop("active_breakers", None)
    if pending_defers:
        state.pop("active_defers", None)
    if pending_breakers or pending_defers:
        # Strip transient entries from cleared_gates too (they should never
        # accumulate there).
        state["cleared_gates"] = sorted(
            c for c in (state.get("cleared_gates") or [])
            if not c.startswith("breaker:") and not c.startswith("defer:")
        )
    state["history"] = history
    _maybe_clear_pause_marker(state)
    _write_state(plan_dir, state)
    return newly + pending_breakers + pending_defers


def record_pause(
    plan_dir: Path,
    *,
    plan_id: str,
    pause_gates: list[Any],
) -> None:
    """Record that the supervisor paused waiting on these gates."""
    pause_strs = _stringify_gates(pause_gates)
    state = _read_state(plan_dir)
    state["plan_id"] = plan_id
    state["paused_at"] = _now_iso()
    state["pause_gates"] = pause_strs
    history = list(state.get("history") or [])
    history.append(
        {
            "action": "pause",
            "at": state["paused_at"],
            "actor": "supervisor",
            "pause_gates": pause_strs,
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
    cleared = list(state.get("cleared_gates") or [])
    active_breakers_list = list(state.get("active_breakers") or [])
    active_defers_list = list(state.get("active_defers") or [])
    plan_unmet = [g for g in declared_strs if g not in cleared]
    combined_declared = declared_strs + active_breakers_list + active_defers_list
    unmet = plan_unmet + active_breakers_list + active_defers_list
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
    "GateCheck",
    "active_breakers",
    "active_defers",
    "add_breaker",
    "add_defer",
    "approve_gate",
    "cleared_gates",
    "evaluate",
    "gate_state_path",
    "is_gate_cleared",
    "reconcile_defers",
    "record_pause",
    "reset_for_test",
    "resume_all",
    "unmet_gates",
]
