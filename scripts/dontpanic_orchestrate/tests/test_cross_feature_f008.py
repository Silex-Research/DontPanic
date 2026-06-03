"""Tests for plan-review F008 — cross-feature edit detection.

Reproduces the onboarding-v0 ``F008-touches-F013-dashboard`` bleed (a dispatch
implementing one feature editing files owned by another), plus the clean and
operator-acknowledged cases, and the ownership-map derivation contract.
"""

from __future__ import annotations

import json

import pytest

from dontpanic_orchestrate.plan_review import cross_feature as cf

# ─────────────────────────── ownership derivation ──────────────────────────


def test_ownership_map_from_explicit_owned_paths():
    features = [
        {"id": "F001", "owned_paths": ["scripts/foo/lint.py", "./bar.py"]},
    ]
    omap = cf.derive_ownership_map(features)
    assert omap["F001"] == {"scripts/foo/lint.py", "bar.py"}


def test_ownership_map_from_text_tokens_not_symbols():
    """File tokens are owned; dotted code symbols are NOT mistaken for paths."""
    features = [
        {
            "id": "F009",
            "description": "Validate quota_caps.json at pre-flight.",
            "steps": ["Route remediation through command_validation.py"],
            "acceptance": (
                "command_validation.validate_command_tokens accepts the command "
                "and writes dashboard/config.html"
            ),
        }
    ]
    omap = cf.derive_ownership_map(features)
    assert "quota_caps.json" in omap["F009"]
    assert "command_validation.py" in omap["F009"]
    assert "dashboard/config.html" in omap["F009"]
    # The dotted symbol (no source extension at its tail) is not a path.
    assert "command_validation.validate_command_tokens" not in omap["F009"]


def test_ownership_map_skips_idless_features():
    omap = cf.derive_ownership_map([{"description": "no id here cli.py"}])
    assert omap == {}


# ─────────────────────── the F008 -> F013 bleed (acceptance #2/#5) ──────────


def _onboarding_v0_features() -> list[dict]:
    """A two-feature plan mirroring the onboarding-v0 bleed: F008 owns the
    cross-feature engine paths, F013 owns the dashboard surface."""
    return [
        {
            "id": "F008",
            "description": "Cross-feature edit detection at patch-completeness.",
            "steps": ["Add the ownership map in cross_feature.py"],
            "acceptance": "A finding fires when a diff bleeds.",
        },
        {
            "id": "F013",
            "description": "Config-readiness dashboard affordance.",
            "steps": ["Render the fix UI in dashboard/app.js"],
            "acceptance": "dashboard/config_panel.html shows the remediation.",
        },
    ]


def test_cross_feature_bleed_flags_foreign_feature_and_paths():
    features = _onboarding_v0_features()
    omap = cf.derive_ownership_map(features)
    # F008's dispatch touched its own module AND bled into F013's dashboard.
    touched = [
        "scripts/dontpanic_orchestrate/plan_review/cross_feature.py",
        "scripts/dontpanic_orchestrate/dashboard/app.js",
    ]
    findings = cf.check_cross_feature_edit(touched, "F008", omap)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.foreign_feature_id == "F013"
    assert finding.current_feature_id == "F008"
    assert finding.severity == "block"
    assert finding.mode == "cross_feature_edit"
    assert finding.paths == ("scripts/dontpanic_orchestrate/dashboard/app.js",)
    # The finding names the foreign feature and the paths (acceptance #2).
    blob = finding.to_dict()
    assert "F013" in blob["reason"]
    assert "dashboard/app.js" in blob["reason"]


def test_partial_token_matches_source_root_prefixed_git_path():
    """A bare-filename owned token (``app.js``) resolves to the full git path."""
    features = [
        {"id": "FX", "description": "owns nothing relevant cli.py"},
        {"id": "FY", "description": "Render app.js"},
    ]
    omap = cf.derive_ownership_map(features)
    findings = cf.check_cross_feature_edit(
        ["packages/web/src/app.js"], "FX", omap
    )
    assert [f.foreign_feature_id for f in findings] == ["FY"]
    # boundary guard: my_app.js must NOT match token app.js
    assert cf.check_cross_feature_edit(["packages/web/my_app.js"], "FX", omap) == []


# ─────────────────────────── clean case (acceptance #3) ─────────────────────


def test_same_feature_patch_yields_no_finding():
    features = _onboarding_v0_features()
    omap = cf.derive_ownership_map(features)
    # F013's dispatch touches only F013-owned dashboard paths.
    touched = ["scripts/dontpanic_orchestrate/dashboard/app.js"]
    assert cf.check_cross_feature_edit(touched, "F013", omap) == []


def test_co_owned_path_is_not_flagged():
    """A path named by BOTH the current and a foreign feature is co-owned."""
    features = [
        {"id": "FA", "description": "edits shared cli.py"},
        {"id": "FB", "description": "also edits cli.py"},
    ]
    omap = cf.derive_ownership_map(features)
    assert cf.check_cross_feature_edit(["pkg/cli.py"], "FA", omap) == []


def test_unowned_path_is_not_flagged():
    features = _onboarding_v0_features()
    omap = cf.derive_ownership_map(features)
    # A path no feature claims is not a cross-feature bleed.
    assert cf.check_cross_feature_edit(["scripts/util/misc.py"], "F008", omap) == []


# ─────────────────────── acknowledged case (acceptance #4) ──────────────────


def test_acknowledged_path_is_exempt_in_pure_check():
    features = _onboarding_v0_features()
    omap = cf.derive_ownership_map(features)
    touched = ["scripts/dontpanic_orchestrate/dashboard/app.js"]
    findings = cf.check_cross_feature_edit(
        touched, "F008", omap, acknowledged_paths=touched
    )
    assert findings == []


# ─────────────────────────────── git-state extraction ──────────────────────


def test_touched_paths_from_git_state_unions_all_surfaces():
    git_state = {
        "staged": [{"path": "a.py"}],
        "unstaged_modified": [{"path": "b.py"}],
        "untracked": ["c.py"],
    }
    assert cf.touched_paths_from_git_state(git_state) == {"a.py", "b.py", "c.py"}


# ─────────────────────────────── enforce() gate ────────────────────────────


def test_enforce_raises_on_unacknowledged_bleed(tmp_path):
    features = _onboarding_v0_features()
    touched = [
        "scripts/dontpanic_orchestrate/plan_review/cross_feature.py",
        "scripts/dontpanic_orchestrate/dashboard/app.js",
    ]
    with pytest.raises(cf.CrossFeatureEditError) as exc:
        cf.enforce(
            tmp_path,
            plan_id="p1",
            current_feature_id="F008",
            features=features,
            touched_paths=touched,
        )
    msg = str(exc.value)
    assert "F013" in msg
    assert "dashboard/app.js" in msg
    assert "--acknowledge-cross-feature" in msg


def test_enforce_clean_returns_none(tmp_path):
    features = _onboarding_v0_features()
    result = cf.enforce(
        tmp_path,
        plan_id="p1",
        current_feature_id="F013",
        features=features,
        touched_paths=["scripts/dontpanic_orchestrate/dashboard/app.js"],
    )
    assert result is None


def test_enforce_dry_run_returns_block_without_raising(tmp_path):
    features = _onboarding_v0_features()
    block = cf.enforce(
        tmp_path,
        plan_id="p1",
        current_feature_id="F008",
        features=features,
        touched_paths=["scripts/dontpanic_orchestrate/dashboard/app.js"],
        dry_run=True,
    )
    assert block["status"] == "fail"
    assert block["findings"][0]["foreign_feature_id"] == "F013"


def test_enforce_acknowledged_records_rationale_and_passes(tmp_path):
    features = _onboarding_v0_features()
    block = cf.enforce(
        tmp_path,
        plan_id="p1",
        current_feature_id="F008",
        features=features,
        touched_paths=["scripts/dontpanic_orchestrate/dashboard/app.js"],
        acknowledge_reason="shared render helper edited intentionally for F008",
    )
    assert block["status"] == "acknowledged"
    ack_path = tmp_path / "evidence" / "plan-review" / "cross_feature" / "F008-cross-feature-ack.json"
    assert ack_path.is_file()
    payload = json.loads(ack_path.read_text())
    assert payload["current_feature_id"] == "F008"
    assert payload["reason"].startswith("shared render helper")
    assert payload["acknowledged_findings"][0]["foreign_feature_id"] == "F013"


def test_enforce_acknowledge_reason_too_short_rejected(tmp_path):
    features = _onboarding_v0_features()
    with pytest.raises(ValueError):
        cf.enforce(
            tmp_path,
            plan_id="p1",
            current_feature_id="F008",
            features=features,
            touched_paths=["scripts/dontpanic_orchestrate/dashboard/app.js"],
            acknowledge_reason="short",
        )
