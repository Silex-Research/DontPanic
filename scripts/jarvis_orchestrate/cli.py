"""argparse entry for `python -m jarvis_orchestrate`.

Single-agent dispatch (F004):
  python -m jarvis_orchestrate <plan-id> [--feature F001] [--role implementer]

Volley dispatch (F005a — implementer/auditor pair, iterate until signoff or cap):
  python -m jarvis_orchestrate <plan-id> --volley [--feature F001]
                                                  [--implementer claude] [--auditor codex]
                                                  [--max-iterations 3]

Active-supervisor registry (F023 EC13):
  python -m jarvis_orchestrate ps

Engagement-surface gate handling (F008):
  python -m jarvis_orchestrate approve <plan-id> <gate>   # clear one declared gate
  python -m jarvis_orchestrate resume  <plan-id>          # clear every declared gate
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jarvis_orchestrate import (
    active_supervisors,
    circuit_breakers as cb,
    gate_pause,
    inbox,
    plan_loader,
    supervisor,
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
    plan_dir = _resolve_plan_dir(plan_arg)
    loaded = plan_loader.load(plan_dir)
    # plan.human_gates is a list of HumanGate enum members; compare on .value
    # so the user-supplied string CLI arg matches the declared set.
    declared_strs = [g.value if hasattr(g, "value") else str(g) for g in (loaded.plan.human_gates or [])]
    # F006: synthetic breaker:<kind> gates are valid declared names too — the
    # supervisor adds them to active_breakers on trip. Don't false-warn when
    # operator approves a known breaker name (either currently active or any
    # known BreakerKind, in case the operator is pre-clearing).
    active = gate_pause.active_breakers(plan_dir)
    breaker_names = {f"breaker:{k.value}" for k in cb.BreakerKind}
    valid_targets = set(declared_strs) | set(active) | breaker_names
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
    remaining = gate_pause.unmet_gates(plan_dir, declared_strs)
    print(f"[approve] remaining unmet gates: {remaining or '(none)'}")
    return 0


def _resume_main(argv: list[str]) -> int:
    """F008 Item 2 + F006: clear every plan-declared gate AND every active
    breaker. Returns success even when both sets are empty (idempotent)."""
    if len(argv) != 1:
        print("usage: jarvis-orchestrate resume <plan-id>", file=sys.stderr)
        return 2
    plan_arg = argv[0]
    plan_dir = _resolve_plan_dir(plan_arg)
    loaded = plan_loader.load(plan_dir)
    declared = list(loaded.plan.human_gates or [])
    active = gate_pause.active_breakers(plan_dir)
    if not declared and not active:
        print(f"[resume] plan {loaded.plan_id} has no plan-declared gates and no active breakers — nothing to clear")
        return 0
    # gate_pause.resume_all clears declared_gates AND every active breaker, so
    # passing declared (even when empty) is enough to reach active_breakers.
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
                f"Active breakers (pre-clear): {active}"
            ),
            cleared_gates=",".join(newly),
        )
        print(f"[resume] cleared {len(newly)} gates: {newly}")
    else:
        print("[resume] all declared gates were already cleared")
    return 0


def main(argv: list[str] | None = None) -> int:
    raw = argv if argv is not None else sys.argv[1:]
    if raw and raw[0] == "ps":
        return _ps_main(raw[1:])
    if raw and raw[0] == "approve":
        return _approve_main(raw[1:])
    if raw and raw[0] == "resume":
        return _resume_main(raw[1:])

    p = argparse.ArgumentParser(prog="jarvis-orchestrate", description=__doc__)
    p.add_argument("plan", help="Plan ID (resolved against ./docs/plans/) or absolute dir path")
    p.add_argument("--feature", default="F001", help="Feature ID to dispatch (default F001)")
    p.add_argument("--role", default="implementer", help="Single-agent mode: agent role (default implementer)")
    p.add_argument("--iteration", type=int, default=0, help="Single-agent mode: iteration number (default 0)")
    p.add_argument("--volley", action="store_true", help="Volley mode: implementer/auditor pair iterating until signoff or cap")
    p.add_argument("--implementer", default=None, help="Volley mode: implementer agent (default: agents_required[0])")
    p.add_argument("--auditor", default=None, help="Volley mode: auditor agent (default: agents_required[1])")
    p.add_argument("--max-iterations", type=int, default=None, help="Volley mode: override loop_caps.max_iterations")
    args = p.parse_args(raw)

    plan_dir = _resolve_plan_dir(args.plan)
    print(f"[supervisor] plan_dir={plan_dir}")

    if args.volley:
        print(f"[supervisor] mode=volley feature={args.feature} impl={args.implementer or '(plan default)'} aud={args.auditor or '(plan default)'}")
        try:
            result = supervisor.dispatch_volley(
                plan_dir=plan_dir,
                feature_id=args.feature,
                implementer_agent=args.implementer,
                auditor_agent=args.auditor,
                max_iterations=args.max_iterations,
            )
        except QuotaExceeded as exc:
            print(f"[supervisor] BLOCKED by quota gate: {exc}", file=sys.stderr)
            return 2
        except (FileNotFoundError, KeyError, ValueError, RuntimeError) as exc:
            print(f"[supervisor] ERROR: {exc}", file=sys.stderr)
            return 1

        print(f"\n[supervisor] volley terminal: {result.final_status} after {result.rounds} round(s)")
        print(f"[supervisor] reason: {result.reason}")
        print(f"[supervisor] {len(result.audit_paths)} audit JSONs written")
        # Exit 0 only if signed_off; non-zero for any non-success terminal
        return 0 if result.final_status == "signed_off" else 3

    # Single-agent path (F004)
    print(f"[supervisor] mode=single feature={args.feature} role={args.role} iter={args.iteration}")
    try:
        audit_path = supervisor.dispatch_single_agent(
            plan_dir=plan_dir,
            feature_id=args.feature,
            agent_role=args.role,
            iteration=args.iteration,
        )
    except QuotaExceeded as exc:
        print(f"[supervisor] BLOCKED by quota gate: {exc}", file=sys.stderr)
        return 2
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print(f"[supervisor] ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"[supervisor] ✓ wrote {audit_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
