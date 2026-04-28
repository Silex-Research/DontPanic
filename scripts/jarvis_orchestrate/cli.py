"""argparse entry for `python -m jarvis_orchestrate`.

Single-agent dispatch (F004):
  python -m jarvis_orchestrate <plan-id> [--feature F001] [--role implementer]

Volley dispatch (F005a — implementer/auditor pair, iterate until signoff or cap):
  python -m jarvis_orchestrate <plan-id> --volley [--feature F001]
                                                  [--implementer claude] [--auditor codex]
                                                  [--max-iterations 3]
                                                  [--mode interactive|p0|autonomous]

Active-supervisor registry (F023 EC13):
  python -m jarvis_orchestrate ps

Engagement-surface gate handling (F008 + F006 + F007):
  python -m jarvis_orchestrate approve <plan-id> <gate>   # clear one declared gate
  python -m jarvis_orchestrate resume  <plan-id>          # clear every declared gate

Interactive backoff touch (F007 Slice 2):
  python -m jarvis_orchestrate claude-touch               # record human Claude request now
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jarvis_orchestrate import (
    active_supervisors,
    gate_pause,
    inbox,
    interactive_state,
    plan_loader,
    quota_admission,
    supervisor,
)
from jarvis_orchestrate import (
    circuit_breakers as cb,
)
from jarvis_orchestrate.supervisor import QuotaExceeded


def _resolve_plan_dir(plan_arg: str) -> Path:
    p = Path(plan_arg)
    if p.is_dir():
        return p
    cwd_match = Path.cwd() / "docs" / "plans" / plan_arg
    if cwd_match.is_dir():
        return cwd_match
    raise SystemExit(f"plan not found: {plan_arg}")


def _ps_main(argv: list[str]) -> int:
    """F023 EC13: list live supervisors registered in
    ~/.jarvis/active_supervisors.jsonl. Filters dead PIDs and prunes the file
    as a side effect."""
    entries = active_supervisors.list_active()
    print(active_supervisors.format_entries(entries))
    return 0


def _approve_main(argv: list[str]) -> int:
    """F008 Item 2: clear a single declared gate for a plan."""
    if len(argv) != 2:
        print("usage: jarvis-orchestrate approve <plan-id> <gate>", file=sys.stderr)
        return 2
    plan_arg, gate = argv
    # F006: the global circuit breaker is hard-stop and intentionally has no
    # operator clearance path. Refuse the approve so the CLI surface matches
    # the spec ("APPROVAL_BREAKERS frozenset names the 6 pause-for-approval
    # kinds; the 7th (global) is hard-stop"). Operators wait out the 24h
    # window; there is no jarvis clear-global-breaker.
    global_gate = f"breaker:{cb.BreakerKind.GLOBAL_CIRCUIT_BREAKER.value}"
    if gate == global_gate:
        print(
            f"[approve] REFUSED gate {gate!r} — the global circuit breaker is "
            "hard-stop and has no operator clearance path. Wait for the 24h "
            "window to expire (see ~/.jarvis/breaker_history.jsonl).",
            file=sys.stderr,
        )
        return 2
    plan_dir = _resolve_plan_dir(plan_arg)
    loaded = plan_loader.load(plan_dir)
    # plan.human_gates is a list of HumanGate enum members; compare on .value
    # so the user-supplied string CLI arg matches the declared set.
    declared_strs = [
        g.value if hasattr(g, "value") else str(g) for g in (loaded.plan.human_gates or [])
    ]
    # F006: synthetic breaker:<kind> gates are valid declared names too — the
    # supervisor adds them to active_breakers on trip. Don't false-warn when
    # operator approves a known breaker name (either currently active or any
    # known approval-required BreakerKind, in case the operator is pre-clearing).
    # The global kind is excluded above; the rest of APPROVAL_BREAKERS is fair game.
    # F007: same treatment for synthetic defer:<kind> gates added by the
    # admission reconcile.
    active_breakers = gate_pause.active_breakers(plan_dir)
    active_defers = gate_pause.active_defers(plan_dir)
    breaker_names = {f"breaker:{k.value}" for k in cb.APPROVAL_BREAKERS}
    defer_names = {quota_admission.gate_name(k) for k in quota_admission.DeferKind}
    valid_targets = (
        set(declared_strs) | set(active_breakers) | set(active_defers) | breaker_names | defer_names
    )
    if gate not in valid_targets:
        print(
            f"[approve] WARNING gate {gate!r} not in plan.human_gates {declared_strs} "
            f"and not a known breaker:* name; recording anyway",
            file=sys.stderr,
        )
    changed = gate_pause.approve_gate(plan_dir, gate, plan_id=loaded.plan_id)
    if changed:
        inbox.append_event(
            plan_dir,
            event="gate_cleared",
            plan_id=loaded.plan_id,
            body=f"Operator approved gate {gate!r} via `jarvis approve`.",
            gate=gate,
        )
        print(f"[approve] cleared gate {gate!r} for {loaded.plan_id}")
    else:
        print(f"[approve] gate {gate!r} was already cleared")
    # Remaining unmet = unmet plan-declared + every still-active breaker +
    # every still-active defer. unmet_gates() considers only plan-declared
    # gates, which used to give operators a misleading "(none)" while a
    # transient breaker:* / defer:* was still blocking dispatch.
    remaining = gate_pause.evaluate(plan_dir, declared_strs).unmet
    print(f"[approve] remaining unmet gates: {remaining or '(none)'}")
    return 0


def _resume_main(argv: list[str]) -> int:
    """F008 Item 2 + F006 + F007: clear every plan-declared gate AND every
    active transient gate (breakers + defers). Returns success even when all
    sets are empty (idempotent)."""
    if len(argv) != 1:
        print("usage: jarvis-orchestrate resume <plan-id>", file=sys.stderr)
        return 2
    plan_arg = argv[0]
    plan_dir = _resolve_plan_dir(plan_arg)
    loaded = plan_loader.load(plan_dir)
    declared = list(loaded.plan.human_gates or [])
    active_breakers = gate_pause.active_breakers(plan_dir)
    active_defers = gate_pause.active_defers(plan_dir)
    if not declared and not active_breakers and not active_defers:
        print(
            f"[resume] plan {loaded.plan_id} has no plan-declared gates, "
            f"no active breakers, and no active defers — nothing to clear"
        )
        return 0
    # gate_pause.resume_all clears declared_gates + active breakers + active
    # defers; passing declared (even when empty) is enough to reach the rest.
    newly = gate_pause.resume_all(plan_dir, plan_id=loaded.plan_id, declared_gates=declared)
    if newly:
        inbox.append_event(
            plan_dir,
            event="resumed",
            plan_id=loaded.plan_id,
            body=(
                f"Operator cleared all gates via `jarvis resume`.\n"
                f"Newly cleared: {newly}\n"
                f"Plan-declared: {declared}\n"
                f"Active breakers (pre-clear): {active_breakers}\n"
                f"Active defers (pre-clear): {active_defers}"
            ),
            cleared_gates=",".join(newly),
        )
        print(f"[resume] cleared {len(newly)} gates: {newly}")
    else:
        print("[resume] all declared gates were already cleared")
    return 0


def _claude_touch_main(argv: list[str]) -> int:
    """F007 Slice 2: record that a human just made a Claude request. The
    supervisor's autonomous-class admission check reads this state and pauses
    via defer:interactive_backoff for JARVIS_INTERACTIVE_BACKOFF_MINUTES (30
    min default) after the touch.

    No args. Touches `claude` only — future agent variants can ride a later
    slice. State path overridable via JARVIS_INTERACTIVE_STATE_PATH for
    hermetic tests; conftest autouse fixture sets it per-test.
    """
    if argv:
        print("usage: jarvis-orchestrate claude-touch", file=sys.stderr)
        return 2
    ts = interactive_state.touch("claude")
    minutes = interactive_state.backoff_minutes()
    print(
        f"[claude-touch] recorded human Claude request at {ts} "
        f"(backoff window {minutes:g} min). Autonomous Claude-heavy "
        "dispatches will defer until the window elapses."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    raw = argv if argv is not None else sys.argv[1:]
    if raw and raw[0] == "ps":
        return _ps_main(raw[1:])
    if raw and raw[0] == "approve":
        return _approve_main(raw[1:])
    if raw and raw[0] == "resume":
        return _resume_main(raw[1:])
    if raw and raw[0] == "claude-touch":
        return _claude_touch_main(raw[1:])

    p = argparse.ArgumentParser(prog="jarvis-orchestrate", description=__doc__)
    p.add_argument("plan", help="Plan ID (resolved against ./docs/plans/) or absolute dir path")
    p.add_argument("--feature", default="F001", help="Feature ID to dispatch (default F001)")
    p.add_argument(
        "--role", default="implementer", help="Single-agent mode: agent role (default implementer)"
    )
    p.add_argument(
        "--iteration", type=int, default=0, help="Single-agent mode: iteration number (default 0)"
    )
    p.add_argument(
        "--volley",
        action="store_true",
        help="Volley mode: implementer/auditor pair iterating until signoff or cap",
    )
    p.add_argument(
        "--implementer",
        default=None,
        help="Volley mode: implementer agent (default: agents_required[0])",
    )
    p.add_argument(
        "--auditor", default=None, help="Volley mode: auditor agent (default: agents_required[1])"
    )
    p.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Volley mode: override loop_caps.max_iterations",
    )
    p.add_argument(
        "--mode",
        default=None,
        choices=["interactive", "autonomous"],
        help="F007: runtime dispatch class override. interactive=bypass admission gates; "
        "autonomous=enforce. P0 is plan-derived only (plan.tier=p0) and cannot be "
        "forced via this flag — that would silently expand emergency-lane scope. "
        "Default: derived from plan.tier (p0 → p0; else autonomous).",
    )
    args = p.parse_args(raw)

    plan_dir = _resolve_plan_dir(args.plan)
    print(f"[supervisor] plan_dir={plan_dir}")

    if args.volley:
        print(
            f"[supervisor] mode=volley feature={args.feature} "
            f"impl={args.implementer or '(plan default)'} "
            f"aud={args.auditor or '(plan default)'} "
            f"runtime_class={args.mode or '(derived)'}"
        )
        try:
            result = supervisor.dispatch_volley(
                plan_dir=plan_dir,
                feature_id=args.feature,
                implementer_agent=args.implementer,
                auditor_agent=args.auditor,
                max_iterations=args.max_iterations,
                mode=args.mode,
            )
        except QuotaExceeded as exc:
            print(f"[supervisor] BLOCKED by quota gate: {exc}", file=sys.stderr)
            return 2
        except (FileNotFoundError, KeyError, ValueError, RuntimeError) as exc:
            print(f"[supervisor] ERROR: {exc}", file=sys.stderr)
            return 1

        print(
            f"\n[supervisor] volley terminal: {result.final_status} after {result.rounds} round(s)"
        )
        print(f"[supervisor] reason: {result.reason}")
        print(f"[supervisor] {len(result.audit_paths)} audit JSONs written")
        # Exit 0 only if signed_off; non-zero for any non-success terminal
        return 0 if result.final_status == "signed_off" else 3

    # Single-agent path (F004 + F007 admission)
    print(
        f"[supervisor] mode=single feature={args.feature} role={args.role} "
        f"iter={args.iteration} runtime_class={args.mode or '(derived)'}"
    )
    try:
        audit_path = supervisor.dispatch_single_agent(
            plan_dir=plan_dir,
            feature_id=args.feature,
            agent_role=args.role,
            iteration=args.iteration,
            mode=args.mode,
        )
    except QuotaExceeded as exc:
        print(f"[supervisor] BLOCKED by quota gate: {exc}", file=sys.stderr)
        return 2
    except supervisor.PausedOnGate as exc:
        print(f"[supervisor] PAUSED on gate: {exc}", file=sys.stderr)
        return 3
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print(f"[supervisor] ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"[supervisor] ✓ wrote {audit_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
