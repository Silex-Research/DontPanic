"""Plan G F006 — doctor check registration framework.

F006 ships ONLY the registration framework + a single baseline check
(Python version). Adapter-specific checks (web / iOS / Android /
backend) ship with their own plans (G2-G5 per D013) — F006 must NOT
know about them.

The registry is a process-level singleton: adapters register checks at
import time via :func:`register_doctor_check`. Tests reset state with
:func:`_reset_for_tests`.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass

DoctorCheck = Callable[[], "DoctorResult"]


@dataclass(frozen=True)
class DoctorResult:
    name: str
    status: str  # "pass" | "warn" | "fail"
    detail: str = ""


_REGISTRY: dict[str, DoctorCheck] = {}


def register_doctor_check(check_id: str, check: DoctorCheck) -> None:
    """Register a doctor check. Idempotent — registering the same
    ``check_id`` twice is a no-op (the second call wins only if the
    callable identity differs, but even then we keep the first to avoid
    surprising adapters that re-import)."""
    if check_id in _REGISTRY:
        return
    _REGISTRY[check_id] = check


def run_all_checks() -> list[DoctorResult]:
    """Run every registered check in registration order.

    Each check is wrapped in a try/except so one adapter's bad probe
    can't block the rest of the report. Failures surface as ``fail``
    with the exception in ``detail``."""
    out: list[DoctorResult] = []
    for check_id, check in _REGISTRY.items():
        try:
            out.append(check())
        except Exception as exc:  # noqa: BLE001 — defensive: doctor is best-effort
            out.append(
                DoctorResult(
                    name=check_id,
                    status="fail",
                    detail=f"check raised: {exc!r}",
                )
            )
    return out


_RECOMMENDED_PYTHON = (3, 11)


def _python_version_check() -> DoctorResult:
    """Soft check — DontPanic's pyproject.toml pins ``requires-python >= 3.10``,
    but Google API Core warns 3.10 will lose support in 2026-10. Surface as
    ``warn`` rather than ``fail`` so operators on 3.10 can keep running while
    seeing the upgrade prompt."""
    cur = sys.version_info
    detail = f"{cur.major}.{cur.minor}.{cur.micro}"
    if (cur.major, cur.minor) < _RECOMMENDED_PYTHON:
        return DoctorResult(
            name="python_version",
            status="warn",
            detail=f"{detail} (>= 3.11 recommended)",
        )
    return DoctorResult(name="python_version", status="pass", detail=detail)


def _register_baseline_checks() -> None:
    """Idempotent: registers F006's baseline checks. Adapter-specific
    checks register through their own modules (G2-G5)."""
    register_doctor_check("python_version", _python_version_check)


def _reset_for_tests() -> None:
    """Clear the registry. Tests use this between runs so registrations
    don't leak across test cases."""
    _REGISTRY.clear()


# Register baseline checks at import time so the framework is usable
# without explicit setup. G2-G5 adapter modules will append their own
# checks when imported.
_register_baseline_checks()


__all__ = [
    "DoctorCheck",
    "DoctorResult",
    "register_doctor_check",
    "run_all_checks",
]
