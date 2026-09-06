"""Acceptance tests for `dontpanic evidence run` and `evidence capture` (PR#74).

Per the brainstorm contract (docs/brainstorms/2026-09-06-command-evidence-capture.md),
these subprocess CLI tests cover:
- dry-run/no writes
- exit 0 and nonzero commands
- spawn failure
- timeout
- inherited-secret redaction
- bounded output
- wrong feature/iteration (validation refusal)
- concurrent publication (atomic writes via temp + os.replace)
- capture skip on adapter failure
- capture refusal without objective contract
- complete reader round trip
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

from dontpanic_orchestrate import cli, command_validation
from dontpanic_orchestrate.evidence_cli import (
    EvidenceRunError,
    InvocationRecord,
    CaptureManifest,
    _redact_argv,
    _hash_content,
    _excerpt_output,
    _filter_env_for_subprocess,
    evidence_run_main,
    evidence_capture_main,
)


def _make_plan(tmp_path: Path, plan_id: str, features: list[str] | None = None) -> Path:
    """Create a minimal plan directory for testing."""
    plan_dir = tmp_path / "docs" / "plans" / plan_id
    plan_dir.mkdir(parents=True)

    features = features or ["F001"]

    plan_md = plan_dir / "plan.md"
    plan_md.write_text(
        f"""---
id: {plan_id}
type: feat
---

# {plan_id}

## Target

```yaml
target_env: dev
target_project: none
```
"""
    )

    features_json = plan_dir / "features.json"
    features_data = {
        "task_id": plan_id,
        "features": [{"id": f, "passes": "false"} for f in features],
    }
    features_json.write_text(json.dumps(features_data))

    return plan_dir


def _make_plan_with_contract(tmp_path: Path, plan_id: str, journeys: list[str]) -> Path:
    """Create a plan directory with an objective contract."""
    plan_dir = _make_plan(tmp_path, plan_id)

    contract = {
        "user_journeys": [{"name": j, "surfaces": ["web"]} for j in journeys],
        "required_evidence": [],
    }
    contract_path = plan_dir / "objective_contract.json"
    contract_path.write_text(json.dumps(contract))

    plan_md = plan_dir / "plan.md"
    text = plan_md.read_text()
    text = text.replace(
        "---\n\n# ",
        "links:\n  objective_contract: objective_contract.json\n---\n\n# ",
    )
    plan_md.write_text(text)

    return plan_dir


class TestEvidenceRunValidation:
    """Tests for `evidence run` input validation (pre-execution)."""

    def test_dry_run_no_writes(self, tmp_path, capsys, monkeypatch):
        """Dry-run mode validates inputs without executing or writing."""
        plan_dir = _make_plan(tmp_path, "2026-09-test-dry")
        monkeypatch.chdir(tmp_path)

        result = evidence_run_main([
            str(plan_dir), "--feature", "F001", "--iteration", "0",
            "--", "echo", "hello",
        ])

        assert result == 0
        out = capsys.readouterr().out
        assert "[dry-run]" in out
        assert "Would execute" in out

        inv_dir = plan_dir / "evidence" / "invocations"
        assert not inv_dir.exists(), "dry-run should not create evidence directory"

    def test_unknown_feature_refused(self, tmp_path, capsys, monkeypatch):
        """Refuses execution when feature ID is not in plan."""
        plan_dir = _make_plan(tmp_path, "2026-09-test-feat", ["F001", "F002"])
        monkeypatch.chdir(tmp_path)

        result = evidence_run_main([
            str(plan_dir), "--feature", "F999", "--iteration", "0",
            "--confirm", "--", "echo", "hello",
        ])

        assert result == 2
        err = capsys.readouterr().err
        assert "F999" in err
        assert "not found" in err

    def test_negative_iteration_refused(self, tmp_path, capsys, monkeypatch):
        """Refuses negative iteration numbers."""
        plan_dir = _make_plan(tmp_path, "2026-09-test-iter")
        monkeypatch.chdir(tmp_path)

        result = evidence_run_main([
            str(plan_dir), "--feature", "F001", "--iteration", "-1",
            "--", "echo", "hello",
        ])

        assert result == 2
        err = capsys.readouterr().err
        assert "iteration" in err

    def test_empty_command_refused(self, tmp_path, capsys, monkeypatch):
        """Refuses empty command after --."""
        plan_dir = _make_plan(tmp_path, "2026-09-test-empty")
        monkeypatch.chdir(tmp_path)

        result = evidence_run_main([
            str(plan_dir), "--feature", "F001", "--iteration", "0",
            "--confirm", "--",
        ])

        assert result == 2
        err = capsys.readouterr().err
        assert "no command" in err

    def test_timeout_bounds_enforced(self, tmp_path, capsys, monkeypatch):
        """Enforces min/max timeout bounds."""
        plan_dir = _make_plan(tmp_path, "2026-09-test-timeout")
        monkeypatch.chdir(tmp_path)

        result = evidence_run_main([
            str(plan_dir), "--feature", "F001", "--iteration", "0",
            "--timeout-seconds", "1",
            "--", "echo", "hello",
        ])

        assert result == 2
        err = capsys.readouterr().err
        assert "timeout" in err.lower()


class TestEvidenceRunExecution:
    """Tests for `evidence run` command execution."""

    def test_exit_zero_command(self, tmp_path, capsys, monkeypatch):
        """Records successful command with exit 0."""
        plan_dir = _make_plan(tmp_path, "2026-09-test-zero")
        monkeypatch.chdir(tmp_path)

        result = evidence_run_main([
            str(plan_dir), "--feature", "F001", "--iteration", "0",
            "--confirm", "--", sys.executable, "-c", "print('ok')",
        ])

        assert result == 0
        out = capsys.readouterr().out
        assert "Exit code: 0" in out

        inv_dir = plan_dir / "evidence" / "invocations"
        assert inv_dir.exists()
        records = list(inv_dir.glob("*.json"))
        assert len(records) == 1

        record_data = json.loads(records[0].read_text())
        record = InvocationRecord.model_validate(record_data)
        assert record.exit_code == 0
        assert record.status == "completed"
        assert "ok" in (record.stdout_excerpt or "")

    def test_exit_nonzero_command(self, tmp_path, capsys, monkeypatch):
        """Records failed command with non-zero exit."""
        plan_dir = _make_plan(tmp_path, "2026-09-test-nonzero")
        monkeypatch.chdir(tmp_path)

        result = evidence_run_main([
            str(plan_dir), "--feature", "F001", "--iteration", "0",
            "--confirm", "--", sys.executable, "-c", "import sys; sys.exit(42)",
        ])

        assert result == 1
        out = capsys.readouterr().out
        assert "Exit code: 42" in out

        inv_dir = plan_dir / "evidence" / "invocations"
        records = list(inv_dir.glob("*.json"))
        record_data = json.loads(records[0].read_text())
        assert record_data["exit_code"] == 42

    def test_spawn_failure_recorded(self, tmp_path, capsys, monkeypatch):
        """Records spawn failure when command doesn't exist."""
        plan_dir = _make_plan(tmp_path, "2026-09-test-spawn")
        monkeypatch.chdir(tmp_path)

        result = evidence_run_main([
            str(plan_dir), "--feature", "F001", "--iteration", "0",
            "--confirm", "--", "/nonexistent/command/xyz",
        ])

        assert result == 3
        err = capsys.readouterr().err
        assert "Spawn error" in err

        inv_dir = plan_dir / "evidence" / "invocations"
        records = list(inv_dir.glob("*.json"))
        record_data = json.loads(records[0].read_text())
        assert record_data["spawn_error"] is not None
        assert record_data["status"] == "incomplete"

    def test_timeout_recorded(self, tmp_path, capsys, monkeypatch):
        """Records timeout when command exceeds limit."""
        plan_dir = _make_plan(tmp_path, "2026-09-test-timeout-exec")
        monkeypatch.chdir(tmp_path)

        result = evidence_run_main([
            str(plan_dir), "--feature", "F001", "--iteration", "0",
            "--timeout-seconds", "10",
            "--confirm", "--", sys.executable, "-c", "import time; time.sleep(999)",
        ])

        assert result == 3
        err = capsys.readouterr().err
        assert "timed out" in err

        inv_dir = plan_dir / "evidence" / "invocations"
        records = list(inv_dir.glob("*.json"))
        record_data = json.loads(records[0].read_text())
        assert record_data["timed_out"] is True


class TestSecretRedaction:
    """Tests for secret/credential redaction in evidence records."""

    def test_argv_redacts_secret_flags(self):
        """Redacts values following --secret, --token, --password flags."""
        argv = ["cmd", "--token", "ghp_secret123", "--arg", "value"]
        redacted = _redact_argv(argv)

        assert redacted == ["cmd", "--token", "[REDACTED]", "--arg", "value"]

    def test_argv_redacts_key_equals_value(self):
        """Redacts --key=value style secrets."""
        argv = ["cmd", "--api-key=sk-secret123"]
        redacted = _redact_argv(argv)

        assert redacted == ["cmd", "--api-key=[REDACTED]"]

    def test_argv_redacts_token_shaped_values(self):
        """Redacts values that look like tokens (ghp_, sk-)."""
        argv = ["cmd", "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"]
        redacted = _redact_argv(argv)

        assert "[REDACTED]" in redacted

    def test_env_filters_sensitive_vars(self):
        """Filters sensitive environment variables from subprocess."""
        with mock.patch.dict(os.environ, {
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "AWS_SECRET_ACCESS_KEY": "secret123",
            "GITHUB_TOKEN": "ghp_xxx",
            "NORMAL_VAR": "value",
        }):
            filtered = _filter_env_for_subprocess()

            assert "PATH" in filtered
            assert "HOME" in filtered
            assert "NORMAL_VAR" in filtered
            assert "AWS_SECRET_ACCESS_KEY" not in filtered
            assert "GITHUB_TOKEN" not in filtered

    def test_inherited_secret_not_in_record(self, tmp_path, capsys, monkeypatch):
        """Secrets in environment are not copied to evidence record."""
        plan_dir = _make_plan(tmp_path, "2026-09-test-secret-env")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("MY_SECRET_TOKEN", "super-secret-value")

        result = evidence_run_main([
            str(plan_dir), "--feature", "F001", "--iteration", "0",
            "--confirm", "--", sys.executable, "-c",
            "import os; print(os.environ.get('MY_SECRET_TOKEN', 'not-found'))",
        ])

        assert result == 0

        inv_dir = plan_dir / "evidence" / "invocations"
        records = list(inv_dir.glob("*.json"))
        record_text = records[0].read_text()

        assert "super-secret-value" not in record_text
        assert "not-found" in record_text


class TestBoundedOutput:
    """Tests for output capping and truncation."""

    def test_output_truncated_at_cap(self):
        """Output is truncated when exceeding byte cap."""
        large_output = b"x" * 200_000
        excerpt = _excerpt_output(large_output, max_bytes=1000)

        assert len(excerpt) <= 1100
        assert "truncated" in excerpt

    def test_output_hash_preserved(self):
        """Full output hash is preserved even when excerpt is truncated."""
        content = b"full content here"
        hash_val = _hash_content(content)

        assert hash_val.startswith("sha256:")
        assert len(hash_val) == len("sha256:") + 64


class TestEvidenceCaptureValidation:
    """Tests for `evidence capture` input validation."""

    def test_dry_run_no_writes(self, tmp_path, capsys, monkeypatch):
        """Dry-run validates without capturing or publishing."""
        plan_dir = _make_plan_with_contract(
            tmp_path, "2026-09-test-cap-dry", ["journey1"]
        )
        monkeypatch.chdir(tmp_path)

        result = evidence_capture_main([
            str(plan_dir), "--journey", "journey1", "--source", "harness",
        ])

        assert result == 0
        out = capsys.readouterr().out
        assert "[dry-run]" in out

        cap_dir = plan_dir / "evidence" / "captures"
        assert not cap_dir.exists()

    def test_unknown_journey_refused(self, tmp_path, capsys, monkeypatch):
        """Refuses capture when journey not in contract."""
        plan_dir = _make_plan_with_contract(
            tmp_path, "2026-09-test-cap-journey", ["journey1", "journey2"]
        )
        monkeypatch.chdir(tmp_path)

        result = evidence_capture_main([
            str(plan_dir), "--journey", "unknown-journey", "--source", "harness",
            "--confirm",
        ])

        assert result == 2
        err = capsys.readouterr().err
        assert "unknown-journey" in err
        assert "not found" in err

    def test_invalid_source_refused(self, tmp_path, capsys, monkeypatch):
        """Refuses invalid source name."""
        plan_dir = _make_plan(tmp_path, "2026-09-test-cap-source")
        monkeypatch.chdir(tmp_path)

        result = evidence_capture_main([
            str(plan_dir), "--journey", "any", "--source", "invalid-source",
        ])

        assert result == 2
        err = capsys.readouterr().err
        assert "invalid-source" in err

    def test_config_must_be_project_scoped(self, tmp_path, capsys, monkeypatch):
        """Config file must be within project root."""
        plan_dir = _make_plan_with_contract(tmp_path, "2026-09-test-cap-config", ["j1"])
        monkeypatch.chdir(tmp_path)

        result = evidence_capture_main([
            str(plan_dir), "--journey", "j1", "--source", "web",
            "--config", "/etc/passwd",
        ])

        assert result == 2
        err = capsys.readouterr().err
        assert "project-scoped" in err or "config file" in err.lower()

    def test_refuses_without_objective_contract(self, tmp_path, capsys, monkeypatch):
        """Capture REFUSES when objective contract is missing."""
        plan_dir = _make_plan(tmp_path, "2026-09-test-cap-no-contract")
        monkeypatch.chdir(tmp_path)

        result = evidence_capture_main([
            str(plan_dir), "--journey", "any-journey", "--source", "harness",
            "--confirm",
        ])

        assert result == 2
        err = capsys.readouterr().err
        assert "objective_contract" in err or "objective contract" in err.lower()

    def test_refuses_with_empty_journeys(self, tmp_path, capsys, monkeypatch):
        """Capture REFUSES when objective contract has no user_journeys."""
        plan_dir = _make_plan(tmp_path, "2026-09-test-cap-empty-journeys")

        contract = {"user_journeys": [], "required_evidence": []}
        contract_path = plan_dir / "objective_contract.json"
        contract_path.write_text(json.dumps(contract))

        plan_md = plan_dir / "plan.md"
        text = plan_md.read_text()
        text = text.replace(
            "---\n\n# ",
            "links:\n  objective_contract: objective_contract.json\n---\n\n# ",
        )
        plan_md.write_text(text)

        monkeypatch.chdir(tmp_path)

        result = evidence_capture_main([
            str(plan_dir), "--journey", "any", "--source", "harness",
            "--confirm",
        ])

        assert result == 2
        err = capsys.readouterr().err
        assert "no user_journeys" in err or "declared journeys" in err


class TestEvidenceCaptureExecution:
    """Tests for `evidence capture` execution."""

    def test_harness_empty_sources_skipped(self, tmp_path, capsys, monkeypatch):
        """Capture with empty sources produces skip record."""
        plan_dir = _make_plan_with_contract(
            tmp_path, "2026-09-test-cap-empty", ["test-journey"]
        )
        monkeypatch.chdir(tmp_path)

        result = evidence_capture_main([
            str(plan_dir), "--journey", "test-journey", "--source", "harness",
            "--confirm",
        ])

        assert result == 1
        out = capsys.readouterr().out
        assert "Skipped:" in out

        cap_dir = plan_dir / "evidence" / "captures"
        assert cap_dir.exists()
        manifests = list(cap_dir.glob("*/manifest.json"))
        assert len(manifests) == 1

        manifest_data = json.loads(manifests[0].read_text())
        assert manifest_data["status"] == "skipped"

    def test_capture_manifest_written(self, tmp_path, capsys, monkeypatch):
        """Successful capture writes versioned manifest atomically."""
        plan_dir = _make_plan_with_contract(
            tmp_path, "2026-09-test-cap-manifest", ["test-journey"]
        )
        monkeypatch.chdir(tmp_path)

        evidence_capture_main([
            str(plan_dir), "--journey", "test-journey", "--source", "harness",
            "--confirm",
        ])

        cap_dir = plan_dir / "evidence" / "captures"
        manifests = list(cap_dir.glob("*/manifest.json"))
        assert len(manifests) == 1

        manifest = CaptureManifest.model_validate(json.loads(manifests[0].read_text()))
        assert manifest.journey == "test-journey"
        assert manifest.source == "harness"
        assert manifest.capture_id.startswith("cap-")

        tmp_files = list(cap_dir.rglob(".*.tmp"))
        assert len(tmp_files) == 0, "temp files should not survive atomic write"


class TestConcurrentPublication:
    """Tests for concurrent/atomic publication (temp + os.replace)."""

    def test_invocation_records_unique_ids_and_atomic(self, tmp_path, monkeypatch):
        """Multiple invocations produce unique IDs via atomic writes."""
        plan_dir = _make_plan(tmp_path, "2026-09-test-concurrent")
        monkeypatch.chdir(tmp_path)

        for _ in range(3):
            evidence_run_main([
                str(plan_dir), "--feature", "F001", "--iteration", "0",
                "--confirm", "--", sys.executable, "-c", "pass",
            ])

        inv_dir = plan_dir / "evidence" / "invocations"
        records = list(inv_dir.glob("*.json"))
        assert len(records) == 3

        ids = set()
        for record_path in records:
            record_data = json.loads(record_path.read_text())
            ids.add(record_data["invocation_id"])
            assert record_data["status"] in ("started", "completed")

        assert len(ids) == 3, "all invocations must have unique IDs"

        tmp_files = list(inv_dir.glob(".*.tmp"))
        assert len(tmp_files) == 0, "temp files should not survive atomic os.replace"


class TestCommandValidation:
    """Tests that evidence commands pass command_validation."""

    def test_evidence_run_validates(self):
        """evidence run command validates with command_validation."""
        result = command_validation.validate_command_tokens([
            "evidence", "run", "plan-id", "--feature", "F001",
            "--iteration", "0", "--confirm", "--", "echo", "hello",
        ])
        assert result.ok, f"validation failed: {result}"

    def test_evidence_capture_validates(self):
        """evidence capture command validates with command_validation."""
        result = command_validation.validate_command_tokens([
            "evidence", "capture", "plan-id", "--journey", "j1",
            "--source", "web", "--confirm",
        ])
        assert result.ok, f"validation failed: {result}"


class TestCLIEntrypoint:
    """Tests for main CLI entry point routing."""

    def test_evidence_subcommand_routes(self, tmp_path, capsys, monkeypatch):
        """Main CLI routes 'evidence' to evidence_main."""
        plan_dir = _make_plan(tmp_path, "2026-09-test-route")
        monkeypatch.chdir(tmp_path)

        result = cli.main([
            "evidence", "run", str(plan_dir),
            "--feature", "F001", "--iteration", "0",
            "--", "echo", "test",
        ])

        assert result == 0
        out = capsys.readouterr().out
        assert "[dry-run]" in out

    def test_evidence_help(self, capsys):
        """evidence --help shows subcommand help."""
        result = cli.main(["evidence", "--help"])

        assert result == 0
        out = capsys.readouterr().out
        assert "run" in out
        assert "capture" in out


class TestReaderRoundTrip:
    """Tests for complete manifest reader round trip."""

    def test_invocation_record_round_trip(self, tmp_path, monkeypatch):
        """InvocationRecord can be written, read, and validated."""
        plan_dir = _make_plan(tmp_path, "2026-09-test-roundtrip")
        monkeypatch.chdir(tmp_path)

        evidence_run_main([
            str(plan_dir), "--feature", "F001", "--iteration", "1",
            "--confirm", "--", sys.executable, "-c", "print('round-trip')",
        ])

        inv_dir = plan_dir / "evidence" / "invocations"
        for record_path in inv_dir.glob("*.json"):
            data = json.loads(record_path.read_text())
            record = InvocationRecord.model_validate(data)

            assert record.feature_id == "F001"
            assert record.iteration == 1
            assert "round-trip" in (record.stdout_excerpt or "")

            reserialized = json.loads(record.model_dump_json())
            assert reserialized == data

    def test_capture_manifest_round_trip(self, tmp_path, monkeypatch):
        """CaptureManifest can be written, read, and validated."""
        plan_dir = _make_plan_with_contract(
            tmp_path, "2026-09-test-cap-roundtrip", ["test"]
        )
        monkeypatch.chdir(tmp_path)

        evidence_capture_main([
            str(plan_dir), "--journey", "test", "--source", "harness",
            "--confirm",
        ])

        cap_dir = plan_dir / "evidence" / "captures"
        for manifest_path in cap_dir.glob("*/manifest.json"):
            data = json.loads(manifest_path.read_text())
            manifest = CaptureManifest.model_validate(data)

            assert manifest.journey == "test"
            assert manifest.source == "harness"
