"""In-memory Firestore stand-in for adapter tests.

Mirrors the minimal subset of the `firebase_admin.firestore.Client`
shape the sync daemon depends on:

    client.collection(<path>).document(<doc_id>).set(<dict>)
    client.collection(<path>).document(<doc_id>).delete()

The daemon never reads from Firestore — it diffs against its own
in-process last-written cache — so this stub only needs to record
writes. Tests assert on `stub.writes` and `stub.docs`.

Failure injection: set `stub.fail_paths.add("projects/foo/plans")` and
any `set()` against that collection raises a RuntimeError so the
daemon's per-doc try/except path is exercisable.

This file lives in `scripts/firebase_adapter/` (not under `tests/`)
because the daemon imports the protocol-shape from here at runtime to
keep production + test surfaces aligned. No network, no Firebase SDK
import — usable in environments where `firebase-admin` isn't installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WriteEvent:
    path: str
    doc_id: str
    op: str  # "set" | "delete"
    data: dict | None


@dataclass
class InMemoryFirestore:
    """A toy Firestore that records every write and stores docs by path."""

    docs: dict[str, dict[str, dict]] = field(default_factory=dict)
    writes: list[WriteEvent] = field(default_factory=list)
    fail_paths: set[str] = field(default_factory=set)

    def collection(self, path: str) -> _Collection:
        return _Collection(self, path)

    # Test-only helpers
    def reset_log(self) -> None:
        self.writes = []

    def docs_at(self, path: str) -> dict[str, dict]:
        return dict(self.docs.get(path, {}))

    def write_count(self, op: str | None = None) -> int:
        if op is None:
            return len(self.writes)
        return sum(1 for w in self.writes if w.op == op)


class _Collection:
    def __init__(self, fs: InMemoryFirestore, path: str) -> None:
        self._fs = fs
        self._path = path

    def document(self, doc_id: str) -> _Document:
        return _Document(self._fs, self._path, doc_id)


class _Document:
    def __init__(self, fs: InMemoryFirestore, path: str, doc_id: str) -> None:
        self._fs = fs
        self._path = path
        self._doc_id = doc_id

    def set(self, data: dict) -> None:
        if self._path in self._fs.fail_paths:
            raise RuntimeError(
                f"InMemoryFirestore: injected failure on path {self._path!r}"
            )
        bucket = self._fs.docs.setdefault(self._path, {})
        # Defensive copy so callers can't mutate stored docs after-the-fact.
        bucket[self._doc_id] = dict(data)
        self._fs.writes.append(
            WriteEvent(self._path, self._doc_id, "set", dict(data))
        )

    def delete(self) -> None:
        bucket = self._fs.docs.setdefault(self._path, {})
        bucket.pop(self._doc_id, None)
        self._fs.writes.append(
            WriteEvent(self._path, self._doc_id, "delete", None)
        )


__all__ = ["InMemoryFirestore", "WriteEvent"]
