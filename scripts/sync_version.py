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
PINNED_PATHS = (
    "README.md",
    "docs/DISCOVERABILITY.md",
    "docs/USE_CASES.md",
    "docs/PUBLISHING.md",
    "docs/roadmap-2026-05-19-install-ux-architecture-v0.md",
    "server.json",
    ".cursor-plugin/plugin.json",
    ".cursor-plugin/mcp.json",
    ".claude-plugin/plugin.json",
)

_SOURCE_VERSION = re.compile(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
_DISTRIBUTION_PIN = re.compile(r"(dontpanic-orchestrate==)[0-9][^\s\"'`,)]*")
_JSON_PINNED_PATHS = {
    "server.json",
    ".cursor-plugin/plugin.json",
    ".cursor-plugin/mcp.json",
    ".claude-plugin/plugin.json",
}


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

    changed: list[tuple[str, str]] = []
    for relative_path in PINNED_PATHS:
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
            updated = desired_text(relative_path, original, version)
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON in {relative_path}: {exc}", file=sys.stderr)
            return 2
        except ValueError as exc:
            print(f"Invalid JSON structure in {relative_path}: {exc}", file=sys.stderr)
            return 2
        if updated != original:
            changed.append((relative_path, updated))

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
