"""F008 Item 4 — signoff.json closeout writer.

When dispatch_volley reaches a terminal state (signed_off, blocked,
stopped_quota, stopped_no_progress, stopped_max_iterations, paused_on_gate),
this module aggregates the per-iteration audit JSONs into a single closeout
artifact at <plan_dir>/audit/signoff-<task_id>.json that validates against
agent-conventions Signoff schema.

Per the F008 AC, signoff.json is required on signed_off; for non-signoff
terminal states the writer can still produce a record (with signoff=false
and an appropriate next_action) so operators get a single artifact summary
of the volley regardless of outcome.

DPN-012: when the volley's ``feature_id`` is passed, the same signoff (and
child-plan compliance side-car) is also recorded as that feature's own durable
evidence under ``<plan_dir>/audit/feature-signoffs/`` so another feature's
later volley cannot overwrite it.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import errno
import hashlib
import json
import os
import re
import secrets
import stat
from pathlib import Path
from typing import Any

from .agent_conventions.schemas.v1_0.models.signoff_model import Signoff  # noqa: E402
from pydantic import ValidationError  # noqa: E402

VALID_TIERS = {"trivial", "local", "cross-cutting", "architectural", "p0"}


class SignoffWriteError(RuntimeError):
    pass


def _now() -> dt.datetime:
    """The writer clock: aware UTC, full precision (microseconds kept)."""
    return dt.datetime.now(dt.timezone.utc)


def _iso_seconds(moment: dt.datetime) -> str:
    """``moment`` as the signoff ``decided_at`` text (whole second, ``Z``)."""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_iso() -> str:
    return _iso_seconds(_now())


def _next_action_for(volley_status: str, signed_off: bool) -> str:
    if signed_off:
        return "merge"
    if volley_status == "blocked":
        return "blocked_awaiting_human"
    if volley_status == "paused_on_gate":
        return "blocked_awaiting_human"
    # Plan 2026-05-12-001 v4 F002 — auditor returned verdict=blocked with
    # an empty findings list. Operator must inspect manually; we don't
    # auto-promote to environmental because there's no advisory signal.
    if volley_status == "blocked_no_findings":
        return "blocked_awaiting_human"
    # supervisor.dispatch_volley emits "stopped_cap" when iteration cap is
    # reached; the legacy "stopped_max_iterations" alias is kept for callers
    # that may emit it directly.
    if volley_status in {
        "stopped_quota",
        "stopped_cap",
        "stopped_max_iterations",
        "stopped_no_progress",
        "stopped_budget",
        "stopped_wall_clock",
        "stopped_diminishing_returns",
        "stopped_convergence_collapse",
        # Plan 2026-05-09-002 F003 — env-only first-round short-circuit.
        # Operator runs the cited verification locally on a host with the
        # missing capability, attaches evidence, then approves the breaker.
        "stopped_environmental_blocker",
    }:
        return "remediate"
    if volley_status == "stopped_global_breaker":
        # Global circuit breaker is hard stop; operator can't approve, must
        # wait. Closeout marks blocked_awaiting_human + signoff=false.
        return "blocked_awaiting_human"
    return "defer"


def _audit_relpath(audit_path: Path, plan_dir: Path) -> str:
    """Render audit path relative to plan_dir if possible, else absolute."""
    try:
        return str(audit_path.relative_to(plan_dir))
    except ValueError:
        return str(audit_path)


def _summarize_votes(audit_paths: list[Path]) -> dict[str, int]:
    counts = {
        "signed_off_count": 0,
        "needs_changes_count": 0,
        "blocked_count": 0,
        "inconclusive_count": 0,
    }
    for ap in audit_paths:
        try:
            data = json.loads(ap.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        status = data.get("audit_status")
        key = f"{status}_count" if status else None
        if key in counts:
            counts[key] += 1
    return counts


def _quota_totals(audit_paths: list[Path]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for ap in audit_paths:
        try:
            data = json.loads(ap.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        agent = data.get("agent")
        qc = data.get("quota_consumed") or {}
        pct = qc.get("percent_weekly")
        if agent and isinstance(pct, (int, float)):
            key = f"{agent}_percent"
            totals[key] = max(totals.get(key, 0.0), float(pct))
    # Filter to fields the schema knows about (claude_percent / codex_percent /
    # gemini_percent only; grok_calls counted separately).
    keep = {
        k: v
        for k, v in totals.items()
        if k in {"claude_percent", "codex_percent", "gemini_percent"}
    }
    return keep


def build_signoff_dict(
    *,
    plan_id: str,
    tier: str,
    iteration: int,
    agents_in_panel: list[str],
    audit_paths: list[Path],
    plan_dir: Path,
    volley_status: str,
    signoff_reason: str | None = None,
    patch_completeness: dict[str, Any] | None = None,
    decided_at: str | None = None,
) -> dict[str, Any]:
    """``decided_at`` (default: read the clock) lets a caller stamp a value it already checked."""
    if not audit_paths:
        raise SignoffWriteError("cannot write signoff: no audit paths")
    if tier not in VALID_TIERS:
        raise SignoffWriteError(f"tier {tier!r} not in {sorted(VALID_TIERS)}")
    signed_off = volley_status == "signed_off"
    audits_rel = [_audit_relpath(p, plan_dir) for p in audit_paths]

    payload: dict[str, Any] = {
        "task_id": plan_id,
        "signoff_id": f"{plan_id}#signoff#{iteration}",
        "iteration": iteration,
        "tier": tier,
        "agents_in_panel": list(agents_in_panel),
        "audits": audits_rel,
        "vote_summary": _summarize_votes(audit_paths),
        "signoff": signed_off,
        "signoff_reason": signoff_reason
        or (f"volley_status={volley_status}; final iteration={iteration}"),
        "next_action": _next_action_for(volley_status, signed_off),
        "decided_at": decided_at if decided_at is not None else _now_iso(),
    }
    quota = _quota_totals(audit_paths)
    if quota:
        payload["quota_consumed_total"] = quota

    # Strict validation — surfaces drift between code + schema early.
    # Plan 2026-05-01-004 F003: ``patch_completeness`` is recorded in
    # signoff.json as a sibling key, but the canonical agent-conventions
    # Signoff schema is NOT bumped here (D004 defers v1.4.0). We validate
    # the payload WITHOUT the extra block, then attach it post-validation.
    # This satisfies acceptance #11's "validator-level acceptance only".
    try:
        Signoff.model_validate(payload)
    except ValidationError as exc:
        raise SignoffWriteError(f"signoff payload failed validation: {exc}") from exc
    if patch_completeness is not None:
        payload["patch_completeness"] = patch_completeness
    # DPN-011 — bind the signoff to the exact bytes of every envelope it
    # lists (same post-validation sibling-key pattern as patch_completeness;
    # the vendored Signoff schema is unchanged). An in-place overwrite of a
    # listed ``-iN`` envelope changes its digest even within the same second.
    payload["audit_digests"] = _audit_digests(audit_paths, audits_rel)
    return payload


def _audit_digest(path: Path) -> str:
    """``"sha256:<hex>"`` of ``path``'s bytes."""
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _audit_digests(audit_paths: list[Path], audits_rel: list[str]) -> dict[str, str]:
    """Map each ``audits`` entry to the sha256 digest of its file's bytes at
    signoff time. An unreadable file gets no entry (a consumer that requires
    the entry then fails closed)."""
    digests: dict[str, str] = {}
    for path, rel in zip(audit_paths, audits_rel, strict=True):
        try:
            digests[rel] = _audit_digest(path)
        except OSError:
            continue
    return digests


# ───────── DPN-012b review round 2 — ONE shared no-follow safe-write helper ─────────
#
# Every signoff-evidence file (plan-level signoff + side-car, per-feature
# signoff + side-car) is read, written, retired and restored RELATIVE TO A
# DIRECTORY FD whose every component below ``plan_dir`` (``audit``,
# ``feature-signoffs``) was opened with ``O_NOFOLLOW``. ``plan_dir`` itself is
# opened normally (it may legitimately sit under a symlinked ``/tmp``). A
# symlink (or non-directory) at any component, or a symlink at the file
# itself, is refused with :class:`SignoffWriteError`; a link swapped into a
# component AFTER it was opened cannot redirect the write, because the temp
# file and the rename are both relative to the already-open fd.

_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | _CLOEXEC
_NOFOLLOW_DIR_FLAGS = _DIR_FLAGS | os.O_NOFOLLOW
# Same mode tempfile.mkstemp gives the files today (0o600, before umask).
_EVIDENCE_FILE_MODE = 0o600


def _component_refusal(parent_fd: int, name: str, path: Path) -> SignoffWriteError:
    """The refusal for a component ``name`` (under ``parent_fd``) that could
    not be opened no-follow as a directory (``ELOOP`` / ``ENOTDIR``)."""
    try:
        is_link = stat.S_ISLNK(os.stat(name, dir_fd=parent_fd, follow_symlinks=False).st_mode)
    except OSError:
        is_link = False
    if is_link:
        return SignoffWriteError(
            f"signoff evidence directory {path} is a symlink; refusing to "
            f"write or read signoff evidence through it"
        )
    return SignoffWriteError(
        f"signoff evidence path {path} exists but is not a directory; "
        f"refusing to write or read signoff evidence"
    )


def _open_child_dir(parent_fd: int, name: str, path: Path, *, create: bool) -> tuple[int, bool]:
    """Open directory ``name`` relative to ``parent_fd`` WITHOUT following a
    symlink; with ``create`` a missing one is ``mkdir``-ed relative to
    ``parent_fd`` first. Returns ``(fd, created)``. A missing directory
    without ``create`` raises ``FileNotFoundError``; a symlink or
    non-directory raises :class:`SignoffWriteError`."""
    created = False
    try:
        try:
            return os.open(name, _NOFOLLOW_DIR_FLAGS, dir_fd=parent_fd), False
        except FileNotFoundError:
            if not create:
                raise
            try:
                os.mkdir(name, dir_fd=parent_fd)
                created = True
            except FileExistsError:
                pass
            return os.open(name, _NOFOLLOW_DIR_FLAGS, dir_fd=parent_fd), created
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise _component_refusal(parent_fd, name, path) from exc
        raise


def _safe_open_dir(plan_dir: Path, *components: str, create: bool = False) -> int:
    """Return an fd for ``plan_dir/<components...>``: ``plan_dir`` opened
    normally, every component below it opened no-follow relative to its
    parent's fd (see :func:`_open_child_dir`). The caller closes the fd."""
    plan_dir = Path(plan_dir)
    if create:
        plan_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(plan_dir, _DIR_FLAGS)
    path = plan_dir
    try:
        for name in components:
            path = path / name
            child, _created = _open_child_dir(fd, name, path, create=create)
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd


def _symlink_file_refusal(path: Path) -> SignoffWriteError:
    return SignoffWriteError(
        f"signoff evidence file {path} is a symlink; refusing to write or "
        f"read signoff evidence through it"
    )


def _read_regular_file(dir_fd: int, name: str, path: Path) -> bytes | None:
    """Bytes of the regular file ``name`` in ``dir_fd``, never following a
    symlink there (refused with :class:`SignoffWriteError`). ``None`` when
    it is absent or not a regular file (e.g. a directory)."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC, dir_fd=dir_fd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise _symlink_file_refusal(path) from exc
        raise
    with os.fdopen(fd, "rb") as fh:
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
            return None
        return fh.read()


def _safe_read_bytes(plan_dir: Path, *rel_components: str) -> bytes | None:
    """No-follow read of ``plan_dir/<rel_components...>`` (the last component
    is the file). ``None`` when the file or a directory on the way is absent,
    or the file is not a regular file; a symlink at any component below
    ``plan_dir`` (or a non-directory where a directory is expected) raises
    :class:`SignoffWriteError`."""
    if not rel_components:
        raise SignoffWriteError(f"no file named under {plan_dir}")
    *dirs, name = rel_components
    try:
        dfd = _safe_open_dir(plan_dir, *dirs)
    except FileNotFoundError:
        return None
    try:
        return _read_regular_file(dfd, name, Path(plan_dir, *rel_components))
    finally:
        os.close(dfd)


def safe_write_evidence_text(plan_dir: Path, rel_components: tuple[str, ...], text: str) -> None:
    """DPN-012b review round 3 — write ``text`` (UTF-8) to
    ``plan_dir/<rel_components...>`` (the last component is the file) through
    the shared no-follow helper: every directory below ``plan_dir`` is opened
    (created if missing) no-follow relative to its parent's fd, and the file
    is written temp + rename relative to that fd (:func:`_safe_write_bytes`).
    A symlink (or non-directory) at any directory component, or a symlink at
    the file, raises :class:`SignoffWriteError` and nothing is written."""
    if not rel_components:
        raise SignoffWriteError(f"no file named under {plan_dir}")
    *dirs, name = rel_components
    dfd = _safe_open_dir(plan_dir, *dirs, create=True)
    try:
        _safe_write_bytes(dfd, name, text.encode("utf-8"), Path(plan_dir, *rel_components))
    finally:
        os.close(dfd)


def safe_unlink_evidence(plan_dir: Path, rel_components: tuple[str, ...]) -> None:
    """Remove ``plan_dir/<rel_components...>`` (absent is fine) relative to a
    directory fd opened no-follow below ``plan_dir`` (a link at the file is
    removed, never its target). A symlinked directory component raises
    :class:`SignoffWriteError`."""
    if not rel_components:
        raise SignoffWriteError(f"no file named under {plan_dir}")
    *dirs, name = rel_components
    try:
        dfd = _safe_open_dir(plan_dir, *dirs)
    except FileNotFoundError:
        return
    try:
        with contextlib.suppress(FileNotFoundError):
            _safe_unlink(dfd, name)
    finally:
        os.close(dfd)


def _refuse_symlink_destination(dir_fd: int, name: str, path: Path) -> None:
    try:
        st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(st.st_mode):
        raise _symlink_file_refusal(path)


def _safe_write_bytes(dir_fd: int, name: str, data: bytes, path: Path | None = None) -> None:
    """Atomically write ``data`` to ``name`` in ``dir_fd``: a temp file
    created ``O_EXCL | O_NOFOLLOW`` in the same directory fd is fully written,
    the destination is re-checked (a symlink there is refused, the temp
    removed), then ``os.rename``d over it — both sides relative to
    ``dir_fd``. Any other error (e.g. ``IsADirectoryError`` when a directory
    occupies ``name``) propagates unchanged after the temp is removed."""
    shown = path if path is not None else Path(name)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | _CLOEXEC
    for _attempt in range(100):
        tmp = f".{name}.{secrets.token_hex(6)}.tmp"
        try:
            fd = os.open(tmp, flags, _EVIDENCE_FILE_MODE, dir_fd=dir_fd)
            break
        except FileExistsError:
            continue
    else:
        raise FileExistsError(f"could not create a temp file for {shown}")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        _refuse_symlink_destination(dir_fd, name, shown)
        os.rename(tmp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp, dir_fd=dir_fd)
        raise


def _safe_unlink(dir_fd: int, name: str) -> None:
    """Remove ``name`` from ``dir_fd`` (never follows: a link is removed, not
    its target)."""
    os.unlink(name, dir_fd=dir_fd)


@dataclasses.dataclass(frozen=True)
class _Target:
    """A signoff-evidence file ``name`` inside the no-follow-checked open
    directory ``dir_fd``. ``path`` is for messages and ``os.fspath`` (so a
    ``Path(target)`` compares equal to the plain path)."""

    dir_fd: int
    name: str
    path: Path

    def __fspath__(self) -> str:
        return os.fspath(self.path)


def _as_target(path: _Target | Path) -> tuple[_Target, int | None]:
    """``(target, fd_to_close)``: a plain path is opened as its parent
    directory (normally) + the file name."""
    if isinstance(path, _Target):
        return path, None
    p = Path(path)
    dfd = _safe_open_dir(p.parent)
    return _Target(dfd, p.name, p), dfd


def _write_target(path: _Target | Path, data: bytes) -> None:
    target, owned = _as_target(path)
    try:
        _safe_write_bytes(target.dir_fd, target.name, data, target.path)
    finally:
        if owned is not None:
            os.close(owned)


def _atomic_write_json(path: _Target | Path, obj: dict[str, Any]) -> None:
    """Write ``obj`` as JSON to ``path`` atomically through
    :func:`_safe_write_bytes`: readers never see a torn file, the temp file is
    removed if any step fails, and the original error (e.g.
    ``IsADirectoryError`` when a directory occupies ``path``) propagates
    unchanged; a symlink at ``path`` is refused (:class:`SignoffWriteError`)."""
    _write_target(path, (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def _atomic_write_bytes(path: _Target | Path, data: bytes) -> None:
    """Byte-exact atomic restore helper (:func:`_safe_write_bytes`) used only
    by :func:`_commit_signoff_pair` rollback."""
    _write_target(path, data)


def _read_bytes_if_file(target: _Target) -> bytes | None:
    """Snapshot read: the bytes of a regular file, ``None`` when absent / not
    a regular file; a symlink there is refused (:class:`SignoffWriteError`)
    before anything is retired."""
    return _read_regular_file(target.dir_fd, target.name, target.path)


def _restore(target: _Target, previous: bytes | None) -> None:
    """Put ``target`` back to ``previous`` (``None`` = absent). Never raises; a
    failed restore of a file falls back to removing it so no half-state
    survives."""
    try:
        if previous is None:
            with contextlib.suppress(FileNotFoundError):
                _safe_unlink(target.dir_fd, target.name)
        else:
            _atomic_write_bytes(target, previous)
    except (OSError, SignoffWriteError):
        with contextlib.suppress(OSError):
            _safe_unlink(target.dir_fd, target.name)


def _commit_signoff_pair(
    out: _Target,
    payload: dict[str, Any],
    side_car: _Target | None,
    compliance: dict[str, Any] | None,
) -> None:
    """Write the signoff (and, for child plans, its compliance side-car) as one
    all-or-nothing transaction (DP-003 + Sentinel 5870049314 HIGH-3).

    Order: snapshot the previous signoff/side-car bytes, RETIRE the previous
    signoff (unlink) so it can never be read as the new one, write the
    side-car, then write the signoff LAST — each atomically (temp +
    ``os.replace``). If any step fails, roll back to the exact previous pair
    (or to absence when there was none) and re-raise the original error.

    Outcomes therefore are exactly: the new signoff + its bound side-car, or
    the previous state unchanged. Never a valid-looking new signoff without
    its side-car, never a new side-car paired with the old signoff, never a
    torn file. If a rollback restore itself fails, that file is removed
    (absence is never treated as success by any consumer)."""
    _commit_signoff_pairs([(out, payload, side_car, compliance)])


def _commit_signoff_pairs(
    pairs: list[tuple[_Target, dict[str, Any], _Target | None, dict[str, Any] | None]],
) -> None:
    """DPN-012 — commit one or more ``(signoff, payload, side_car, compliance)``
    pairs as ONE all-or-nothing transaction (generalises
    :func:`_commit_signoff_pair`; a single pair behaves exactly as before).

    Order: snapshot every target's previous bytes, RETIRE every previous
    signoff (unlink), then for each pair in order write its side-car and then
    its signoff — each atomically. Callers list the plan-level pair LAST so
    the plan-level signoff is the final write. If any step fails, EVERY
    target (all signoffs and side-cars) is restored to its previous bytes (or
    absence) and the original error is re-raised.

    DPN-012b review round 2 — every step goes through the no-follow helper
    (targets are files in already-opened, checked directory fds): a symlink at
    any target is refused by the snapshot read BEFORE anything is retired, and
    re-checked right before each rename."""
    targets: list[_Target] = []
    for out, _payload, side_car, _compliance in pairs:
        targets.append(out)
        if side_car is not None:
            targets.append(side_car)
    previous = {t: _read_bytes_if_file(t) for t in targets}
    try:
        for out, _payload, _side_car, _compliance in pairs:
            if previous[out] is not None:
                _safe_unlink(out.dir_fd, out.name)
        for out, payload, side_car, compliance in pairs:
            if side_car is not None and compliance is not None:
                _atomic_write_json(side_car, compliance)
            _atomic_write_json(out, payload)
    except BaseException:
        for target in reversed(targets):
            _restore(target, previous[target])
        raise


def signoff_path(plan_dir: Path, plan_id: str) -> Path:
    return plan_dir / "audit" / f"signoff-{plan_id}.json"


def charter_compliance_path(plan_dir: Path, plan_id: str) -> Path:
    """Plan 2026-05-02-003 F002: side-car compliance file path. Lives next
    to the signoff envelope so operators see both artifacts together."""
    return plan_dir / "audit" / f"charter-compliance-{plan_id}.json"


# DPN-012 — per-feature durable signoff evidence. Lives in a SUBDIRECTORY of
# ``audit/`` so top-level ``audit/*.json`` scanners (e.g.
# ``closeout._audit_paths_for_feature``, which splits names on ``-``) never
# mistake it for an audit envelope.
FEATURE_SIGNOFF_DIRNAME = "feature-signoffs"
# Real feature ids are ``F<digits>``; no ``/``, no ``..`` and no ``-`` so the
# ``--`` separator in the per-feature file name stays unambiguous.
_FEATURE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.]*$")


def _require_feature_id(feature_id: Any) -> str:
    if (
        not isinstance(feature_id, str)
        or not _FEATURE_ID_RE.fullmatch(feature_id)
        or ".." in feature_id
    ):
        raise SignoffWriteError(
            f"invalid feature_id {feature_id!r} for per-feature signoff evidence "
            f"(must match {_FEATURE_ID_RE.pattern} with no '..')"
        )
    return feature_id


def feature_signoff_dir(plan_dir: Path) -> Path:
    return plan_dir / "audit" / FEATURE_SIGNOFF_DIRNAME


def feature_signoff_path(plan_dir: Path, plan_id: str, feature_id: str) -> Path:
    """DPN-012: per-feature signoff written alongside the plan-level one."""
    fid = _require_feature_id(feature_id)
    return feature_signoff_dir(plan_dir) / f"signoff-{plan_id}--{fid}.json"


def feature_charter_compliance_path(plan_dir: Path, plan_id: str, feature_id: str) -> Path:
    """DPN-012: per-feature child charter-compliance side-car."""
    fid = _require_feature_id(feature_id)
    return feature_signoff_dir(plan_dir) / f"charter-compliance-{plan_id}--{fid}.json"


def _require_real_feature_signoff_dir(plan_dir: Path) -> Path:
    """DPN-012b — return :func:`feature_signoff_dir` when it is absent or a
    real directory. A symlink there (to a directory or dangling) or any other
    non-directory (e.g. a stray regular file) raises
    :class:`SignoffWriteError`: evidence is never written or read through it.
    Review round 2: walks ``audit/`` and ``feature-signoffs/`` with the shared
    no-follow helper (:func:`_safe_open_dir`), so a symlinked ``audit/``
    parent is refused too."""
    d = feature_signoff_dir(plan_dir)
    try:
        fd = _safe_open_dir(plan_dir, "audit", FEATURE_SIGNOFF_DIRNAME)
    except FileNotFoundError:
        return d
    os.close(fd)
    return d


def _require_no_case_collision(plan_dir: Path, plan_id: str, feature_id: str) -> None:
    """DPN-012b — raise :class:`SignoffWriteError` when the per-feature
    directory holds an entry whose name casefolds equal to this feature's
    signoff or side-car name but is not identical to it (feature ids that
    differ only by case, e.g. ``F1`` / ``f1``, collide on a case-insensitive
    volume). Compares ``os.listdir`` names, so it behaves the same on
    case-sensitive and case-insensitive volumes. Lists the directory through
    the no-follow helper."""
    d = feature_signoff_dir(plan_dir)
    try:
        fd = _safe_open_dir(plan_dir, "audit", FEATURE_SIGNOFF_DIRNAME)
    except FileNotFoundError:
        return
    try:
        entries = os.listdir(fd)
    finally:
        os.close(fd)
    targets = {
        p.name.casefold(): p.name
        for p in (
            feature_signoff_path(plan_dir, plan_id, feature_id),
            feature_charter_compliance_path(plan_dir, plan_id, feature_id),
        )
    }
    for entry in sorted(entries):
        name = targets.get(entry.casefold())
        if name is not None and entry != name:
            raise SignoffWriteError(
                f"per-feature signoff evidence {entry!r} in {d} case-collides with "
                f"{name!r} for feature {feature_id!r}; feature ids that differ only "
                f"by case cannot hold separate evidence"
            )


class _EvidenceDirs:
    """DPN-012b review round 2 — the open, no-follow-checked directory chain
    ``plan_dir`` → ``audit`` (→ ``feature-signoffs``) a signoff write goes
    through. Existing components are opened (and checked) up front and HELD
    until the commit, so a link swapped in afterwards cannot redirect it;
    missing ones are created by :meth:`ensure` relative to the held parent
    fd. ``fds[0]`` is ``plan_dir``; ``fds[i]`` is ``components[i-1]``."""

    def __init__(self, plan_dir: Path, components: tuple[str, ...]) -> None:
        self._plan_dir = Path(plan_dir)
        self._components = components
        self._fds: list[int] = []
        self._created: set[int] = set()
        try:
            self._fds.append(os.open(self._plan_dir, _DIR_FLAGS))
            for depth in range(1, len(components) + 1):
                fd, _created = _open_child_dir(
                    self._fds[-1], components[depth - 1], self._path(depth), create=False
                )
                self._fds.append(fd)
        except FileNotFoundError:
            pass  # the rest is created by ensure()
        except BaseException:
            self.close()
            raise

    def _path(self, depth: int) -> Path:
        return self._plan_dir.joinpath(*self._components[:depth])

    def ensure(self, depth: int) -> int:
        """The fd of the component at ``depth``, creating missing ones."""
        if not self._fds:
            self._plan_dir.mkdir(parents=True, exist_ok=True)
            self._fds.append(os.open(self._plan_dir, _DIR_FLAGS))
        while len(self._fds) <= depth:
            d = len(self._fds)
            fd, created = _open_child_dir(
                self._fds[-1], self._components[d - 1], self._path(d), create=True
            )
            self._fds.append(fd)
            if created:
                self._created.add(d)
        return self._fds[depth]

    def target(self, depth: int, name: str) -> _Target:
        return _Target(self.ensure(depth), name, self._path(depth) / name)

    def remove_if_created(self, depth: int) -> None:
        """Best-effort ``rmdir`` (relative to the parent fd) of the component
        at ``depth`` when this transaction created it."""
        if depth in self._created and len(self._fds) > depth:
            with contextlib.suppress(OSError):
                os.rmdir(self._components[depth - 1], dir_fd=self._fds[depth - 1])

    def close(self) -> None:
        for fd in reversed(self._fds):
            with contextlib.suppress(OSError):
                os.close(fd)
        self._fds = []


def _write_signoff_in(
    dirs: _EvidenceDirs,
    *,
    plan_id: str,
    tier: str,
    iteration: int,
    agents_in_panel: list[str],
    audit_paths: list[Path],
    plan_dir: Path,
    volley_status: str,
    signoff_reason: str | None,
    child_charter: Any,
    commit_policy: Any,
    modified_files: list[str] | None,
    patch_completeness: dict[str, Any] | None,
    feature_id: str | None,
    plan_level: bool,
    decided_at: str | None,
) -> tuple[Path, dict[str, Any] | None]:
    """Body of :func:`write_signoff` once ``dirs`` holds the checked
    directory chain. Returns ``(path write_signoff returns, compliance)``."""
    if feature_id is not None:
        _require_no_case_collision(plan_dir, plan_id, feature_id)

    payload = build_signoff_dict(
        plan_id=plan_id,
        tier=tier,
        iteration=iteration,
        agents_in_panel=agents_in_panel,
        audit_paths=audit_paths,
        plan_dir=plan_dir,
        volley_status=volley_status,
        signoff_reason=signoff_reason,
        patch_completeness=patch_completeness,
        decided_at=decided_at,
    )

    compliance: dict[str, Any] | None = None
    if child_charter is not None and commit_policy is not None:
        # Late import to avoid a load-time cycle (nested_orchestration imports
        # nothing from signoff_writer, but plan_loader imports both).
        from dontpanic_orchestrate.nested_orchestration import (
            check_child_charter_compliance,
        )

        compliance = check_child_charter_compliance(
            plan_dir=plan_dir,
            child_charter=child_charter,
            commit_policy=commit_policy,
            signoff_data=payload,
            modified_files=modified_files,
        )

    out = signoff_path(plan_dir, plan_id)
    side_name = charter_compliance_path(plan_dir, plan_id).name
    dirs.ensure(1)
    if feature_id is None:
        _commit_signoff_pair(
            dirs.target(1, out.name),
            payload,
            dirs.target(1, side_name) if compliance is not None else None,
            compliance,
        )
        return out, compliance
    feature_out = feature_signoff_path(plan_dir, plan_id, feature_id)
    feature_side_name = feature_charter_compliance_path(plan_dir, plan_id, feature_id).name
    try:
        pairs: list[tuple[_Target, dict[str, Any], _Target | None, dict[str, Any] | None]] = [
            (
                dirs.target(2, feature_out.name),
                payload,
                dirs.target(2, feature_side_name) if compliance is not None else None,
                compliance,
            )
        ]
        if plan_level:
            # Plan-level pair LAST: its signoff is the transaction's final write.
            pairs.append(
                (
                    dirs.target(1, out.name),
                    payload,
                    dirs.target(1, side_name) if compliance is not None else None,
                    compliance,
                )
            )
        else:
            out = feature_out
        _commit_signoff_pairs(pairs)
    except BaseException:
        dirs.remove_if_created(2)
        raise
    return out, compliance


def write_signoff(
    *,
    plan_id: str,
    tier: str,
    iteration: int,
    agents_in_panel: list[str],
    audit_paths: list[Path],
    plan_dir: Path,
    volley_status: str,
    signoff_reason: str | None = None,
    child_charter: Any = None,
    commit_policy: Any = None,
    modified_files: list[str] | None = None,
    orchestration: Any = None,
    patch_completeness: dict[str, Any] | None = None,
    feature_id: str | None = None,
    plan_level: bool = True,
    decided_at: str | None = None,
) -> Path:
    """Build, validate, and write the signoff.json closeout. Returns the path.

    DPN-012 — per-feature evidence. When ``feature_id`` is given, the same
    payload (same bytes, same ``signoff_id``) and, for child plans, the same
    compliance side-car are ALSO written to
    :func:`feature_signoff_path` / :func:`feature_charter_compliance_path`,
    for every volley outcome (success and non-success), in one all-or-nothing
    transaction with the plan-level pair (any failure restores all four files
    to their previous bytes or absence). ``plan_level=False`` (requires
    ``feature_id``) writes ONLY the per-feature pair and never touches the
    plan-level pair; the returned path is then the per-feature signoff. With
    ``feature_id=None`` behaviour is byte-for-byte unchanged (the plan-level
    pair only; ``audit/feature-signoffs/`` is never opened, created or
    checked, so a stray file or symlink there does not affect it), except
    that a symlink on the plan-level path is refused (below). An invalid
    ``feature_id`` raises :class:`SignoffWriteError` before anything is
    written.

    DPN-012b review round 2 — every evidence file is read, retired, written
    and restored relative to directory fds opened no-follow below
    ``plan_dir`` (``audit/``, and for a per-feature write
    ``audit/feature-signoffs/``). A symlink (or non-directory) at any of those
    components, or a symlink at any signoff / side-car file being replaced,
    raises :class:`SignoffWriteError` and nothing is written outside the
    plan tree — including when a link is swapped in after the check.

    Plan 2026-05-02-003 F002: when both ``child_charter`` and ``commit_policy``
    are passed, runs ``check_child_charter_compliance`` BEFORE persisting any
    artifact. On ``ChildCharterViolation`` neither the signoff envelope nor
    the side-car compliance file is written (no-partial-artifact, mirrors
    plan 005 F002 acceptance #5). On compliance pass, writes the side-car
    file at ``audit/charter-compliance-{plan_id}.json`` recording the parsed
    return-condition status + satisfied requires items.

    The Signoff schema (agent-conventions v1.0) is unchanged — compliance
    output lives in the side-car, matching F001's pop-orchestration-block
    schema-discipline pattern (D006-style).
    """
    if feature_id is not None:
        _require_feature_id(feature_id)
    elif not plan_level:
        raise SignoffWriteError("plan_level=False requires a feature_id")
    # DPN-012b — refuse before ANY write when a directory on the evidence path
    # (``audit/``, and for a per-feature write ``audit/feature-signoffs/``) is
    # a symlink / non-directory, or (per-feature) when another feature id's
    # evidence case-collides with this one. The checked directories stay open
    # and every read / write / retire below is relative to them (review
    # round 2). A plan-level-only write never opens or touches
    # ``feature-signoffs/``.
    components: tuple[str, ...] = ("audit",)
    if feature_id is not None:
        components = ("audit", FEATURE_SIGNOFF_DIRNAME)
    dirs = _EvidenceDirs(plan_dir, components)
    try:
        out, compliance = _write_signoff_in(
            dirs,
            plan_id=plan_id,
            tier=tier,
            iteration=iteration,
            agents_in_panel=agents_in_panel,
            audit_paths=audit_paths,
            plan_dir=plan_dir,
            volley_status=volley_status,
            signoff_reason=signoff_reason,
            child_charter=child_charter,
            commit_policy=commit_policy,
            modified_files=modified_files,
            patch_completeness=patch_completeness,
            feature_id=feature_id,
            plan_level=plan_level,
            decided_at=decided_at,
        )
    finally:
        dirs.close()

    # Plan 2026-05-02-003 F003: when this signoff is for a child plan,
    # record a best-effort volley.return_to_parent trace on the child's
    # events.jsonl. Parent reads its own trace + the child's compliance
    # side-car when operator invokes `approve pre_resume_after_child`.
    # NEVER raises (D006 — events.jsonl is best-effort).
    if orchestration is not None and getattr(orchestration, "parent_plan_id", None):
        from dontpanic_orchestrate.nested_orchestration import record_event

        return_status = compliance.get("return_condition_status") if compliance else None
        record_event(
            plan_dir,
            kind="volley.return_to_parent",
            payload={
                "child_plan_id": plan_id,
                "parent_plan_id": orchestration.parent_plan_id,
                "child_final_status": volley_status,
                "return_condition_status": return_status,
            },
            plan_id=plan_id,
        )

    return out


__all__ = [
    "SignoffWriteError",
    "VALID_TIERS",
    "build_signoff_dict",
    "FEATURE_SIGNOFF_DIRNAME",
    "charter_compliance_path",
    "feature_charter_compliance_path",
    "feature_signoff_dir",
    "feature_signoff_path",
    "safe_unlink_evidence",
    "safe_write_evidence_text",
    "signoff_path",
    "write_signoff",
]
