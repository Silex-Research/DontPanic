"""Append-only `audit/transcript.md` writer for human visibility.

Each round of a volley appends one line. `tail -f audit/transcript.md` shows live
progress. The audit JSONs are the authoritative artifacts; the transcript is a
human-friendly index.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

HEADER = """# Volley transcript

One line per dispatch. Authoritative state lives in `audit/<agent>-<role>-i<N>.json`.

| timestamp | feature | iter | agent / role | status | tokens in/out | audit |
|---|---|---|---|---|---|---|
"""


def ensure_header(plan_dir: Path) -> Path:
    transcript = plan_dir / "audit" / "transcript.md"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    if not transcript.exists():
        transcript.write_text(HEADER)
    return transcript


def append_round(
    plan_dir: Path,
    feature_id: str,
    iteration: int,
    agent: str,
    role: str,
    audit_status: str,
    tokens_in: int | None,
    tokens_out: int | None,
    audit_path: Path,
) -> None:
    transcript = ensure_header(plan_dir)
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rel = audit_path.relative_to(plan_dir) if audit_path.is_relative_to(plan_dir) else audit_path
    tin = "—" if tokens_in is None else f"{tokens_in:,}"
    tout = "—" if tokens_out is None else f"{tokens_out:,}"
    line = (
        f"| {ts} | {feature_id} | i{iteration} | {agent} / {role} | "
        f"{audit_status} | {tin} / {tout} | [{rel.name}]({rel}) |\n"
    )
    with transcript.open("a") as f:
        f.write(line)


def append_terminal(
    plan_dir: Path,
    feature_id: str,
    final_status: str,
    rounds: int,
    reason: str,
) -> None:
    transcript = ensure_header(plan_dir)
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with transcript.open("a") as f:
        f.write(
            f"\n**{ts}** — feature **{feature_id}** terminal: `{final_status}` after {rounds} round(s) — {reason}\n\n"
        )
