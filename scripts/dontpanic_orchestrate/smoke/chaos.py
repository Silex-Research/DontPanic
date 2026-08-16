"""Deterministic chaos perturbations (plan 2026-08-09-003 F003).

A chaos scenario that asserts recovery behavior encodes current
supervisor behavior, not a requirement. This module observes: it fires
the declared perturbation on the declared call index and records what
happened. It does not prescribe how the supervisor should recover.

Perturbations fire by (role, call_index), never at random. The same
scenario therefore produces the same sequence on every run.

Covered kinds (v0):

  * timeout        — implementer/auditor Nth dispatch times out
  * nonzero_exit   — implementer/auditor Nth dispatch returns non-zero
  * quota_exhausted — applied at the existing admission path
                     (quota_admission.evaluate) rather than swallowed
                     inside the executor. Delayed-to-Nth-call quota
                     would require a supervisor change; that is a
                     finding, not a patch.
"""

from __future__ import annotations

from collections.abc import Sequence

from dontpanic_orchestrate.smoke.loader import Perturbation


class ChaosInjector:
    """Replay a scenario's perturbations deterministically by call index."""

    def __init__(self, perturbations: Sequence[Perturbation] | None = None) -> None:
        self._items: tuple[Perturbation, ...] = tuple(perturbations or ())
        self._counts: dict[str, int] = {}
        self.fired: list[Perturbation] = []

    @property
    def fired_kinds(self) -> list[str]:
        return [p.kind for p in self.fired]

    def quota_perturbations(self) -> tuple[Perturbation, ...]:
        return tuple(p for p in self._items if p.kind == "quota_exhausted")

    def fire_quota_at_admission(self) -> list[Perturbation]:
        """Record quota perturbations as fired at the admission seam."""
        fired: list[Perturbation] = []
        for item in self.quota_perturbations():
            self.fired.append(item)
            fired.append(item)
        return fired

    def on_dispatch(self, role: str, agent: str | None = None) -> Perturbation | None:
        idx = self._counts.get(role, 0)
        self._counts[role] = idx + 1
        for item in self._items:
            if item.kind == "quota_exhausted":
                continue
            if item.call_index != idx:
                continue
            if item.role is not None and item.role != role:
                continue
            if item.agent is not None and agent is not None and item.agent != agent:
                continue
            self.fired.append(item)
            return item
        return None
