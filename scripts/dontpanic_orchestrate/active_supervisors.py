"""F023 EC13 — active-supervisor registry.

Each running supervisor appends a JSONL entry to ~/.jarvis/active_supervisors.jsonl
when it starts a dispatch and removes its entry on exit (via atexit). `jarvis ps`
reads the file, filters dead PIDs, and prints the live set. `check_reentrancy`
returns the active entry for the same plan_id if one exists, so the supervisor
can warn before launching a parallel run on the same plan.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

_DEFAULT_REGISTRY_PATH = Path.home() / ".jarvis" / "active_supervisors.jsonl"
REGISTRY_PATH = _DEFAULT_REGISTRY_PATH


def _effective_registry_path() -> Path:
    """Honor JARVIS_ACTIVE_SUPERVISORS_PATH for hermetic test isolation;
    fall back to the module-attribute path so legacy tests that monkey-patch
    REGISTRY_PATH directly still work."""
    env_override = os.environ.get("JARVIS_ACTIVE_SUPERVISORS_PATH")
    if env_override:
        return Path(env_override)
    return REGISTRY_PATH


@dataclass(frozen=True)
class SupervisorEntry:
    pid: int
    plan_id: str
    target_env: str
    target_project: str | None
    started_at: str
    supervisor_config_dir: str | None  # ExecutionEnvironment root, when known
    # F009 — the plan-run fingerprint captured at dispatch start: source file
    # content hashes + mtimes + capture timestamp. Lets `dontpanic ps` and any
    # external reconciler see WHAT plan state this run is operating against
    # without re-reading the plan dir. Optional/default None so registry lines
    # written before this field still parse.
    plan_fingerprint: dict | None = None


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_parent() -> None:
    _effective_registry_path().parent.mkdir(parents=True, exist_ok=True)


def _read_all() -> list[SupervisorEntry]:
    path = _effective_registry_path()
    if not path.is_file():
        return []
    out: list[SupervisorEntry] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            out.append(SupervisorEntry(**data))
        except (json.JSONDecodeError, TypeError):
            continue
    return out


def _write_all(entries: list[SupervisorEntry]) -> None:
    _ensure_parent()
    body = "".join(json.dumps(asdict(e)) + "\n" for e in entries)
    _effective_registry_path().write_text(body)


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it — still alive.
        return True
    except OSError:
        return False
    return True


def register(
    plan_id: str,
    target_env: str,
    target_project: str | None,
    supervisor_config_dir: str | None,
    pid: int | None = None,
    plan_fingerprint: dict | None = None,
) -> SupervisorEntry:
    """Append a fresh entry for the current process to the registry."""
    entry = SupervisorEntry(
        pid=pid if pid is not None else os.getpid(),
        plan_id=plan_id,
        target_env=target_env,
        target_project=target_project,
        started_at=_now_iso(),
        supervisor_config_dir=supervisor_config_dir,
        plan_fingerprint=plan_fingerprint,
    )
    entries = _read_all()
    entries.append(entry)
    _write_all(entries)
    return entry


def unregister(plan_id: str, pid: int | None = None) -> int:
    """Remove every entry matching (plan_id, pid). Returns count removed."""
    target_pid = pid if pid is not None else os.getpid()
    entries = _read_all()
    kept = [e for e in entries if not (e.plan_id == plan_id and e.pid == target_pid)]
    removed = len(entries) - len(kept)
    if removed:
        _write_all(kept)
    return removed


def list_active(*, prune: bool = True) -> list[SupervisorEntry]:
    """Return all entries with live PIDs. When prune=True (default), the
    registry file is rewritten without dead entries as a side effect."""
    entries = _read_all()
    alive = [e for e in entries if _is_pid_alive(e.pid)]
    if prune and len(alive) != len(entries):
        _write_all(alive)
    return alive


def live_supervisor_rows() -> list[dict]:
    """Live supervisor rows as plain dicts for the operator-triage run_state
    join (idle/running/conflicted). Alive-pid filtered, best-effort, read-only;
    a missing/corrupt registry yields []."""
    try:
        rows = _read_all()
    except Exception:
        return []
    out: list[dict] = []
    for e in rows:
        pid = getattr(e, "pid", None)
        if pid is not None and _is_pid_alive(pid):
            out.append({
                "plan_id": getattr(e, "plan_id", None),
                "pid": pid,
                "started_at": getattr(e, "started_at", None),
                "agent": getattr(e, "agent", None),
                "session": getattr(e, "session", None),
            })
    return out


def check_reentrancy(plan_id: str) -> SupervisorEntry | None:
    """Return any live entry sharing this plan_id (any PID), else None.
    Supervisor uses this to warn before launching a parallel run on the same
    plan dir — concurrent volleys against the same plan corrupt audit
    iteration numbering and target_context recording.
    """
    for e in list_active():
        if e.plan_id == plan_id:
            return e
    return None


def format_entries(entries: list[SupervisorEntry]) -> str:
    """Human-readable single-string render for `jarvis ps`."""
    if not entries:
        return "No active supervisors."
    headers = ["PID", "PLAN_ID", "ENV", "PROJECT", "STARTED", "CONFIG_DIR"]
    rows = [
        [
            str(e.pid),
            e.plan_id,
            e.target_env,
            e.target_project or "(none)",
            e.started_at,
            e.supervisor_config_dir or "(inherit)",
        ]
        for e in entries
    ]
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    lines = [fmt.format(*headers), fmt.format(*["-" * w for w in widths])]
    for r in rows:
        lines.append(fmt.format(*r))
    return "\n".join(lines)


__all__ = [
    "REGISTRY_PATH",
    "SupervisorEntry",
    "check_reentrancy",
    "format_entries",
    "list_active",
    "register",
    "unregister",
]
