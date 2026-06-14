"""Plan 2026-06-04-003 F003 — gated deploy/realtime band semantics.

The Firebase deploy + realtime-smoke rows are operator-owned gated actions:
they ALWAYS render (gating is shown as band state, never by hiding), carry
their external command in operator_command (exact_command=None per honest-
commands), and move through THREE band states driven ONLY by the append-only
evidence history + presence-only env-var NAME checks — never by probing live
environment state or reading credential values:

  trigger un-met                        -> info       (not-yet-needed, visible)
  trigger met, credentials absent       -> advisory   (waiting on provisioning)
  trigger met, credentials present      -> needs_action (ready to execute)

The trigger is met ONLY via an operator-attested evidence record using the
integration's declared trigger action id (firebase-trigger), never inferred
from the environment. Everything here is provable offline with fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import integration_actions as itg  # noqa: E402
from dontpanic_orchestrate import operator_console as oc  # noqa: E402

# The gated Firebase rows under test (integration_id, action_id, reversible).
GATED_ROWS = [
    ("firebase-functions-deploy", "firebase-creds", False),
    ("firebase-functions-deploy", "firebase-deploy", False),
    ("firebase-realtime-smoke", "firebase-realtime-smoke", True),
]
FIREBASE_ENV = "FIREBASE_TOKEN"


@pytest.fixture()
def evidence_dir(tmp_path):
    return tmp_path / "integrations" / "evidence"


def _no_firebase_creds(monkeypatch):
    monkeypatch.delenv(FIREBASE_ENV, raising=False)


def _items_by_id(evidence_dir, now=None):
    items = oc.provide_integration_actions(evidence_dir, now=now)
    return {it.id: it for it in items}


def _id(integration_id, action_id):
    return f"{oc.SOURCE_INTEGRATION}:{integration_id}:{action_id}"


def _attest_trigger(evidence_dir, integration_id):
    """Operator-attested trigger record — the ONLY way a gated row's trigger
    becomes met (uses the declared trigger action id, not the row's own id)."""
    itg.write_integration_evidence(
        evidence_dir,
        integration_id,
        itg.TRIGGER_ACTION_FIREBASE,
        source="attestation",
        outcome="passed",
    )


class TestUntriggeredRendersInfo:
    @pytest.mark.parametrize("integration_id,action_id,reversible", GATED_ROWS)
    def test_gated_row_is_info_and_visible_when_trigger_unmet(
        self, evidence_dir, monkeypatch, integration_id, action_id, reversible
    ):
        _no_firebase_creds(monkeypatch)
        items = _items_by_id(evidence_dir)
        item = items[_id(integration_id, action_id)]  # rendered, never hidden
        assert item.band == oc.Band.INFO
        assert "Not yet needed" in item.detail
        assert "multi-operator dashboard need" in item.detail
        # honest-commands: no in-repo execution path for a gated external step
        assert item.exact_command is None
        assert item.operator_command is not None
        assert item.automatable is False
        assert item.resolution_class == oc.RESOLUTION_OPERATOR_ATTESTED
        assert item.credential_env_vars == (FIREBASE_ENV,)
        assert item.reversible is reversible
        assert oc.AUDIENCE_OPERATOR in item.audience


class TestTriggerMetCredentialsAbsentRendersAdvisory:
    @pytest.mark.parametrize("integration_id,action_id,reversible", GATED_ROWS)
    def test_advisory_names_missing_env_var(
        self, evidence_dir, monkeypatch, integration_id, action_id, reversible
    ):
        _no_firebase_creds(monkeypatch)
        _attest_trigger(evidence_dir, integration_id)
        item = _items_by_id(evidence_dir)[_id(integration_id, action_id)]
        assert item.band == oc.Band.ADVISORY
        assert "Waiting on credential provisioning" in item.detail
        assert FIREBASE_ENV in item.detail  # names the missing env-var
        assert item.exact_command is None
        assert item.automatable is False


class TestTriggerMetCredentialsPresentRendersNeedsAction:
    @pytest.mark.parametrize("integration_id,action_id,reversible", GATED_ROWS)
    def test_needs_action_when_trigger_and_creds_present(
        self, evidence_dir, monkeypatch, integration_id, action_id, reversible
    ):
        # presence-only NAME check: a non-empty value is enough; the value
        # itself must never surface in any rendered field.
        monkeypatch.setenv(FIREBASE_ENV, "super-secret-token-value-XYZ")
        _attest_trigger(evidence_dir, integration_id)
        item = _items_by_id(evidence_dir)[_id(integration_id, action_id)]
        assert item.band == oc.Band.NEEDS_ACTION
        # value never read into the item
        blob = " ".join(
            str(v) for v in (item.detail, item.operator_command, item.exact_command)
        )
        assert "super-secret-token-value-XYZ" not in blob
        assert item.automatable is False  # still operator-owned, never executes


class TestTriggerIsAttestationOnly:
    def test_env_credentials_alone_do_not_meet_the_trigger(
        self, evidence_dir, monkeypatch
    ):
        """Live env state (even full creds) must NOT advance a gated row past
        info — only an attested trigger record can. Guards against inferring
        the trigger from the environment."""
        monkeypatch.setenv(FIREBASE_ENV, "present")
        # no trigger attestation written
        item = _items_by_id(evidence_dir)[_id("firebase-functions-deploy", "firebase-deploy")]
        assert item.band == oc.Band.INFO

    def test_passed_action_evidence_suppresses_the_action_item(
        self, evidence_dir, monkeypatch
    ):
        """Once the row's OWN action evidence is passed, it is no longer an
        action item (F004 renders its status instead)."""
        _no_firebase_creds(monkeypatch)
        _attest_trigger(evidence_dir, "firebase-functions-deploy")
        itg.write_integration_evidence(
            evidence_dir,
            "firebase-functions-deploy",
            "firebase-deploy",
            source="attestation",
            outcome="passed",
        )
        ids = set(_items_by_id(evidence_dir))
        assert _id("firebase-functions-deploy", "firebase-deploy") not in ids
        # sibling row (creds) still pending → still rendered
        assert _id("firebase-functions-deploy", "firebase-creds") in ids


class TestNoSecretLeakInRenderedItems:
    def test_no_credential_values_in_any_gated_item_field(
        self, evidence_dir, monkeypatch
    ):
        monkeypatch.setenv(FIREBASE_ENV, "leaky-value-ABC123")
        for integration_id, _action, _rev in GATED_ROWS:
            _attest_trigger(evidence_dir, integration_id)
        for item in oc.provide_integration_actions(evidence_dir):
            serialized = str(item.to_dict())
            assert "leaky-value-ABC123" not in serialized
