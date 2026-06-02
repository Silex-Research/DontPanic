"""F004 — quota_caps_loader.

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_quota_caps_loader.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from dontpanic_orchestrate import quota_caps_loader as qcl


def test_starter_caps_with_codex_sample_derives_cap_from_observed() -> None:
    print("\n[test] starter_caps_with_codex_sample_derives_cap_from_observed ...")
    data = qcl.starter_caps(codex_observed_5h=237_258_206)
    cap = data["codex"]["plus"]["rolling_5h"]["cap"]
    assert cap == math.ceil(237_258_206 * 1.25)
    assert data["codex"]["plus"]["rolling_5h"]["unit"] == "tokens_local_proxy"
    assert "derived" in data["codex"]["plus"]["rolling_5h"]["_note"]
    print(f"  ✓ cap={cap} = ceil(observed * 1.25)")


def test_starter_caps_without_sample_uses_high_provisional() -> None:
    print("\n[test] starter_caps_without_sample_uses_high_provisional ...")
    data = qcl.starter_caps(codex_observed_5h=None)
    cap = data["codex"]["plus"]["rolling_5h"]["cap"]
    assert cap == qcl.CODEX_PROVISIONAL_CAP
    assert "high provisional" in data["codex"]["plus"]["rolling_5h"]["_note"]
    print(f"  ✓ falls back to high provisional ({cap}) with documented note")


def test_starter_caps_includes_defaults_claude_tier_for_detector() -> None:
    """_detect_claude_tier reads defaults.claude_tier as one of its fallbacks
    (after data.claude.tier and data.claude_tier). The starter file must seed
    this so the tier flowing into the v2 vendors{} block matches the cap key
    operators see in this same file."""
    print("\n[test] starter_caps_includes_defaults_claude_tier_for_detector ...")
    data = qcl.starter_caps()
    assert data["defaults"]["claude_tier"] == "max_20x"
    assert "max_20x" in data["claude"]
    print("  ✓ defaults.claude_tier = 'max_20x' matches the cap key")


def test_starter_caps_claude_carries_uncalibrated_warning() -> None:
    """F006 must skip Claude windows when calibration.confidence ==
    'uncalibrated'; the cap-file _note documents this so an operator
    reading the file understands why the cap will appear inert."""
    print("\n[test] starter_caps_claude_carries_uncalibrated_warning ...")
    data = qcl.starter_caps()
    note = data["claude"]["max_20x"]["rolling_7d"]["_note"]
    assert "uncalibrated" in note
    assert "F006" in note
    print("  ✓ Claude rolling_7d _note flags F006 + uncalibrated dependency")


def test_starter_caps_grok_is_empty_until_signal_exists() -> None:
    print("\n[test] starter_caps_grok_is_empty_until_signal_exists ...")
    data = qcl.starter_caps()
    assert data["grok"] == {}
    print("  ✓ grok block empty (no caps until F003 detects a real signal)")


def test_validate_accepts_starter_file() -> None:
    print("\n[test] validate_accepts_starter_file ...")
    errors = qcl.validate(qcl.starter_caps(codex_observed_5h=100))
    assert errors == []
    print("  ✓ generated starter file validates with no errors")


@pytest.mark.parametrize(
    "mutation, expect_substring",
    [
        ({"schema_version": 99}, "schema_version"),
        ({"unknown_vendor": {}}, "unknown vendor"),
        (
            {"claude": {"max_20x": {"rolling_7d": {"cap": -1, "unit": "percent_of_plan"}}}},
            "must be positive",
        ),
        (
            {"claude": {"max_20x": {"rolling_7d": {"cap": 100, "unit": "bogus_unit"}}}},
            "must be one of",
        ),
        (
            {"claude": {"max_20x": {"rolling_99h": {"cap": 100, "unit": "percent_of_plan"}}}},
            "unknown window",
        ),
        (
            {"claude": {"unobtanium": {"rolling_7d": {"cap": 100, "unit": "percent_of_plan"}}}},
            "unknown tier",
        ),
    ],
)
def test_validate_rejects_malformed_inputs(mutation, expect_substring) -> None:
    print(f"\n[test] validate_rejects_malformed_inputs ({list(mutation.keys())}) ...")
    base = qcl.starter_caps(codex_observed_5h=100)
    base.update(mutation)
    errors = qcl.validate(base)
    assert errors, f"expected errors for mutation {mutation!r}"
    assert any(expect_substring in e for e in errors), (
        f"no error matched {expect_substring!r}; got {errors}"
    )
    print(f"  ✓ rejected with {expect_substring!r} in {len(errors)} error(s)")


def test_validate_permits_underscore_prefixed_keys() -> None:
    """Operators may add `_note` / `_owner` etc. without breaking the loader."""
    print("\n[test] validate_permits_underscore_prefixed_keys ...")
    data = qcl.starter_caps(codex_observed_5h=100)
    data["_owner"] = "bilotto@gmail.com"
    data["claude"]["_note"] = "tuned 2026-04-30"
    errors = qcl.validate(data)
    assert errors == []
    print("  ✓ underscore-prefixed sibling keys ignored by validator")


def test_load_round_trip_via_init_starter_file(tmp_path: Path) -> None:
    print("\n[test] load_round_trip_via_init_starter_file ...")
    caps_path = tmp_path / "quota_caps.json"
    qcl.init_starter_file(path=caps_path, codex_observed_5h=237_258_206)
    loaded = qcl.load(caps_path)
    assert loaded["schema_version"] == qcl.CAPS_SCHEMA_VERSION
    assert loaded["codex"]["plus"]["rolling_5h"]["cap"] == math.ceil(237_258_206 * 1.25)
    assert loaded["defaults"]["claude_tier"] == "max_20x"
    print("  ✓ init → load → fields match")


def test_init_refuses_to_overwrite_without_flag(tmp_path: Path) -> None:
    print("\n[test] init_refuses_to_overwrite_without_flag ...")
    caps_path = tmp_path / "quota_caps.json"
    qcl.init_starter_file(path=caps_path, codex_observed_5h=10)
    with pytest.raises(qcl.QuotaCapsError, match="already exists"):
        qcl.init_starter_file(path=caps_path, codex_observed_5h=999)
    # overwrite=True succeeds
    qcl.init_starter_file(path=caps_path, codex_observed_5h=999, overwrite=True)
    refreshed = qcl.load(caps_path)
    assert refreshed["codex"]["plus"]["rolling_5h"]["cap"] == math.ceil(999 * 1.25)
    print("  ✓ refuses without flag, overwrites with flag")


def test_load_raises_on_missing_file(tmp_path: Path) -> None:
    print("\n[test] load_raises_on_missing_file ...")
    with pytest.raises(qcl.QuotaCapsError, match="not found"):
        qcl.load(tmp_path / "missing.json")
    print("  ✓ guides operator to run init")


def test_load_raises_on_invalid_json(tmp_path: Path) -> None:
    print("\n[test] load_raises_on_invalid_json ...")
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    with pytest.raises(qcl.QuotaCapsError, match="failed to read"):
        qcl.load(p)
    print("  ✓ json parse error surfaces with file path")


def test_load_raises_on_validation_errors(tmp_path: Path) -> None:
    print("\n[test] load_raises_on_validation_errors ...")
    p = tmp_path / "invalid.json"
    # schema_version 1 (supported) so load() reaches validate(); the bad cap is
    # what must compose into the "invalid" error. An UNSUPPORTED version is a
    # separate normalize-stage error (see test_load_rejects_unsupported_schema_version).
    p.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "claude": {
                    "max_20x": {"rolling_7d": {"cap": "not a number", "unit": "percent_of_plan"}}
                },
            }
        )
    )
    with pytest.raises(qcl.QuotaCapsError, match="invalid"):
        qcl.load(p)
    print("  ✓ load() composes validate() errors into single QuotaCapsError")


def test_load_accepts_and_normalizes_schema_version_2(tmp_path: Path) -> None:
    # F009 re-implemented (D047/D052): a schema_version 2 file nests vendors under
    # a `vendors` object; load() normalizes it to canonical v1 top-level vendor
    # keys so downstream get()/F006 are version-agnostic.
    print("\n[test] load_accepts_and_normalizes_schema_version_2 ...")
    p = tmp_path / "v2.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "defaults": {"claude_tier": "max_20x"},
                "vendors": {
                    "codex": {"plus": {"rolling_5h": {"cap": 200000000, "unit": "tokens_local_proxy"}}},
                    "claude": {"max_20x": {"rolling_7d": {"cap": 100, "unit": "percent_of_plan"}}},
                },
            }
        )
    )
    data = qcl.load(p)
    assert data["schema_version"] == qcl.CAPS_SCHEMA_VERSION  # normalized to canonical 1
    assert "vendors" not in data  # wrapper stripped
    assert data["defaults"] == {"claude_tier": "max_20x"}  # preserved
    block = qcl.get(data, "codex", "plus", "rolling_5h")
    assert block is not None and block["cap"] == 200000000
    print("  ✓ v2 file normalized to canonical v1 and validated")


def test_load_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    print("\n[test] load_rejects_unsupported_schema_version ...")
    p = tmp_path / "v99.json"
    p.write_text(json.dumps({"schema_version": 99, "vendors": {}}))
    with pytest.raises(qcl.QuotaCapsError, match="unsupported caps schema_version"):
        qcl.load(p)
    # v2 missing its vendors object is a normalize-stage error too.
    p.write_text(json.dumps({"schema_version": 2}))
    with pytest.raises(qcl.QuotaCapsError, match="requires a `vendors` object"):
        qcl.load(p)
    print("  ✓ unsupported version + malformed v2 wrapper rejected at normalize")


def test_starter_seeds_both_codex_windows(tmp_path: Path) -> None:
    # F009 re-implemented: init must seed codex rolling_5h AND rolling_7d so a
    # dispatch checking either window finds a cap (D047/D052).
    print("\n[test] starter_seeds_both_codex_windows ...")
    data = qcl.starter_caps(codex_observed_5h=1000, codex_observed_7d=8000)
    codex = data["codex"]["plus"]
    assert set(codex.keys()) == {"rolling_5h", "rolling_7d"}
    assert codex["rolling_5h"]["cap"] == 1250  # ceil(1000 * 1.25)
    assert codex["rolling_7d"]["cap"] == 10000  # ceil(8000 * 1.25)
    # init_starter_file threads both samples + round-trips through load().
    p = tmp_path / "caps.json"
    qcl.init_starter_file(p, codex_observed_5h=1000, codex_observed_7d=8000)
    loaded = qcl.load(p)
    assert qcl.get(loaded, "codex", "plus", "rolling_7d")["cap"] == 10000
    print("  ✓ both codex windows seeded + load round-trips")


def test_get_returns_window_block_or_none() -> None:
    print("\n[test] get_returns_window_block_or_none ...")
    data = qcl.starter_caps(codex_observed_5h=100)
    block = qcl.get(data, "codex", "plus", "rolling_5h")
    assert block is not None
    assert block["unit"] == "tokens_local_proxy"
    assert qcl.get(data, "codex", "plus", "rolling_99h") is None
    assert qcl.get(data, "codex", "unknown", "rolling_5h") is None
    assert qcl.get(data, "unknown_vendor", "plus", "rolling_5h") is None
    print("  ✓ get() returns block on hit, None on any segment miss")


def test_show_renders_human_readable_output(tmp_path: Path) -> None:
    """show() is what `quota-caps show` prints. Verify it surfaces vendor,
    tier, window, cap, unit, and note."""
    print("\n[test] show_renders_human_readable_output ...")
    caps_path = tmp_path / "quota_caps.json"
    qcl.init_starter_file(path=caps_path, codex_observed_5h=100)
    rendered = qcl.show(path=caps_path)
    assert "claude" in rendered
    assert "codex" in rendered
    assert "gemini" in rendered
    assert "rolling_5h" in rendered
    assert "tokens_local_proxy" in rendered
    assert "percent_of_plan" in rendered
    assert "Code Assist Individuals" in rendered
    print("  ✓ show() output contains vendor/tier/window/cap/unit/note")
