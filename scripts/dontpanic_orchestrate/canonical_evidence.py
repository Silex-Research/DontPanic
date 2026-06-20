"""Plan 2026-06-17-001 F006 — the C4 canonical-backfill evidence contract.

This module pins the *exact* shape of
``~/.dontpanic/canonical-backfill-evidence.json`` so that ambiguity detection is
deterministic **before** the F002 backfill engine consumes the file. F006
validates **SHAPE only** — presence of keys, exact value types, allowed fields,
and the shared no-secret-shape assertion. It deliberately does NOT trust the
semantic truth of ``durable_checkout``: F002 recomputes that against the
reconstructed canonical path's temp-prefix test (C3). F006 only proves the value
is a boolean.

Two defect tiers (C4):

* **File-fatal** — abort the whole run (the caller maps this to exit 2 and
  stamps nothing): not valid JSON / parse error, a missing required top-level
  key, ``schema_version != "1.0"``, or a top-level structural type error
  (``canonical_repos`` or ``observation_path_key_to_canonical`` is not a map).
  Raised as :class:`EvidenceFatalError` with a stable ``.reason`` code.

* **Row-level** — a per-record SKIP + report (the run continues, exit 0): an
  absent observation key, a list mapping to zero or multiple canonicals, an
  unknown canonical reference, a missing/mistyped required field, an unknown
  field, a raw-secret-shaped value, a non-hash-shaped/raw-URL ``origin_key``, or
  a canonical object whose ``path_key`` differs from its map key. Surfaced
  through :meth:`EvidenceContract.resolve` as an :class:`EvidenceResolution`
  carrying a stable ``skip_reason`` code.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dontpanic_orchestrate import operator_console as _operator_console

# ── contract constants ───────────────────────────────────────────────────

#: The only accepted ``schema_version`` value.
SCHEMA_VERSION = "1.0"

#: Required top-level keys of the evidence file.
REQUIRED_TOP_LEVEL_KEYS = ("schema_version", "canonical_repos", "observation_path_key_to_canonical")

#: Fields a ``canonical_repos`` value is allowed to carry. Anything else is an
#: unknown field (row-level skip).
ALLOWED_CANONICAL_FIELDS = frozenset(
    {"path_key", "path_display", "durable_checkout", "origin_key", "observed_under_temp_prefix"}
)

#: Fields a ``canonical_repos`` value MUST carry.
REQUIRED_CANONICAL_FIELDS = ("path_key", "path_display", "durable_checkout")

#: A hash-shaped key is lowercase hex of hash length (truncated 16 through full
#: sha256 64). A raw origin URL (``git@…``, ``https://…``) never matches this, so
#: this pattern is what rejects a raw URL smuggled into ``origin_key``.
_HASH_SHAPE_RE = re.compile(r"^[0-9a-f]{16,64}$")


# ── file-fatal reason codes ──────────────────────────────────────────────

FATAL_MISSING_FILE = "missing_evidence_file"
FATAL_UNREADABLE_FILE = "unreadable_evidence_file"
FATAL_INVALID_JSON = "invalid_json"
FATAL_NOT_A_MAPPING = "top_level_not_a_mapping"
FATAL_MISSING_TOP_LEVEL_KEY = "missing_top_level_key"
FATAL_WRONG_SCHEMA_VERSION = "wrong_schema_version"
FATAL_CANONICAL_REPOS_NOT_MAP = "canonical_repos_not_map"
FATAL_OBSERVATION_MAP_NOT_MAP = "observation_map_not_map"


# ── row-level reason codes ───────────────────────────────────────────────

SKIP_ABSENT_OBSERVATION_KEY = "absent_observation_key"
SKIP_NON_LIST_MAPPING = "non_list_mapping"
SKIP_ZERO_MAPPINGS = "zero_mappings"
SKIP_MULTIPLE_MAPPINGS = "multiple_mappings"
SKIP_UNKNOWN_CANONICAL_REFERENCE = "unknown_canonical_reference"
SKIP_UNKNOWN_CANONICAL_FIELD = "unknown_canonical_field"
SKIP_MISSING_REQUIRED_FIELD = "missing_required_field"
SKIP_WRONG_VALUE_TYPE = "wrong_value_type"
SKIP_PATH_KEY_MISMATCH = "path_key_mismatch"
SKIP_ORIGIN_NOT_HASH_SHAPED = "origin_key_not_hash_shaped"
SKIP_RAW_SECRET_SHAPE = "raw_secret_shape"  # noqa: S105 — reason code, not a secret


class EvidenceFatalError(Exception):
    """A file-fatal structural defect in the evidence file (C4).

    The caller (F002) maps this to exit 2 and stamps nothing. ``reason`` is one
    of the ``FATAL_*`` codes and is stable for tests and operator reporting.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class CanonicalRepoEvidence:
    """A shape-validated ``canonical_repos`` entry. Every field has passed the
    exact C4 type check and the shared no-secret-shape assertion; the truth of
    ``durable_checkout`` is NOT trusted here (F002 recomputes it)."""

    path_key: str
    path_display: str
    durable_checkout: bool
    origin_key: str | None = None
    observed_under_temp_prefix: bool | None = None


@dataclass(frozen=True)
class EvidenceResolution:
    """Outcome of resolving one observation key. Exactly one of ``canonical`` /
    ``skip_reason`` is set: ``canonical`` is a shape-confirmed entry, or
    ``skip_reason`` is a stable ``SKIP_*`` code for a row-level defect."""

    canonical: CanonicalRepoEvidence | None = None
    skip_reason: str | None = None

    @property
    def confirmed(self) -> bool:
        return self.canonical is not None


def _is_hash_shaped(value: str) -> bool:
    """True iff ``value`` is a lowercase-hex hash of hash length — never a raw
    origin URL."""
    return bool(_HASH_SHAPE_RE.match(value))


def _validate_canonical_object(
    map_key: str, obj: Any
) -> tuple[CanonicalRepoEvidence | None, str | None]:
    """Shape-validate a single ``canonical_repos`` entry.

    Returns ``(evidence, None)`` when the object is well-formed, else
    ``(None, skip_reason)`` with a stable ``SKIP_*`` code. No field is copied out
    until the shared no-secret-shape assertion has passed over the whole object.
    """
    if not isinstance(obj, Mapping):
        return None, SKIP_WRONG_VALUE_TYPE

    unknown = set(obj) - ALLOWED_CANONICAL_FIELDS
    if unknown:
        return None, SKIP_UNKNOWN_CANONICAL_FIELD

    for field in REQUIRED_CANONICAL_FIELDS:
        if field not in obj:
            return None, SKIP_MISSING_REQUIRED_FIELD

    # Exact value types. ``bool`` is checked with isinstance(_, bool) so an int
    # 0/1 does NOT pass as a boolean.
    if not isinstance(obj["path_key"], str) or not isinstance(obj["path_display"], str):
        return None, SKIP_WRONG_VALUE_TYPE
    if not isinstance(obj["durable_checkout"], bool):
        return None, SKIP_WRONG_VALUE_TYPE

    if "observed_under_temp_prefix" in obj and not isinstance(
        obj["observed_under_temp_prefix"], bool
    ):
        return None, SKIP_WRONG_VALUE_TYPE

    origin_key = obj.get("origin_key")
    if "origin_key" in obj:
        if not isinstance(origin_key, str):
            return None, SKIP_WRONG_VALUE_TYPE
        # A raw origin URL is rejected here: only a hash-shaped key is accepted.
        if not _is_hash_shaped(origin_key):
            return None, SKIP_ORIGIN_NOT_HASH_SHAPED

    # The canonical object's own path_key must equal its map key (C4).
    if obj["path_key"] != map_key:
        return None, SKIP_PATH_KEY_MISMATCH

    # No-secret-shape over the whole object BEFORE any field is copied (C1).
    try:
        _operator_console._assert_no_secret_shapes(dict(obj))  # noqa: SLF001
    except ValueError:
        return None, SKIP_RAW_SECRET_SHAPE

    return (
        CanonicalRepoEvidence(
            path_key=obj["path_key"],
            path_display=obj["path_display"],
            durable_checkout=obj["durable_checkout"],
            origin_key=origin_key if "origin_key" in obj else None,
            observed_under_temp_prefix=(
                obj["observed_under_temp_prefix"]
                if "observed_under_temp_prefix" in obj
                else None
            ),
        ),
        None,
    )


@dataclass(frozen=True)
class EvidenceContract:
    """A file-fatal-clean view of the evidence file. Top-level structure is
    proven valid; per-record canonical shape is validated lazily by
    :meth:`resolve` so each defect maps to a row-level skip."""

    schema_version: str
    canonical_repos: Mapping[str, Any]
    observation_map: Mapping[str, Any]

    def resolve(self, observed_path_key: str) -> EvidenceResolution:
        """Resolve one observed path key to its single confirmable canonical
        evidence entry, or a row-level skip reason. Validates SHAPE only — the
        caller (F002) performs the semantic path/durability recompute."""
        if observed_path_key not in self.observation_map:
            return EvidenceResolution(skip_reason=SKIP_ABSENT_OBSERVATION_KEY)

        mapping = self.observation_map[observed_path_key]
        if not isinstance(mapping, list):
            return EvidenceResolution(skip_reason=SKIP_NON_LIST_MAPPING)
        if len(mapping) == 0:
            return EvidenceResolution(skip_reason=SKIP_ZERO_MAPPINGS)
        if len(mapping) > 1:
            return EvidenceResolution(skip_reason=SKIP_MULTIPLE_MAPPINGS)

        canonical_key = mapping[0]
        if not isinstance(canonical_key, str) or canonical_key not in self.canonical_repos:
            return EvidenceResolution(skip_reason=SKIP_UNKNOWN_CANONICAL_REFERENCE)

        canonical, reason = _validate_canonical_object(
            canonical_key, self.canonical_repos[canonical_key]
        )
        if reason is not None:
            return EvidenceResolution(skip_reason=reason)
        return EvidenceResolution(canonical=canonical)


def parse_evidence(data: Any) -> EvidenceContract:
    """Validate the file-fatal structure of already-parsed evidence ``data``.

    Raises :class:`EvidenceFatalError` for any file-fatal defect (C4). Per-record
    canonical shape is NOT validated here — that is row-level and handled by
    :meth:`EvidenceContract.resolve`.
    """
    if not isinstance(data, Mapping):
        raise EvidenceFatalError(
            FATAL_NOT_A_MAPPING, "evidence top-level value is not a JSON object"
        )

    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in data:
            raise EvidenceFatalError(
                FATAL_MISSING_TOP_LEVEL_KEY, f"evidence missing required top-level key {key!r}"
            )

    schema_version = data["schema_version"]
    if schema_version != SCHEMA_VERSION:
        raise EvidenceFatalError(
            FATAL_WRONG_SCHEMA_VERSION,
            f"evidence schema_version {schema_version!r} != {SCHEMA_VERSION!r}",
        )

    canonical_repos = data["canonical_repos"]
    if not isinstance(canonical_repos, Mapping):
        raise EvidenceFatalError(
            FATAL_CANONICAL_REPOS_NOT_MAP, "evidence canonical_repos is not a map"
        )

    observation_map = data["observation_path_key_to_canonical"]
    if not isinstance(observation_map, Mapping):
        raise EvidenceFatalError(
            FATAL_OBSERVATION_MAP_NOT_MAP,
            "evidence observation_path_key_to_canonical is not a map",
        )

    return EvidenceContract(
        schema_version=schema_version,
        canonical_repos=canonical_repos,
        observation_map=observation_map,
    )


def load_evidence_file(path: str | Path) -> EvidenceContract:
    """Read and file-fatal-validate the evidence file at ``path``.

    Raises :class:`EvidenceFatalError` for a missing/unreadable file, invalid
    JSON, or any structural defect. The caller maps that to exit 2.
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise EvidenceFatalError(
            FATAL_MISSING_FILE, f"evidence file not found: {p}"
        ) from exc
    except OSError as exc:
        raise EvidenceFatalError(
            FATAL_UNREADABLE_FILE, f"evidence file unreadable: {p}: {exc}"
        ) from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EvidenceFatalError(
            FATAL_INVALID_JSON, f"evidence file is not valid JSON: {p}: {exc}"
        ) from exc

    return parse_evidence(data)


__all__ = [
    "ALLOWED_CANONICAL_FIELDS",
    "CanonicalRepoEvidence",
    "EvidenceContract",
    "EvidenceFatalError",
    "EvidenceResolution",
    "REQUIRED_CANONICAL_FIELDS",
    "REQUIRED_TOP_LEVEL_KEYS",
    "SCHEMA_VERSION",
    "load_evidence_file",
    "parse_evidence",
]
