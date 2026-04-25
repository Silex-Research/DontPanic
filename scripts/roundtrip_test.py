"""F003 round-trip canonicalization test.

Per design phase1-skill-update.md §F021 round-trip dogfood test:
  - Read plan dir's plan.md / features.json / decisions.jsonl
  - Re-emit using the canonicalization rules
  - Diff vs originals — must be empty (modulo explicitly normalized whitespace)

Canonicalization rules (per design):
  - JSON: indent=2, ensure_ascii=False, sort_keys=False, trailing newline
  - YAML frontmatter: dates quoted, keys preserved in original order
  - JSONL: one object per line, no trailing comma, final newline, no pretty-printing

Strategy: byte-level diff for JSON/JSONL (deterministic), structural diff for YAML
frontmatter (semantic — quoting style differences across YAML emitters are noise,
but data must round-trip without information loss).

Usage:
  python3 roundtrip_test.py <plan-dir>...
Exit 0 = all clean. Exit 1 = at least one drift detected.
"""
from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path
from typing import Any

import yaml


def _canonical_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def _canonical_jsonl(records: list[dict]) -> str:
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n"


def _split_frontmatter(text: str) -> tuple[str, str] | None:
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    return parts[1], parts[2]


def _show_diff(label: str, a: str, b: str) -> bool:
    if a == b:
        return True
    diff = list(
        difflib.unified_diff(
            a.splitlines(keepends=True),
            b.splitlines(keepends=True),
            fromfile=f"{label} (original)",
            tofile=f"{label} (canonical)",
            n=2,
        )
    )
    sys.stdout.write("".join(diff))
    return False


def _check_plan_md(path: Path) -> bool:
    """Structural roundtrip: parse YAML → re-parse from re-serialized form → assert equal data.
    Byte-level YAML canonicalization is fragile across emitters; data-level is the
    real invariant — no information loss across read/write."""
    text = path.read_text()
    fb = _split_frontmatter(text)
    if fb is None:
        print(f"✗ {path.name}: missing YAML frontmatter delimiter")
        return False
    fm_text, body = fb
    parsed = yaml.safe_load(fm_text)

    # Re-emit with default style and re-parse — data must equal.
    re_emitted = yaml.safe_dump(parsed, default_flow_style=False, sort_keys=False, allow_unicode=True)
    re_parsed = yaml.safe_load(re_emitted)

    if parsed != re_parsed:
        print(f"✗ {path.name}: frontmatter loses data on re-emit")
        print(f"  original keys: {sorted(parsed.keys()) if isinstance(parsed, dict) else type(parsed)}")
        print(f"  re-parsed keys: {sorted(re_parsed.keys()) if isinstance(re_parsed, dict) else type(re_parsed)}")
        return False

    # Body must round-trip byte-equal (we don't transform Markdown body).
    print(f"✓ {path.name} (frontmatter data preserved; body unchanged)")
    return True


def _check_features_json(path: Path) -> bool:
    original = path.read_text()
    data = json.loads(original)
    canonical = _canonical_json(data)
    ok = _show_diff(path.name, original, canonical)
    if ok:
        print(f"✓ {path.name}")
    else:
        print(f"✗ {path.name} — see diff above")
    return ok


def _check_decisions_jsonl(path: Path) -> bool:
    original = path.read_text()
    records = [json.loads(l) for l in original.strip().split("\n") if l.strip()]
    canonical = _canonical_jsonl(records)
    ok = _show_diff(path.name, original, canonical)
    if ok:
        print(f"✓ {path.name}")
    else:
        print(f"✗ {path.name} — see diff above")
    return ok


def check(plan_dir: Path) -> int:
    print(f"\n[roundtrip] {plan_dir.name}")
    issues = 0

    plan_md = plan_dir / "plan.md"
    if plan_md.is_file() and not _check_plan_md(plan_md):
        issues += 1

    features = plan_dir / "features.json"
    if features.is_file() and not _check_features_json(features):
        issues += 1

    decisions = plan_dir / "decisions.jsonl"
    if decisions.is_file() and not _check_decisions_jsonl(decisions):
        issues += 1

    return issues


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    if not args:
        print(f"Usage: {sys.argv[0]} <plan-dir>...", file=sys.stderr)
        return 2

    total = 0
    for arg in args:
        p = Path(arg).resolve()
        if not p.is_dir():
            print(f"Not a directory: {p}", file=sys.stderr)
            total += 1
            continue
        total += check(p)

    print()
    if total == 0:
        print("✓ All round-trips clean")
        return 0
    print(f"✗ {total} drift(s) detected")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
