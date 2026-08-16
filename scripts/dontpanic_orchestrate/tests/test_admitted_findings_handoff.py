"""Plan 2026-08-12-001 F005 — next implementer sees admitted claims, not a rewrite."""

from __future__ import annotations

import json
from pathlib import Path

from dontpanic_orchestrate import prompts


def _envelope(tmp: Path) -> Path:
    path = tmp / "codex-auditor-F001-i0.json"
    path.write_text(
        json.dumps(
            {
                "audit_status": "needs_changes",
                "findings": [
                    {
                        "severity": "high",
                        "category": "test_coverage",
                        "issue": "The named pytest was never run.",
                        "recommendation": "Run test_foo.py",
                        "evidence_refs": [{"type": "log", "uri": "audit/commands.txt"}],
                    },
                    {
                        "severity": "low",
                        "category": "style",
                        "issue": "This sentence has no evidence and must not reach the next worker.",
                        "recommendation": "Ignore me",
                    },
                ],
            }
        )
    )
    return path


class TestAdmittedFindingsHandoff:
    def test_prompt_contains_admitted_claim_and_path(self, tmp_path: Path) -> None:
        audit = _envelope(tmp_path)
        block = prompts._findings_block(audit)
        assert "The named pytest was never run." in block
        assert str(audit) in block or audit.name in block
        assert "This sentence has no evidence" not in block

    def test_audit_file_still_the_unfold_target(self, tmp_path: Path) -> None:
        audit = _envelope(tmp_path)
        block = prompts._findings_block(audit)
        assert audit.is_file()
        assert "unfold" in block.lower() or str(audit) in block
