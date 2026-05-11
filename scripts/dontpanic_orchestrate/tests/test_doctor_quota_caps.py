"""Plan 2026-05-11-002 F001 — doctor quota-cap surface.

Promotes the parent plan 2026-05-11-001 dispatch-time stderr warnings
(no cap entry for ``claude.max_20x.rolling_5h`` / ``codex.plus.rolling_7d``
and stale ``claude.rolling_7d`` calibration) into actionable doctor
findings with copy-paste config snippets.

Fixture tests cover three shapes: missing-cap with signal, present-cap
silenced, and stale calibration. The acceptance-pinning test reproduces
the three known-missing pairs from the parent plan dispatch state.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCTOR_PATH = REPO_ROOT / "scripts" / "dontpanic_doctor.py"

CAPS_SCHEMA: dict = {
    "schema_version": 1,
    "defaults": {"claude_tier": "max_20x"},
    "claude": {
        "max_20x": {
            "rolling_7d": {"cap": 100, "unit": "percent_of_plan"},
        },
    },
    "codex": {
        "plus": {
            "rolling_5h": {"cap": 1_000_000_000, "unit": "tokens_local_proxy"},
        },
    },
    "gemini": {},
    "grok": {},
}


def _load_doctor():
    spec = importlib.util.spec_from_file_location("jarvis_doctor", DOCTOR_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["jarvis_doctor"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def doctor():
    return _load_doctor()


@pytest.fixture(autouse=True)
def _isolated_calibration(monkeypatch, tmp_path):
    """Default every test to an empty calibration file. Tests that want
    to assert stale-calibration findings overwrite this file with a
    stale-stamped entry. Without this, the operator's real
    ~/.jarvis/quota_calibration.json bleeds in via Path.home() —
    conftest.py only redirects JARVIS_HOME, not the literal home dir."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from dontpanic_orchestrate import calibration_loader
    finally:
        sys.path.pop(0)
    calibration_path = tmp_path / "quota_calibration.json"
    monkeypatch.setattr(calibration_loader, "CALIBRATION_FILE", calibration_path)
    return calibration_path


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def _state_with_signal(*, vendors: dict) -> dict:
    return {
        "schema_version": 2,
        "generated": "2026-05-11T00:00:00+00:00",
        "vendors": vendors,
    }


def _claude_window(
    *,
    observed: float,
    confidence: str = "uncalibrated",
    ratio: float | None = None,
    stamped_at: str | None = None,
) -> dict:
    return {
        "kind": "rolling_5h",
        "observed_native": observed,
        "observed_unit": "weighted_tokens_local_proxy",
        "models": {},
        "diagnostics": {"signal": "ok"},
        "calibration": {
            "ratio": ratio,
            "confidence": confidence,
            "source": None,
            "stamped_at": stamped_at,
        },
    }


def _codex_window(*, observed: float, kind: str = "rolling_5h") -> dict:
    return {
        "kind": kind,
        "observed_native": observed,
        "observed_unit": "tokens_local_proxy",
        "models": {},
        "diagnostics": {"signal": "ok"},
    }


# ── unit shape ─────────────────────────────────────────────────────────────


def test_quota_caps_check_silent_when_all_covered(doctor, monkeypatch, tmp_path):
    """When every signal-bearing (vendor, window) has a cap entry, the
    check emits a single PASS finding. No WARN. This is the green path
    operators see after `quota-caps init` + calibrate-claude."""
    caps_path = tmp_path / "quota_caps.json"
    state_path = tmp_path / "quota_state.json"
    _write(caps_path, CAPS_SCHEMA)
    fresh = dt.datetime.now(dt.timezone.utc).isoformat()
    _write(
        state_path,
        _state_with_signal(
            vendors={
                "claude": {
                    "tier": "max_20x",
                    "windows": {
                        "rolling_7d": _claude_window(
                            observed=1_000_000.0,
                            confidence="manual",
                            ratio=2.22e-08,
                            stamped_at=fresh,
                        ),
                    },
                },
                "codex": {
                    "tier": "plus",
                    "windows": {
                        "rolling_5h": _codex_window(observed=42_000.0),
                    },
                },
            }
        ),
    )
    monkeypatch.setenv("JARVIS_QUOTA_CAPS_PATH", str(caps_path))
    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(state_path))

    results = doctor.check_quota_caps()
    assert len(results) == 1
    assert results[0].ok and not results[0].warn
    assert "covered" in results[0].message


def test_quota_caps_check_warns_on_missing_pair(doctor, monkeypatch, tmp_path):
    """Codex plus rolling_5h has signal but the caps file lacks the entry —
    expect one WARN finding with a copy-paste snippet pointing at the right
    JSON path."""
    caps_path = tmp_path / "quota_caps.json"
    state_path = tmp_path / "quota_state.json"
    # Caps file present but codex block empty
    caps_without_codex = json.loads(json.dumps(CAPS_SCHEMA))
    caps_without_codex["codex"] = {}
    _write(caps_path, caps_without_codex)
    _write(
        state_path,
        _state_with_signal(
            vendors={
                "codex": {
                    "tier": "plus",
                    "windows": {
                        "rolling_5h": _codex_window(observed=42_000.0),
                    },
                }
            }
        ),
    )
    monkeypatch.setenv("JARVIS_QUOTA_CAPS_PATH", str(caps_path))
    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(state_path))

    results = doctor.check_quota_caps()
    warns = [r for r in results if r.warn]
    assert len(warns) == 1
    w = warns[0]
    assert w.name == "quota-caps:codex.plus.rolling_5h"
    assert "42000" in w.message
    # Remediation snippet must include the schema location AND the cap unit
    assert '"rolling_5h"' in w.remediation
    assert '"unit": "tokens_local_proxy"' in w.remediation


def test_quota_caps_check_warns_on_stale_calibration(
    doctor, monkeypatch, tmp_path, _isolated_calibration
):
    """A calibration stamped >7d ago must surface its own WARN. The
    remediation must mention calibrate-claude with the right window."""
    caps_path = tmp_path / "quota_caps.json"
    state_path = tmp_path / "quota_state.json"
    calibration_path = _isolated_calibration
    _write(caps_path, CAPS_SCHEMA)
    # Signal covered (so no missing-cap WARN), but calibration is stale.
    stale_stamp = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)
    ).isoformat()
    _write(
        state_path,
        _state_with_signal(
            vendors={
                "claude": {
                    "tier": "max_20x",
                    "windows": {
                        "rolling_7d": _claude_window(
                            observed=1_000_000.0,
                            confidence="manual",
                            ratio=2.22e-08,
                            stamped_at=stale_stamp,
                        ),
                    },
                }
            }
        ),
    )
    _write(
        calibration_path,
        {
            "schema_version": 1,
            "claude": {
                "rolling_7d": {
                    "ratio": 2.22e-08,
                    "confidence": "manual",
                    "source": "operator_dashboard_sample",
                    "dashboard_pct": 13.0,
                    "observed_native": 1_000_000.0,
                    "stamped_at": stale_stamp,
                }
            },
        },
    )
    monkeypatch.setenv("JARVIS_QUOTA_CAPS_PATH", str(caps_path))
    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(state_path))

    results = doctor.check_quota_caps()
    stale_warns = [r for r in results if r.warn and "calibration" in r.name]
    assert len(stale_warns) == 1
    w = stale_warns[0]
    assert w.name == "quota-caps:calibration:claude.rolling_7d"
    assert "stale" in w.message
    assert "calibrate-claude" in w.remediation
    assert "--window rolling_7d" in w.remediation


def test_quota_caps_check_skips_no_signal_windows(doctor, monkeypatch, tmp_path):
    """Windows with observed_native == 0 are benign — no cap needed.
    Don't pollute doctor output with false positives for vendors the
    operator hasn't started using."""
    caps_path = tmp_path / "quota_caps.json"
    state_path = tmp_path / "quota_state.json"
    caps_empty = {"schema_version": 1, "defaults": {}, "claude": {}, "codex": {},
                  "gemini": {}, "grok": {}}
    _write(caps_path, caps_empty)
    _write(
        state_path,
        _state_with_signal(
            vendors={
                "gemini": {
                    "tier": "code_assist_individuals",
                    "windows": {
                        "rolling_24h": {
                            "kind": "rolling_24h",
                            "observed_native": 0,
                            "observed_unit": "requests",
                            "models": {},
                            "diagnostics": {"signal": "ok"},
                        }
                    },
                },
                "grok": {"tier": "absent", "windows": {}},
            }
        ),
    )
    monkeypatch.setenv("JARVIS_QUOTA_CAPS_PATH", str(caps_path))
    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(state_path))

    results = doctor.check_quota_caps()
    assert not any(r.warn for r in results), [
        (r.name, r.message) for r in results if r.warn
    ]


def test_quota_caps_check_missing_state_file_is_benign(doctor, monkeypatch, tmp_path):
    """Fresh clone state: no quota_state.json yet. Don't fail the doctor —
    PASS with a hint to run quota_check."""
    state_path = tmp_path / "quota_state.json"
    caps_path = tmp_path / "quota_caps.json"
    monkeypatch.setenv("JARVIS_QUOTA_CAPS_PATH", str(caps_path))
    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(state_path))

    results = doctor.check_quota_caps()
    assert len(results) == 1
    assert results[0].ok and not results[0].warn
    assert "quota_check" in results[0].message


# ── acceptance ─────────────────────────────────────────────────────────────


def test_acceptance_three_known_missing_pairs_from_parent_plan(
    doctor, monkeypatch, tmp_path, _isolated_calibration
):
    """Acceptance #4: replay the parent plan 2026-05-11-001 dispatch state
    where (a) claude.max_20x.rolling_5h had signal but no cap, (b)
    codex.plus.rolling_7d had signal but no cap, (c) claude.rolling_7d
    calibration was stale. Doctor must surface exactly those three WARN
    findings."""
    caps_path = tmp_path / "quota_caps.json"
    state_path = tmp_path / "quota_state.json"
    calibration_path = _isolated_calibration
    # Starter caps shape: claude rolling_7d + codex rolling_5h + gemini.
    _write(caps_path, CAPS_SCHEMA)
    stale_stamp = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=11)
    ).isoformat()
    _write(
        state_path,
        _state_with_signal(
            vendors={
                "claude": {
                    "tier": "max_20x",
                    "windows": {
                        "rolling_7d": _claude_window(
                            observed=600_000_000.0,
                            confidence="manual",
                            ratio=2.22e-08,
                            stamped_at=stale_stamp,
                        ),
                        "rolling_5h": _claude_window(
                            observed=12_000_000.0,
                            confidence="uncalibrated",
                        ),
                    },
                },
                "codex": {
                    "tier": "plus",
                    "windows": {
                        "rolling_5h": _codex_window(observed=120_000_000.0),
                        "rolling_7d": _codex_window(
                            observed=500_000_000.0, kind="rolling_7d"
                        ),
                    },
                },
            }
        ),
    )
    _write(
        calibration_path,
        {
            "schema_version": 1,
            "claude": {
                "rolling_7d": {
                    "ratio": 2.22e-08,
                    "confidence": "manual",
                    "source": "operator_dashboard_sample",
                    "dashboard_pct": 13.0,
                    "observed_native": 585_551_755.7,
                    "stamped_at": stale_stamp,
                }
            },
        },
    )
    monkeypatch.setenv("JARVIS_QUOTA_CAPS_PATH", str(caps_path))
    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(state_path))

    results = doctor.check_quota_caps()
    warn_names = {r.name for r in results if r.warn}
    assert "quota-caps:claude.max_20x.rolling_5h" in warn_names
    assert "quota-caps:codex.plus.rolling_7d" in warn_names
    assert "quota-caps:calibration:claude.rolling_7d" in warn_names


# ── runner wiring ──────────────────────────────────────────────────────────


def test_run_all_checks_includes_quota_caps_finding(doctor, monkeypatch, tmp_path):
    """run_all_checks must call check_quota_caps so the finding shows up
    in the default doctor output, not gated behind --include-projects."""
    caps_path = tmp_path / "quota_caps.json"
    state_path = tmp_path / "quota_state.json"
    _write(caps_path, CAPS_SCHEMA)
    _write(
        state_path,
        _state_with_signal(
            vendors={
                "codex": {
                    "tier": "plus",
                    "windows": {
                        "rolling_7d": _codex_window(
                            observed=99_000.0, kind="rolling_7d"
                        )
                    },
                }
            }
        ),
    )
    monkeypatch.setenv("JARVIS_QUOTA_CAPS_PATH", str(caps_path))
    monkeypatch.setenv("JARVIS_QUOTA_STATE_PATH", str(state_path))

    results = doctor.run_all_checks(skip_auth=True)
    quota_finds = [r for r in results if r.name.startswith("quota-caps")]
    assert quota_finds, "check_quota_caps should run as part of run_all_checks"
    assert any(r.warn for r in quota_finds)


# ── CLI entrypoint regression (F001 i1 auditor finding) ───────────────────


def test_dontpanic_doctor_cli_entrypoint_does_not_attribute_error(tmp_path):
    """Regression for prior auditor finding: ``python -m dontpanic_orchestrate
    doctor`` exited with ``AttributeError: module 'jarvis_doctor' has no
    attribute 'run_all_checks'`` because ``scripts/jarvis_doctor.py`` was a
    runpy shim with no module attributes. The CLI now imports
    ``dontpanic_doctor`` directly; the legacy alias also re-exports the
    public API. This test exercises the real module entry-point in a
    subprocess so a future regression of either path is caught."""
    caps_path = tmp_path / "quota_caps.json"
    state_path = tmp_path / "quota_state.json"
    _write(caps_path, CAPS_SCHEMA)
    _write(
        state_path,
        _state_with_signal(
            vendors={
                "codex": {
                    "tier": "plus",
                    "windows": {"rolling_5h": _codex_window(observed=1_000.0)},
                }
            }
        ),
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "scripts")
    env["JARVIS_QUOTA_CAPS_PATH"] = str(caps_path)
    env["JARVIS_QUOTA_STATE_PATH"] = str(state_path)
    # Isolate from operator state: empty dontpanic/jarvis homes + an
    # ephemeral calibration file means no real ~/.jarvis bleed-in.
    dontpanic_home = tmp_path / "dontpanic_home"
    dontpanic_home.mkdir()
    env["DONTPANIC_HOME"] = str(dontpanic_home)
    env["JARVIS_HOME"] = str(dontpanic_home)

    proc = subprocess.run(
        [sys.executable, "-m", "dontpanic_orchestrate", "doctor",
         "--skip-auth", "--json"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=60,
    )
    # Exit code 0|1|2 is fine (WARN/FAIL is allowed). The regression we
    # are guarding against is AttributeError → non-zero exit with no JSON.
    assert "AttributeError" not in proc.stderr, proc.stderr
    assert "no attribute 'run_all_checks'" not in proc.stderr, proc.stderr
    payload = json.loads(proc.stdout)
    assert "checks" in payload
    quota_findings = [c for c in payload["checks"]
                      if c["name"].startswith("quota-caps")]
    assert quota_findings, "doctor CLI must surface quota-caps check"


def test_jarvis_doctor_legacy_alias_exposes_run_all_checks():
    """``import jarvis_doctor`` must yield a real module with
    ``run_all_checks`` callable — not the pre-fix runpy shim that only
    re-executed dontpanic_doctor.py under __main__."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        # Drop any prior fixture-loaded jarvis_doctor so the legacy file
        # gets a fresh import.
        sys.modules.pop("jarvis_doctor", None)
        sys.modules.pop("dontpanic_doctor", None)
        import importlib as _il

        jd = _il.import_module("jarvis_doctor")
        assert callable(getattr(jd, "run_all_checks", None)), (
            "legacy alias must re-export run_all_checks"
        )
        assert callable(getattr(jd, "render_json", None))
        assert callable(getattr(jd, "compute_strict_exit", None))
        assert callable(getattr(jd, "check_quota_caps", None))
    finally:
        sys.path.pop(0)
        sys.modules.pop("jarvis_doctor", None)
        sys.modules.pop("dontpanic_doctor", None)
