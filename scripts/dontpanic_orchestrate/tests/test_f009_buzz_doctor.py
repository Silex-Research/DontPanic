"""F009: Buzz setup/doctor surface — advisory WARN, never a hard fail.

Contract under test:
- Unconfigured Buzz (missing ``~/.dontpanic/buzz.json``) yields an advisory
  WARN whose remediation names the private-community checklist (F005) and
  the expected buzz.json keys — never a FAIL, never secret values.
- Configured Buzz is ok.
- ``DONTPANIC_SKIP_BUZZ`` silences the check for CI/headless runs.
- Malformed or key-incomplete config stays advisory (WARN, ok=True).
- The check never writes anything (no default public community URL).
- Both exit-code surfaces (``dontpanic doctor`` wrapper and the bare
  script's ``--strict-codes`` path) strip the buzz WARN so a hard install
  never fails solely because Buzz is absent.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCTOR_PATH = REPO_ROOT / "scripts" / "dontpanic_doctor.py"


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
def _no_skip_env(monkeypatch):
    monkeypatch.delenv("DONTPANIC_SKIP_BUZZ", raising=False)


# relay_url is the private community's relay — in Buzz the relay URL is the
# community/workspace authority (no separate community key); channels are
# channel UUIDs.
VALID_CONFIG = {
    "relay_url": "https://relay.example.internal",
    "channels": [
        "0f5e8a3c-9d41-4c7b-8a2e-1d3f5b7c9e01",
        "b2c4d6e8-1a3b-4c5d-8e7f-9a0b1c2d3e4f",
    ],
    "reporter_key_ref": "env:BUZZ_PRIVATE_KEY",
}


def test_missing_config_is_advisory_warn_with_private_community_remediation(
    doctor, tmp_path
):
    result = doctor.check_buzz_config(config_path=tmp_path / "buzz.json")
    assert result.ok is True, "missing Buzz config must never FAIL"
    assert result.warn is True
    assert result.name == "buzz-config"
    assert "strongly recommended" in result.message.lower()
    # Remediation points at the F005 private-community checklist and names
    # the buzz.json keys.
    rem = result.remediation
    assert "private" in rem.lower()
    assert "GETTING_STARTED" in rem
    assert "buzz.json" in rem
    for key in ("relay_url", "channels", "reporter_key_ref"):
        assert key in rem
    # The documented CI silence env is part of the fix path.
    assert "DONTPANIC_SKIP_BUZZ" in rem


def test_missing_config_check_writes_nothing(doctor, tmp_path):
    """No default config (and so no default public community URL) is written."""
    path = tmp_path / "buzz.json"
    doctor.check_buzz_config(config_path=path)
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


def test_no_public_community_url_in_output(doctor, tmp_path):
    """The advisory must never steer operators at a maintainer/public
    community as the notify default."""
    result = doctor.check_buzz_config(config_path=tmp_path / "buzz.json")
    text = (result.message + " " + result.remediation).lower()
    assert "silex" not in text
    assert "buzz.xyz/c" not in text  # no community URL, only the product domain


def test_configured_buzz_is_ok(doctor, tmp_path):
    path = tmp_path / "buzz.json"
    path.write_text(json.dumps(VALID_CONFIG), encoding="utf-8")
    result = doctor.check_buzz_config(config_path=path)
    assert result.ok is True
    assert result.warn is False


def test_skip_env_silences_for_ci(doctor, tmp_path, monkeypatch):
    monkeypatch.setenv("DONTPANIC_SKIP_BUZZ", "1")
    result = doctor.check_buzz_config(config_path=tmp_path / "buzz.json")
    assert result.ok is True
    assert result.warn is False
    assert "DONTPANIC_SKIP_BUZZ" in result.message


def test_malformed_json_stays_advisory(doctor, tmp_path):
    path = tmp_path / "buzz.json"
    path.write_text("{not json", encoding="utf-8")
    result = doctor.check_buzz_config(config_path=path)
    assert result.ok is True, "a broken buzz.json must stay advisory, never FAIL"
    assert result.warn is True


def test_missing_keys_warn_names_keys_but_not_values(doctor, tmp_path):
    path = tmp_path / "buzz.json"
    partial = {"relay_url": "wss://relay.example.internal"}
    path.write_text(json.dumps(partial), encoding="utf-8")
    result = doctor.check_buzz_config(config_path=path)
    assert result.ok is True
    assert result.warn is True
    for key in ("channels", "reporter_key_ref"):
        assert key in result.message + result.remediation


def test_key_complete_but_null_values_stays_advisory_warn(doctor, tmp_path):
    """i0 audit finding: all expected keys present but every value null must
    NOT report configured — the config is unusable."""
    path = tmp_path / "buzz.json"
    path.write_text(json.dumps(dict.fromkeys(VALID_CONFIG)), encoding="utf-8")
    result = doctor.check_buzz_config(config_path=path)
    assert result.ok is True
    assert result.warn is True, "null-valued config must not PASS as configured"
    for key in ("relay_url", "channels", "reporter_key_ref"):
        assert key in result.message


@pytest.mark.parametrize(
    ("key", "bad_value"),
    [
        ("relay_url", ""),
        ("relay_url", "   "),
        ("relay_url", 42),
        ("channels", []),
        ("channels", "not-a-list"),
        ("channels", ["#ok", ""]),
        ("channels", [7]),
        ("reporter_key_ref", ""),
        ("reporter_key_ref", ["env:X"]),
    ],
)
def test_unusable_value_warns_and_names_key_not_value(doctor, tmp_path, key, bad_value):
    path = tmp_path / "buzz.json"
    path.write_text(json.dumps(dict(VALID_CONFIG, **{key: bad_value})), encoding="utf-8")
    result = doctor.check_buzz_config(config_path=path)
    assert result.ok is True
    assert result.warn is True
    assert key in result.message
    # Secret-free: the offending VALUE never appears, only the key name.
    if isinstance(bad_value, str) and bad_value.strip():
        assert bad_value not in result.message


def test_invalid_utf8_stays_advisory_warn(doctor, tmp_path):
    """i0 audit finding: non-UTF-8 bytes in buzz.json crashed the doctor
    (UnicodeDecodeError) instead of yielding the advisory WARN."""
    path = tmp_path / "buzz.json"
    path.write_bytes(b"\xff\xfe\x00garbage")
    result = doctor.check_buzz_config(config_path=path)
    assert result.ok is True
    assert result.warn is True
    assert result.remediation == doctor._BUZZ_REMEDIATION


def test_config_values_never_echoed(doctor, tmp_path):
    """No secrets in output: config VALUES must never appear in the check's
    message or remediation, only key names."""
    path = tmp_path / "buzz.json"
    secretish = dict(VALID_CONFIG, reporter_key_ref="nsec1deadbeefcafe")
    path.write_text(json.dumps(secretish), encoding="utf-8")
    result = doctor.check_buzz_config(config_path=path)
    text = result.message + " " + result.remediation
    assert "nsec1deadbeefcafe" not in text
    assert "https://relay.example.internal" not in text


def test_run_all_checks_includes_buzz_config_name(doctor):
    """The battery wires the probe in (source-level pin; running the full
    battery here would probe auth/subprocess surfaces)."""
    src = DOCTOR_PATH.read_text(encoding="utf-8")
    assert "check_buzz_config()" in src.split("def run_all_checks", 1)[1]


def test_cli_wrapper_strips_buzz_warn_from_exit(monkeypatch):
    """`dontpanic doctor` exits 0 when the ONLY warn is buzz-config —
    a hard install never fails solely because Buzz is absent."""
    from dontpanic_orchestrate import cli

    doctor = _load_doctor()
    buzz_warn = doctor._warn("buzz-config", "not configured", "see checklist")
    stub = types.ModuleType("jarvis_doctor")
    stub.run_all_checks = lambda **kwargs: [buzz_warn]
    stub.render_text = lambda results: "rendered"
    stub.render_json = lambda results: "[]"
    stub.compute_strict_exit = doctor.compute_strict_exit
    monkeypatch.setitem(sys.modules, "jarvis_doctor", stub)

    assert cli._doctor_main([]) == 0


def test_bare_script_strict_codes_strips_buzz_warn(doctor, monkeypatch, capsys):
    """`python3 scripts/dontpanic_doctor.py --strict-codes` likewise exits 0
    when the only warn is the advisory buzz probe."""
    buzz_warn = doctor._warn("buzz-config", "not configured", "see checklist")
    monkeypatch.setattr(doctor, "run_all_checks", lambda **kwargs: [buzz_warn])
    assert doctor.main(["--strict-codes"]) == 0
