"""F001 changelog — render a markdown changelog for a git revision range.

Pure parsing + template rendering. No LLM calls, no network, no secrets. The skill
either runs `git log` against the working tree or reads a recorded fixture. Output is
byte-stable for identical inputs so fixture-based golden tests work without any git
history available (fresh-clone safe).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Stable git log format. Each commit emits a record fenced by --COMMIT-- / --FILES--
# markers. The body (%B) is variable-line; --FILES-- bounds it. --name-status appends
# tab-separated status\tpath lines after %B.
COMMIT_MARKER = "--COMMIT--"
FILES_MARKER = "--FILES--"
GIT_LOG_FORMAT = f"{COMMIT_MARKER}%n%H%n%h%n%aI%n%an <%ae>%n%P%n%B%n{FILES_MARKER}"

# Canonical Conventional Commits groups. Order is the rendered order.
CANONICAL_GROUPS: list[tuple[str, str]] = [
    ("feat", "Features"),
    ("fix", "Fixes"),
    ("perf", "Performance"),
    ("refactor", "Refactor"),
    ("docs", "Documentation"),
    ("test", "Tests"),
    ("build", "Build"),
    ("ci", "CI"),
    ("chore", "Chore"),
    ("style", "Style"),
    ("revert", "Reverts"),
    ("other", "Other"),
]
KNOWN_TYPES = {t for t, _ in CANONICAL_GROUPS if t != "other"}
GROUP_TITLE = {t: title for t, title in CANONICAL_GROUPS}

# Conventional Commits subject pattern: type(scope)?!?: subject
CC_SUBJECT_RE = re.compile(r"^(?P<type>[a-zA-Z]+)(\([^)]*\))?(!)?:\s*(?P<rest>.*)$")


@dataclass
class Commit:
    sha: str
    short: str
    date: str  # ISO-8601
    author: str
    parents: list[str]
    subject: str
    body: str
    files: list[tuple[str, str]] = field(default_factory=list)  # (status, path)

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1

    def classify(self) -> tuple[str, str]:
        """Return (group_type, clean_subject_without_prefix). Falls back to 'other'."""
        m = CC_SUBJECT_RE.match(self.subject)
        if not m:
            return "other", self.subject
        t = m.group("type").lower()
        if t not in KNOWN_TYPES:
            return "other", self.subject
        return t, m.group("rest").strip()


def parse_git_log(text: str) -> list[Commit]:
    """Parse a `git log --pretty=format:<GIT_LOG_FORMAT> --name-status` blob.

    Tolerant to leading/trailing whitespace and the standard blank line git inserts
    between records. Returns commits in input order (caller controls --reverse).
    """
    commits: list[Commit] = []
    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        if lines[i].strip() != COMMIT_MARKER:
            i += 1
            continue
        i += 1
        # Five fixed fields: sha, short, date, author, parents.
        if i + 5 > n:
            break
        sha = lines[i].strip()
        i += 1
        short = lines[i].strip()
        i += 1
        date = lines[i].strip()
        i += 1
        author = lines[i].rstrip("\n")
        i += 1
        parents_line = lines[i].strip()
        i += 1
        parents = parents_line.split() if parents_line else []

        # Body: everything until FILES_MARKER.
        body_lines: list[str] = []
        while i < n and lines[i].strip() != FILES_MARKER:
            body_lines.append(lines[i])
            i += 1
        # Drop leading/trailing blank lines from body block.
        while body_lines and body_lines[0].strip() == "":
            body_lines.pop(0)
        while body_lines and body_lines[-1].strip() == "":
            body_lines.pop()
        subject = body_lines[0].rstrip() if body_lines else ""
        body_remainder = body_lines[1:] if len(body_lines) > 1 else []
        # Drop blank line between subject and body if present.
        while body_remainder and body_remainder[0].strip() == "":
            body_remainder.pop(0)
        body = "\n".join(line.rstrip() for line in body_remainder).rstrip()

        # Skip the FILES_MARKER line.
        if i < n and lines[i].strip() == FILES_MARKER:
            i += 1

        # File-status lines: STATUS\tPATH (or STATUS\tOLD\tNEW for renames). Stop at
        # next COMMIT_MARKER or EOF or blank-then-marker.
        files: list[tuple[str, str]] = []
        while i < n:
            line = lines[i]
            if line.strip() == COMMIT_MARKER:
                break
            if line.strip() == "":
                i += 1
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                status = parts[0].strip()
                # For rename/copy (R*/C*) the path is the new (last) field.
                path = parts[-1].strip()
                if path:
                    files.append((status, path))
            i += 1

        commits.append(
            Commit(
                sha=sha,
                short=short,
                date=date,
                author=author,
                parents=parents,
                subject=subject,
                body=body,
                files=files,
            )
        )
    return commits


def group_by_type(commits: list[Commit]) -> dict[str, list[Commit]]:
    """Bucket commits by Conventional Commits type. Unmatched fall in 'other'.

    Result is a dict keyed by the canonical type (only types with >=1 commit appear).
    Within each bucket, commits preserve input order.
    """
    groups: dict[str, list[Commit]] = {}
    for c in commits:
        t, _ = c.classify()
        groups.setdefault(t, []).append(c)
    return groups


def _summarize_files(commits: list[Commit]) -> tuple[int, int, int, int]:
    """Return (files_touched, added, modified, deleted) across the group."""
    seen: set[str] = set()
    added = modified = deleted = 0
    # Distinct paths win the union; for status counting, we tally per (path, status)
    # using the worst-case status so a file touched twice doesn't double-count.
    status_for: dict[str, str] = {}
    for c in commits:
        for status, path in c.files:
            seen.add(path)
            # Take the most "destructive" classification per path: D > A > everything else.
            existing = status_for.get(path, "")
            if status.startswith("D"):
                status_for[path] = "D"
            elif status.startswith("A") and not existing.startswith("D"):
                status_for[path] = "A"
            else:
                status_for.setdefault(path, status[:1] or "M")
    for s in status_for.values():
        if s == "A":
            added += 1
        elif s == "D":
            deleted += 1
        else:
            modified += 1
    return len(seen), added, modified, deleted


def _format_subject(commit: Commit) -> str:
    """Strip the type prefix from the subject for display, but keep merge tags."""
    t, rest = commit.classify()
    if t == "other":
        return commit.subject
    return rest


def render_markdown(commits: list[Commit], *, from_ref: str, to_ref: str) -> str:
    """Render a deterministic markdown changelog."""
    out: list[str] = []
    out.append("# Changelog")
    out.append("")
    out.append(f"Range: `{from_ref}..{to_ref}`")
    out.append(f"Commits: {len(commits)}")
    out.append("")

    if not commits:
        out.append("_No commits in range._")
        out.append("")
        return "\n".join(out)

    groups = group_by_type(commits)
    for type_key, title in CANONICAL_GROUPS:
        bucket = groups.get(type_key)
        if not bucket:
            continue
        files, added, modified, deleted = _summarize_files(bucket)
        out.append(f"## {title} ({len(bucket)})")
        out.append("")
        out.append(
            f"_Files touched: {files} (added {added}, modified {modified}, deleted {deleted})_"
        )
        out.append("")
        for c in bucket:
            tag = " [merge]" if c.is_merge else ""
            out.append(f"- `{c.short}` {_format_subject(c)}{tag}")
        out.append("")
    return "\n".join(out)


def render_json(commits: list[Commit], *, from_ref: str, to_ref: str) -> str:
    """Render a deterministic JSON document mirroring the markdown structure."""
    groups = group_by_type(commits)
    payload: dict[str, Any] = {
        "range": {"from": from_ref, "to": to_ref},
        "commit_count": len(commits),
        "groups": [],
    }
    for type_key, title in CANONICAL_GROUPS:
        bucket = groups.get(type_key)
        if not bucket:
            continue
        files, added, modified, deleted = _summarize_files(bucket)
        payload["groups"].append(
            {
                "type": type_key,
                "title": title,
                "commit_count": len(bucket),
                "files_touched": files,
                "files_added": added,
                "files_modified": modified,
                "files_deleted": deleted,
                "commits": [
                    {
                        "sha": c.sha,
                        "short": c.short,
                        "date": c.date,
                        "author": c.author,
                        "parents": c.parents,
                        "subject": _format_subject(c),
                        "is_merge": c.is_merge,
                    }
                    for c in bucket
                ],
            }
        )
    return json.dumps(payload, indent=2, sort_keys=False) + "\n"


def _resolve_git_range(from_ref: str | None, to_ref: str | None) -> tuple[str, str]:
    """Resolve --from/--to defaults: latest tag → HEAD when omitted."""
    to_resolved = to_ref or "HEAD"
    if from_ref:
        return from_ref, to_resolved
    try:
        last_tag = subprocess.run(  # noqa: S603 — trusted git argv (resolved against operator-supplied --to) per 2026-05-08-001 D001/S603 disposition
            ["git", "describe", "--tags", "--abbrev=0", to_resolved],  # noqa: S607 — PATH-relative git invocation per 2026-05-08-001 D001/S607 disposition
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if last_tag:
            return last_tag, to_resolved
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    # No tag — fall back to first commit reachable from --to.
    try:
        first = (
            subprocess.run(  # noqa: S603 — trusted git argv (resolved against operator-supplied --to) per 2026-05-08-001 D001/S603 disposition
                ["git", "rev-list", "--max-parents=0", to_resolved],  # noqa: S607 — PATH-relative git invocation per 2026-05-08-001 D001/S607 disposition
                check=True,
                capture_output=True,
                text=True,
            )
            .stdout.strip()
            .splitlines()
        )
        if first:
            return first[0], to_resolved
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return "", to_resolved


def _run_git_log(from_ref: str, to_ref: str) -> str:
    """Invoke git log with the stable format. Empty range → empty output."""
    range_arg = f"{from_ref}..{to_ref}" if from_ref else to_ref
    cmd = [
        "git",
        "log",
        "--no-color",
        "--reverse",
        "--name-status",
        f"--pretty=format:{GIT_LOG_FORMAT}",
        range_arg,
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)  # noqa: S603,S607 — trusted git argv + PATH-relative git invocation per 2026-05-08-001 D001/S603/S607 dispositions
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Render a deterministic markdown/JSON changelog for a git revision range.",
    )
    p.add_argument("--from", dest="from_ref", help="Start revision (exclusive). Default: last tag.")
    p.add_argument("--to", dest="to_ref", help="End revision (inclusive). Default: HEAD.")
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")
    p.add_argument(
        "--fixtures", help="Fixture directory containing git_log.txt (and optional meta.json)."
    )
    p.add_argument("--out", help="Write output to this path instead of stdout.")
    args = p.parse_args(argv)

    if args.fixtures:
        base = Path(args.fixtures)
        log_path = base / "git_log.txt"
        if not log_path.is_file():
            print(f"Error: fixture missing git_log.txt: {log_path}", file=sys.stderr)
            return 2
        text = log_path.read_text()
        meta_path = base / "meta.json"
        meta: dict[str, Any] = {}
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text())
            except json.JSONDecodeError:
                meta = {}
        from_ref = args.from_ref or meta.get("from") or ""
        to_ref = args.to_ref or meta.get("to") or "HEAD"
    else:
        from_ref, to_ref = _resolve_git_range(args.from_ref, args.to_ref)
        text = _run_git_log(from_ref, to_ref)

    commits = parse_git_log(text)
    if args.format == "json":
        rendered = render_json(commits, from_ref=from_ref, to_ref=to_ref)
    else:
        rendered = render_markdown(commits, from_ref=from_ref, to_ref=to_ref)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered)
    else:
        sys.stdout.write(rendered)
        if not rendered.endswith("\n"):
            sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
