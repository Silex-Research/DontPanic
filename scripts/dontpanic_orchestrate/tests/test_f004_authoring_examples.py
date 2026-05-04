from __future__ import annotations

import json
import re
from pathlib import Path

from dontpanic_orchestrate import plan_loader

ROOT = Path(__file__).resolve().parents[3]
AUTHORING = ROOT / "docs" / "AUTHORING_PLANS.md"
REQUIRED_NON_GOAL = (
    "This is authoring guidance, not the Phase C intake engine. "
    "F004 does not embed sufficiency logic, discovery rules, or "
    "cost-model decisions; those land in Phase C."
)


def _doc_text() -> str:
    return AUTHORING.read_text(encoding="utf-8")


def _extract_example(name: str) -> dict[str, str]:
    pattern = (
        rf"<!-- dontpanic-plan-example: {re.escape(name)} -->\n"
        r"````text\n(.*?)\n````"
    )
    match = re.search(pattern, _doc_text(), flags=re.S)
    assert match, name
    parts = re.split(r"^=== (.+)$", match.group(1), flags=re.M)
    files: dict[str, str] = {}
    for index in range(1, len(parts), 2):
        files[parts[index].strip()] = parts[index + 1].strip() + "\n"
    return files


def _materialize(tmp_path: Path, name: str) -> Path:
    files = _extract_example(name)
    plan_md = files["plan.md"]
    plan_id_match = re.search(r"^id: (.+)$", plan_md, flags=re.M)
    assert plan_id_match
    plan_dir = tmp_path / plan_id_match.group(1).strip()
    plan_dir.mkdir()
    for rel, body in files.items():
        (plan_dir / rel).write_text(body, encoding="utf-8")
    (plan_dir / "audit").mkdir()
    (plan_dir / "evidence").mkdir()
    return plan_dir


def test_authoring_doc_has_required_sections_and_non_goal() -> None:
    text = _doc_text()
    for heading in [
        "## Plan Directory Layout",
        "## Minimum Valid Plan",
        "## Two Substantive Examples",
        "## Sufficiency vs Implementation",
        "## Validation",
    ]:
        assert heading in text
    assert REQUIRED_NON_GOAL in text
    assert "claude/shared/schemas/v1.0/" in text


def test_examples_extract_and_load_with_plan_loader(tmp_path: Path) -> None:
    for name in ["minimum-valid", "feature-add", "bug-fix"]:
        plan_dir = _materialize(tmp_path, name)
        loaded = plan_loader.load(plan_dir)
        assert loaded.plan_id == plan_dir.name
        assert loaded.features.task_id == loaded.plan_id


def test_example_decisions_are_valid_json_lines() -> None:
    for name in ["minimum-valid", "feature-add", "bug-fix"]:
        files = _extract_example(name)
        decisions = files["decisions.jsonl"].strip().splitlines()
        assert decisions
        for line in decisions:
            data = json.loads(line)
            assert data["id"].startswith("D")
            assert data["title"]
            assert data["body"]
