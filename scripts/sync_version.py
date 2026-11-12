#!/usr/bin/env python3
"""Sync pinned distribution versions from the package source.

Usage: run ``python3 scripts/sync_version.py`` after changing
``scripts/dontpanic_orchestrate/__init__.py``; use ``--check`` to report drift
without writing any files. The MCP launch pin is
``uvx dontpanic-orchestrate==<version>``. Requires Python 3.10 or newer.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION_SOURCE = Path("scripts/dontpanic_orchestrate/__init__.py")
# Every file here MUST exist and MUST carry at least one version pin (a
# ``dontpanic-orchestrate==<version>`` pin, or a top-level ``"version"`` field
# for the JSON listings); ``--check`` fails naming any file that does not.
PINNED_PATHS = (
    "README.md",
    "docs/DISCOVERABILITY.md",
    "docs/PUBLISHING.md",
    "server.json",
    ".cursor-plugin/plugin.json",
    ".cursor-plugin/mcp.json",
    ".claude-plugin/plugin.json",
)
# Docs that mention the distribution but carry no version pin today. They are
# still scanned (any pin added later is checked and synced like the others),
# but a pin is not required and they may be absent.
SCANNED_PATHS = (
    "docs/USE_CASES.md",
    "docs/roadmap-2026-05-19-install-ux-architecture-v0.md",
)

_SOURCE_VERSION = re.compile(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
_DISTRIBUTION_PIN = re.compile(r"(dontpanic-orchestrate==)[0-9][^\s\"'`,)]*")
_JSON_PINNED_PATHS = {
    "server.json",
    ".cursor-plugin/plugin.json",
    ".cursor-plugin/mcp.json",
    ".claude-plugin/plugin.json",
}
# JSON listings whose pin requirement is the uvx MCP launch pin under
# ``mcpServers.dontpanic.args`` (in addition to the top-level ``"version"``).
_LAUNCH_PIN_PATHS = {".claude-plugin/plugin.json"}


def read_source_version() -> str:
    """Read the package version assignment without importing the package."""
    source_path = ROOT / VERSION_SOURCE
    source = source_path.read_text(encoding="utf-8")
    match = _SOURCE_VERSION.search(source)
    if match is None:
        raise ValueError(f"Could not find __version__ assignment in {VERSION_SOURCE}")
    return match.group(1)


def rewrite_text(text: str, version: str) -> str:
    """Replace every versioned dontpanic-orchestrate pin in text."""
    return _DISTRIBUTION_PIN.sub(lambda match: f"{match.group(1)}{version}", text)


def rewrite_listing_json(text: str, relative_path: str, version: str) -> str:
    """Update version fields in supported JSON listings."""
    if relative_path in _JSON_PINNED_PATHS:
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError(f"{relative_path}: top-level JSON value must be an object")

        if relative_path in {
            "server.json",
            ".cursor-plugin/plugin.json",
            ".claude-plugin/plugin.json",
        }:
            payload["version"] = version
        if relative_path == "server.json":
            packages = payload.get("packages", [])
            if isinstance(packages, list):
                for package in packages:
                    if isinstance(package, dict):
                        package["version"] = version

        def rewrite_pins(value):
            if isinstance(value, dict):
                return {key: rewrite_pins(item) for key, item in value.items()}
            if isinstance(value, list):
                return [rewrite_pins(item) for item in value]
            if isinstance(value, str):
                return _DISTRIBUTION_PIN.sub(
                    lambda match: f"{match.group(1)}{version}", value
                )
            return value

        payload = rewrite_pins(payload)
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    return text


def _has_uvx_launch_pin(payload: object) -> bool:
    """True when ``mcpServers.dontpanic`` launches via ``uvx`` with a
    ``dontpanic-orchestrate==<version>`` entry in its ``args``."""
    if not isinstance(payload, dict):
        return False
    servers = payload.get("mcpServers")
    server = servers.get("dontpanic") if isinstance(servers, dict) else None
    if not isinstance(server, dict) or server.get("command") != "uvx":
        return False
    args = server.get("args")
    return isinstance(args, list) and any(
        isinstance(arg, str) and _DISTRIBUTION_PIN.fullmatch(arg) for arg in args
    )


def has_version_pin(relative_path: str, text: str) -> bool:
    """True when ``text`` carries at least one version pin: a
    ``dontpanic-orchestrate==`` distribution pin, or (JSON listings only) a
    top-level string ``"version"`` field. Invalid JSON raises
    ``json.JSONDecodeError`` for the caller to report.

    ``.claude-plugin/plugin.json`` is stricter: it MUST carry BOTH the
    top-level ``"version"`` string AND the uvx launch pin
    (``mcpServers.dontpanic`` = ``uvx dontpanic-orchestrate==<version>``); a
    top-level version alone (or a pin mentioned elsewhere in the text) is
    not a pin for this file."""
    if relative_path in _LAUNCH_PIN_PATHS:
        payload = json.loads(text)
        return (
            isinstance(payload, dict)
            and isinstance(payload.get("version"), str)
            and _has_uvx_launch_pin(payload)
        )
    if _DISTRIBUTION_PIN.search(text):
        return True
    if relative_path in _JSON_PINNED_PATHS:
        payload = json.loads(text)
        return isinstance(payload, dict) and isinstance(payload.get("version"), str)
    return False


def desired_text(relative_path: str, original: str, version: str) -> str:
    if relative_path in _JSON_PINNED_PATHS:
        return rewrite_listing_json(original, relative_path, version)
    return rewrite_text(original, version)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report drift without writing files",
    )
    args = parser.parse_args(argv)

    try:
        version = read_source_version()
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    missing = [relative for relative in PINNED_PATHS if not (ROOT / relative).is_file()]
    if missing:
        for relative in missing:
            print(f"Missing required version-pinned file: {relative}", file=sys.stderr)
        return 2

    scanned = [relative for relative in SCANNED_PATHS if (ROOT / relative).is_file()]
    changed: list[tuple[str, str]] = []
    unpinned: list[str] = []
    for relative_path in (*PINNED_PATHS, *scanned):
        path = ROOT / relative_path
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            print(f"Invalid JSON/text encoding in {relative_path}: {exc}", file=sys.stderr)
            return 2
        except OSError as exc:
            print(f"Could not read {relative_path}: {exc}", file=sys.stderr)
            return 2
        try:
            if relative_path in PINNED_PATHS and not has_version_pin(relative_path, original):
                unpinned.append(relative_path)
                continue
            updated = desired_text(relative_path, original, version)
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON in {relative_path}: {exc}", file=sys.stderr)
            return 2
        except ValueError as exc:
            print(f"Invalid JSON structure in {relative_path}: {exc}", file=sys.stderr)
            return 2
        if updated != original:
            changed.append((relative_path, updated))

    if unpinned:
        # A required file with no pin cannot be synced (write mode never
        # invents one) and must fail --check: report and write nothing.
        for relative_path in unpinned:
            print(f"No version pin found in required file: {relative_path}", file=sys.stderr)
        return 2

    if args.check:
        if changed:
            for relative_path, _ in changed:
                print(relative_path, file=sys.stderr)
            return 1
        return 0

    for relative_path, updated in changed:
        (ROOT / relative_path).write_text(updated, encoding="utf-8")
        print(relative_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
