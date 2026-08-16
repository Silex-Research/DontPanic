"""Plan 2026-08-12-001 F006 — hidden process judges over existing envelopes."""

from __future__ import annotations

import json
from pathlib import Path

from dontpanic_orchestrate import process_behaviors, prompts


def _envelope(*, commands: list[str], vendor: str = "codex") -> dict:
    return {
        "vendor": vendor,
        "commands_run": commands,
        "declaration": {"repo": "DontPanic", "env": "dev", "project": "none"},
        "steps_named_test": "tests/test_foo.py",
    }


class TestProcessBehaviors:
    def test_each_behavior_returns_closed_verdict(self, tmp_path: Path) -> None:
        env = _envelope(commands=["$ pytest tests/test_foo.py"])
        path = tmp_path / "audit.json"
        path.write_text(json.dumps(env))
        verdicts = process_behaviors.judge_envelope(path, implementer_vendor="claude")
        assert verdicts
        assert {v.adherence for v in verdicts} <= {"expected", "n/a", "violated"}

    def test_named_test_omitted_is_violated(self, tmp_path: Path) -> None:
        env = _envelope(commands=["$ ls"])
        path = tmp_path / "audit.json"
        path.write_text(json.dumps(env))
        verdicts = process_behaviors.judge_envelope(path, implementer_vendor="claude")
        named = [v for v in verdicts if v.id == "B001"]
        assert named
        assert named[0].adherence == "violated"
        assert named[0].evidence_refs

    def test_behavior_text_not_in_worker_prompts(self) -> None:
        text = Path(prompts.__file__).read_text()
        for needle in process_behaviors.HIDDEN_SPEC_PHRASES:
            assert needle not in text

    def test_persist_beside_audit(self, tmp_path: Path) -> None:
        env = _envelope(commands=["$ pytest tests/test_foo.py"])
        audit = tmp_path / "codex-auditor-F001-i0.json"
        audit.write_text(json.dumps(env))
        out = process_behaviors.persist_verdicts(
            audit, implementer_vendor="claude"
        )
        assert out.is_file()
        payload = json.loads(out.read_text())
        assert payload["behaviors"]
