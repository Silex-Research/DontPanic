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

import contextlib
import datetime
import fcntl
import hashlib
import logging
import os
import signal
import subprocess
import threading
from collections.abc import Iterator, Mapping, Sequence
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


# ──────────────────────────────  canonical repo (C2/C3)  ──────────────────────────────

# A path under any of these prefixes is EPHEMERAL: it is never stamped as a
# `canonical_repo` and is never self-canonicalized (C3). macOS realpaths land
# under ``/private/...`` so we also strip a leading ``/private`` when testing.
_TEMP_PREFIXES = ("/tmp", "/private/tmp", "/var/folders")


def _is_temp_path(path: str | Path) -> bool:
    """True iff ``path`` resolves under a temp prefix (``/tmp``, ``/private/tmp``,
    ``/var/folders``). Tests the literal absolute path, its realpath, and the
    ``/private``-stripped form so macOS realpath variants are caught."""
    raw = os.path.abspath(os.path.expanduser(str(path)))
    candidates = {raw}
    try:
        candidates.add(os.path.realpath(raw))
    except OSError:
        pass
    for cand in list(candidates):
        if cand.startswith("/private/"):
            candidates.add(cand[len("/private") :])
    for cand in candidates:
        for prefix in _TEMP_PREFIXES:
            if cand == prefix or cand.startswith(prefix + "/"):
                return True
    return False


def _run_git(root: str | Path, *args: str) -> str | None:
    """Single git probe. Returns trimmed stdout, or ``None`` on any failure
    (non-zero exit, git missing). NEVER raises."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True
        )
    except (OSError, ValueError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _normalize_origin(url: str) -> str:
    """Normalize an origin URL for stable hashing: trim, drop a trailing slash
    and a ``.git`` suffix. The result is ONLY ever hashed, never persisted."""
    norm = url.strip().rstrip("/")
    if norm.endswith(".git"):
        norm = norm[:-4]
    return norm


def _origin_key(url: str | None) -> str | None:
    """Stable non-secret 16-hex hash of the normalized origin URL (C1). Returns
    ``None`` for an empty/blank URL. The raw URL is NEVER stored."""
    if not url:
        return None
    norm = _normalize_origin(url)
    if not norm:
        return None
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def canonicalize_repo(observed_root: str | Path) -> dict[str, Any]:
    """Resolve the durable canonical repo for ``observed_root`` (C3 three-case rule).

    Pinned algorithm: a single ``git -C <root> rev-parse --path-format=absolute
    --git-common-dir`` probe. The returned common-dir points at the MAIN
    worktree's git dir for both a main checkout and a linked worktree, so the
    canonical root is the parent of that common-dir when it ends in ``/.git`` —
    this collapses linked worktrees onto their main checkout. A bare repo (no
    ``.git`` suffix) or a non-git dir is treated as unresolved.

    Returns ``{canonical_root, origin_url, durable_checkout}``:

    * **C3-1 durable+git** — observed not temp, git resolves a durable root ->
      ``canonical_root`` = that root, ``durable_checkout=True``.
    * **C3-2 durable+non-git** — observed not temp, git does not resolve ->
      ``canonical_root`` = self (observed root), ``durable_checkout=True``.
    * **C3-3a temp->durable** — observed temp, git resolves a *durable* root ->
      ``canonical_root`` = that durable root, ``durable_checkout=True``.
    * **C3-3b unresolved/temp** — observed temp and resolution fails OR the
      resolved root is itself temp -> ``canonical_root=None`` (no stamp). A temp
      path is never self-canonicalized.
    """
    observed = os.path.abspath(os.path.expanduser(str(observed_root)))
    observed_temp = _is_temp_path(observed)

    common = _run_git(observed, "rev-parse", "--path-format=absolute", "--git-common-dir")
    resolved_root: str | None = None
    if common:
        common_norm = common.rstrip("/")
        if common_norm.endswith("/.git"):
            resolved_root = os.path.dirname(common_norm)
        # else: bare repo / no working tree -> unresolved (resolved_root stays None)

    if resolved_root is not None:
        if _is_temp_path(resolved_root):
            # C3-3b: canonical root is itself temp -> stamp nothing.
            return {"canonical_root": None, "origin_url": None, "durable_checkout": False}
        # C3-1 (durable observed) or C3-3a (temp observed -> durable canonical).
        origin = _run_git(observed, "remote", "get-url", "origin")
        return {
            "canonical_root": resolved_root,
            "origin_url": origin or None,
            "durable_checkout": True,
        }

    # git did not resolve a durable root.
    if observed_temp:
        # C3-3b: temp observed + unresolved -> stamp nothing.
        return {"canonical_root": None, "origin_url": None, "durable_checkout": False}
    # C3-2: durable + non-git -> self-canonical.
    return {"canonical_root": observed, "origin_url": None, "durable_checkout": True}


def _stamp_canonical_repo(observed_root: str | Path) -> dict[str, Any] | None:
    """Build the persisted ``canonical_repo`` dict for ``observed_root``, or
    ``None`` when no durable canonical exists (C3 case 3b). NEVER raises — a
    canonicalization failure simply omits the field, the record is still written.

    The persisted shape is ``{path_key, path_display, durable_checkout,
    origin_key?, observed_under_temp_prefix?}``. Only the hashed ``origin_key`` is
    stored, never the raw origin URL (C1); ``path_display`` is the home-scrubbed
    string from :func:`make_path_pair`, never a raw home path (C1)."""
    try:
        result = canonicalize_repo(observed_root)
    except Exception as exc:  # noqa: BLE001 — never break the record over canonicalization
        _LOG.warning("canonical repo resolution failed: %s", exc)
        return None
    canonical_root = result.get("canonical_root")
    if canonical_root is None:
        return None
    pair = make_path_pair(canonical_root)
    if pair is None:
        return None
    canonical: dict[str, Any] = dict(pair)
    canonical["durable_checkout"] = bool(result.get("durable_checkout"))
    origin_key = _origin_key(result.get("origin_url"))
    if origin_key:
        canonical["origin_key"] = origin_key
    if _is_temp_path(observed_root):
        # C3 case 3a: durable canonical reached from a temp observed worktree.
        canonical["observed_under_temp_prefix"] = True
    return canonical


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


# ──────────────────────────────  C8 sidecar lock  ──────────────────────────────
#
# Every writer of the ledger coordinates through ONE dedicated sidecar lock file
# (`<ledger>.lock`), never a lock on the data-file inode. Locking the sidecar (not
# the data inode) is what makes the whole-file rewrites (compaction, backfill)
# safe: a writer can never open the old inode before a rewriter's atomic rename
# and then write to the orphaned inode after replacement, because it must hold the
# sidecar lock to open at all, and the rewriter holds that same lock across its
# rename. The three writers ALL fail closed over the lock — none ever touches the
# data file without the sidecar held: the live append path raises
# :class:`LedgerLockUnavailable` (so the data file is never opened unlocked; the
# caller's fail-open ``finalize`` wrapper still keeps the command non-fatal) and
# the two whole-file rewriters (compaction here, backfill in F005) raise
# ``SystemExit(2)`` if flock is unavailable rather than perform an uncoordinated
# rename.


class LedgerLockUnavailable(OSError):
    """Raised by the live append path when the C8 sidecar lock cannot be acquired.

    Subclasses :class:`OSError` so the live writer's fail-open ``finalize``
    wrapper (``except Exception``) catches it and the command is never broken —
    but, because we raise BEFORE opening the data file, no unlocked append ever
    occurs (the C8 guarantee holds for the append path too)."""


def _sidecar_lock_path(target: Path) -> Path:
    return target.with_name(target.name + ".lock")


@contextlib.contextmanager
def _append_sidecar_lock(target: Path) -> Iterator[None]:
    """Exclusive sidecar lock for the live append path. FAIL-CLOSED at the lock:
    if flock is unavailable we raise :class:`LedgerLockUnavailable` BEFORE the
    caller opens the data file, so a write never proceeds without the sidecar
    held (C8). The live writer stays non-fatal because ``finalize`` wraps the
    append in ``except Exception`` — a lock hiccup drops this one record but
    never changes the command's exit code."""
    lock_path = _sidecar_lock_path(target)
    fh = None
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(lock_path, "a+", encoding="utf-8")  # noqa: SIM115 — released in finally
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    except (OSError, AttributeError) as exc:
        if fh is not None:
            fh.close()
        raise LedgerLockUnavailable(
            f"C8 sidecar lock unavailable for {lock_path}; refusing unlocked append"
        ) from exc
    try:
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


@contextlib.contextmanager
def _rewriter_sidecar_lock(target: Path) -> Iterator[None]:
    """Exclusive sidecar lock for a whole-file rewriter (compaction / backfill),
    held across the full read+rewrite+temp-file+rename sequence. FAIL CLOSED:
    if flock is unavailable, raise ``SystemExit(2)`` rather than perform an
    uncoordinated rename that could strand a stale inode or lose a write."""
    lock_path = _sidecar_lock_path(target)
    fh = None
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(lock_path, "a+", encoding="utf-8")  # noqa: SIM115 — released in finally
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    except (OSError, AttributeError) as exc:
        if fh is not None:
            fh.close()
        raise SystemExit(2) from exc
    try:
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


# ──────────────────────────────  atomic append  ──────────────────────────────


def _atomic_append_line(path: Path, line: str) -> None:
    """Append one line under the C8 sidecar lock (concurrency-safe). The sidecar
    lock is acquired BEFORE opening the data file and released after the append,
    so a concurrent rewriter's atomic rename can never strand this writer on an
    orphaned inode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _append_sidecar_lock(path):
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())


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
        # C2/C3: stamp the durable canonical repo identity alongside the observed
        # `repo`. `repo.path_key` is untouched (it remains observation identity and
        # still drives bucket/conflict/locality logic). When resolution fails from a
        # temp path (C3 case 3b), no canonical_repo is stamped — the field is absent,
        # never a temp canonical.
        canonical_repo = _stamp_canonical_repo(repo_root)
        if canonical_repo is not None:
            base["canonical_repo"] = canonical_repo
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


def _record_observed_count(record: Mapping[str, Any]) -> int:
    """Observation count contributed by ``record``. Legacy/no-field rows count as
    ``1``; rows carrying a valid non-negative ``observed_count`` int use it (so
    sums stay correct across re-compaction)."""
    value = record.get("observed_count")
    if isinstance(value, bool):  # bool is an int subclass — treat as legacy
        return 1
    if isinstance(value, int) and value >= 0:
        return value
    return 1


def _record_canonical_key(record: Mapping[str, Any]) -> str | None:
    """The canonical_repo path_key for ``record``, or ``None`` if the record
    carries no (valid) ``canonical_repo``."""
    canonical = record.get("canonical_repo")
    if isinstance(canonical, Mapping):
        key = canonical.get("path_key")
        if isinstance(key, str) and key:
            return key
    return None


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
    # C8: a whole-file rewrite ending in a rename — hold the sidecar lock across
    # the full read+rewrite+temp-file+rename so a concurrent append or backfill
    # rename can never strand a stale inode or lose a write. flock-unavailable ->
    # fail closed (SystemExit 2), raised by _rewriter_sidecar_lock.
    with _rewriter_sidecar_lock(target):
        try:
            if not target.exists():
                return {"records_before": 0, "records_after": 0, "buckets": 0}
            records = [json.loads(line) for line in target.read_text().splitlines() if line.strip()]
            before = len(records)
            # Group every record by bucket so we can both pick the most-recent
            # preserved row AND fold observed_count + canonical attribution across
            # the whole bucket (C2).
            grouped: dict[str, list[dict[str, Any]]] = {}
            order: list[str] = []
            for r in records:
                key = _bucket_key(r)
                if key not in grouped:
                    grouped[key] = []
                    order.append(key)
                grouped[key].append(r)

            collapsed: dict[str, dict[str, Any]] = {}
            for key in order:
                collapsed[key] = _collapse_bucket(grouped[key])

            kept = sorted(collapsed.values(), key=lambda r: str(r.get("last_seen")))
            if len(kept) > max_records:
                kept = kept[len(kept) - max_records :]  # keep newest buckets
            tmp = target.with_suffix(target.suffix + ".compact.tmp")
            tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in kept))
            os.replace(tmp, target)
            return {"records_before": before, "records_after": len(kept), "buckets": len(collapsed)}
        except Exception as exc:  # noqa: BLE001 — FAIL-OPEN (lock errors fail closed above)
            _LOG.warning("invocation ledger compaction failed: %s", exc)
            return {"records_before": 0, "records_after": 0, "buckets": 0, "error": str(exc)}


def _collapse_bucket(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Collapse one bucket's duplicate observations into a single preserved row.

    The preserved row is the most-recent observation (by ``last_seen``), with the
    bucket-summed ``observed_count`` stamped on it (C2). Canonical attribution
    (C2 fail-closed):

    * all rows share one ``canonical_repo.path_key`` (and none lack it) -> keep
      that ``canonical_repo`` and the summed ``observed_count``;
    * no row carries a ``canonical_repo`` -> no canonical fields, but the summed
      ``observed_count`` is still carried (honest observed bucket);
    * mixed attribution (some rows canonical, some not) OR multiple distinct
      canonical keys -> CONFLICT: omit ``canonical_repo``, set
      ``canonical_compaction_conflict=true``, and carry NO ``observed_count`` so
      discovery neither inflates nor silently drops a canonical count.
    """
    preserved = dict(rows[0])
    for r in rows[1:]:
        if str(r.get("last_seen")) >= str(preserved.get("last_seen")):
            preserved = dict(r)

    total = sum(_record_observed_count(r) for r in rows)
    canonical_keys = {k for r in rows if (k := _record_canonical_key(r)) is not None}
    has_noncanonical = any(_record_canonical_key(r) is None for r in rows)

    # Start from a clean slate for the canonical/observed-count fields; the
    # preserved raw row may carry stale values from a prior compaction.
    preserved.pop("canonical_repo", None)
    preserved.pop("canonical_compaction_conflict", None)
    preserved.pop("observed_count", None)

    if len(canonical_keys) >= 2 or (canonical_keys and has_noncanonical):
        # Mixed attribution — fail closed.
        preserved["canonical_compaction_conflict"] = True
        return preserved

    if len(canonical_keys) == 1:
        # Uniform canonical attribution — keep the preserved row's canonical_repo
        # (it shares the single key) and the summed count.
        the_key = next(iter(canonical_keys))
        canonical = next(
            (r.get("canonical_repo") for r in rows if _record_canonical_key(r) == the_key),
            None,
        )
        if isinstance(canonical, Mapping):
            preserved["canonical_repo"] = dict(canonical)
    preserved["observed_count"] = total
    return preserved


__all__ = [
    "InvocationRecord",
    "InvocationRecorder",
    "LEDGER_FILENAME",
    "RESULT_ERROR",
    "RESULT_INTERRUPTED",
    "RESULT_OK",
    "canonicalize_repo",
    "compact_ledger",
    "derive_buckets",
    "ledger_path",
    "make_path_pair",
    "redact_command",
    "start_recording",
]
