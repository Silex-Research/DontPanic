"""Plan 2026-05-09-004 F002 — DontPanic → Firestore sync daemon.

The polling bridge that converts the state-projection envelope from
plan 2026-05-09-003 (`dontpanic state snapshot --json`) into Firestore
docs under the single-tenant `projects/{project_id}/<stream>` shape
(plan D002).

Adapter boundary (plan D001): this module never imports
`dontpanic_orchestrate.*`. The projection is consumed via subprocess
to `dontpanic state snapshot --json --compact` (or via an injected
`SnapshotSource` callable in tests). State changes always flow the
other way through MCP (plan D003) — this daemon is one-way, read-only
on the DontPanic side.

Idempotency (acceptance #2): each call to `sync_once()` rehashes the
incoming snapshot per-doc and writes only docs whose payload hash
diverged from the in-process `last_written` cache. Re-running the
same snapshot against the same engine produces zero writes.

Include filtering (acceptance #3): `--include` is forwarded verbatim
to the projection CLI. The engine ALSO tracks "owned streams" — when
`--include` is set, the engine only diffs / writes / deletes within
those streams. Streams outside the include list are left untouched
on Firestore so toggling `--include` doesn't catastrophically wipe
collections the operator left behind.

Failure handling (acceptance #4): per-doc set/delete errors are
logged and counted; the daemon keeps going. The failed doc stays out
of `last_written` so a subsequent sync retries it.

Real-Firestore latency measurement (acceptance #5) is deferred to
F005 per parent_acceptance_item credential gate (plan D007).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

# Mirrors state_projection.ALL_STREAMS — kept literal so the adapter
# does not import dontpanic_orchestrate (D001 boundary).
ALL_STREAMS: tuple[str, ...] = (
    "plans",
    "gates",
    "inbox",
    "supervisors",
    "quota",
    "decisions",
    "evidence_refs",
)


# ─────────────────── doc-id strategy ───────────────────


def _doc_id_for(stream: str, item: dict[str, Any]) -> str:
    """Deterministic per-stream document id.

    Same-shaped item → same doc id across runs (idempotency). The
    id MUST be a valid Firestore document id (no `/`, ≤ 1500 bytes).
    We sanitize `/` to `__` defensively for any stream whose natural
    key may contain a path-style separator.
    """
    if stream == "plans":
        return _sanitize(item["plan_id"])
    if stream == "gates":
        return _sanitize(f'{item["plan_id"]}__{item["gate_name"]}')
    if stream == "inbox":
        return _sanitize(item["event_id"])
    if stream == "supervisors":
        return _sanitize(item["supervisor_id"])
    if stream == "quota":
        return _sanitize(f'{item["vendor"]}__{item["window"]}')
    if stream == "decisions":
        return _sanitize(f'{item["plan_id"]}__{item["decision_id"]}')
    if stream == "evidence_refs":
        # No natural uniqueness key — hash a stable tuple of the
        # identifying fields. Falls back to "_" for optional fields so
        # the digest is comparable across runs.
        key = json.dumps(
            [
                item.get("plan_id"),
                item.get("feature_id"),
                item.get("type"),
                item.get("uri"),
            ],
            sort_keys=True,
        )
        digest = hashlib.sha1(  # noqa: S324 — dedup key, not crypto
            key.encode("utf-8"), usedforsecurity=False
        ).hexdigest()[:16]
        plan = _sanitize(item.get("plan_id") or "_")
        feat = _sanitize(item.get("feature_id") or "_")
        return f"{plan}__{feat}__{digest}"
    raise KeyError(f"unknown stream: {stream!r}")


def _sanitize(s: str) -> str:
    # Firestore doc ids must not contain '/' and cannot be empty / "." / "..".
    out = s.replace("/", "__")
    if out in ("", ".", ".."):
        out = "_" + out
    return out[:1400]


def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha1(  # noqa: S324 — diff-cache key, not crypto
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()


# ─────────────────── snapshot sources ───────────────────


SnapshotSource = Callable[[], dict[str, Any]]


def fetch_snapshot_via_cli(
    *,
    plans_root: Path | None = None,
    include: Iterable[str] | None = None,
    plan_id: str | None = None,
    redact_level: str = "operator",
    dontpanic_cmd: tuple[str, ...] = ("dontpanic", "state", "snapshot"),
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """Shell out to `dontpanic state snapshot --json --compact` and
    return the parsed envelope. The adapter only knows about the JSON
    contract — never imports state_projection.
    """
    argv: list[str] = list(dontpanic_cmd) + ["--json", "--compact"]
    if plans_root is not None:
        argv += ["--plans-root", str(plans_root)]
    if plan_id is not None:
        argv += ["--plan", plan_id]
    if include is not None:
        included = ",".join(include)
        if included:
            argv += ["--include", included]
    argv += ["--redact-level", redact_level]
    proc = subprocess.run(  # noqa: S603 — argv built from typed kwargs, not user-controlled
        argv,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"snapshot CLI exit {proc.returncode}: {proc.stderr.strip()[:400]}"
        )
    return json.loads(proc.stdout)


# ─────────────────── sync engine ───────────────────


@dataclass
class SyncResult:
    sets: int = 0
    deletes: int = 0
    failures: int = 0
    skipped_unchanged: int = 0
    by_stream: dict[str, dict[str, int]] = field(default_factory=dict)

    def record(self, stream: str, op: str) -> None:
        bucket = self.by_stream.setdefault(
            stream, {"set": 0, "delete": 0, "failure": 0, "skipped": 0}
        )
        bucket[op] = bucket.get(op, 0) + 1
        if op == "set":
            self.sets += 1
        elif op == "delete":
            self.deletes += 1
        elif op == "failure":
            self.failures += 1
        elif op == "skipped":
            self.skipped_unchanged += 1


@dataclass
class SyncEngine:
    """Holds the last-written hash cache per (stream, doc_id) tuple.

    The cache is process-local; daemon restart re-syncs everything
    on the first poll which is correct (idempotent on the consumer
    side anyway). Persisting it to disk is a future optimization, not
    needed for v0.
    """

    project_id: str
    last_written: dict[str, dict[str, str]] = field(default_factory=dict)

    def sync_once(
        self,
        snapshot: dict[str, Any],
        firestore_client: Any,
        *,
        owned_streams: Iterable[str] = ALL_STREAMS,
    ) -> SyncResult:
        """Diff-and-upsert one snapshot. Returns counters; never raises
        for individual doc failures — those are recorded and skipped.
        """
        result = SyncResult()
        streams = snapshot.get("streams") or {}
        owned = tuple(owned_streams)
        for stream in owned:
            items = streams.get(stream, []) or []
            self._sync_stream(
                stream=stream,
                items=items,
                firestore_client=firestore_client,
                result=result,
            )
        return result

    def _sync_stream(
        self,
        *,
        stream: str,
        items: list[dict[str, Any]],
        firestore_client: Any,
        result: SyncResult,
    ) -> None:
        path = f"projects/{self.project_id}/{stream}"
        cache = self.last_written.setdefault(stream, {})

        new_hashes: dict[str, str] = {}
        new_payloads: dict[str, dict[str, Any]] = {}
        for item in items:
            try:
                doc_id = _doc_id_for(stream, item)
            except (KeyError, TypeError) as e:
                _LOG.warning(
                    "skip malformed %s item (missing key for doc-id): %s",
                    stream,
                    e,
                )
                result.record(stream, "failure")
                continue
            h = _payload_hash(item)
            new_hashes[doc_id] = h
            new_payloads[doc_id] = item

        # Upserts: doc_id new or hash diverged.
        for doc_id, h in new_hashes.items():
            if cache.get(doc_id) == h:
                result.record(stream, "skipped")
                continue
            try:
                firestore_client.collection(path).document(doc_id).set(
                    new_payloads[doc_id]
                )
            except Exception as e:  # noqa: BLE001 — broad on purpose; per-doc
                _LOG.error(
                    "set failed for %s/%s: %s", path, doc_id, e
                )
                result.record(stream, "failure")
                # Leave cache unchanged so the next sync retries.
                continue
            cache[doc_id] = h
            result.record(stream, "set")

        # Deletes: doc_id present in cache but no longer in snapshot.
        for doc_id in list(cache.keys()):
            if doc_id in new_hashes:
                continue
            try:
                firestore_client.collection(path).document(doc_id).delete()
            except Exception as e:  # noqa: BLE001
                _LOG.error(
                    "delete failed for %s/%s: %s", path, doc_id, e
                )
                result.record(stream, "failure")
                continue
            cache.pop(doc_id, None)
            result.record(stream, "delete")


# ─────────────────── daemon loop ───────────────────


def run_daemon(
    *,
    engine: SyncEngine,
    snapshot_source: SnapshotSource,
    firestore_client: Any,
    interval_s: float,
    owned_streams: Iterable[str] = ALL_STREAMS,
    max_iterations: int | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] | None = None,
    on_cycle: Callable[[int, SyncResult], None] | None = None,
) -> list[SyncResult]:
    """Poll → sync → sleep. Returns the per-cycle results list.

    Stops when `should_stop()` is true, when `max_iterations` is
    reached, or on SIGINT/SIGTERM if the default signal handler is
    installed by the caller. Sleep and stop hooks are injectable so
    tests can drive the loop deterministically without real sleeps.
    """
    owned = tuple(owned_streams)
    cycles: list[SyncResult] = []
    iteration = 0
    while True:
        if should_stop and should_stop():
            break
        if max_iterations is not None and iteration >= max_iterations:
            break
        iteration += 1
        try:
            snapshot = snapshot_source()
        except Exception as e:  # noqa: BLE001
            _LOG.error("snapshot fetch failed on cycle %d: %s", iteration, e)
            sleep_fn(interval_s)
            continue
        try:
            result = engine.sync_once(
                snapshot, firestore_client, owned_streams=owned
            )
        except Exception as e:  # noqa: BLE001
            _LOG.error("sync_once raised on cycle %d: %s", iteration, e)
            sleep_fn(interval_s)
            continue
        cycles.append(result)
        if on_cycle is not None:
            on_cycle(iteration, result)
        if max_iterations is not None and iteration >= max_iterations:
            break
        sleep_fn(interval_s)
    return cycles


# ─────────────────── CLI ───────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m firebase_adapter.dontpanic_sync",
        description=(
            "Sync the DontPanic state projection into Firestore under "
            "projects/<project_id>/<stream>. Single-tenant shape per plan D002."
        ),
    )
    subs = parser.add_subparsers(dest="subcommand", required=True)

    start = subs.add_parser("start", help="Start the polling daemon loop.")
    start.add_argument(
        "--interval",
        type=float,
        default=10.0,
        help="Polling interval in seconds (default: 10).",
    )
    start.add_argument(
        "--project-id",
        required=True,
        help="DontPanic project_id; becomes the Firestore parent doc.",
    )
    start.add_argument(
        "--include",
        default=None,
        help=(
            "Comma-separated streams to sync. Default: all. Streams "
            "not listed are left untouched on Firestore."
        ),
    )
    start.add_argument(
        "--plan",
        default=None,
        dest="plan_id",
        help="If set, only sync this single plan_id.",
    )
    start.add_argument(
        "--plans-root",
        default=None,
        help="Forwarded to dontpanic state snapshot --plans-root.",
    )
    start.add_argument(
        "--redact-level",
        default="operator",
        choices=("public", "operator", "full"),
    )
    start.add_argument(
        "--once",
        action="store_true",
        help="Run one cycle and exit (useful for cron / launchd).",
    )
    start.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Stop after N cycles (default: run forever).",
    )
    start.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print would-write counts but DO NOT touch Firestore. Uses the "
            "in-memory stub so this never opens a network connection."
        ),
    )
    start.add_argument(
        "--verbose",
        action="store_true",
        help="Set log level to DEBUG.",
    )
    return parser


def _resolve_streams(include_csv: str | None) -> tuple[str, ...]:
    if not include_csv:
        return ALL_STREAMS
    parts = tuple(s.strip() for s in include_csv.split(",") if s.strip())
    unknown = [s for s in parts if s not in ALL_STREAMS]
    if unknown:
        raise SystemExit(
            f"--include contains unknown stream(s): {unknown}; "
            f"valid: {list(ALL_STREAMS)}"
        )
    return parts


def _default_firestore_client(project_id: str) -> Any:
    """Lazy-import firebase_admin so the package is usable in
    environments where the SDK is not installed (tests, dry-run, dev).
    """
    try:
        import firebase_admin  # type: ignore[import-not-found]
        from firebase_admin import credentials, firestore  # type: ignore[import-not-found]
    except ImportError as e:
        raise SystemExit(
            "firebase-admin is not installed. Install with "
            "`pip install firebase-admin` or run with --dry-run."
        ) from e

    if not firebase_admin._apps:  # type: ignore[attr-defined]
        firebase_admin.initialize_app(credentials.ApplicationDefault())
    return firestore.client()


def _build_signal_stop() -> Callable[[], bool]:
    stop_flag = {"stop": False}

    def _handler(signum: int, _frame: Any) -> None:
        _LOG.info("received signal %d; shutting down after current cycle", signum)
        stop_flag["stop"] = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            # Not on main thread or not supported — caller can still
            # interrupt via max_iterations / Ctrl-C.
            pass

    return lambda: stop_flag["stop"]


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.subcommand != "start":
        parser.print_help(sys.stderr)
        return 2

    owned = _resolve_streams(args.include)

    def source() -> dict[str, Any]:
        return fetch_snapshot_via_cli(
            plans_root=Path(args.plans_root) if args.plans_root else None,
            include=owned,
            plan_id=args.plan_id,
            redact_level=args.redact_level,
        )

    if args.dry_run:
        from firebase_adapter.firestore_stub import InMemoryFirestore

        client: Any = InMemoryFirestore()
        _LOG.info(
            "--dry-run: writes are recorded in an in-memory stub, never sent."
        )
    else:
        client = _default_firestore_client(args.project_id)

    engine = SyncEngine(project_id=args.project_id)

    max_iter: int | None
    if args.once:
        max_iter = 1
    else:
        max_iter = args.max_iterations

    stop = _build_signal_stop()

    def log_cycle(i: int, r: SyncResult) -> None:
        _LOG.info(
            "cycle %d: sets=%d deletes=%d skipped=%d failures=%d",
            i,
            r.sets,
            r.deletes,
            r.skipped_unchanged,
            r.failures,
        )

    run_daemon(
        engine=engine,
        snapshot_source=source,
        firestore_client=client,
        interval_s=args.interval,
        owned_streams=owned,
        max_iterations=max_iter,
        should_stop=stop,
        on_cycle=log_cycle,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ALL_STREAMS",
    "SnapshotSource",
    "SyncEngine",
    "SyncResult",
    "fetch_snapshot_via_cli",
    "main",
    "run_daemon",
]
