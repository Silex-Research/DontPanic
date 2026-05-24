"""Plan 2026-05-19-004 F004 — supervisor post-commit architecture regen hook.

After ``dispatch_volley`` reaches the ``signed_off`` terminal AND the plan's
``commit_policy.mode`` is ``child_commit``, this hook inspects the just-
committed diff against the architecture-relevant globs. If any committed
file matches, it runs :func:`architecture.regen` into the working tree and
emits an INBOX ``architecture_regenerated`` event.

Discipline (mirrors F005):

* The hook **never** ``git add``s or commits the regenerated map. Operator
  sees ``docs/architecture/architecture.json`` in ``git status`` and decides
  whether to amend, commit separately, or discard.
* Regen failure is logged via an INBOX ``architecture_regen_failed`` event
  and the volley terminal continues uninterrupted — the architecture map is
  advisory, not load-bearing for the dispatch path.
* Pure no-op for non-``child_commit`` policies, no-commit working trees,
  and diffs that don't touch any relevant glob.
"""

from __future__ import annotations

import fnmatch
import json
import subprocess
from pathlib import Path
from typing import Any

import datetime as dt

from dontpanic_orchestrate import architecture, inbox, notify_event

ARCHITECTURE_RELEVANT_GLOBS: tuple[str, ...] = (
    "scripts/dontpanic_orchestrate/*",
    "scripts/dontpanic_orchestrate/**",
    "claude/shared/*",
    "claude/shared/**",
    "docs/plans/*/plan.md",
    "docs/plans/*/features.json",
)


def matches_relevant_glob(path: str) -> bool:
    """True iff ``path`` matches any architecture-relevant glob.

    Uses :func:`fnmatch.fnmatch` so ``**`` is treated as a literal ``*`` —
    we deliberately list both the one-segment and recursive forms in
    :data:`ARCHITECTURE_RELEVANT_GLOBS` so a single-level match like
    ``claude/shared/VERSION`` and a nested match like
    ``claude/shared/schemas/v1.0/plan.schema.json`` both fire.
    """
    norm = path.replace("\\", "/")
    for pattern in ARCHITECTURE_RELEVANT_GLOBS:
        if fnmatch.fnmatch(norm, pattern):
            return True
    return False


def _repo_root_from_plan_dir(plan_dir: Path) -> Path | None:
    candidate = plan_dir.resolve()
    for parent in (candidate, *candidate.parents):
        if (parent / ".git").exists():
            return parent
    return None


def _git_committed_files(repo_root: Path) -> list[str]:
    """Files in the most recent commit (``HEAD~1..HEAD``).

    Returns ``[]`` when there is no second-to-last commit (root commit),
    when ``git`` is unavailable, or when the diff fails for any reason —
    the hook degrades to a no-op rather than crashing the volley terminal.
    """
    proc = subprocess.run(
        ["git", "diff", "--name-only", "HEAD~1..HEAD"],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _git_staged_files(repo_root: Path) -> list[str]:
    """Files currently staged for the next commit."""
    proc = subprocess.run(
        ["git", "diff", "--name-only", "--cached"],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _load_fingerprint(snap_path: Path) -> tuple[str | None, dict[str, str], dict[str, Any]]:
    if not snap_path.is_file():
        return None, {}, {}
    try:
        data = json.loads(snap_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, {}, {}
    if not isinstance(data, dict):
        return None, {}, {}
    fp = data.get("source_fingerprint")
    if not isinstance(fp, dict):
        return None, {}, data
    root_hash = fp.get("file_hashes_root") if isinstance(fp.get("file_hashes_root"), str) else None
    per_file = fp.get("file_hashes") if isinstance(fp.get("file_hashes"), dict) else {}
    return root_hash, dict(per_file), data


def maybe_regen_after_commit(
    *,
    plan_dir: Path,
    plan_id: str,
    feature_id: str,
    commit_policy_mode: str | None,
    repo_root: Path | None = None,
    feature_display_name: str | None = None,
) -> dict[str, Any] | None:
    """Run architecture regen when an architecture-relevant file was just
    committed. Returns a result dict on regen, ``None`` on no-op.

    The hook never raises — failures emit an INBOX
    ``architecture_regen_failed`` event so the operator can see what
    happened, but the volley terminal continues uninterrupted.
    """
    if commit_policy_mode != "child_commit":
        return None
    if repo_root is None:
        repo_root = _repo_root_from_plan_dir(plan_dir)
    if repo_root is None:
        return None
    repo_root = Path(repo_root).resolve()

    try:
        committed = _git_committed_files(repo_root)
    except OSError:
        return None
    if not committed:
        return None
    relevant = sorted({p for p in committed if matches_relevant_glob(p)})
    if not relevant:
        return None

    snap_path = repo_root / architecture.DEFAULT_OUTPUT_REL
    prior_root, prior_per_file, _ = _load_fingerprint(snap_path)

    try:
        out_path = architecture.regen(repo_root, with_html=False)
    except Exception as exc:  # noqa: BLE001 — never crash the volley terminal
        body = (
            "Architecture regen hook failed after child_commit. The volley\n"
            "terminal is unaffected; the architecture map is now potentially\n"
            "stale until the operator re-runs `dontpanic architecture regen`.\n\n"
            f"Error type: {type(exc).__name__}\n"
            f"Error: {exc}\n"
            f"Matched files: {relevant}\n"
        )
        inbox_written = False
        try:
            inbox.append_event(
                plan_dir,
                event="architecture_regen_failed",
                plan_id=plan_id,
                body=body,
                feature_id=feature_id,
                matched_files=",".join(relevant),
                error_type=type(exc).__name__,
            )
            inbox_written = True
        except Exception:  # noqa: BLE001 — INBOX is best-effort here
            pass
        # Plan 2026-05-24-004 F003 (audit i0 finding #1): fan to ALL sinks
        # + pass plan_dir so the rendered terminal + sidecar + INBOX-
        # annotation paths fire for this LIVE-disposition event. INBOX
        # write above is the truth-of-record; this dispatch is best-effort
        # and never crashes the volley terminal. If the INBOX write
        # failed, skip advisory dispatch so D013's truth-of-record
        # invariant stays intact.
        if inbox_written:
            try:
                notify_event.dispatch_event(
                    notify_event.NotifyEvent(
                        kind="architecture_regen_failed",
                        severity=notify_event.SEVERITY_INFO,
                        plan_id=plan_id,
                        feature_id=feature_id,
                        body=(
                            f"**Architecture regen failed** — `{type(exc).__name__}` "
                            f"after child_commit on {feature_id}. Map may be stale; "
                            "operator can re-run `dontpanic architecture regen`."
                        ),
                        evidence_uri=str(plan_dir / "INBOX.md"),
                        timestamp=dt.datetime.now(dt.timezone.utc),
                        inbox_event="architecture_regen_failed",
                        feature_display_name=feature_display_name,
                        technical_metadata={
                            "matched_files": ",".join(relevant),
                            "error_type": type(exc).__name__,
                        },
                    ),
                    plan_dir=plan_dir,
                )
            except Exception:  # noqa: BLE001 — sink failure must not crash hook
                pass
        return None

    new_root, new_per_file, snap_data = _load_fingerprint(out_path)
    prior_keys = set(prior_per_file)
    new_keys = set(new_per_file)
    files_added = sorted(new_keys - prior_keys)
    files_removed = sorted(prior_keys - new_keys)
    files_modified = sorted(
        path
        for path in prior_keys & new_keys
        if prior_per_file[path] != new_per_file[path]
    )
    total_modules = len(snap_data.get("modules") or []) if isinstance(snap_data, dict) else 0
    total_plans = len(snap_data.get("plans") or []) if isinstance(snap_data, dict) else 0

    if prior_root is None:
        prior_state = "absent"
    elif prior_root == new_root:
        prior_state = "fresh"
    else:
        prior_state = "stale"
    state_transition = f"{prior_state}->fresh"

    body_lines = [
        f"Architecture map regenerated after child_commit on {feature_id}.",
        "",
        f"state: {state_transition}",
        f"prior_fingerprint: {prior_root or '(absent)'}",
        f"new_fingerprint: {new_root or '(unknown)'}",
        f"files_added: {len(files_added)}",
        f"files_removed: {len(files_removed)}",
        f"files_modified: {len(files_modified)}",
        f"total_modules: {total_modules}",
        f"total_plans: {total_plans}",
        "",
        "The supervisor does NOT auto-commit architecture.json. Inspect",
        "`git status` and decide whether to amend, commit separately, or",
        "discard.",
    ]
    try:
        inbox.append_event(
            plan_dir,
            event="architecture_regenerated",
            plan_id=plan_id,
            body="\n".join(body_lines),
            feature_id=feature_id,
            prior_fingerprint=prior_root or "absent",
            new_fingerprint=new_root or "unknown",
            files_added=len(files_added),
            files_removed=len(files_removed),
            files_modified=len(files_modified),
            total_modules=total_modules,
            total_plans=total_plans,
            state_transition=state_transition,
        )
    except Exception:  # noqa: BLE001 — INBOX is best-effort
        pass

    return {
        "out_path": str(out_path),
        "prior_fingerprint": prior_root,
        "new_fingerprint": new_root,
        "files_added": files_added,
        "files_removed": files_removed,
        "files_modified": files_modified,
        "total_modules": total_modules,
        "total_plans": total_plans,
        "state_transition": state_transition,
        "matched_files": relevant,
    }


__all__ = [
    "ARCHITECTURE_RELEVANT_GLOBS",
    "matches_relevant_glob",
    "maybe_regen_after_commit",
]
