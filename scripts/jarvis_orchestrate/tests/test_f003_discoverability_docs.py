from __future__ import annotations

import json
import re
from pathlib import Path

from jarvis_orchestrate.agent_manifest import SAFETY_RULE_NO_AUTO_DISPATCH

ROOT = Path(__file__).resolve().parents[3]
README = ROOT / "README.md"
ECOSYSTEM = ROOT / "docs" / "ECOSYSTEM.md"
DISCOVERABILITY = ROOT / "docs" / "DISCOVERABILITY.md"
ROADMAP = ROOT / "docs" / "ROADMAP.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _json_blocks(path: Path) -> list[dict]:
    text = _read(path)
    blocks: list[dict] = []
    for match in re.finditer(r"```json\n(.*?)\n```", text, flags=re.S):
        data = json.loads(match.group(1))
        if "mcpServers" in data:
            blocks.append(data)
    return blocks


def test_safety_rule_present_in_all_agent_facing_docs() -> None:
    for path in [README, ECOSYSTEM, DISCOVERABILITY]:
        assert SAFETY_RULE_NO_AUTO_DISPATCH in _read(path), path


def test_readme_has_four_caller_examples() -> None:
    text = _read(README)
    for heading in ["Claude Code", "Cursor", "OpenClaw", "Codex CLI"]:
        assert f"### {heading}" in text
    assert text.count("dontpanic.validate_plan") >= 4


def test_mcp_json_snippets_parse_and_use_canonical_command() -> None:
    blocks = _json_blocks(README) + _json_blocks(DISCOVERABILITY)
    assert len(blocks) >= 5
    for block in blocks:
        server = block["mcpServers"]["dontpanic"]
        assert server["command"] == "dontpanic"
        assert server["args"] == ["mcp", "serve"]


def test_cross_references_exist() -> None:
    assert DISCOVERABILITY.exists()
    assert (ROOT / "docs" / "ECOSYSTEM.md").exists()
    assert (ROOT / "docs" / "ROADMAP.md").exists()
    assert "[`docs/ECOSYSTEM.md`](./docs/ECOSYSTEM.md)" in _read(README)
    assert "[`docs/DISCOVERABILITY.md`](./docs/DISCOVERABILITY.md)" in _read(README)
    assert "[`DISCOVERABILITY.md`](./DISCOVERABILITY.md)" in _read(ECOSYSTEM)
    assert "[`DISCOVERABILITY.md`](./DISCOVERABILITY.md)" in _read(ROADMAP)
