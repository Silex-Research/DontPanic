"""Plan 2026-05-09-003 F004 — `dontpanic state` CLI subcommand.

Surface:
  dontpanic state snapshot
      [--json | --yaml]                # default --json
      [--plan <id>]                    # single-plan filter
      [--include <streams>]            # comma-separated subset
      [--redact-level public|operator|full]  # default operator
      [--out <path>]                   # write to file; default stdout
      [--compact]                      # single-line JSON (no indent)
      [--select <jsonpath>]            # minimal jsonpath subset, read-only
      [--plans-root <path>]            # default cwd/docs/plans

Flag vocabulary aligns with Printing Press agent-CLI norms (--json /
--compact / --select / --dry-run family) per plan 2026-05-09-003 D010
so PP-trained agents drive `dontpanic state` without per-command
relearning.

`--select` accepts a constrained jsonpath subset:

    $                       root
    $.field                 dotted field access
    $.field.sub             nested
    $.array[*]              list every element
    $.array[*].field        list-extract
    $.array[<int>]          positional list index

Anything else (operators, alternation, recursion `..`, filter `[?(...)]`,
function calls, `;`, shell metachars) is refused with exit 2. There is
no full jsonpath implementation here — that's a conscious scope cut.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import state_projection

# Reuse the schema-pinned enums for help text.
_VALID_INCLUDE = state_projection.ALL_STREAMS
_VALID_REDACT = ("public", "operator", "full")

# Minimal jsonpath grammar — see module docstring.
_SELECT_RE = re.compile(
    r"^\$"                          # root
    r"(?:"
    r"\.[A-Za-z_][A-Za-z0-9_]*"     # .field
    r"|\[\*\]"                      # [*]
    r"|\[\d+\]"                     # [N]
    r")*$"
)


def _usage() -> str:
    return (
        "usage: dontpanic state snapshot "
        "[--json|--yaml] [--plan <id>] [--include <streams>] "
        "[--redact-level public|operator|full] [--out <path>] "
        "[--compact] [--select <jsonpath>] [--plans-root <path>]"
    )


def main(argv: list[str]) -> int:
    if not argv:
        print(_usage(), file=sys.stderr)
        print("  subcommands: snapshot, export-dashboard", file=sys.stderr)
        return 2
    sub, rest = argv[0], argv[1:]
    if sub == "snapshot":
        return _snapshot_main(rest)
    if sub == "export-dashboard":
        return _export_dashboard_main(rest)
    print(f"unknown state subcommand: {sub!r}", file=sys.stderr)
    print(_usage(), file=sys.stderr)
    return 2


def _export_dashboard_main(argv: list[str]) -> int:
    """Plan 2026-05-09-003 F007 — write projection streams to per-stream
    JSON files in <out_dir>. Each file holds one F001 stream's array; a
    top-level state-snapshot.json holds the full envelope including
    schema_version + captured_at + redact_level metadata.

    Static-dashboard consumers point their loader at <out_dir>; any
    static host (file://, python -m http.server, GitHub Pages, nginx,
    Firebase Hosting) can serve the resulting directory.
    """
    parser = argparse.ArgumentParser(
        prog="dontpanic state export-dashboard",
        description=(
            "Write the state-projection envelope + per-stream files into "
            "<out_dir> so a static dashboard can render the projection "
            "without any server runtime."
        ),
    )
    parser.add_argument("--out", required=True, dest="out_dir")
    parser.add_argument(
        "--plans-root",
        default=None,
        help="default: <cwd>/docs/plans",
    )
    parser.add_argument(
        "--redact-level",
        choices=_VALID_REDACT,
        default="operator",
    )
    parser.add_argument("--plan", dest="plan_id", default=None)
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    plans_root = (
        Path(args.plans_root) if args.plans_root else Path.cwd() / "docs" / "plans"
    )

    try:
        snap = state_projection.gather(
            plans_root,
            redact_level=args.redact_level,
            plan_id=args.plan_id,
        )
    except ValueError as e:
        print(f"gather error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"gather failed: {e}", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    envelope = snap.model_dump(mode="json")

    # Top-level envelope file — the canonical adapter input.
    (out_dir / "state-snapshot.json").write_text(
        json.dumps(envelope, indent=2, ensure_ascii=False)
    )

    # Per-stream files — each contains JUST that stream's array.
    # Adapters with single-stream pages avoid loading the whole envelope.
    streams = envelope["streams"]
    for stream_name in state_projection.ALL_STREAMS:
        (out_dir / f"{stream_name}.json").write_text(
            json.dumps(streams[stream_name], indent=2, ensure_ascii=False)
        )

    # Manifest — lets a static loader discover what's in the directory
    # without reading every file.
    manifest = {
        "schema_version": envelope["schema_version"],
        "captured_at": envelope["captured_at"],
        "redact_level": envelope["redact_level"],
        "dontpanic_version": envelope.get("dontpanic_version"),
        "streams": [
            {
                "name": s,
                "file": f"{s}.json",
                "count": len(streams[s]),
                # F001 real provenance: the actual upstream source this stream is
                # projected from, as data on the section. The canonical projection
                # never cites the legacy tasks/agents/activity.json adapters.
                "source": state_projection.STREAM_PROVENANCE[s],
            }
            for s in state_projection.ALL_STREAMS
        ],
        # F002 lifecycle vs activity: distinct, separately-sourced counts so no
        # label conflates "plans with status==active" with "live agents".
        "activity": state_projection.activity_summary(snap),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False)
    )

    print(
        f"wrote {len(state_projection.ALL_STREAMS)+2} files to {out_dir}",
        file=sys.stderr,
    )
    return 0


def _snapshot_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dontpanic state snapshot",
        description="Emit a read-only state snapshot envelope.",
    )
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument("--json", dest="as_json", action="store_true")
    fmt.add_argument("--yaml", dest="as_yaml", action="store_true")
    parser.add_argument("--plan", dest="plan_id", default=None)
    parser.add_argument(
        "--include",
        default=None,
        help="comma-separated streams: " + ",".join(_VALID_INCLUDE),
    )
    parser.add_argument(
        "--redact-level",
        choices=_VALID_REDACT,
        default="operator",
    )
    parser.add_argument("--out", dest="out_path", default=None)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--select", dest="select", default=None)
    parser.add_argument(
        "--plans-root",
        default=None,
        help="default: <cwd>/docs/plans",
    )
    args = parser.parse_args(argv)

    plans_root = (
        Path(args.plans_root) if args.plans_root else Path.cwd() / "docs" / "plans"
    )

    include = state_projection.ALL_STREAMS
    if args.include:
        try:
            include = tuple(s.strip() for s in args.include.split(",") if s.strip())
        except Exception as e:
            print(f"--include parse error: {e}", file=sys.stderr)
            return 2

    try:
        snap = state_projection.gather(
            plans_root,
            redact_level=args.redact_level,
            include=include,
            plan_id=args.plan_id,
        )
    except ValueError as e:
        print(f"gather error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"gather failed: {e}", file=sys.stderr)
        return 1

    payload: Any = snap.model_dump(mode="json")

    if args.select:
        try:
            payload = _apply_select(payload, args.select)
        except ValueError as e:
            print(f"--select error: {e} (jsonpath subset only)", file=sys.stderr)
            return 2

    rendered = _render(payload, as_yaml=args.as_yaml, compact=args.compact)

    if args.out_path:
        Path(args.out_path).write_text(rendered)
    else:
        print(rendered, end="" if rendered.endswith("\n") else "\n")
    return 0


def _render(payload: Any, *, as_yaml: bool, compact: bool) -> str:
    if as_yaml:
        import yaml
        return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)
    if compact:
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)


def _apply_select(payload: Any, expr: str) -> Any:
    """Evaluate a constrained jsonpath subset. Read-only by construction.

    Refuses anything not matching `_SELECT_RE`. No code-eval; no filter
    predicates; no recursion descent. Indexes are bounded to the list
    length.
    """
    if not _SELECT_RE.match(expr):
        raise ValueError(
            f"jsonpath {expr!r} does not match the allowed subset "
            "($, .field, [*], [N] only)"
        )
    cursor: Any = payload
    # Tokenize: $.field → ('.field', '.field'), $.a[*] → ('.a', '[*]')
    tokens = re.findall(r"\.[A-Za-z_][A-Za-z0-9_]*|\[\*\]|\[\d+\]", expr)
    for tok in tokens:
        if tok.startswith("."):
            field = tok[1:]
            if not isinstance(cursor, dict):
                raise ValueError(f"cannot access {field!r} on non-object")
            cursor = cursor.get(field)
            if cursor is None:
                return None
        elif tok == "[*]":
            if not isinstance(cursor, list):
                raise ValueError("[*] requires a list")
            # If the next iteration is a field access, map each element;
            # otherwise return as-is. We handle this lazily by peeking the
            # remaining tokens — simplest approach is to keep cursor as the
            # list and let subsequent iterations operate on it as a list.
            cursor = list(cursor)
        elif tok.startswith("["):
            idx = int(tok[1:-1])
            if not isinstance(cursor, list):
                raise ValueError(f"index {idx} requires a list")
            if idx < 0 or idx >= len(cursor):
                return None
            cursor = cursor[idx]
        # Handle field access ON a list-typed cursor (mapped extraction)
        # by post-processing: if cursor is a list and the next token is a
        # field, map per element.
        # We achieve this by detecting and re-dispatching at the top of the
        # loop — done with the simple two-pass below.
    return cursor


def _apply_select(payload: Any, expr: str) -> Any:  # noqa: F811 — replace above
    if not _SELECT_RE.match(expr):
        raise ValueError(
            f"jsonpath {expr!r} does not match the allowed subset "
            "($, .field, [*], [N] only)"
        )
    tokens = re.findall(r"\.[A-Za-z_][A-Za-z0-9_]*|\[\*\]|\[\d+\]", expr)
    cursors: list[Any] = [payload]
    list_mode = False
    for tok in tokens:
        if tok.startswith("."):
            field = tok[1:]
            new_cursors = []
            for c in cursors:
                if isinstance(c, dict):
                    new_cursors.append(c.get(field))
                else:
                    raise ValueError(f"cannot access {field!r} on non-object")
            cursors = new_cursors
        elif tok == "[*]":
            new_cursors = []
            for c in cursors:
                if isinstance(c, list):
                    new_cursors.extend(c)
                else:
                    raise ValueError("[*] requires a list")
            cursors = new_cursors
            list_mode = True
        elif tok.startswith("["):
            idx = int(tok[1:-1])
            new_cursors = []
            for c in cursors:
                if not isinstance(c, list):
                    raise ValueError(f"index {idx} requires a list")
                if 0 <= idx < len(c):
                    new_cursors.append(c[idx])
                else:
                    new_cursors.append(None)
            cursors = new_cursors
    if list_mode:
        return cursors
    if len(cursors) == 1:
        return cursors[0]
    return cursors


__all__ = ["main"]
