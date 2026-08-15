"""Capture the ``exact_command`` each renderable emitter's event renders to.

Plan 2026-08-09-002 F005, audit i0 finding 2. Acceptance 7 says every exact
command is byte-identical before and after, and the F005 test module checks
that by re-rendering a captured baseline. That baseline is built from
*synthetic* events, whose ``technical_metadata`` deliberately supplies more
than production does — so a change made at an **emit site** rather than in the
templates moves the real command without moving the baseline. Audit i0 found
exactly that: an earlier revision of F005 taught the gate-pause emitter to
publish gate metadata, which turned the live approval command from
``dontpanic approve <plan> implement`` into ``dontpanic approve <plan>
pre_merge`` while all 549 tests stayed green.

This module closes that hole by driving the **real emitters** and recording
what they actually render to. It is deliberately standalone — it imports only
production modules, never the F005 test module — so the identical file runs
against the pre-change tree:

    git worktree add /tmp/f005-before HEAD
    cp scripts/dontpanic_orchestrate/tests/tools/f005_emitter_command_probe.py \\
        /tmp/f005-before/scripts/dontpanic_orchestrate/tests/tools/
    python3 /tmp/f005-before/scripts/dontpanic_orchestrate/tests/tools/\\
        f005_emitter_command_probe.py --write <fixture path in the real tree>

Emitters are called with their **pre-change** signatures only (no ``loaded=``),
because the file has to be callable in both trees. That costs nothing: a
``DecisionBrief`` never reaches ``exact_command``, so the command a probe
records is independent of whether a brief rode along.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from dontpanic_orchestrate import (  # noqa: E402
    circuit_breakers,
    event_copy,
    gate_pause,
    inbox,
    notify,
    notify_event,
    supervisor,
)

PLAN_ID = "2026-08-09-002-feat-decision-brief-at-gates"
FEATURE_ID = "F005"


@contextmanager
def _captured_events() -> Iterator[list[Any]]:
    """Silence every sink an emitter touches and collect the events it builds.

    Hand-rolled rather than pytest's ``monkeypatch`` so the probe runs as a
    plain script inside a throwaway worktree of the pre-change tree, where the
    F005 test module does not exist and pytest may not be installed.
    """
    captured: list[Any] = []
    originals = {
        (notify_event, "dispatch_event"): notify_event.dispatch_event,
        (inbox, "append_event"): inbox.append_event,
        (notify, "notify"): notify.notify,
        (circuit_breakers, "record_global_hit"): circuit_breakers.record_global_hit,
        (gate_pause, "add_breaker"): gate_pause.add_breaker,
    }
    notify_event.dispatch_event = lambda ev, **kw: captured.append(ev)  # type: ignore[assignment]
    inbox.append_event = lambda *a, **k: None  # type: ignore[assignment]
    notify.notify = lambda *a, **k: True  # type: ignore[assignment]
    circuit_breakers.record_global_hit = lambda *a, **k: None  # type: ignore[assignment]
    gate_pause.add_breaker = lambda *a, **k: None  # type: ignore[assignment]
    try:
        yield captured
    finally:
        for (module, name), original in originals.items():
            setattr(module, name, original)


def _budget_result(
    kind: circuit_breakers.BudgetCeilingKind, **fields: Any
) -> circuit_breakers.BudgetCeilingResult:
    return circuit_breakers.BudgetCeilingResult(
        kind=kind,
        tripped=True,
        reason="probe",
        agent="claude",
        window="weekly",
        **fields,
    )


def _probes(plan_dir: Path) -> dict[str, Callable[[], None]]:
    """One entry per live emit site, keyed by a stable probe name.

    Three gate-pause shapes because the pause is where the gate / stage
    distinction bites: one gate, two gates, and the default stage with no
    explicit one.
    """
    return {
        "gate_pause.single_gate": lambda: supervisor._emit_gate_paused_discord(
            plan_dir, PLAN_ID, FEATURE_ID, pending_gates=["pre_merge"], stage="implement"
        ),
        "gate_pause.two_gates": lambda: supervisor._emit_gate_paused_discord(
            plan_dir,
            PLAN_ID,
            FEATURE_ID,
            pending_gates=["pre_impl", "pre_merge"],
            stage="implement",
        ),
        "gate_pause.default_stage": lambda: supervisor._emit_gate_paused_discord(
            plan_dir, PLAN_ID, FEATURE_ID, pending_gates=["pre_merge"]
        ),
        "trip_breaker.iteration_cap": lambda: supervisor._trip_breaker(
            plan_dir,
            PLAN_ID,
            FEATURE_ID,
            circuit_breakers.BreakerKind.ITERATION_CAP,
            "cap reached",
        ),
        "trip_breaker.global": lambda: supervisor._trip_breaker(
            plan_dir,
            PLAN_ID,
            FEATURE_ID,
            circuit_breakers.BreakerKind.GLOBAL_CIRCUIT_BREAKER,
            "3 hits in 24h",
        ),
        "budget.calibration_required": lambda: supervisor._emit_budget_kind_specific_event(
            plan_dir,
            PLAN_ID,
            _budget_result(
                circuit_breakers.BudgetCeilingKind.CALIBRATION_REQUIRED,
                confidence="low",
            ),
            FEATURE_ID,
        ),
        "budget.unit_mismatch": lambda: supervisor._emit_budget_kind_specific_event(
            plan_dir,
            PLAN_ID,
            _budget_result(
                circuit_breakers.BudgetCeilingKind.UNIT_MISMATCH,
                cap_unit="tokens",
                observed_unit="percent",
            ),
            FEATURE_ID,
        ),
        "budget.config_required": lambda: supervisor._emit_budget_kind_specific_event(
            plan_dir,
            PLAN_ID,
            _budget_result(
                circuit_breakers.BudgetCeilingKind.CONFIG_REQUIRED,
                details={"cause": "no_cap_for_signal"},
            ),
            FEATURE_ID,
        ),
    }


def capture() -> dict[str, dict[str, Any]]:
    """``{probe: {inbox_event, exact_command}}`` for every live emit site.

    ``exact_command`` is what ``event_copy.render`` produces for the event the
    emitter actually dispatched — the string the operator is told to paste.
    """
    out: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        plan_dir = Path(tmp)
        for name, run in _probes(plan_dir).items():
            with _captured_events() as captured:
                run()
            if not captured:
                out[name] = {"inbox_event": None, "exact_command": None}
                continue
            event = captured[-1]
            rendered = event_copy.render(event)
            out[name] = {
                "inbox_event": getattr(event, "inbox_event", None),
                "exact_command": None if rendered is None else rendered.exact_command,
            }
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", type=Path, help="write the capture to this path as JSON"
    )
    args = parser.parse_args(argv)
    payload = {
        "note": (
            "Rendered exact_command per live emit site, captured against the "
            "tree as it stood before plan 2026-08-09-002 F005. Regenerating "
            "against the post-change tree would make F005 acceptance 7 "
            "vacuous. gate_pause.* names the *stage* rather than the pending "
            "gate: that is the pre-existing defect plan 2026-08-10-001 owns, "
            "recorded here so F005 can be shown not to have changed it."
        ),
        "probes": capture(),
    }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(text, encoding="utf-8")
        print(f"wrote {args.write}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main(sys.argv[1:]))
