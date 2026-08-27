"""Print the remaining ceremony when a feature ledger stays ``passes: false``.

``passes=false`` mixes two operator situations: the code still fails, and the
code already works but the flip ceremony is incomplete (auditor envelope,
supervisor receipt, named human gate, AC-named evidence). The next implementer
rewrites a green feature unless the print names what still blocks the flip.

No second ledger field. No supervisor state machine. Inspect on-disk artifacts
and print.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from dontpanic_orchestrate import closeout, gate_pause, signoff_writer

TESTS_PASSED = "passed"
TESTS_FAILED = "failed"
TESTS_UNKNOWN = "unknown"

_TEST_FAIL_STATUSES = frozenset({"failed", "timed_out", "error", "refused"})
_TEST_EVIDENCE_MARKERS = (".xcresult", "test_output", "junit", "regression-")
_PATH_RE = re.compile(
    r"(?:"
    r"`([^`]+)`|"
    r"(evidence/[A-Za-z0-9_./-]+)|"
    r"(audit/[A-Za-z0-9_./-]+\.(?:json|txt|log|xml))|"
    r"([A-Za-z0-9_./-]+\.xcresult)"
    r")"
)


@dataclass(frozen=True)
class RemainingCeremony:
    """What still blocks a ``passes: true`` flip, plus local test status."""

    feature_id: str
    tests_status: str
    blockers: tuple[str, ...]

    @property
    def tests_passed(self) -> bool:
        return self.tests_status == TESTS_PASSED

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "passes": False,
            "tests_status": self.tests_status,
            "blockers": list(self.blockers),
        }


def _stringify_gates(gates: Sequence[Any] | None) -> list[str]:
    out: list[str] = []
    for gate in gates or ():
        value = gate.value if hasattr(gate, "value") else str(gate)
        if value:
            out.append(value)
    return out


def _latest_verification_status(plan_dir: Path) -> str | None:
    evidence = plan_dir / "evidence"
    if not evidence.is_dir():
        return None
    best: str | None = None
    best_mtime = -1.0
    for path in evidence.glob("regression-*.json"):
        try:
            mtime = path.stat().st_mtime
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        status = data.get("status")
        if isinstance(status, str) and mtime >= best_mtime:
            best_mtime = mtime
            best = status
    return best


def _ac_named_paths(feature: Mapping[str, Any]) -> list[str]:
    blobs = [str(feature.get("acceptance") or "")]
    steps = feature.get("steps") or []
    if isinstance(steps, list):
        blobs.extend(str(s) for s in steps)
    found: list[str] = []
    seen: set[str] = set()
    for blob in blobs:
        for match in _PATH_RE.finditer(blob):
            token = next((g for g in match.groups() if g), None)
            if not token:
                continue
            token = token.strip()
            if not token or token in seen:
                continue
            if "/" not in token and "." not in token:
                continue
            seen.add(token)
            found.append(token)
    return found


def _path_exists(plan_dir: Path, token: str) -> bool:
    candidate = Path(token)
    if candidate.is_absolute():
        return candidate.exists()
    return (plan_dir / token).exists()


def _looks_like_test_evidence(token: str) -> bool:
    lowered = token.lower()
    return any(marker in lowered for marker in _TEST_EVIDENCE_MARKERS)


def _tests_status(
    plan_dir: Path,
    feature: Mapping[str, Any],
    ac_paths: Sequence[str],
) -> str:
    verification = _latest_verification_status(plan_dir)
    if verification == TESTS_PASSED:
        return TESTS_PASSED
    if verification in _TEST_FAIL_STATUSES:
        return TESTS_FAILED
    for ref in feature.get("evidence_refs") or []:
        if not isinstance(ref, dict) or ref.get("type") != "test_output":
            continue
        uri = ref.get("uri")
        if isinstance(uri, str) and uri and _path_exists(plan_dir, uri):
            return TESTS_PASSED
    if any(_looks_like_test_evidence(p) and _path_exists(plan_dir, p) for p in ac_paths):
        return TESTS_PASSED
    if isinstance(verification, str):
        return verification
    return TESTS_UNKNOWN


def _auditor_blocker(plan_dir: Path, feature_id: str) -> str | None:
    audit_paths = closeout._audit_paths_for_feature(plan_dir, feature_id)
    envelope = closeout._latest_auditor_envelope(audit_paths)
    if envelope is None:
        return "auditor envelope missing"
    verdict = ""
    for key in ("audit_status", "verdict"):
        val = envelope.get(key)
        if isinstance(val, str) and val:
            verdict = val
            break
    if verdict == "signed_off":
        return None
    if verdict:
        return f"auditor envelope is {verdict} (not signed_off)"
    return "auditor envelope present but has no signed_off verdict"


def _supervisor_receipt_blocker(plan_dir: Path, plan_id: str) -> str | None:
    path = signoff_writer.signoff_path(plan_dir, plan_id)
    if path.is_file():
        return None
    return f"supervisor receipt missing ({path.relative_to(plan_dir)})"


def _human_gate_blockers(plan_dir: Path, human_gates: Sequence[str]) -> list[str]:
    if not human_gates:
        return []
    try:
        unmet = gate_pause.unmet_gates(plan_dir, list(human_gates))
    except Exception:  # noqa: BLE001 — print should never crash an operator surface
        unmet = list(human_gates)
    return [f"human gate pending: {gate}" for gate in unmet]


def _missing_ac_evidence(plan_dir: Path, ac_paths: Sequence[str]) -> list[str]:
    return [
        f"missing evidence path from AC: {token}"
        for token in ac_paths
        if not _path_exists(plan_dir, token)
    ]


def inspect_feature(
    plan_dir: Path,
    feature: Mapping[str, Any],
    *,
    plan_id: str,
    human_gates: Sequence[Any] = (),
) -> RemainingCeremony | None:
    """Inspect one feature. ``None`` when ``passes`` is already true."""
    if feature.get("passes") is True:
        return None
    feature_id = str(feature.get("id") or "")
    if not feature_id:
        return None
    plan_dir = Path(plan_dir)
    ac_paths = _ac_named_paths(feature)
    tests_status = _tests_status(plan_dir, feature, ac_paths)
    blockers: list[str] = []
    auditor = _auditor_blocker(plan_dir, feature_id)
    if auditor:
        blockers.append(auditor)
    receipt = _supervisor_receipt_blocker(plan_dir, plan_id)
    if receipt:
        blockers.append(receipt)
    blockers.extend(_human_gate_blockers(plan_dir, _stringify_gates(human_gates)))
    blockers.extend(_missing_ac_evidence(plan_dir, ac_paths))
    if not blockers:
        blockers.append(
            "ledger is still passes=false; attach evidence_refs and finalize"
        )
    return RemainingCeremony(
        feature_id=feature_id,
        tests_status=tests_status,
        blockers=tuple(blockers),
    )


def inspect(
    plan_dir: Path,
    feature_id: str,
    *,
    loaded: Any | None = None,
) -> RemainingCeremony | None:
    """Load the plan if needed and inspect ``feature_id``."""
    plan_dir = Path(plan_dir)
    if loaded is None:
        from dontpanic_orchestrate import plan_loader

        try:
            loaded = plan_loader.load(plan_dir)
        except Exception:  # noqa: BLE001 — operator print is best-effort
            return _inspect_from_features_json(plan_dir, feature_id)
    try:
        feature = loaded.feature(feature_id)
    except (KeyError, AttributeError):
        return None
    human_gates = getattr(getattr(loaded, "plan", None), "human_gates", None)
    plan_id = getattr(loaded, "plan_id", None) or plan_dir.name
    return inspect_feature(
        plan_dir,
        feature,
        plan_id=str(plan_id),
        human_gates=human_gates or (),
    )


def _inspect_from_features_json(
    plan_dir: Path, feature_id: str
) -> RemainingCeremony | None:
    feats_path = plan_dir / "features.json"
    try:
        data = json.loads(feats_path.read_text())
    except (OSError, ValueError):
        return None
    features = data.get("features") if isinstance(data, dict) else None
    if not isinstance(features, list):
        return None
    for feature in features:
        if isinstance(feature, dict) and feature.get("id") == feature_id:
            return inspect_feature(
                plan_dir,
                feature,
                plan_id=str(data.get("task_id") or plan_dir.name),
            )
    return None


def render(report: RemainingCeremony) -> str:
    """Operator-facing remaining-ceremony block."""
    if report.tests_status == TESTS_PASSED:
        tests_line = "tests: already passed locally — do not rewrite the feature"
    elif report.tests_status == TESTS_FAILED:
        tests_line = "tests: failed — implementation still open"
    else:
        tests_line = "tests: not recorded on disk"
    lines = [
        f"[remaining-ceremony] {report.feature_id} ledger passes=false",
        f"  {tests_line}",
        "  still blocks flip:",
    ]
    for blocker in report.blockers:
        lines.append(f"    - {blocker}")
    return "\n".join(lines) + "\n"


def print_remaining_ceremony(
    plan_dir: Path,
    feature_id: str,
    *,
    loaded: Any | None = None,
    file: Any | None = None,
) -> RemainingCeremony | None:
    """Inspect and print when the ledger is still false. No-op on ``passes=true``."""
    import sys

    report = inspect(plan_dir, feature_id, loaded=loaded)
    if report is None:
        return None
    print(render(report), end="", file=file or sys.stdout)
    return report


__all__ = [
    "RemainingCeremony",
    "TESTS_FAILED",
    "TESTS_PASSED",
    "TESTS_UNKNOWN",
    "inspect",
    "inspect_feature",
    "print_remaining_ceremony",
    "render",
]
