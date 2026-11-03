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
