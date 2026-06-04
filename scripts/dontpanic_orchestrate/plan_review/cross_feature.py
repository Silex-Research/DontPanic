"""Cross-feature edit detection (F008).

Detects when a dispatch's diff touches files **owned by a different feature**
than the one being implemented — the ``F008-touches-F013-dashboard`` bleed a
human auditor caught by hand during onboarding-v0. The point of F008 is to make
that scope-creep a *system* finding (block-severity, surfaced at
patch-completeness) rather than something only a vigilant reviewer catches.

Two layers, mirroring the other plan-review gates (F004 / F007):

  * **pure detection** — :func:`derive_ownership_map` builds a
    ``feature_id -> owned-paths`` map from the plan's features, and
    :func:`check_cross_feature_edit` intersects a dispatch's touched paths
    against *other* features' owned paths, returning a typed
    :class:`CrossFeatureFinding` per foreign feature whose paths were touched.
    No network, no filesystem, no mutation.
  * **enforcement seam** — :func:`enforce` runs the detection at
    patch-completeness time and either raises :class:`CrossFeatureEditError`
    (block) or, when the operator supplied an acknowledgement rationale for a
    legitimate shared-file edit, records the rationale to an evidence sidecar
    and passes. ``record_acknowledgement`` is the one I/O seam.

Ownership derivation
--------------------
A feature owns a path if it **declares** it (an explicit ``owned_paths`` list on
the feature record) or, lacking that, if its ``description`` / ``steps`` /
``acceptance`` text **names** the path as a file token (``cli.py``,
``dashboard/app.js``, ``quota_caps.json``). The text heuristic is intentionally
conservative: only tokens ending in a known source extension count, so a dotted
code symbol (``command_validation.validate_command_tokens``) is NOT mistaken for
a path while its module file (``command_validation.py``) is.

Known limitation (documented, not silently swallowed): two features may name the
same shared file (e.g. both touch ``cli.py``). A path matched by BOTH the current
feature and a foreign one is treated as co-owned and never flagged; a path matched
only by a foreign feature is flagged. A feature that edits a shared file it never
declared can therefore false-positive — that is exactly what the operator
acknowledgement override (recorded rationale) exists to clear.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Minimum non-whitespace length of an acknowledgement rationale. Mirrors
# patch_completeness_gate.MIN_REASON_LEN / the F004 / F007 override bar so every
# operator-override surface shares one length contract.
MIN_REASON_LEN = 8

# A path token is any dotted filename — optionally directory-qualified — ending
# in a known source extension. The trailing-extension anchor is what separates a
# *path* (``command_validation.py``) from a dotted code *symbol*
# (``command_validation.validate_command_tokens``): the latter has no source
# extension at its tail, so it never matches. The extension set mirrors lint.py's
# ``_FILE_EXT_RE`` plus the mobile/web source kinds a plan might own.
_PATH_TOKEN_RE = re.compile(
    r"(?<![\w/.-])"
    r"((?:[\w.-]+/)*[\w.-]+"
    r"\.(?:jsonl?|ya?ml|md|txt|py|tsx?|jsx?|sh|toml|csv|html?|cfg|ini|lock|swift|rb|sql|css|kt))"
    r"\b",
    re.IGNORECASE,
)


# ─────────────────────────────── public types ──────────────────────────────


@dataclass(frozen=True)
class CrossFeatureFinding:
    """One feature's paths bled into by the current dispatch.

    ``foreign_feature_id`` owns ``paths`` (per the ownership map) but the
    dispatch implementing ``current_feature_id`` touched them. ``mode`` /
    ``severity`` mirror the patch-completeness ``Finding`` shape so the finding
    renders/serialises consistently with the rest of the gate output.
    """

    current_feature_id: str
    foreign_feature_id: str
    paths: tuple[str, ...]
    severity: str = "block"
    mode: str = "cross_feature_edit"

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "severity": self.severity,
            "current_feature_id": self.current_feature_id,
            "foreign_feature_id": self.foreign_feature_id,
            "paths": list(self.paths),
            "reason": (
                f"Dispatch for {self.current_feature_id} touched "
                f"{len(self.paths)} path(s) owned by {self.foreign_feature_id}: "
                f"{', '.join(self.paths)}. Cross-feature edits leak scope between "
                "features and should be split out or explicitly acknowledged."
            ),
            "recommendation": (
                "Revert the foreign-owned paths from this dispatch and land them "
                f"under {self.foreign_feature_id}, OR re-run with "
                "--acknowledge-cross-feature <reason> (>=8 chars) if the shared "
                "edit is legitimate."
            ),
        }


class CrossFeatureEditError(RuntimeError):
    """Raised at patch-completeness when an unacknowledged cross-feature edit is
    found. The string form renders one foreign feature per block so the operator
    can act without parsing JSON."""

    def __init__(self, findings: Sequence[CrossFeatureFinding], plan_dir: Path) -> None:
        self.findings = list(findings)
        self.plan_dir = plan_dir
        super().__init__(render_block_message(self.findings))


# ─────────────────────────────── pure detection ────────────────────────────


def _feature_text(feature: Mapping) -> str:
    parts: list[str] = [str(feature.get("description") or "")]
    steps = feature.get("steps") or []
    if isinstance(steps, (list, tuple)):
        parts.extend(str(s) for s in steps)
    parts.append(str(feature.get("acceptance") or ""))
    return "\n".join(parts)


def _extract_path_tokens(text: str) -> set[str]:
    """Return the file-path tokens named in ``text`` (extension-anchored)."""
    out: set[str] = set()
    for match in _PATH_TOKEN_RE.finditer(text):
        token = match.group(1).strip().strip("`'\"().,;:")
        if token:
            out.add(_normalize(token))
    return out


def _normalize(path: str) -> str:
    """Canonicalise a path for comparison: strip whitespace and a leading
    ``./``. Trailing/duplicate separators are left as-is (git never emits them).
    """
    return str(path).strip().lstrip("/").removeprefix("./") if path else ""


def derive_ownership_map(features: Iterable[Mapping]) -> dict[str, set[str]]:
    """Build a ``feature_id -> {owned path token}`` map from the plan.

    An explicit ``owned_paths`` list on a feature record wins; otherwise the
    owned set is the file-path tokens named in the feature's
    description/steps/acceptance text. Pure — never mutates ``features``.
    Features without an ``id`` are skipped.
    """
    result: dict[str, set[str]] = {}
    for feature in features:
        fid = feature.get("id")
        if not fid:
            continue
        explicit = feature.get("owned_paths")
        if explicit:
            owned = {_normalize(p) for p in explicit if _normalize(p)}
        else:
            owned = _extract_path_tokens(_feature_text(feature))
        result[str(fid)] = owned
    return result


def _path_matches_token(repo_path: str, token: str) -> bool:
    """True iff git ``repo_path`` is, or ends with, owned ``token``.

    Ownership tokens extracted from prose are often partial (``cli.py``,
    ``dashboard/app.js``) while git paths are full and source-root prefixed
    (``scripts/dontpanic_orchestrate/cli.py``). A token matches on an exact
    equality OR a path-component-aligned suffix (``.../<token>``) so a partial
    token still resolves to the real file, while ``my_cli.py`` does NOT match
    token ``cli.py`` (the boundary ``/`` is required)."""
    rp = _normalize(repo_path)
    tk = _normalize(token)
    if not rp or not tk:
        return False
    return rp == tk or rp.endswith("/" + tk)


def check_cross_feature_edit(
    touched_paths: Iterable[str],
    current_feature_id: str,
    ownership_map: Mapping[str, Iterable[str]],
    *,
    acknowledged_paths: Iterable[str] | None = None,
) -> list[CrossFeatureFinding]:
    """Return one finding per foreign feature whose owned paths were touched.

    A touched path is a bleed iff it matches a *foreign* feature's owned token
    AND does NOT match the current feature's owned tokens (co-owned/shared paths
    are never flagged) AND is not in ``acknowledged_paths``. Pure.
    """
    ack = {_normalize(a) for a in (acknowledged_paths or []) if _normalize(a)}
    own_tokens = set(ownership_map.get(current_feature_id, set()))

    foreign_hits: dict[str, set[str]] = {}
    for raw in touched_paths:
        path = _normalize(raw)
        if not path:
            continue
        # The current feature's own (or co-owned) paths are never a bleed.
        if any(_path_matches_token(path, t) for t in own_tokens):
            continue
        # Operator-acknowledged shared edits are exempt.
        if path in ack or any(_path_matches_token(path, a) for a in ack):
            continue
        for fid, tokens in ownership_map.items():
            if fid == current_feature_id:
                continue
            if any(_path_matches_token(path, t) for t in tokens):
                foreign_hits.setdefault(fid, set()).add(path)

    return [
        CrossFeatureFinding(
            current_feature_id=current_feature_id,
            foreign_feature_id=fid,
            paths=tuple(sorted(foreign_hits[fid])),
        )
        for fid in sorted(foreign_hits)
    ]


def touched_paths_from_git_state(git_state: Mapping) -> set[str]:
    """Extract the dispatch's touched paths from an F001 git-state sidecar.

    The diff surface is ``staged ∪ unstaged_modified ∪ untracked`` — every file
    the dispatch added or changed. Tolerant of both the ``{"path": ...}`` entry
    shape (staged/unstaged_modified) and the bare-string shape (untracked)."""
    out: set[str] = set()
    for key in ("staged", "unstaged_modified"):
        for entry in git_state.get(key, []) or []:
            path = entry.get("path") if isinstance(entry, Mapping) else entry
            if path:
                out.add(_normalize(path))
    for entry in git_state.get("untracked", []) or []:
        if entry:
            out.add(_normalize(entry))
    return out


# ─────────────────────────────── rendering ─────────────────────────────────


def render_block_message(findings: Sequence[CrossFeatureFinding]) -> str:
    """The refusal message shown when an unacknowledged cross-feature edit is
    found. Names each foreign feature and the offending paths (acceptance #2),
    plus the acknowledgement override affordance (acceptance #4)."""
    if not findings:
        return "[patch-completeness] no cross-feature edits detected."
    current = findings[0].current_feature_id
    lines = [
        f"[patch-completeness] BLOCKED by cross-feature edit detection: the "
        f"dispatch for {current} touched paths owned by other feature(s):",
    ]
    for f in findings:
        lines.append(f"  {f.foreign_feature_id} owns:")
        for path in f.paths:
            lines.append(f"    {path}")
    lines.append(
        "  remediation — revert the foreign-owned paths from this dispatch and "
        "land them under the owning feature."
    )
    lines.append(
        "  override — re-run with `--acknowledge-cross-feature <reason>` "
        "(>=8 non-whitespace chars) to record a rationale and pass anyway."
    )
    return "\n".join(lines)


def validate_reason(reason: str) -> str:
    """Layer-B re-check that an acknowledgement ``reason`` has >=8 non-whitespace
    chars (defense-in-depth mirror of the CLI argparse validator). Raises
    ``ValueError`` on rejection."""
    stripped = (reason or "").strip()
    if len(stripped) < MIN_REASON_LEN:
        raise ValueError(
            f"--acknowledge-cross-feature reason must be at least {MIN_REASON_LEN} "
            f"non-whitespace characters; got {len(stripped)} ({reason!r})."
        )
    return reason


# ─────────────────────────────── I/O seam ──────────────────────────────────


def record_acknowledgement(
    plan_dir: Path,
    *,
    plan_id: str,
    current_feature_id: str,
    reason: str,
    findings: Sequence[CrossFeatureFinding],
    now: datetime | None = None,
) -> Path:
    """Persist a cross-feature-edit acknowledgement rationale to an evidence
    sidecar (mirrors the F007 ``record_override`` convention) so the
    acknowledged shared edit is auditable. Returns the path written."""
    out_dir = plan_dir / "evidence" / "plan-review" / "cross_feature"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{current_feature_id}-cross-feature-ack.json"

    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "gate": "patch_completeness_cross_feature",
        "plan_id": plan_id,
        "current_feature_id": current_feature_id,
        "reason": reason,
        "acknowledged_findings": [f.to_dict() for f in findings],
        "recorded_at": stamp,
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    return out_path


# ─────────────────────────────── enforcement ───────────────────────────────


def enforce(
    plan_dir: Path,
    *,
    plan_id: str,
    current_feature_id: str,
    features: Iterable[Mapping],
    touched_paths: Iterable[str],
    acknowledge_reason: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict | None:
    """Run cross-feature detection at patch-completeness and decide signoff fate.

    Returns ``None`` when no bleed is detected (gate is a no-op). When a bleed is
    found:

      * ``acknowledge_reason`` supplied — validates + records the rationale and
        returns a pass block (acceptance #4);
      * ``dry_run`` — returns the finding block without raising (preview);
      * otherwise — raises :class:`CrossFeatureEditError` (acceptance #2).
    """
    ownership_map = derive_ownership_map(features)
    findings = check_cross_feature_edit(
        touched_paths, current_feature_id, ownership_map
    )
    if not findings:
        return None

    block: dict = {
        "status": "fail",
        "findings": [f.to_dict() for f in findings],
    }

    if acknowledge_reason is not None:
        validate_reason(acknowledge_reason)
        ack_path = record_acknowledgement(
            plan_dir,
            plan_id=plan_id,
            current_feature_id=current_feature_id,
            reason=acknowledge_reason,
            findings=findings,
            now=now,
        )
        block["status"] = "acknowledged"
        block["acknowledge_reason"] = acknowledge_reason
        block["acknowledgement_path"] = str(ack_path)
        return block

    if dry_run:
        return block

    raise CrossFeatureEditError(findings, plan_dir)
