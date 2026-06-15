"""Plan 2026-06-14-001 F003 — sanitized, concurrency-safe invocation presence ledger.

Records every DontPanic CLI invocation as one line in
``<dontpanic_home>/invocations.jsonl``. Each record carries the four-axis
:class:`~dontpanic_orchestrate.invocation_context.InvocationContext` (F001) plus
repo/worktree/branch/plan, the (redacted) command, timing, result, and locality —
the runtime fact source the channel doctor (F007) and channel-view (F009/F010)
derive presence/active/stale/conflict from.

Hardened for many simultaneous agents:

* **Exactly one record per invocation.** A single seam in ``cli.main`` starts a
  recorder and finalizes it in a ``finally`` block, so a well-formed record is
  written under normal return, ``result=error`` for a failing command, argparse
  ``SystemExit``, early import/config failure, ``KeyboardInterrupt``
  (``result=interrupted``), and SIGTERM-style interruption (best-effort signal
  handler). ``finalize`` is idempotent (lock + flag), so the finally path and the
  signal path can both fire yet write only once. Every write is FAIL-OPEN — a
  ledger error never changes the command's exit code.
* **Sanitized paths (D013).** Every path field is a PAIR: ``path_display``
  (home-scrubbed for UI/evidence via the shared sanitizer) and ``path_key`` (a
  stable, non-secret canonical hash for equality + conflict detection). The
  scrubbed display string is NEVER used as the equality key.
* **Redaction.** The command string runs through the single-source secret
  scrubber before storage.
* **Atomic appends.** Appends take an exclusive ``flock`` so N concurrent writers
  yield N intact lines.
* **Retention.** :func:`compact_ledger` bounds the ledger by collapsing
  within-bucket duplicates to the most-recent observation, preserving exactly the
  fields :func:`derive_buckets` (and thus F009/F010) need — so a compacted ledger
  yields the same buckets as the pre-compaction ledger.
"""

from __future__ import annotations

import datetime
import fcntl
import hashlib
import logging
import os
import signal
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import global_config
from dontpanic_orchestrate.completion_dispatch import sanitize_capture
from dontpanic_orchestrate.invocation_context import InvocationContext
from dontpanic_orchestrate.resolve_context import resolve_context
from dontpanic_orchestrate.state_projection import scrub_secrets

_LOG = logging.getLogger(__name__)

LEDGER_FILENAME = "invocations.jsonl"

RESULT_OK = "ok"
RESULT_ERROR = "error"
RESULT_INTERRUPTED = "interrupted"

# Argument names whose VALUE should be dropped entirely (defence in depth on top
# of the regex scrubber, which only catches recognizably token-shaped strings).
_SECRET_FLAGS = frozenset({"--secret", "--token", "--password", "--api-key", "--apikey"})

_WORKTREE_SEGMENT = ".dontpanic/worktrees"


def ledger_path() -> Path:
    """Path to the invocation ledger (honors ``$DONTPANIC_HOME`` via global_config)."""
    return global_config.dontpanic_home() / LEDGER_FILENAME


# ──────────────────────────────  path pair (D013)  ──────────────────────────────


def make_path_pair(real_path: str | Path | None) -> dict[str, str] | None:
    """Return ``{path_display, path_key}`` for ``real_path`` (``None`` -> ``None``).

    ``path_display`` is home-scrubbed for UI/evidence; ``path_key`` is a stable
    non-secret hash of the real absolute path — equality/conflict key that is
    NEVER the scrubbed display string."""
    if real_path is None:
        return None
    raw = str(real_path)
    abs_raw = os.path.abspath(os.path.expanduser(raw))
    display = sanitize_capture(raw) or raw
    key = hashlib.sha256(abs_raw.encode("utf-8")).hexdigest()[:16]
    return {"path_display": display, "path_key": key}


# ──────────────────────────────  redaction  ──────────────────────────────


def redact_command(argv: Sequence[str]) -> str:
    """Join ``argv`` into a single command string with secrets redacted: the value
    after a known secret flag is dropped, and the whole string is run through the
    single-source secret scrubber (``state_projection.scrub_secrets``)."""
    parts: list[str] = []
    drop_next = False
    for tok in argv:
        if drop_next:
            parts.append("[REDACTED]")
            drop_next = False
            continue
        if tok in _SECRET_FLAGS:
            parts.append(tok)
            drop_next = True
            continue
        parts.append(tok)
    joined = " ".join(parts)
    return scrub_secrets(joined) or joined


# ──────────────────────────────  record  ──────────────────────────────


@dataclass(frozen=True)
class InvocationRecord:
    """One ledger line: four-axis context + locale + command + timing + result."""

    operator_surface: str
    agent_runtime: str
    role: str
    execution_locality: str
    repo: dict[str, str] | None
    worktree: dict[str, str] | None
    branch: str | None
    plan: str | None
    command: str
    started_at: str
    finished_at: str
    last_seen: str
    result: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator_surface": self.operator_surface,
            "agent_runtime": self.agent_runtime,
            "role": self.role,
            "execution_locality": self.execution_locality,
            "repo": self.repo,
            "worktree": self.worktree,
            "branch": self.branch,
            "plan": self.plan,
            "command": self.command,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "last_seen": self.last_seen,
            "result": self.result,
            "locality": self.execution_locality,
        }


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


# ──────────────────────────────  atomic append  ──────────────────────────────


def _atomic_append_line(path: Path, line: str) -> None:
    """Append one line under an exclusive advisory lock (concurrency-safe)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


# ──────────────────────────────  context resolution helpers  ──────────────────────────────


def _detect_repo_root(cwd: Path) -> Path:
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".git").exists():
            return candidate
    return cwd


def _detect_branch(repo_root: Path) -> str | None:
    """Cheap, subprocess-free branch read from .git/HEAD (handles worktree .git file)."""
    try:
        git = repo_root / ".git"
        head_file: Path
        if git.is_dir():
            head_file = git / "HEAD"
        elif git.is_file():
            # worktree: .git is a file 'gitdir: <path>'; HEAD lives in that dir
            gitdir = git.read_text().strip()
            if gitdir.startswith("gitdir:"):
                head_file = Path(gitdir.split(":", 1)[1].strip()) / "HEAD"
            else:
                return None
        else:
            return None
        head = head_file.read_text().strip()
        if head.startswith("ref:"):
            return head.split("/", 2)[-1]
        return head[:12] if head else None
    except Exception:  # noqa: BLE001 — best-effort, never break the command
        return None


def _detect_plan(argv: Sequence[str]) -> str | None:
    """Best-effort plan id sniff: the first arg that looks like a plan slug/dir."""
    for tok in argv:
        name = Path(tok).name if ("/" in tok) else tok
        if len(name) >= 12 and name[:4].isdigit() and name[4] == "-":
            return name
    return None


# ──────────────────────────────  recorder  ──────────────────────────────


class InvocationRecorder:
    """Captured-at-start recorder that writes EXACTLY ONE ledger line on finalize.

    ``finalize`` is idempotent and fail-open. A best-effort SIGTERM handler routes
    a kill into an ``interrupted`` finalize."""

    def __init__(self, *, record_base: dict[str, Any], started_at: str) -> None:
        self._base = record_base
        self._started_at = started_at
        self._lock = threading.Lock()
        self._finalized = False
        self._prev_sigterm: Any = None

    def install_sigterm(self) -> None:
        try:
            self._prev_sigterm = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGTERM, self._on_sigterm)
        except (ValueError, OSError):  # not main thread / unsupported — best-effort
            self._prev_sigterm = None

    def _on_sigterm(self, _signum: int, _frame: Any) -> None:
        self.finalize(RESULT_INTERRUPTED)
        raise SystemExit(143)

    def finalize(self, result: str, *, now: str | None = None) -> None:
        with self._lock:
            if self._finalized:
                return
            self._finalized = True
        # restore the previous SIGTERM disposition (outside the write so a failed
        # write still un-hooks us)
        if self._prev_sigterm is not None:
            try:
                signal.signal(signal.SIGTERM, self._prev_sigterm)
            except (ValueError, OSError):
                pass
            self._prev_sigterm = None
        try:
            stamp = now or _now_iso()
            record = dict(self._base)
            record["started_at"] = self._started_at
            record["finished_at"] = stamp
            record["last_seen"] = stamp
            record["result"] = result
            _atomic_append_line(ledger_path(), _dump_json(record))
        except Exception as exc:  # noqa: BLE001 — FAIL-OPEN: never break the command
            _LOG.warning("invocation ledger write failed: %s", exc)


class _NullRecorder:
    """Returned when start-of-record bootstrapping itself fails; no-op finalize."""

    def finalize(self, result: str, *, now: str | None = None) -> None:  # noqa: D401
        return


def _dump_json(record: Mapping[str, Any]) -> str:
    import json

    return json.dumps(record, sort_keys=True)


def start_recording(
    argv: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    now: str | None = None,
    install_signal: bool = True,
) -> InvocationRecorder | _NullRecorder:
    """Begin recording an invocation. NEVER raises — on any bootstrapping error it
    returns a no-op recorder so the command runs unaffected."""
    try:
        environ = dict(os.environ if env is None else env)
        cwd = Path.cwd()
        repo_root = _detect_repo_root(cwd)
        plan = _detect_plan(argv)
        ctx: InvocationContext = resolve_context(environ, repo=repo_root, plan=plan)
        is_worktree = _WORKTREE_SEGMENT in str(repo_root).replace("\\", "/")
        base = {
            "operator_surface": ctx.operator_surface.value,
            "agent_runtime": ctx.agent_runtime,
            "role": ctx.role,
            "execution_locality": ctx.execution_locality.value,
            "locality": ctx.execution_locality.value,
            "repo": make_path_pair(repo_root),
            "worktree": make_path_pair(repo_root) if is_worktree else None,
            "branch": _detect_branch(repo_root),
            "plan": plan,
            "command": redact_command(list(argv)),
        }
        recorder = InvocationRecorder(record_base=base, started_at=now or _now_iso())
        if install_signal:
            recorder.install_sigterm()
        return recorder
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        _LOG.warning("invocation ledger bootstrap failed: %s", exc)
        return _NullRecorder()


# ──────────────────────────────  buckets + compaction  ──────────────────────────────

# The dimensions F009/F010 derive active/stale/conflict from. Compaction must
# preserve these exactly.
_BUCKET_KEY_FIELDS = ("branch", "plan", "locality")


def _record_path_key(record: Mapping[str, Any]) -> str:
    repo = record.get("repo")
    if isinstance(repo, Mapping):
        return str(repo.get("path_key", ""))
    return ""


def _bucket_key(record: Mapping[str, Any]) -> str:
    parts = [_record_path_key(record)]
    parts.extend(str(record.get(f)) for f in _BUCKET_KEY_FIELDS)
    return "|".join(parts)


def derive_buckets(records: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map each presence bucket -> the latest observation's preserved fields. This
    is the contract F009/F010 reproduce; compaction must leave it invariant."""
    out: dict[str, dict[str, Any]] = {}
    for r in records:
        key = _bucket_key(r)
        summary = {
            "path_key": _record_path_key(r),
            "branch": r.get("branch"),
            "plan": r.get("plan"),
            "locality": r.get("locality"),
            "last_seen": r.get("last_seen"),
            "result": r.get("result"),
        }
        prev = out.get(key)
        if prev is None or str(summary["last_seen"]) >= str(prev["last_seen"]):
            out[key] = summary
    return out


def compact_ledger(path: Path | None = None, *, max_records: int, now: str | None = None) -> dict[str, Any]:
    """Collapse within-bucket duplicates to the most-recent observation and bound
    the ledger to ``max_records`` (keeping the newest buckets). Preserves the
    bucket fields F009/F010 need WITHOUT rereading deleted raw records. Returns a
    summary; FAIL-OPEN on error (leaves the ledger untouched)."""
    import json

    target = path or ledger_path()
    try:
        if not target.exists():
            return {"records_before": 0, "records_after": 0, "buckets": 0}
        records = [json.loads(line) for line in target.read_text().splitlines() if line.strip()]
        before = len(records)
        latest: dict[str, dict[str, Any]] = {}
        for r in records:
            key = _bucket_key(r)
            prev = latest.get(key)
            if prev is None or str(r.get("last_seen")) >= str(prev.get("last_seen")):
                latest[key] = r
        kept = sorted(latest.values(), key=lambda r: str(r.get("last_seen")))
        if len(kept) > max_records:
            kept = kept[len(kept) - max_records :]  # keep newest buckets
        tmp = target.with_suffix(target.suffix + ".compact.tmp")
        tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in kept))
        os.replace(tmp, target)
        return {"records_before": before, "records_after": len(kept), "buckets": len(latest)}
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        _LOG.warning("invocation ledger compaction failed: %s", exc)
        return {"records_before": 0, "records_after": 0, "buckets": 0, "error": str(exc)}


__all__ = [
    "InvocationRecord",
    "InvocationRecorder",
    "LEDGER_FILENAME",
    "RESULT_ERROR",
    "RESULT_INTERRUPTED",
    "RESULT_OK",
    "compact_ledger",
    "derive_buckets",
    "ledger_path",
    "make_path_pair",
    "redact_command",
    "start_recording",
]
