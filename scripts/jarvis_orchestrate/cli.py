"""argparse entry for `python -m jarvis_orchestrate`.

Single-agent dispatch (F004):
  python -m jarvis_orchestrate <plan-id> [--feature F001] [--role implementer]

Volley dispatch (F005a — implementer/auditor pair, iterate until signoff or cap):
  python -m jarvis_orchestrate <plan-id> --volley [--feature F001]
                                                  [--implementer claude] [--auditor codex]
                                                  [--max-iterations 3]

Active-supervisor registry (F023 EC13):
  python -m jarvis_orchestrate ps
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jarvis_orchestrate import active_supervisors, supervisor
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


def main(argv: list[str] | None = None) -> int:
    raw = argv if argv is not None else sys.argv[1:]
    if raw and raw[0] == "ps":
        return _ps_main(raw[1:])

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
