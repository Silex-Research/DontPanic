"""Plan 2026-05-23-002 — ``dontpanic reconcile`` subcommand surface.

F001 ships the ``baseline`` subcommand that builds (and optionally
writes) an install snapshot to ``~/.dontpanic/install-snapshot.json``.
F002 will add the ``check`` subcommand. Both share this CLI module so
``dontpanic reconcile <verb>`` is the single entry point.

``reconcile baseline`` is preview-by-default. Without ``--yes`` it
prints the snapshot the operator is about to write but does not touch
the filesystem. With ``--yes`` it writes the snapshot at mode 0o600.

Exit codes (baseline):
  0  preview emitted OR snapshot written
  1  capability loading failed / write failed
  2  argparse / usage error
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from dontpanic_orchestrate.install_snapshot import (
    CapabilityLoadError,
    build_snapshot,
    render_snapshot_json,
    render_snapshot_text,
    snapshot_path,
    write_snapshot,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dontpanic reconcile",
        description=(
            "Install-snapshot reconciliation. v0 ships `baseline`; F002 "
            "adds `check`."
        ),
    )
    sub = parser.add_subparsers(dest="subcommand")

    baseline = sub.add_parser(
        "baseline",
        help=(
            "Build (and optionally write) the install snapshot anchor at "
            "~/.dontpanic/install-snapshot.json. Preview-only without `--yes`."
        ),
    )
    baseline.add_argument(
        "--profile",
        default="core",
        help="Profile to stamp into the snapshot (default: core).",
    )
    baseline.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Write the snapshot to disk. Without this flag, baseline is "
            "preview-only and never touches the filesystem."
        ),
    )
    baseline.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format for the snapshot body (default: text).",
    )
    return parser


def _baseline_main(args: argparse.Namespace) -> int:
    try:
        snapshot = build_snapshot(profile=args.profile)
    except CapabilityLoadError as exc:
        print(f"reconcile baseline: failed to load capabilities: {exc}", file=sys.stderr)
        return 1

    target_path: Path = snapshot_path()
    if args.format == "json":
        sys.stdout.write(render_snapshot_json(snapshot))
    else:
        sys.stdout.write(render_snapshot_text(snapshot, target_path=target_path))
        sys.stdout.write("\n")

    if not args.yes:
        # Preview-only: never touch the filesystem.
        if args.format == "text":
            print(
                f"\n[preview] not written. Re-run with `--yes` to write {target_path} "
                "with mode 0600.",
                file=sys.stderr,
            )
        return 0

    try:
        written = write_snapshot(snapshot, path=target_path)
    except OSError as exc:
        print(f"reconcile baseline: failed to write snapshot: {exc}", file=sys.stderr)
        return 1
    if args.format == "text":
        print(f"\n[ok] wrote {written} (mode 0600).", file=sys.stderr)
    return 0


def reconcile_main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.subcommand is None:
        parser.print_help(sys.stderr)
        return 2
    if args.subcommand == "baseline":
        return _baseline_main(args)
    # F002 will add `check`; for now fall through to help.
    parser.print_help(sys.stderr)
    return 2


__all__ = ["reconcile_main"]
