"""dontpanic showcase — run DontPanic capabilities against external repos
and publish artifacts under ``docs/showcase/`` (Plan 2026-05-19-005 F001).

Public entry: :func:`showcase_main` — wired into the top-level
``dontpanic`` CLI via ``scripts/dontpanic_orchestrate/cli.py``. Supports
one subcommand in v0:

    regen [--target <key>] [--all] [--config <path>] [--json]

``status`` is reserved future-room (a one-line index summary); v0 ships
``regen`` only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dontpanic_orchestrate.showcase import config as _config
from dontpanic_orchestrate.showcase import generator as _generator
from dontpanic_orchestrate.showcase.config import (
    DEFAULT_SHOWCASE_CONFIG,
    SUPPORTED_ARTIFACT_KINDS,
    TargetSpec,
    default_showcase_config,
)
from dontpanic_orchestrate.showcase.generator import (
    ArtifactResult,
    ShowcaseRun,
    TargetResult,
    filter_targets,
    generate,
    render_json,
    render_text,
)
from dontpanic_orchestrate.showcase.redactor import (
    RedactorError,
    redact,
    redact_and_validate,
    validate,
)

__all__ = [
    "ArtifactResult",
    "DEFAULT_SHOWCASE_CONFIG",
    "RedactorError",
    "SUPPORTED_ARTIFACT_KINDS",
    "ShowcaseRun",
    "TargetResult",
    "TargetSpec",
    "default_showcase_config",
    "filter_targets",
    "generate",
    "redact",
    "redact_and_validate",
    "render_json",
    "render_text",
    "showcase_main",
    "validate",
]


def _load_external_config(path: Path) -> list[TargetSpec]:
    """Load a JSON config file shaped like the default config (list of
    target dicts). Each target dict must carry every field of
    :class:`TargetSpec`. ``repo_root`` may be a string path."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: top-level must be a list of target dicts")
    out: list[TargetSpec] = []
    for entry in data:
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: each entry must be a dict; got {type(entry).__name__}")
        out.append(
            TargetSpec(
                repo_key=str(entry["repo_key"]),
                label=str(entry["label"]),
                repo_root=Path(entry["repo_root"]).expanduser(),
                description=str(entry.get("description", "")),
                supported_artifacts=frozenset(entry.get("supported_artifacts", [])),
                has_dontpanic_plans=bool(entry.get("has_dontpanic_plans", False)),
                has_committed_architecture_json=bool(
                    entry.get("has_committed_architecture_json", False)
                ),
            )
        )
    return out


def _regen_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dontpanic showcase regen",
        description=(
            "Generate architecture + validate-plans + drift artifacts for "
            "configured showcase targets. Default = --all over every "
            "target in the active config (v0 default: dontpanic, "
            "agent-conventions, axiom, glam)."
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--target",
        default=None,
        help="Generate artifacts for a single target by repo_key.",
    )
    group.add_argument(
        "--all",
        dest="all_flag",
        action="store_true",
        help=(
            "Generate for every target in the active config (this is the "
            "default when neither --target nor --all is passed)."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="JSON config file overriding the default showcase config.",
    )
    parser.add_argument(
        "--showcase-dir",
        type=Path,
        default=None,
        help=(
            "Override the showcase output directory. Default = "
            "<DontPanic>/docs/showcase/. Test isolation only — operators "
            "should not need this in normal usage."
        ),
    )
    parser.add_argument(
        "--json",
        dest="json_out",
        action="store_true",
        help="Emit structured JSON instead of the pretty terminal chips.",
    )
    args = parser.parse_args(argv)

    if args.config is not None:
        config_list = _load_external_config(args.config)
    else:
        config_list = default_showcase_config()

    try:
        active = filter_targets(
            config_list,
            target_key=args.target,
            all_flag=bool(args.all_flag),
        )
    except KeyError as exc:
        print(f"[showcase] {exc}", file=sys.stderr)
        return 2

    run = generate(targets=active, showcase_dir=args.showcase_dir)

    if args.json_out:
        print(render_json(run))
    else:
        print(render_text(run))
    return run.overall_exit


def showcase_main(argv: list[str] | None = None) -> int:
    """Top-level showcase CLI entry. Returns exit code."""
    raw = list(argv) if argv is not None else []
    if not raw or raw[0] in ("-h", "--help", "help"):
        print(
            "usage: dontpanic showcase regen [--target <key>] [--all] "
            "[--config <path>] [--json]"
        )
        return 0 if raw and raw[0] in ("-h", "--help", "help") else 2
    sub = raw[0]
    if sub == "regen":
        return _regen_main(raw[1:])
    print(f"[showcase] unknown subcommand: {sub}", file=sys.stderr)
    print("usage: dontpanic showcase regen ...", file=sys.stderr)
    return 2
