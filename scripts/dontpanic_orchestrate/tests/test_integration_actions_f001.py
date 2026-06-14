"""Plan 2026-06-04-003 F001 — integration ActionItem catalog + provider.

Contracts under test (lock-binding; see plan.md "Integration catalog"):
- SOURCE_INTEGRATION is a valid ActionItem source beside the five shipped ones.
- provide_integration_actions() emits one item per catalog action row with the
  literal commands / credential env-var names / action ids from plan.md.
- Honest-commands split: external commands ride the display-only
  operator_command field; exact_command is populated ONLY for validated
  dontpanic commands (the static smoke), else None.
- Spine fields: dedupe_key stable, resolution_class never command_resolvable
  for credentialed steps, clears_when uses the registered
  integration_evidence_present predicate.
- New display fields survive ActionItem.to_dict round-trips.
- No secrets in any field (env-var NAMES only, never values).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import operator_console as oc  # noqa: E402
from dontpanic_orchestrate import integration_actions as itg  # noqa: E402


@pytest.fixture()
def evidence_dir(tmp_path):
    d = tmp_path / "integrations" / "evidence"
    d.mkdir(parents=True)
    return d


def _items(evidence_dir):
    return oc.provide_integration_actions(evidence_dir)


class TestSourceKind:
    def test_source_integration_is_valid(self):
        assert oc.SOURCE_INTEGRATION == "integration"
        # constructible: the validator accepts the new source
        item = next(iter(_make := None) for _ in ()) if False else None  # noqa: F841
        assert "integration" in oc._VALID_SOURCES


class TestCatalogLiterals:
    """plan.md catalog table rows are fixture-binding."""

    def test_one_item_per_catalog_action(self, evidence_dir):
        items = _items(evidence_dir)
        ids = {i.id for i in items}
        # action items for the 6 catalog action rows (static smoke, firebase
        # creds, firebase deploy, realtime smoke, discord, linear)
        expected = {
            "integration:static-dashboard:static-dashboard-smoke",
            "integration:firebase-functions-deploy:firebase-creds",
            "integration:firebase-functions-deploy:firebase-deploy",
            "integration:firebase-realtime-smoke:firebase-realtime-smoke",
            "integration:discord-webhook:discord-webhook",
            "integration:linear-credentials:linear-creds",
        }
        # EXACTLY one action item per catalog action row over a clean ledger —
        # not "at least these", so an unexpected/extra emitted row fails the
        # test (CodeRabbit #7).
        assert ids == expected

    def test_static_smoke_exact_command_literal(self, evidence_dir):
        smoke = next(
            i for i in _items(evidence_dir)
            if i.id == "integration:static-dashboard:static-dashboard-smoke"
        )
        assert smoke.exact_command == "dontpanic integrations smoke static-dashboard"
        assert smoke.operator_command is None

    def test_external_commands_are_display_only(self, evidence_dir):
        deploy = next(
            i for i in _items(evidence_dir)
            if i.id == "integration:firebase-functions-deploy:firebase-deploy"
        )
        # honest-commands: external command never enters exact_command
        assert deploy.exact_command is None
        assert "firebase deploy --only functions" in (deploy.operator_command or "")

    def test_credential_env_var_names_literal(self, evidence_dir):
        by_id = {i.id: i for i in _items(evidence_dir)}
        assert by_id["integration:firebase-functions-deploy:firebase-creds"].credential_env_vars == (
            "FIREBASE_TOKEN",
        )
        assert by_id["integration:discord-webhook:discord-webhook"].credential_env_vars == (
            "DONTPANIC_DISCORD_WEBHOOK_URL",
        )
        assert by_id["integration:linear-credentials:linear-creds"].credential_env_vars == (
            "LINEAR_API_KEY",
        )
        assert by_id["integration:static-dashboard:static-dashboard-smoke"].credential_env_vars == ()


class TestSpineFields:
    def test_credentialed_steps_never_command_resolvable(self, evidence_dir):
        for item in _items(evidence_dir):
            if item.credential_env_vars:
                assert item.resolution_class in (
                    oc.RESOLUTION_OPERATOR_ATTESTED,
                    oc.RESOLUTION_BLOCKED_EXTERNAL,
                ), item.id

    def test_clears_when_uses_registered_predicate(self, evidence_dir):
        for item in _items(evidence_dir):
            assert item.clears_when is not None, item.id
            name = getattr(item.clears_when, "predicate", None) or getattr(
                item.clears_when, "name", None
            )
            assert name == "integration_evidence_present", item.id

    def test_dedupe_key_stable_across_rebuilds(self, evidence_dir):
        first = {i.id: i.dedupe_key for i in _items(evidence_dir)}
        second = {i.id: i.dedupe_key for i in _items(evidence_dir)}
        assert first == second
        assert all(first.values())


class TestSerializationRoundTrip:
    def test_display_fields_survive_to_dict(self, evidence_dir):
        for item in _items(evidence_dir):
            d = item.to_dict()
            assert d["source"] == "integration"
            assert "operator_command" in d
            assert "credential_env_vars" in d
            assert "evidence_expected" in d
            assert "trigger_condition" in d


class TestNoSecrets:
    def test_env_values_never_rendered(self, evidence_dir, monkeypatch):
        secret = "wh-secret-token-12345"
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", f"https://discord/{secret}")
        monkeypatch.setenv("FIREBASE_TOKEN", secret)
        for item in _items(evidence_dir):
            payload = str(item.to_dict())
            assert secret not in payload, item.id
