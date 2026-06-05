"""Plan 2026-06-04-004 F001 — real provenance on every dashboard section.

Every exported stream declares the actual upstream source it is projected from,
as DATA on the manifest (not a hardcoded footer). With the canonical projection
active, the legacy tasks.json / agents.json / activity.json adapters are never
cited or rendered.
"""

from __future__ import annotations

import json
from pathlib import Path

from dontpanic_orchestrate import state_cli, state_projection


# ── the provenance map itself is honest ──────────────────────────────────────
def test_provenance_map_covers_exactly_all_streams():
    assert set(state_projection.STREAM_PROVENANCE) == set(state_projection.ALL_STREAMS)


def test_no_provenance_string_cites_a_legacy_source():
    for stream, source in state_projection.STREAM_PROVENANCE.items():
        for legacy in state_projection.LEGACY_SOURCES:
            assert legacy not in source, f"{stream} provenance cites legacy {legacy}"


# ── the EXPORTED manifest carries provenance == the real source ───────────────
def _export(tmp_path: Path) -> dict:
    plans_root = tmp_path / "plans"  # empty -> empty streams, manifest still written
    plans_root.mkdir()
    out_dir = tmp_path / "state"
    rc = state_cli._export_dashboard_main(
        ["--out", str(out_dir), "--plans-root", str(plans_root)]
    )
    assert rc == 0
    return json.loads((out_dir / "manifest.json").read_text())


def test_manifest_stream_source_equals_declared_provenance(tmp_path):
    manifest = _export(tmp_path)
    by_name = {s["name"]: s for s in manifest["streams"]}
    assert set(by_name) == set(state_projection.ALL_STREAMS)
    for name, entry in by_name.items():
        assert entry["source"] == state_projection.STREAM_PROVENANCE[name]
        assert entry["source"]  # never empty


def test_exported_manifest_never_cites_legacy_adapters(tmp_path):
    manifest = _export(tmp_path)
    blob = json.dumps(manifest)
    for legacy in state_projection.LEGACY_SOURCES:
        assert legacy not in blob, f"manifest cites legacy adapter {legacy}"


def test_canonical_projection_state_dir_has_no_legacy_files(tmp_path):
    # The canonical projection writes ONLY state-snapshot.json + per-stream files
    # + manifest.json — never a legacy tasks/agents/activity.json.
    plans_root = tmp_path / "plans"
    plans_root.mkdir()
    out_dir = tmp_path / "state"
    state_cli._export_dashboard_main(
        ["--out", str(out_dir), "--plans-root", str(plans_root)]
    )
    written = {p.name for p in out_dir.iterdir()}
    assert written & state_projection.LEGACY_SOURCES == set()
    assert "manifest.json" in written
    assert "state-snapshot.json" in written
