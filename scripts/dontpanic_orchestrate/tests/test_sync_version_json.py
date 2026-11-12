"""JSON-aware version pin checking for the MCP Registry listing."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[3]


def _load_sync_version(root: Path, monkeypatch: pytest.MonkeyPatch):
    source_module = REPO_ROOT / "scripts" / "sync_version.py"
    spec = importlib.util.spec_from_file_location("sync_version_json_test", source_module)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    monkeypatch.setattr(module, "ROOT", root)
    paths = (*module.PINNED_PATHS, module.VERSION_SOURCE)
    for relative in paths:
        source = REPO_ROOT / relative
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return module


def test_check_detects_minified_server_json_top_level_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    sync_version = _load_sync_version(tmp_path, monkeypatch)
    server_path = tmp_path / "server.json"
    server = json.loads(server_path.read_text(encoding="utf-8"))
    server["version"] = "9.9.9"
    server_path.write_text(json.dumps(server, separators=(",", ":")), encoding="utf-8")

    assert sync_version.main(["--check"]) == 1
    assert "server.json" in capsys.readouterr().err


def test_check_detects_package_version_drift_in_pretty_server_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    sync_version = _load_sync_version(tmp_path, monkeypatch)
    server_path = tmp_path / "server.json"
    server = json.loads(server_path.read_text(encoding="utf-8"))
    server["packages"][0]["version"] = "9.9.9"
    server_path.write_text(json.dumps(server, indent=2) + "\n", encoding="utf-8")

    assert sync_version.main(["--check"]) == 1
    assert "server.json" in capsys.readouterr().err


def test_check_reports_invalid_server_json(tmp_path: Path, monkeypatch, capsys):
    sync_version = _load_sync_version(tmp_path, monkeypatch)
    (tmp_path / "server.json").write_text("{", encoding="utf-8")

    assert sync_version.main(["--check"]) == 2
    assert "server.json" in capsys.readouterr().err


def test_check_accepts_unmodified_json_copies(tmp_path: Path, monkeypatch):
    sync_version = _load_sync_version(tmp_path, monkeypatch)

    assert sync_version.main(["--check"]) == 0


# ── Sentinel r3b (D) — every PINNED_PATHS file must carry a pin ──


def _snapshot(root: Path) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_check_fails_naming_pinned_file_with_no_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    sync_version = _load_sync_version(tmp_path, monkeypatch)
    readme = tmp_path / "README.md"
    readme.write_text("# DontPanic\n\npipx install dontpanic-orchestrate\n", encoding="utf-8")

    assert sync_version.main(["--check"]) == 2
    assert "README.md" in capsys.readouterr().err


def test_write_mode_refuses_unpinned_file_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    sync_version = _load_sync_version(tmp_path, monkeypatch)
    (tmp_path / "README.md").write_text("# DontPanic\n\nno pin here\n", encoding="utf-8")
    server_path = tmp_path / "server.json"
    server = json.loads(server_path.read_text(encoding="utf-8"))
    server["version"] = "9.9.9"
    server_path.write_text(json.dumps(server, indent=2) + "\n", encoding="utf-8")
    before = _snapshot(tmp_path)

    assert sync_version.main([]) == 2
    assert "README.md" in capsys.readouterr().err
    # No file created and no other drift silently rewritten.
    assert _snapshot(tmp_path) == before


def test_check_fails_naming_json_listing_with_no_version_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    sync_version = _load_sync_version(tmp_path, monkeypatch)
    plugin = tmp_path / ".cursor-plugin" / "plugin.json"
    payload = json.loads(plugin.read_text(encoding="utf-8"))
    payload.pop("version")
    plugin.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    assert sync_version.main(["--check"]) == 2
    assert ".cursor-plugin/plugin.json" in capsys.readouterr().err


@pytest.mark.parametrize("relative", ["docs/PUBLISHING.md", ".claude-plugin/plugin.json"])
def test_check_fails_naming_missing_pinned_file(
    relative: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    sync_version = _load_sync_version(tmp_path, monkeypatch)
    (tmp_path / relative).unlink()

    assert sync_version.main(["--check"]) == 2
    assert relative in capsys.readouterr().err
    assert sync_version.main([]) == 2
    assert not (tmp_path / relative).exists()  # write mode never recreates it


def test_check_still_detects_pin_drift_in_scanned_doc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    sync_version = _load_sync_version(tmp_path, monkeypatch)
    doc = tmp_path / "docs" / "USE_CASES.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("uvx dontpanic-orchestrate==0.0.1\n", encoding="utf-8")

    assert sync_version.main(["--check"]) == 1
    assert "docs/USE_CASES.md" in capsys.readouterr().err
