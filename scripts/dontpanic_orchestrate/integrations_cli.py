"""Plan 2026-06-04-003 F002 — `dontpanic integrations` CLI surface.

Two operator-facing verbs, both writing through the single append-only
evidence writer (no other channel mutates integration evidence):

  dontpanic integrations smoke static-dashboard
      Render-proof smoke: builds the dashboard over the exported state and
      asserts the producer cards reach the built artifact. Records
      passed/failed evidence. Exit 0 on pass, 4 on fail.

  dontpanic integrations attest <integration> --action <id> --outcome passed|failed [--note]
      Records an operator attestation (the proof for steps whose evidence
      lives outside the repo: deploys, external smokes, credential setups).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dontpanic_orchestrate import integration_actions as itg
from dontpanic_orchestrate.global_config import dontpanic_home


def _evidence_dir() -> Path:
    return dontpanic_home() / itg.EVIDENCE_SUBDIR


def integrations_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="dontpanic integrations")
    sub = parser.add_subparsers(dest="cmd")

    p_smoke = sub.add_parser("smoke", help="run an integration smoke")
    p_smoke.add_argument("integration", help="integration id (e.g. static-dashboard)")
    p_smoke.add_argument(
        "--plans-root", default=None, help="default: <cwd>/docs/plans"
    )

    p_attest = sub.add_parser("attest", help="record an operator attestation")
    p_attest.add_argument("integration", help="integration id")
    p_attest.add_argument("--action", required=True, dest="action_id")
    p_attest.add_argument("--outcome", required=True, choices=("passed", "failed"))
    p_attest.add_argument("--note", default=None)

    args = parser.parse_args(argv)

    if args.cmd == "smoke":
        return _smoke(args)
    if args.cmd == "attest":
        return _attest(args)
    parser.print_help(sys.stderr)
    return 2


def _smoke(args: argparse.Namespace) -> int:
    if args.integration != "static-dashboard":
        print(
            f"[integrations smoke] unknown integration {args.integration!r}; "
            "only 'static-dashboard' has a runnable smoke",
            file=sys.stderr,
        )
        return 2
    plans_root = (
        Path(args.plans_root) if args.plans_root else Path.cwd() / "docs" / "plans"
    )
    import tempfile

    with tempfile.TemporaryDirectory(prefix="dontpanic-smoke-") as build_dir:
        result = itg.run_static_dashboard_smoke(
            plans_root=plans_root,
            build_dir=Path(build_dir),
            evidence_dir=_evidence_dir(),
        )
    stream = sys.stdout if result.outcome == "passed" else sys.stderr
    print(f"[integrations smoke] static-dashboard: {result.outcome}", file=stream)
    print(f"  {result.detail}", file=stream)
    if result.evidence_path is not None:
        print(f"  evidence: {result.evidence_path}", file=stream)
    return 0 if result.outcome == "passed" else 4


def _attest(args: argparse.Namespace) -> int:
    details = {"note": args.note} if args.note else None
    path = itg.write_integration_evidence(
        _evidence_dir(),
        args.integration,
        args.action_id,
        source="attestation",
        outcome=args.outcome,
        details=details,
    )
    print(
        f"[integrations attest] recorded {args.integration}/{args.action_id} "
        f"outcome={args.outcome}"
    )
    print(f"  evidence: {path}")
    return 0
