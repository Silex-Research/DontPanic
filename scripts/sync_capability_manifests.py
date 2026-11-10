#!/usr/bin/env python3
"""Copy capability manifests into the installable Python package.

Run without arguments to refresh the packaged manifests. Use ``--check`` to
report missing, extra, or byte-different files without writing anything.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "capabilities"
PACKAGE_DIR = ROOT / "scripts" / "dontpanic_orchestrate" / "capability_manifests"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report mirror drift without writing files",
    )
    args = parser.parse_args(argv)

    if not SOURCE_DIR.is_dir():
        print(f"Capability source directory not found: {SOURCE_DIR}", file=sys.stderr)
        return 2

    source_files = {path.name: path for path in SOURCE_DIR.glob("*.json")}
    package_files = (
        {path.name: path for path in PACKAGE_DIR.glob("*.json")}
        if PACKAGE_DIR.is_dir()
        else {}
    )
    drift = sorted(
        name
        for name in source_files.keys() | package_files.keys()
        if name not in source_files
        or name not in package_files
        or source_files[name].read_bytes() != package_files[name].read_bytes()
    )

    if args.check:
        if drift:
            for name in drift:
                print(f"capability manifest drift: {name}", file=sys.stderr)
            return 1
        return 0

    PACKAGE_DIR.mkdir(parents=True, exist_ok=True)
    for name, source in source_files.items():
        shutil.copyfile(source, PACKAGE_DIR / name)
    for name in package_files.keys() - source_files.keys():
        (PACKAGE_DIR / name).unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
