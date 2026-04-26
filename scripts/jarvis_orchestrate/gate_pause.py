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


def approve_gate(plan_dir: Path, gate: Any, *, plan_id: str, actor: str = "operator") -> bool:
    """Mark a single gate cleared. Idempotent — re-approving is a no-op
    (no INBOX append). Returns True if state changed."""
    gate_str = _stringify_gates([gate])[0]
    state = _read_state(plan_dir)
    state["plan_id"] = plan_id
    cleared = list(state.get("cleared_gates") or [])
    if gate_str in cleared:
        return False
    cleared.append(gate_str)
    state["cleared_gates"] = cleared
    history = list(state.get("history") or [])
    history.append(
        {"action": "approve", "gate": gate_str, "at": _now_iso(), "actor": actor}
    )
    state["history"] = history
    _write_state(plan_dir, state)
    return True


def resume_all(plan_dir: Path, *, plan_id: str, declared_gates: list[Any], actor: str = "operator") -> list[str]:
    """Clear every declared gate. Returns the list of gates newly cleared
    (excludes ones that were already cleared)."""
    declared_strs = _stringify_gates(declared_gates)
    state = _read_state(plan_dir)
    state["plan_id"] = plan_id
    cleared = set(state.get("cleared_gates") or [])
    newly = [g for g in declared_strs if g not in cleared]
    if not newly:
        return []
    cleared.update(newly)
    state["cleared_gates"] = sorted(cleared)
    history = list(state.get("history") or [])
    for g in newly:
        history.append(
            {"action": "resume_all", "gate": g, "at": _now_iso(), "actor": actor}
        )
    state["history"] = history
    _write_state(plan_dir, state)
    return newly


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
    """Pure read of current gate state vs declared gates. Does not write."""
    declared_strs = _stringify_gates(declared_gates)
    cleared = cleared_gates(plan_dir)
    unmet = [g for g in declared_strs if g not in cleared]
    return GateCheck(paused=bool(unmet), declared=declared_strs, cleared=cleared, unmet=unmet)


__all__ = [
    "GATE_STATE_FILENAME",
    "GateCheck",
    "approve_gate",
    "cleared_gates",
    "evaluate",
    "gate_state_path",
    "is_gate_cleared",
    "record_pause",
    "reset_for_test",
    "resume_all",
    "unmet_gates",
]
