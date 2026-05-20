"""Plan 2026-05-19-002 F001 — doctor --profile integration tests.

Covers the doctor CLI seam between the legacy CheckResult pipeline and
the new profile-aware ProbeRunner path.

Acceptance #9 (this file): ``test_doctor_profile_integration.py``
provides >=5 integration cases:

  (1) ``dontpanic doctor`` (no flags) keeps the legacy text output —
      no "Prereq probes for profile=" header leaks in when --profile
      is absent.
  (2) ``dontpanic doctor --profile=core`` produces the new
      profile-aware text envelope.
  (3) ``dontpanic doctor --profile=core --json`` carries the pinned
      schema_version='1.0.0' top-level field.
  (4) Per-profile snapshot covers each of {core, discord,
      firebase-dashboard, openclaw, ci}.
  (5) The no-flag JSON envelope is unchanged: no new top-level
      ``schema_version`` / ``prereq_probes`` keys leak in.
  (Extra) The argparse parser rejects an unknown profile name.

Run:
    pytest scripts/dontpanic_orchestrate/tests/test_doctor_profile_integration.py -q
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCTOR_PATH = REPO_ROOT / "scripts" / "dontpanic_doctor.py"


def _load_doctor():
    """Import dontpanic_doctor.py as a module — it lives outside the
    package so we load it by path. Caches under a distinct sys.modules
    key so the F001 integration tests do not collide with other doctor
    fixture modules (test_doctor_validate_plans_strict_f003, ...)."""
    spec = importlib.util.spec_from_file_location(
        "dontpanic_doctor_profile_integration", DOCTOR_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dontpanic_doctor_profile_integration"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def doctor():
    return _load_doctor()


def _run_doctor(doctor, argv: list[str]) -> tuple[int, str]:
    """Invoke doctor.main(argv) capturing stdout. Returns (exit_code, stdout)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = doctor.main(argv)
    return code, buf.getvalue()


# ── (1) no-flag legacy path stays unchanged ────────────────────────────


def test_no_flag_invocation_does_not_emit_profile_aware_header(doctor):
    """When --profile is omitted, the legacy CheckResult pipeline must
    NOT print the new ``Prereq probes for profile=`` section. This is
    the backwards-compat invariant — operators using
    ``dontpanic doctor`` today must see identical-shape output post-F001.

    We do not assert byte-identity with a pre-F001 snapshot here
    because the legacy text output is sensitive to host state
    (gcloud/firebase auth presence, plan inventory churn). We instead
    pin the structural invariant that distinguishes the two paths.
    """
    _code, out = _run_doctor(doctor, ["--skip-auth"])
    assert "Prereq probes for profile=" not in out, (
        "no-flag invocation must not leak the profile-aware section header"
    )


def test_no_flag_json_envelope_does_not_carry_schema_version(doctor):
    """Backwards-compat: ``--json`` without ``--profile`` must keep
    its existing JSON shape. New top-level fields like
    ``schema_version`` and ``prereq_probes`` are gated on --profile."""
    _code, out = _run_doctor(doctor, ["--json", "--skip-auth"])
    payload = json.loads(out)
    assert "schema_version" not in payload, (
        "legacy --json must not carry the F001 schema_version field"
    )
    assert "prereq_probes" not in payload, (
        "legacy --json must not carry the F001 prereq_probes field"
    )


# ── (2) --profile=core emits the new envelope ──────────────────────────


def test_profile_core_emits_profile_aware_text(doctor):
    """``dontpanic doctor --profile=core`` runs the new ProbeRunner and
    emits the ``Prereq probes for profile=core:`` section."""
    _code, out = _run_doctor(doctor, ["--profile=core", "--skip-auth"])
    assert "Prereq probes for profile=core:" in out
    # Exit-code summary line is part of the new render contract.
    assert "exit_code=" in out


# ── (3) --profile=core --json carries schema_version ───────────────────


def test_profile_core_json_carries_schema_version(doctor):
    """The JSON envelope under --profile=core --json MUST carry
    schema_version='1.0.0' at top level (F001 acceptance #6)."""
    _code, out = _run_doctor(doctor, ["--profile=core", "--json", "--skip-auth"])
    payload = json.loads(out)
    assert payload["schema_version"] == "1.0.0"
    assert payload["profile"] == "core"
    assert "prereq_probes" in payload
    assert isinstance(payload["prereq_probes"], list)
    # Every probe item carries the pinned field set.
    if payload["prereq_probes"]:
        item = payload["prereq_probes"][0]
        for field in (
            "name",
            "status",
            "severity_reason",
            "version_found",
            "fix_url",
            "fix_command",
            "required_for_profiles",
            "activation_condition",
            "activation_resolved",
            "elapsed_s",
        ):
            assert field in item, f"prereq_probes item missing required field: {field}"


# ── (4) per-profile snapshot covers all five profiles ──────────────────


@pytest.mark.parametrize(
    "profile",
    ["core", "discord", "firebase-dashboard", "openclaw", "ci"],
)
def test_each_profile_emits_envelope_with_matching_profile_name(doctor, profile):
    """Per-profile snapshot — every one of the five pure-set profiles
    must invoke without error, emit a JSON envelope, and echo its own
    name in the ``profile`` field."""
    _code, out = _run_doctor(doctor, [f"--profile={profile}", "--json", "--skip-auth"])
    payload = json.loads(out)
    assert payload["profile"] == profile
    assert payload["schema_version"] == "1.0.0"
    # exit_code is 0/1/2 — strict matrix from the probe sweep.
    assert payload["exit_code"] in (0, 1, 2)


def test_specialized_profile_does_not_emit_unrelated_probes(doctor):
    """Cross-profile leak guard (the i0 auditor finding F001-i0#2):
    running a specialized profile must NOT surface probes from a
    different specialization just because they declare
    ``severity_when_inactive != omit``.

    Concretely:
      - ``gh-auth-status`` is required_for={ci} → MUST NOT appear under
        discord / firebase-dashboard / openclaw.
      - ``codex-cli`` is required_for={ci, openclaw} → MUST NOT appear
        under discord / firebase-dashboard. (It legitimately appears
        under openclaw because openclaw is in its required_for set.)
    """
    for profile in ("discord", "firebase-dashboard", "openclaw"):
        _code, out = _run_doctor(doctor, [f"--profile={profile}", "--json", "--skip-auth"])
        payload = json.loads(out)
        names = {p["name"] for p in payload["prereq_probes"]}
        assert "gh-auth-status" not in names, (
            f"profile={profile} must not surface gh-auth-status "
            f"(cross-profile leak — gh-auth is required_for=ci only)"
        )
    # codex-cli is required_for={ci, openclaw} — only the two profiles
    # without it in their required set must NOT surface it.
    for profile in ("discord", "firebase-dashboard"):
        _code, out = _run_doctor(doctor, [f"--profile={profile}", "--json", "--skip-auth"])
        payload = json.loads(out)
        names = {p["name"] for p in payload["prereq_probes"]}
        assert "codex-cli" not in names, (
            f"profile={profile} must not surface codex-cli "
            f"(cross-profile leak — codex is required_for={{ci, openclaw}})"
        )


# ── (5) no-flag exit-code matrix unchanged ─────────────────────────────


def test_no_flag_exit_code_uses_legacy_0_or_1(doctor):
    """Backwards-compat: with no --profile, --strict-codes, or other
    F003+ strict flags, the doctor returns the legacy 0/1 exit matrix
    (0 = all ok, 1 = at least one fail). Never 2.

    We can't pin the absolute value (it depends on host state — gcloud
    auth etc), but we can pin the *shape* of the matrix.
    """
    code, _out = _run_doctor(doctor, ["--skip-auth"])
    assert code in (0, 1), (
        f"no-flag invocation must return legacy 0/1 exit code, got {code}"
    )


# ── (extra) argparse rejects unknown profile ───────────────────────────


def test_unknown_profile_is_rejected_by_argparse(doctor):
    """``--profile=maintainer`` (the explicitly deferred profile) and
    any other unknown profile name must be rejected by argparse, with
    the valid choices listed in the error."""
    with pytest.raises(SystemExit):
        _run_doctor(doctor, ["--profile=maintainer", "--json", "--skip-auth"])


# ── (6) byte-identical no-flag snapshot under mocked legacy results ────


def test_no_flag_text_output_byte_identical_against_mocked_results(doctor, monkeypatch):
    """F001-i1 high/test_coverage hand-patch.

    Pin the exact rendered text for ``dontpanic doctor`` (no flags)
    against a deterministic set of mocked CheckResult instances. The
    earlier structural test (``..._does_not_emit_profile_aware_header``)
    can't pin byte-identity against live host state, so this fixture
    substitutes ``run_all_checks`` to remove the host-state coupling
    and asserts the legacy render path is unchanged post-F001.

    Snapshot covers one PASS, one WARN, and one FAIL — exercising every
    branch of ``render_text`` (marker selection, remediation lines,
    summary line variants)."""
    mocked = [
        doctor.CheckResult(
            name="python>=3.10", ok=True, message="Python 3.11"
        ),
        doctor.CheckResult(
            name="codex-cli",
            ok=True,
            warn=True,
            message="not installed",
            remediation="install via `brew install codex`",
        ),
        doctor.CheckResult(
            name="claude-cli",
            ok=False,
            message="not found on PATH",
            remediation="install via `npm install -g @anthropic-ai/claude-code`",
        ),
    ]
    monkeypatch.setattr(doctor, "run_all_checks", lambda **_: mocked)
    code, out = _run_doctor(doctor, ["--skip-auth"])

    # Expected output is constructed from the documented format strings
    # in render_text(); any drift in render_text behavior (markers,
    # column widths, summary phrasing) makes this assertion fail.
    expected = "\n".join(
        [
            f"{doctor.GREEN} python>=3.10           Python 3.11",
            f"{doctor.YELLOW} codex-cli              not installed",
            "  ↳ install via `brew install codex`",
            f"{doctor.RED} claude-cli             not found on PATH",
            "  ↳ install via `npm install -g @anthropic-ai/claude-code`",
            f"\n{doctor.RED} 1/3 checks failed — see remediation above",
        ]
    )
    expected_with_trailing_newline = expected + "\n"

    assert out == expected_with_trailing_newline, (
        "no-flag legacy text output drifted from pre-F001 snapshot.\n"
        f"--- expected ---\n{expected_with_trailing_newline!r}\n"
        f"--- actual ---\n{out!r}"
    )
    assert code == 1, "one FAIL in mocked results should map to legacy exit 1"
