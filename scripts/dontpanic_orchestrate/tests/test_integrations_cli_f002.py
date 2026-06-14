"""Plan 2026-06-04-003 F002 — `dontpanic integrations` CLI surface tests.

Both verbs write through the single append-only evidence writer; these tests
drive the CLI entrypoint end-to-end (argv in, exit code + evidence out) and
prove the `cli.py` dispatch routes `integrations ...` to `integrations_main`.

The autouse conftest fixture redirects DONTPANIC_HOME to a tmp dir, so the
install-level evidence dir the CLI writes to is isolated per test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import global_config  # noqa: E402
from dontpanic_orchestrate import integration_actions as itg  # noqa: E402
from dontpanic_orchestrate.integrations_cli import integrations_main  # noqa: E402


def _evidence_dir():
    return global_config.dontpanic_home() / itg.EVIDENCE_SUBDIR


class TestSmokeVerb:
    def test_smoke_static_dashboard_passes_and_records_evidence(self, tmp_path):
        plans_root = tmp_path / "plans"
        plans_root.mkdir()
        rc = integrations_main(
            ["smoke", "static-dashboard", "--plans-root", str(plans_root)]
        )
        assert rc == 0
        recs = itg.read_evidence(_evidence_dir(), "static-dashboard")
        assert recs and recs[-1]["outcome"] == "passed"
        assert recs[-1]["source"] == "smoke"

    def test_smoke_unknown_integration_is_usage_error(self):
        assert integrations_main(["smoke", "no-such-integration"]) == 2


class TestAttestVerb:
    def test_attest_records_passed_attestation(self):
        rc = integrations_main(
            [
                "attest",
                "firebase-functions-deploy",
                "--action",
                "firebase-deploy",
                "--outcome",
                "passed",
                "--note",
                "deployed via firebase deploy --only functions",
            ]
        )
        assert rc == 0
        recs = itg.read_evidence(_evidence_dir(), "firebase-functions-deploy")
        assert recs and recs[-1]["outcome"] == "passed"
        assert recs[-1]["source"] == "attestation"
        assert itg.has_passed_evidence(recs, "firebase-deploy")

    def test_attest_records_failed_attestation(self):
        rc = integrations_main(
            [
                "attest",
                "discord-webhook",
                "--action",
                "discord-webhook",
                "--outcome",
                "failed",
            ]
        )
        assert rc == 0
        recs = itg.read_evidence(_evidence_dir(), "discord-webhook")
        assert recs and recs[-1]["outcome"] == "failed"

    def test_attest_rejects_bad_outcome(self):
        with pytest.raises(SystemExit):
            integrations_main(
                ["attest", "x", "--action", "y", "--outcome", "maybe"]
            )

    def test_attest_requires_action(self):
        with pytest.raises(SystemExit):
            integrations_main(["attest", "x", "--outcome", "passed"])


class TestNoVerb:
    def test_no_subcommand_returns_usage(self):
        assert integrations_main([]) == 2


class TestCliDispatch:
    def test_cli_routes_integrations_to_integrations_main(self, tmp_path):
        """The top-level `dontpanic integrations ...` dispatch in cli.py must
        reach integrations_main (not fall through to plan/other handlers)."""
        from dontpanic_orchestrate import cli

        plans_root = tmp_path / "plans"
        plans_root.mkdir()
        rc = cli.main(
            ["integrations", "smoke", "static-dashboard", "--plans-root", str(plans_root)]
        )
        assert rc == 0
        recs = itg.read_evidence(_evidence_dir(), "static-dashboard")
        assert recs and recs[-1]["source"] == "smoke"
