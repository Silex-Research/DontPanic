"""F003 — pre-signoff enforcement gate built on top of F002's analyzer.

Spec: plan 2026-05-01-004 F003. Owns:

  * ``PatchCompletenessError`` — structured exception raised when signoff
    would otherwise pass with an incomplete patch surface and no override.
  * ``validate_reason()`` — defense-in-depth (layer B) length check on
    operator-supplied override reasons. Layer A lives in the CLI argparse
    validators that share this min-length constant.
  * Mode 5 promotion logic: F003 (NOT F002) escalates ``unstaged_dirty_state``
    findings from ``info`` to ``block`` when files fall outside the touched
    set AND no ``--unrelated-dirty-state-note`` has been supplied. F002's
    pure analyzer remains touched-set-agnostic for Mode 5.
  * ``enforce()`` — the signoff-time entry point. Loads the F001 git-state
    sidecar, computes ``touched_files``, calls ``patch_completeness.check()``,
    persists the report, applies Mode 5 promotion, and either raises
    ``PatchCompletenessError`` or returns the dict block to embed in
    ``signoff.json``.

D009 carve-out: when ``dry_run=True`` the gate persists the report and
returns the block but never raises. This is what ``jarvis dispatch
--strict-dry-run`` uses to surface findings without blocking the preview.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import inbox, patch_completeness
from dontpanic_orchestrate.patch_completeness import (
    CompletenessReport,
    Finding,
)

MIN_REASON_LEN = 8


class PatchCompletenessError(RuntimeError):
    """Raised at signoff time when the gate refuses to promote ``passes:true``.

    The exception's string form renders one finding per line in the format
    ``<mode> | <severity> | <files> | <reason> | <recommendation>`` so the
    operator can act without parsing JSON. Only block-severity findings are
    rendered; info-tier (Mode 5 advisory) entries are skipped.
    """

    def __init__(self, report: CompletenessReport, plan_dir: Path) -> None:
        self.report = report
        self.plan_dir = plan_dir
        super().__init__(self._render(report))

    @staticmethod
    def _render(report: CompletenessReport) -> str:
        lines = [
            "Patch incomplete — signoff blocked.",
            "Pass --allow-incomplete-patch <reason> (>=8 chars) to override, or fix:",
        ]
        for f in report.findings:
            if f.severity != "block":
                continue
            lines.append(
                f"  {f.mode} | {f.severity} | {','.join(f.files)} | {f.reason} | {f.recommendation}"
            )
        return "\n".join(lines)


def validate_reason(value: str | None, *, flag: str) -> str | None:
    """Layer-B defense-in-depth check on override-reason length.

    Mirrors the argparse layer-A validator's contract: ``None`` is allowed
    (flag absent), present values must satisfy ``len(value.strip()) >=
    MIN_REASON_LEN``. Raises ``ValueError`` on rejection — distinct from
    ``argparse.ArgumentTypeError`` so programmatic callers (which bypass
    argparse) get the same protection without a CLI dependency.
    """
    if value is None:
        return None
    stripped = value.strip()
    if len(stripped) < MIN_REASON_LEN:
        raise ValueError(
            f"{flag} reason must be at least {MIN_REASON_LEN} non-whitespace "
            f"characters; got {len(stripped)} ({value!r}). Provide a substantive "
            "operator note explaining why the patch surface is allowed to ship "
            "with this gap."
        )
    return value


def _load_git_state(plan_dir: Path, *, iteration: int, role: str) -> dict | None:
    sidecar = plan_dir / "evidence" / f"git-state-{iteration}-{role}.json"
    if not sidecar.exists():
        return None
    try:
        return json.loads(sidecar.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _evidence_refs_from_envelopes(audit_paths: list[Path]) -> set[str]:
    """Collect ``evidence_refs[*].uri`` strings from the persisted envelopes.

    Defensive: tolerates missing envelopes, malformed JSON, and envelopes
    that pre-date the ``evidence_refs`` field.
    """
    refs: set[str] = set()
    for ap in audit_paths:
        try:
            blob = json.loads(ap.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for ref in blob.get("evidence_refs") or []:
            if isinstance(ref, dict):
                uri = ref.get("uri")
                if isinstance(uri, str):
                    refs.add(uri)
            elif isinstance(ref, str):
                refs.add(ref)
    return refs


#: Run telemetry the SUPERVISOR authors inside the dispatching plan's own
#: directory. These can never appear in ``touched_files`` — that set is built
#: from the IMPLEMENTER's declared evidence refs — so without this exemption a
#: volley blocks its own signoff on files it wrote seconds earlier (observed
#: 2026-08-09 on plan 2026-08-09-002 F001, which reached signed_off and then
#: terminated blocked).
#:
#: Deliberately NOT covered: ``plan.md``, ``features.json``,
#: ``decisions.jsonl``. Those are the contract and the deliverable; dirty state
#: in them is a real finding and must keep blocking.
_SELF_AUTHORED_FILES: frozenset[str] = frozenset({"INBOX.md"})
_SELF_AUTHORED_DIRS: tuple[str, ...] = ("audit/",)
_SELF_AUTHORED_EVIDENCE_PREFIX = "evidence/git-state-"


def _iter_git_state_paths(git_state: dict) -> list[str]:
    """Every path the F001 sidecar mentions, across all of its buckets."""
    paths: list[str] = []
    for key in ("staged", "unstaged_modified"):
        for entry in git_state.get(key) or []:
            path = entry.get("path") if isinstance(entry, dict) else entry
            if path:
                paths.append(path)
    for key in ("untracked", "deleted_staged", "deleted_unstaged"):
        for entry in git_state.get(key) or []:
            path = entry.get("path") if isinstance(entry, dict) else entry
            if path:
                paths.append(path)
    return paths


def self_authored_telemetry(git_state: dict, *, plan_dir: Path) -> set[str]:
    """Paths in ``git_state`` that this very run wrote into its own plan dir.

    Anchored on the plan directory's own NAME — the plan id — rather than on a
    path relationship with ``repo_root``. That is deliberate: the supervisor
    calls :func:`enforce` with ``repo_root=plan_dir`` (supervisor.py:1445), so
    any prefix derived from ``plan_dir.relative_to(repo_root)`` collapses to
    ``"."`` and matches nothing. The plan id is unique per plan, which also
    gives the scoping this needs for free: a SIBLING plan's dirty telemetry
    carries a different id, does not match, and stays a finding.

    Returns exact path strings so the caller can union them into
    ``touched_files`` without changing how Mode 5 compares.
    """
    plan_name = plan_dir.resolve().name
    if not plan_name:
        return set()

    exempt: set[str] = set()
    for path in _iter_git_state_paths(git_state):
        if path.startswith(f"{plan_name}/"):
            tail = path[len(plan_name) + 1 :]
        elif f"/{plan_name}/" in path:
            tail = path.split(f"/{plan_name}/", 1)[1]
        else:
            continue
        if (
            tail in _SELF_AUTHORED_FILES
            or tail.startswith(_SELF_AUTHORED_DIRS)
            or tail.startswith(_SELF_AUTHORED_EVIDENCE_PREFIX)
        ):
            exempt.add(path)
    return exempt


def _promote_mode5(
    report: CompletenessReport,
    *,
    touched_files: set[str],
    unrelated_dirty_state_note: str | None,
) -> tuple[CompletenessReport, list[str]]:
    """F003 owns the Mode 5 escalation. F002 emits info regardless of touched
    set; F003 escalates to block when files fall outside ``touched_files``
    AND no operator note was supplied.

    Returns ``(promoted_report, unrelated_dirty_files)`` so callers can
    record the cited file list in the signoff block.
    """
    new_findings: list[Finding] = []
    unrelated_dirty: list[str] = []
    for f in report.findings:
        if f.mode != "unstaged_dirty_state":
            new_findings.append(f)
            continue
        outside = sorted(set(f.files) - set(touched_files))
        if outside:
            unrelated_dirty.extend(outside)
        if outside and not unrelated_dirty_state_note:
            promoted = Finding(
                mode=f.mode,
                files=list(f.files),
                reason=(f.reason + " Files outside touched_files: " + ",".join(outside)),
                severity="block",
                recommendation=(
                    "Run: git add -u <paths> for files that should ride along; "
                    "OR pass --unrelated-dirty-state-note <reason> at dispatch."
                ),
            )
            new_findings.append(promoted)
        else:
            new_findings.append(f)
    promoted_report = CompletenessReport(
        schema_version=report.schema_version,
        status=patch_completeness.compute_status(new_findings),
        findings=new_findings,
        files=list(report.files),
    )
    return promoted_report, unrelated_dirty


def _persist_report(plan_dir: Path, *, iteration: int, report: CompletenessReport) -> Path:
    audit_dir = plan_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    out = audit_dir / f"patch-completeness-{iteration}.json"
    out.write_text(json.dumps(report.to_dict(), indent=2) + "\n")
    return out


def _build_signoff_block(
    promoted_report: CompletenessReport,
    *,
    allow_incomplete_patch_reason: str | None,
    unrelated_dirty_state_note: str | None,
    unrelated_dirty_files: list[str],
) -> dict[str, Any]:
    block: dict[str, Any] = {
        "status": promoted_report.status,
        "findings": [f.to_dict() for f in promoted_report.findings],
        "files": list(promoted_report.files),
    }
    if allow_incomplete_patch_reason is not None:
        block["override_flag"] = "allow_incomplete_patch"
        block["override_reason"] = allow_incomplete_patch_reason
    if unrelated_dirty_state_note is not None:
        block["unrelated_dirty_state_note"] = unrelated_dirty_state_note
        block["unrelated_dirty_files"] = sorted(set(unrelated_dirty_files))
    return block


def enforce(
    plan_dir: Path,
    *,
    plan_id: str,
    iteration: int,
    role: str,
    audit_paths: list[Path],
    affected_paths: list[str] | None,
    repo_root: Path,
    allow_incomplete_patch_reason: str | None = None,
    unrelated_dirty_state_note: str | None = None,
    dry_run: bool = False,
    git_state_override: dict | None = None,
) -> dict[str, Any] | None:
    """Run F002's analyzer against the F001 sidecar and decide signoff fate.

    Returns the signoff ``patch_completeness`` block to attach when the gate
    passes (or when overridden); returns ``None`` when no F001 sidecar is
    present and no ``git_state_override`` was supplied (gate is best-effort
    and silently no-ops without git state, same contract as F001 itself).

    The ``git_state_override`` parameter is used by the CLI strict-dry-run
    preview path: no audit envelope has been finalized yet, so no F001
    sidecar exists, but the operator wants the gate's findings rendered
    against a fresh ``git_state.capture()`` of the current working tree.

    Raises ``PatchCompletenessError`` only when ALL of the following hold:
      - ``dry_run`` is False
      - report status is ``'fail'`` after Mode 5 promotion
      - ``allow_incomplete_patch_reason`` is None
    """
    # Layer-B re-validation (defense-in-depth). Argparse already validated
    # at layer A; this catches programmatic callers.
    validate_reason(allow_incomplete_patch_reason, flag="--allow-incomplete-patch")
    validate_reason(unrelated_dirty_state_note, flag="--unrelated-dirty-state-note")

    git_state = git_state_override
    if git_state is None:
        git_state = _load_git_state(plan_dir, iteration=iteration, role=role)
    if git_state is None:
        return None

    touched_files = _evidence_refs_from_envelopes(audit_paths) | set(affected_paths or [])
    # A run's own telemetry is touched by definition — it exists because this
    # dispatch wrote it. Without this the gate blocks every volley that reaches
    # signoff, since the implementer never declares supervisor-authored files.
    touched_files |= self_authored_telemetry(git_state, plan_dir=plan_dir)
    raw_report = patch_completeness.check(git_state, repo_root, touched_files)
    promoted_report, unrelated_dirty_files = _promote_mode5(
        raw_report,
        touched_files=touched_files,
        unrelated_dirty_state_note=unrelated_dirty_state_note,
    )

    report_path = _persist_report(plan_dir, iteration=iteration, report=promoted_report)

    block = _build_signoff_block(
        promoted_report,
        allow_incomplete_patch_reason=allow_incomplete_patch_reason,
        unrelated_dirty_state_note=unrelated_dirty_state_note,
        unrelated_dirty_files=unrelated_dirty_files,
    )

    if dry_run:
        return block

    if promoted_report.status == "fail" and allow_incomplete_patch_reason is None:
        try:
            inbox.append_event(
                plan_dir,
                event="breaker:patch_incomplete",
                plan_id=plan_id,
                body=PatchCompletenessError._render(promoted_report),
                report_path=str(report_path),
            )
        except Exception:  # pragma: no cover — INBOX write is best-effort  # noqa: S110  # INBOX write is documented best-effort; pragma:no cover above
            pass
        raise PatchCompletenessError(promoted_report, plan_dir)

    return block
