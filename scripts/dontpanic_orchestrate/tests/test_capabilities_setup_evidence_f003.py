"""Plan 2026-05-22-004 F003 — setup-run evidence record tests.

Covers the F003 acceptance matrix:
  #1 Evidence records capability_id, attempted steps, skipped
     human-required steps, before/after status, and next actions.
  #2 No secret values are persisted (sanitization + requires-as-names).
  #3 Tests cover evidence shape.

Acceptance #4 (parent roadmap D-entry) lives in the roadmap's
decisions.jsonl and is verified by the auditor reading the file
directly, not by automated test assertion.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import os
import stat
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from dontpanic_orchestrate import capabilities_setup as cs_setup
from dontpanic_orchestrate import capabilities_setup_evidence as cs_evidence
from dontpanic_orchestrate import capabilities_setup_runner as cs_runner
from dontpanic_orchestrate import capabilities_status as cs_status
from dontpanic_orchestrate.capabilities import CapabilityManifest, SetupStep, load_capabilities

REPO_ROOT = Path(__file__).resolve().parents[3]


# ── fixtures ─────────────────────────────────────────────────────────────


def _firebase_manifest() -> CapabilityManifest:
    return load_capabilities(REPO_ROOT).require("firebase-dashboard")


def _linear_manifest() -> CapabilityManifest:
    return load_capabilities(REPO_ROOT).require("linear")


def _make_status_probe(
    statuses: list[cs_status.CapabilityStatus],
) -> cs_runner.StatusProbe:
    """Return a deterministic probe that walks ``statuses`` in order."""

    state = {"i": 0}

    def _probe(manifest: CapabilityManifest) -> cs_status.CapabilityStatusResult:
        idx = min(state["i"], len(statuses) - 1)
        state["i"] += 1
        return cs_status.CapabilityStatusResult(
            capability_id=manifest.id,
            status=statuses[idx],
            owner_boundary={
                "dontpanic_core": manifest.owner_boundary.dontpanic_core,
                "adapter": manifest.owner_boundary.adapter,
                "operator": manifest.owner_boundary.operator,
            },
            configured=(),
            missing=(),
            automatable=(),
            human_required=(),
            pending_probes=(),
            next_actions=(),
        )

    return _probe


class _RecorderRunner:
    """:class:`CommandRunner` that returns canned output."""

    def __init__(self, *, exit_code: int = 0, stdout: str = "", stderr: str = "") -> None:
        self._exit_code = exit_code
        self._stdout = stdout
        self._stderr = stderr
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv) -> cs_runner.CommandResult:
        self.calls.append(tuple(argv))
        return cs_runner.CommandResult(
            exit_code=self._exit_code,
            stdout=self._stdout,
            stderr=self._stderr,
        )


def _firebase_report(
    *,
    stdout: str = "firebase-tools@13.0.0 installed",
    stderr: str = "",
    exit_code: int = 0,
) -> cs_runner.AutomateSafeReport:
    manifest = _firebase_manifest()
    runner = _RecorderRunner(exit_code=exit_code, stdout=stdout, stderr=stderr)
    probe = _make_status_probe(
        [
            cs_status.CapabilityStatus.NEEDS_SETUP,
            cs_status.CapabilityStatus.NEEDS_SETUP,
            cs_status.CapabilityStatus.READY,
        ]
    )
    return cs_runner.run_automate_safe(
        manifest,
        confirm=True,
        command_runner=runner,
        status_probe=probe,
    )


# ── build_evidence_record shape (acceptance #1, #3) ──────────────────────


def test_build_evidence_record_has_required_top_level_fields():
    """Acceptance #1/#3: every top-level field documented in the
    plan exists on the record."""
    report = _firebase_report()
    manifest = _firebase_manifest()

    evidence = cs_evidence.build_evidence_record(report, manifest)
    payload = evidence.to_json_dict()

    for field in (
        "schema_version",
        "generated_at",
        "capability_id",
        "confirm",
        "before_status",
        "after_status",
        "attempted_steps",
        "denied_steps",
        "skipped_human_required",
        "next_human_actions",
        "declared_requires",
    ):
        assert field in payload, f"missing top-level field {field!r}"
    assert payload["schema_version"] == cs_evidence.EVIDENCE_SCHEMA_VERSION
    assert payload["capability_id"] == "firebase-dashboard"
    assert payload["confirm"] is True
    assert payload["before_status"] in {"needs_setup", "ready", "blocked"}


def test_build_evidence_record_generated_at_is_iso8601_z():
    """``generated_at`` is the operator-stable timestamp the filename uses."""
    fixed = _dt.datetime(2026, 5, 22, 23, 4, 5, tzinfo=_dt.timezone.utc)
    evidence = cs_evidence.build_evidence_record(
        _firebase_report(), _firebase_manifest(), now=fixed
    )

    assert evidence.generated_at == "2026-05-22T23:04:05Z"


def test_build_evidence_record_attempted_step_includes_command_and_argv_and_exit_code():
    """Acceptance #1: attempted steps name the step, its command, and exit code."""
    report = _firebase_report()
    manifest = _firebase_manifest()

    evidence = cs_evidence.build_evidence_record(report, manifest)
    attempted = {step["step_id"]: step for step in evidence.attempted_steps}

    # install_firebase_cli is the canonical allowlisted automatable step.
    assert "install_firebase_cli" in attempted
    ifc = attempted["install_firebase_cli"]
    assert ifc["decision"] == "executed"
    assert ifc["command_template"] == "npm install -g firebase-tools"
    assert ifc["argv"] == ["npm", "install", "-g", "firebase-tools"]
    assert ifc["exit_code"] == 0
    assert ifc["status_after"] in {"needs_setup", "ready", "blocked"}
    # stdout_tail surfaces the canned output unmodified (no secret pattern).
    assert "firebase-tools" in (ifc["stdout_tail"] or "")


def test_build_evidence_record_skipped_human_required_carries_reason():
    """Acceptance #1: human-required skips name the step and the reason."""
    report = _firebase_report()
    manifest = _firebase_manifest()

    evidence = cs_evidence.build_evidence_record(report, manifest)
    by_id = {s["step_id"]: s for s in evidence.skipped_human_required}

    assert "firebase_login" in by_id
    fl = by_id["firebase_login"]
    assert fl["decision"] == "skipped_human_required"
    assert "interactive browser" in fl["reason"]
    assert "smoke_test" in by_id  # the second human-required step


def test_build_evidence_record_denied_steps_record_reason():
    """Acceptance #1: denied automatable steps surface the policy reason."""
    report = _firebase_report()
    manifest = _firebase_manifest()

    evidence = cs_evidence.build_evidence_record(report, manifest)
    by_id = {s["step_id"]: s for s in evidence.denied_steps}

    # select_target_project has the <YOUR_FIREBASE_PROJECT_ID> placeholder.
    assert "select_target_project" in by_id
    assert "placeholder" in by_id["select_target_project"]["reason"].lower()
    # install_gcloud_cli uses curl | bash — shell metacharacter denial.
    assert "install_gcloud_cli" in by_id
    assert "shell metacharacter" in by_id["install_gcloud_cli"]["reason"].lower()


def test_build_evidence_record_next_human_actions_unions_human_and_denied():
    """Acceptance #1: next-actions list = human-required skips + denied steps."""
    report = _firebase_report()
    manifest = _firebase_manifest()

    evidence = cs_evidence.build_evidence_record(report, manifest)

    kinds_by_id = {a["step_id"]: a["kind"] for a in evidence.next_human_actions}
    # human-required skip → human_required kind
    assert kinds_by_id.get("firebase_login") == "human_required"
    assert kinds_by_id.get("smoke_test") == "human_required"
    # denied automatable → denied_unsafe kind, surfacing manifest command template
    assert kinds_by_id.get("select_target_project") == "denied_unsafe"
    # The denied entry preserves the manifest's command template with placeholder
    select_entry = next(
        a for a in evidence.next_human_actions if a["step_id"] == "select_target_project"
    )
    assert "<YOUR_FIREBASE_PROJECT_ID>" in (select_entry["command_template"] or "")


def test_build_evidence_record_linear_covers_register_adapter_and_paste_token():
    """Linear is the second backfilled manifest — non-Firebase coverage."""
    manifest = _linear_manifest()
    runner = _RecorderRunner(exit_code=0)
    probe = _make_status_probe([cs_status.CapabilityStatus.NEEDS_SETUP])
    report = cs_runner.run_automate_safe(
        manifest,
        confirm=True,
        command_runner=runner,
        status_probe=probe,
    )

    evidence = cs_evidence.build_evidence_record(report, manifest)
    by_id_skipped = {s["step_id"]: s for s in evidence.skipped_human_required}
    by_id_denied = {s["step_id"]: s for s in evidence.denied_steps}

    # paste_api_token is the canonical human-required Linear step.
    assert "paste_api_token" in by_id_skipped
    assert "API token" in by_id_skipped["paste_api_token"]["reason"]
    # register_adapter has a placeholder → denied automatable.
    assert "register_adapter" in by_id_denied


# ── secret sanitization (acceptance #2) ──────────────────────────────────


def test_build_evidence_record_redacts_bearer_token_in_stdout():
    """Acceptance #2: a JWT-shaped bearer in stdout must NOT survive."""
    bearer = (
        "Authorization: Bearer eyJhbGciOi.eyJzdWIiOi.ZjU2ZjUxZTFm"
    )
    report = _firebase_report(stdout=f"deploy ok {bearer}")
    manifest = _firebase_manifest()

    evidence = cs_evidence.build_evidence_record(report, manifest)
    payload_text = json.dumps(evidence.to_json_dict())

    assert "eyJhbGciOi.eyJzdWIiOi.ZjU2ZjUxZTFm" not in payload_text
    assert "Bearer eyJ" not in payload_text
    assert "[redacted-secret]" in payload_text


def test_build_evidence_record_redacts_token_equals_value_in_stdout():
    """``token=...``/``api_key=...`` keep the *key* but drop the value."""
    report = _firebase_report(
        stdout="config token=abcdef1234567890 saved",
        stderr="DONTPANIC_API_KEY=supersecretvalue123 received",
    )
    manifest = _firebase_manifest()

    evidence = cs_evidence.build_evidence_record(report, manifest)
    payload_text = json.dumps(evidence.to_json_dict())

    assert "abcdef1234567890" not in payload_text
    assert "supersecretvalue123" not in payload_text
    # The key half is preserved so the operator sees which token was elided.
    assert "token=[redacted-secret]" in payload_text


def test_build_evidence_record_redacts_common_credential_tokens():
    """Common credential-shaped tokens must be redacted."""
    secrets_to_redact = [
        "Bearer abcdefghijklmnop",
        "token=abcdef1234567890",
        "xoxb-1234567890-abcdefghijklm",
        "DONTPANIC_API_KEY=supersecretvalue123",
    ]
    report = _firebase_report(stdout=" ".join(secrets_to_redact))
    manifest = _firebase_manifest()

    evidence = cs_evidence.build_evidence_record(report, manifest)
    payload_text = json.dumps(evidence.to_json_dict())

    for raw in secrets_to_redact:
        assert raw not in payload_text, f"secret token {raw!r} leaked into evidence"
    assert "[redacted-secret]" in payload_text


def test_build_evidence_record_declared_requires_names_only():
    """``requires`` env entries are *names* the manifest declares —
    the record must never carry the operator's actual env values."""
    manifest = _firebase_manifest()
    report = _firebase_report()

    # Inject what looks like a real value into the operator environment so
    # the assertion fails loudly if the record ever starts reading values.
    env_name = manifest.requires.env[0]  # DONTPANIC_FIREBASE_PROJECT
    secret_value = "my-prod-firebase-project-supersecret-value"  # noqa: S105 — sentinel string for leak assertion, not a real credential
    os.environ[env_name] = secret_value
    try:
        evidence = cs_evidence.build_evidence_record(report, manifest)
        payload_text = json.dumps(evidence.to_json_dict())
    finally:
        os.environ.pop(env_name, None)

    assert env_name in evidence.declared_requires["env"]
    assert secret_value not in payload_text


def test_build_evidence_record_redacts_token_in_command_template_and_argv():
    """Auditor finding: ``command_template`` and ``argv`` are persisted
    raw and can carry credentials. A synthetic manifest whose
    allowlisted command embeds a ``--token=...`` value must NOT round-
    trip that value into the evidence file — neither in
    ``command_template`` nor in any element of ``argv``."""
    base = _firebase_manifest()
    leaky_template = "npm install --token=abcdef1234567890 -g styln-cli"
    synthetic = base.model_copy(
        update={
            "setup_steps": (
                SetupStep(
                    id="leaky_step",
                    what="A step whose template embeds a token argument.",
                    automatable=True,
                    command_template=leaky_template,
                    verify_probe=None,
                    human_required_reason=None,
                ),
            )
        }
    )
    runner = _RecorderRunner(exit_code=0, stdout="", stderr="")
    probe = _make_status_probe([cs_status.CapabilityStatus.NEEDS_SETUP])
    report = cs_runner.run_automate_safe(
        synthetic,
        confirm=True,
        command_runner=runner,
        status_probe=probe,
    )

    evidence = cs_evidence.build_evidence_record(report, synthetic)
    payload_text = json.dumps(evidence.to_json_dict())
    step = next(s for s in evidence.attempted_steps if s["step_id"] == "leaky_step")

    # Raw credential value must not appear anywhere on disk.
    assert "abcdef1234567890" not in payload_text
    # The command_template field still names the option but elides the value.
    assert "[redacted-secret]" in (step["command_template"] or "")
    assert "token=abcdef1234567890" not in (step["command_template"] or "")
    # argv is the executed form — every element must be scrubbed independently.
    assert any("[redacted-secret]" in arg for arg in step["argv"])
    for arg in step["argv"]:
        assert "abcdef1234567890" not in arg
    # Non-secret tokens around the credential survive unchanged.
    assert "npm" in step["argv"]
    assert "install" in step["argv"]


def test_build_evidence_record_redacts_bearer_token_in_argv_positional():
    """Bare positional credential (no ``key=`` prefix) in argv must
    still be redacted by the prefixed-token / JWT pattern."""
    base = _firebase_manifest()
    jwt = "eyJhbGciOiJI.eyJzdWIiOiJ0.ZjU2ZjUxZTFm"
    leaky_template = f"dontpanic capability auth set {jwt}"
    synthetic = base.model_copy(
        update={
            "setup_steps": (
                SetupStep(
                    id="positional_secret",
                    what="Positional credential — no key=value boundary to lean on.",
                    automatable=True,
                    command_template=leaky_template,
                    verify_probe=None,
                    human_required_reason=None,
                ),
            )
        }
    )
    runner = _RecorderRunner(exit_code=0, stdout="", stderr="")
    probe = _make_status_probe([cs_status.CapabilityStatus.NEEDS_SETUP])
    report = cs_runner.run_automate_safe(
        synthetic,
        confirm=True,
        command_runner=runner,
        status_probe=probe,
    )

    evidence = cs_evidence.build_evidence_record(report, synthetic)
    payload_text = json.dumps(evidence.to_json_dict())

    assert jwt not in payload_text
    assert "[redacted-secret]" in payload_text
    step = next(
        s for s in evidence.attempted_steps if s["step_id"] == "positional_secret"
    )
    # The positional secret element collapses to the bare marker.
    assert "[redacted-secret]" in step["argv"]
    # The verb tokens survive.
    assert "dontpanic" in step["argv"]
    assert "set" in step["argv"]


def test_build_evidence_record_redacts_dash_style_and_aws_tokens_in_command_fields():
    """Regression for F003 auditor finding: dash-style OpenAI keys and
    AWS access-key-shaped values must not survive command_template or argv."""
    base = _firebase_manifest()
    bearer_token = "Bearer abcdefghijklmnop"  # noqa: S105 - redaction sentinel
    aws_key = "AKIA1234567890ABCDEF"
    leaky_template = f"echo {bearer_token} {aws_key}"
    synthetic = base.model_copy(
        update={
            "setup_steps": (
                SetupStep(
                    id="dash_and_aws_secret",
                    what="Command field with common secret shapes.",
                    automatable=True,
                    command_template=leaky_template,
                    verify_probe=None,
                    human_required_reason=None,
                ),
            )
        }
    )
    runner = _RecorderRunner(exit_code=0, stdout="", stderr="")
    probe = _make_status_probe([cs_status.CapabilityStatus.NEEDS_SETUP])
    report = cs_runner.run_automate_safe(
        synthetic,
        confirm=True,
        command_runner=runner,
        status_probe=probe,
    )

    evidence = cs_evidence.build_evidence_record(report, synthetic)
    payload_text = json.dumps(evidence.to_json_dict())
    step = next(
        s for s in evidence.attempted_steps if s["step_id"] == "dash_and_aws_secret"
    )

    assert bearer_token not in payload_text
    assert aws_key not in payload_text
    assert "[redacted-secret]" in (step["command_template"] or "")
    assert all(bearer_token not in arg and aws_key not in arg for arg in step["argv"])


def test_build_evidence_record_preserves_manifest_placeholders_in_command_template():
    """Sanitization must not eat the ``<YOUR_*>`` placeholders the
    operator needs to fill in for denied steps."""
    report = _firebase_report()
    manifest = _firebase_manifest()

    evidence = cs_evidence.build_evidence_record(report, manifest)
    denied_by_id = {s["step_id"]: s for s in evidence.denied_steps}

    # The placeholder must still be visible so the operator knows what
    # to substitute when running the step manually.
    assert "<YOUR_FIREBASE_PROJECT_ID>" in (
        denied_by_id["select_target_project"]["command_template"] or ""
    )


def test_build_evidence_record_output_tail_is_capped():
    """Pathologically large stdout must not bloat the evidence record."""
    huge = "A" * 50_000
    report = _firebase_report(stdout=huge)
    manifest = _firebase_manifest()

    evidence = cs_evidence.build_evidence_record(report, manifest)
    attempted = next(s for s in evidence.attempted_steps if s["step_id"] == "install_firebase_cli")
    assert attempted["stdout_tail"] is not None
    assert len(attempted["stdout_tail"]) <= cs_evidence._OUTPUT_TAIL_MAX_CHARS


def test_build_evidence_record_executed_step_with_no_output_keeps_none_tails():
    """The runner returns empty string when the binary printed nothing.

    Sanitization must not invent a non-None placeholder — the operator
    sees ``stdout_tail: null`` only when ``stdout_tail`` was already
    ``None`` on the StepOutcome (i.e. the step did not execute)."""

    base = _firebase_manifest()
    synthetic = base.model_copy(
        update={
            "setup_steps": (
                SetupStep(
                    id="silent_step",
                    what="A silent allowlisted step.",
                    automatable=True,
                    command_template="echo silent",
                    verify_probe=None,
                    human_required_reason=None,
                ),
            )
        }
    )
    runner = _RecorderRunner(exit_code=0, stdout="", stderr="")
    probe = _make_status_probe([cs_status.CapabilityStatus.NEEDS_SETUP])
    report = cs_runner.run_automate_safe(
        synthetic,
        confirm=True,
        command_runner=runner,
        status_probe=probe,
    )

    evidence = cs_evidence.build_evidence_record(report, synthetic)
    step = evidence.attempted_steps[0]
    # SubprocessRunner returns empty string; sanitizer preserves empty
    # string verbatim (it is not None).
    assert step["stdout_tail"] == ""
    assert step["stderr_tail"] == ""


# ── write_evidence on disk ──────────────────────────────────────────────


def test_write_evidence_defaults_to_dontpanic_home_setup_runs(tmp_path):
    """The conftest redirects $DONTPANIC_HOME to tmp_path/dontpanic_home;
    the writer must honor that, *not* the operator's real ~/.dontpanic."""
    evidence = cs_evidence.build_evidence_record(
        _firebase_report(), _firebase_manifest()
    )

    written = cs_evidence.write_evidence(evidence)

    assert written.parent == tmp_path / "dontpanic_home" / "setup-runs"
    assert written.exists()
    # The payload round-trips through json.loads — proves it's valid JSON.
    loaded = json.loads(written.read_text(encoding="utf-8"))
    assert loaded["capability_id"] == "firebase-dashboard"


def test_write_evidence_to_explicit_dir_writes_payload(tmp_path):
    target_dir = tmp_path / "plan-evidence"
    evidence = cs_evidence.build_evidence_record(
        _firebase_report(), _firebase_manifest()
    )

    written = cs_evidence.write_evidence(evidence, evidence_dir=target_dir)

    assert written.parent == target_dir
    assert written.name.startswith("firebase-dashboard-")
    assert written.name.endswith(".json")
    loaded = json.loads(written.read_text(encoding="utf-8"))
    assert loaded["capability_id"] == evidence.capability_id


def test_write_evidence_sets_tight_file_permissions(tmp_path):
    """Operator-local state files must be mode 0600 — matches the V0b cache."""
    target_dir = tmp_path / "perms-check"
    evidence = cs_evidence.build_evidence_record(
        _firebase_report(), _firebase_manifest()
    )

    written = cs_evidence.write_evidence(evidence, evidence_dir=target_dir)
    mode = stat.S_IMODE(written.stat().st_mode)

    assert mode == cs_evidence.EVIDENCE_FILE_MODE


def test_evidence_filename_sanitizes_capability_id():
    """A malformed capability id cannot escape the target directory."""
    name = cs_evidence.evidence_filename(
        "../../etc/passwd", "2026-05-22T23:04:05Z"
    )

    assert "/" not in name
    assert ".." not in name
    assert name.endswith(".json")


# ── CLI integration ─────────────────────────────────────────────────────


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = cs_setup.main(argv)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def test_cli_automate_safe_confirm_writes_evidence_to_default_path(monkeypatch, tmp_path):
    class _FakeCompleted:
        returncode = 0
        stdout = "fake-stdout"
        stderr = ""

    monkeypatch.setattr(
        "dontpanic_orchestrate.capabilities_setup_runner.subprocess.run",
        lambda argv, **kwargs: _FakeCompleted(),
    )

    exit_code, stdout, stderr = _run_cli(
        ["firebase-dashboard", "--automate-safe", "--confirm"]
    )

    assert exit_code == 0, stderr
    default_dir = tmp_path / "dontpanic_home" / "setup-runs"
    assert default_dir.is_dir()
    written = list(default_dir.glob("firebase-dashboard-*.json"))
    assert len(written) == 1, written
    payload = json.loads(written[0].read_text(encoding="utf-8"))
    assert payload["capability_id"] == "firebase-dashboard"
    assert payload["confirm"] is True
    # CLI prints the path it wrote for the operator.
    assert "evidence_written:" in stdout


def test_cli_automate_safe_confirm_evidence_dir_redirects_record(monkeypatch, tmp_path):
    """When invoked from a plan, ``--evidence-dir`` redirects the record."""
    plan_evidence = tmp_path / "plan" / "evidence"

    class _FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(
        "dontpanic_orchestrate.capabilities_setup_runner.subprocess.run",
        lambda argv, **kwargs: _FakeCompleted(),
    )

    exit_code, stdout, stderr = _run_cli(
        [
            "firebase-dashboard",
            "--automate-safe",
            "--confirm",
            "--evidence-dir",
            str(plan_evidence),
        ]
    )

    assert exit_code == 0, stderr
    files = list(plan_evidence.glob("firebase-dashboard-*.json"))
    assert len(files) == 1, files
    # The default operator-local path was NOT used in this mode.
    default_dir = tmp_path / "dontpanic_home" / "setup-runs"
    assert not default_dir.exists() or list(default_dir.iterdir()) == []


def test_cli_has_no_no_evidence_bypass_for_governed_setup_runs():
    """F003 requires every governed setup run to persist evidence."""
    parser = cs_setup.build_parser()
    option_strings = {
        option
        for action in parser._actions
        for option in getattr(action, "option_strings", ())
    }

    assert "--no-evidence" not in option_strings


def test_cli_print_steps_does_not_write_evidence(monkeypatch, tmp_path):
    """``--print-steps`` is a planning surface — no evidence on disk."""
    exit_code, _, _ = _run_cli(["firebase-dashboard", "--print-steps"])

    assert exit_code == 0
    default_dir = tmp_path / "dontpanic_home" / "setup-runs"
    assert not default_dir.exists() or list(default_dir.glob("*.json")) == []
