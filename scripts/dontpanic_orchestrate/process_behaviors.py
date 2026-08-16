"""Plan 2026-08-12-001 F006 — process judges over existing audit envelopes.

Pure functions of the envelope (and optional git-state). No model call.
Verdicts persist beside the audit. Spec text is hidden from worker prompts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HIDDEN_SPEC_PHRASES: tuple[str, ...] = (
    "behavior spec hidden from worker",
    "process-behavior rubric",
    "adherence violated unless named test ran",
)


@dataclass(frozen=True)
class BehaviorVerdict:
    id: str
    trigger: str
    owner_role: str
    adherence: str
    evidence_refs: tuple[dict[str, str], ...] = ()


def _commands(envelope: dict[str, Any]) -> list[str]:
    raw = envelope.get("commands_run") or []
    return [str(c) for c in raw]


def judge_named_test(envelope: dict[str, Any], audit_path: Path) -> BehaviorVerdict:
    named = envelope.get("steps_named_test") or envelope.get("named_test")
    if not named:
        return BehaviorVerdict(
            id="B001",
            trigger="steps name a test",
            owner_role="implementer",
            adherence="n/a",
        )
    commands = _commands(envelope)
    hit = any(str(named) in cmd for cmd in commands)
    if hit:
        return BehaviorVerdict(
            id="B001",
            trigger="steps name a test",
            owner_role="implementer",
            adherence="expected",
        )
    return BehaviorVerdict(
        id="B001",
        trigger="steps name a test",
        owner_role="implementer",
        adherence="violated",
        evidence_refs=({"type": "file", "uri": str(audit_path)},),
    )


def judge_declaration(envelope: dict[str, Any]) -> BehaviorVerdict:
    decl = envelope.get("declaration")
    if not decl:
        return BehaviorVerdict(
            id="B002",
            trigger="target_context present",
            owner_role="implementer",
            adherence="n/a",
        )
    ok = all(decl.get(k) for k in ("repo", "env", "project"))
    return BehaviorVerdict(
        id="B002",
        trigger="target_context present",
        owner_role="implementer",
        adherence="expected" if ok else "violated",
        evidence_refs=()
        if ok
        else ({"type": "file", "uri": "declaration"},),
    )


def judge_cross_vendor(envelope: dict[str, Any], *, implementer_vendor: str) -> BehaviorVerdict:
    auditor = str(envelope.get("vendor") or "")
    if not auditor or not implementer_vendor:
        return BehaviorVerdict(
            id="B003",
            trigger="implementer vendor ≠ auditor vendor",
            owner_role="supervisor",
            adherence="n/a",
        )
    ok = auditor != implementer_vendor
    return BehaviorVerdict(
        id="B003",
        trigger="implementer vendor ≠ auditor vendor",
        owner_role="supervisor",
        adherence="expected" if ok else "violated",
        evidence_refs=()
        if ok
        else ({"type": "file", "uri": "vendor"},),
    )


def judge_commands_recorded(envelope: dict[str, Any]) -> BehaviorVerdict:
    commands = _commands(envelope)
    if not commands:
        return BehaviorVerdict(
            id="B004",
            trigger="commands_run recorded when the prompt required commands",
            owner_role="implementer",
            adherence="violated",
            evidence_refs=({"type": "file", "uri": "commands_run"},),
        )
    return BehaviorVerdict(
        id="B004",
        trigger="commands_run recorded when the prompt required commands",
        owner_role="implementer",
        adherence="expected",
    )


def judge_envelope(
    audit_path: Path, *, implementer_vendor: str = ""
) -> tuple[BehaviorVerdict, ...]:
    data = json.loads(Path(audit_path).read_text())
    return (
        judge_named_test(data, Path(audit_path)),
        judge_declaration(data),
        judge_cross_vendor(data, implementer_vendor=implementer_vendor),
        judge_commands_recorded(data),
    )


def persist_verdicts(
    audit_path: Path, *, implementer_vendor: str = ""
) -> Path:
    verdicts = judge_envelope(audit_path, implementer_vendor=implementer_vendor)
    out = Path(audit_path).with_name(
        Path(audit_path).stem + "-behaviors.json"
    )
    payload = {
        "behaviors": [
            {
                "id": v.id,
                "trigger": v.trigger,
                "owner_role": v.owner_role,
                "adherence": v.adherence,
                "evidence_refs": list(v.evidence_refs),
            }
            for v in verdicts
        ]
    }
    out.write_text(json.dumps(payload, indent=2) + "\n")
    return out
