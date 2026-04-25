"""argparse entry for `python -m jarvis_orchestrate`.

Usage:
  python -m jarvis_orchestrate <plan-id> [--feature F001] [--role implementer]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jarvis_orchestrate import supervisor
from jarvis_orchestrate.supervisor import QuotaExceeded


def _resolve_plan_dir(plan_arg: str) -> Path:
    p = Path(plan_arg)
    if p.is_dir():
        return p
    cwd_match = Path.cwd() / "docs" / "plans" / plan_arg
    if cwd_match.is_dir():
        return cwd_match
    raise SystemExit(f"plan not found: {plan_arg}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="jarvis-orchestrate", description=__doc__)
    p.add_argument("plan", help="Plan ID (resolved against ./docs/plans/) or absolute dir path")
    p.add_argument("--feature", default="F001", help="Feature ID to dispatch (default F001)")
    p.add_argument("--role", default="implementer", help="Agent role (default implementer)")
    p.add_argument("--iteration", type=int, default=0)
    args = p.parse_args(argv)

    plan_dir = _resolve_plan_dir(args.plan)
    print(f"[supervisor] plan_dir={plan_dir}")
    print(f"[supervisor] feature={args.feature} role={args.role} iter={args.iteration}")

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
