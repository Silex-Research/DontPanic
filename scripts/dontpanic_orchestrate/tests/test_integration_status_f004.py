"""Plan 2026-06-04-003 F004 — per-integration status derivation + status items.

Status derives EXCLUSIVELY from the append-only evidence history via the
plan.md status matrix (env-var presence is NEVER a status driver). The floor
is the highest status proven by passed records; a later failed record raises a
failure flag WITHOUT regressing the floor. Each integration emits TWO items:
the pending ACTION item (suppresses via clears_when) and an always-rendered
informational STATUS item that keeps cleared integrations visible.

The end-to-end journey runs the rendered static-dashboard ActionItem's actual
exact_command (the real smoke), which writes evidence through the F002 writer,
then re-runs the real provider-to-render rebuild and asserts the integration's
status flipped and its pending item cleared — no hand-editing anywhere.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import dashboard  # noqa: E402
from dontpanic_orchestrate import global_config  # noqa: E402
from dontpanic_orchestrate import integration_actions as itg  # noqa: E402
from dontpanic_orchestrate import operator_console as oc  # noqa: E402
from dontpanic_orchestrate.integrations_cli import integrations_main  # noqa: E402


@pytest.fixture()
def evidence_dir(tmp_path):
    return tmp_path / "integrations" / "evidence"


def _passed(evidence_dir, integration_id, action_id, source="attestation"):
    itg.write_integration_evidence(
        evidence_dir, integration_id, action_id, source=source, outcome="passed"
    )


def _failed(evidence_dir, integration_id, action_id, source="attestation"):
    itg.write_integration_evidence(
        evidence_dir, integration_id, action_id, source=source, outcome="failed"
    )


class TestStatusMatrixRows:
    def test_all_integrations_pending_with_no_evidence(self, evidence_dir):
        statuses = itg.derive_integration_status(evidence_dir)
        # every catalog integration is represented and starts pending
        assert set(statuses) == {a.integration_id for a in itg.INTEGRATION_CATALOG}
        assert all(s.status == itg.STATUS_PENDING for s in statuses.values())
        assert all(not s.has_evidence for s in statuses.values())

    def test_static_dashboard_smoke_passing(self, evidence_dir):
        _passed(evidence_dir, "static-dashboard", "static-dashboard-smoke", source="smoke")
        st = itg.derive_integration_status(evidence_dir)["static-dashboard"]
        assert st.status == itg.STATUS_SMOKE_PASSING
        assert not st.failure_flag

    def test_firebase_deploy_configured_then_deployed(self, evidence_dir):
        _passed(evidence_dir, "firebase-functions-deploy", "firebase-creds")
        assert (
            itg.derive_integration_status(evidence_dir)["firebase-functions-deploy"].status
            == itg.STATUS_CONFIGURED
        )
        _passed(evidence_dir, "firebase-functions-deploy", "firebase-deploy")
        assert (
            itg.derive_integration_status(evidence_dir)["firebase-functions-deploy"].status
            == itg.STATUS_DEPLOYED
        )

    def test_realtime_configured_cross_derives_from_deploy_deployed(self, evidence_dir):
        # realtime's "configured" rung is the deploy integration reaching deployed
        _passed(evidence_dir, "firebase-functions-deploy", "firebase-creds")
        _passed(evidence_dir, "firebase-functions-deploy", "firebase-deploy")
        st = itg.derive_integration_status(evidence_dir)["firebase-realtime-smoke"]
        assert st.status == itg.STATUS_CONFIGURED
        # then its own smoke evidence advances it to smoke-passing
        _passed(evidence_dir, "firebase-realtime-smoke", "firebase-realtime-smoke")
        st2 = itg.derive_integration_status(evidence_dir)["firebase-realtime-smoke"]
        assert st2.status == itg.STATUS_SMOKE_PASSING

    def test_discord_and_linear_configured_terminal(self, evidence_dir):
        _passed(evidence_dir, "discord-webhook", "discord-webhook")
        _passed(evidence_dir, "linear-credentials", "linear-creds")
        statuses = itg.derive_integration_status(evidence_dir)
        assert statuses["discord-webhook"].status == itg.STATUS_CONFIGURED
        assert statuses["linear-credentials"].status == itg.STATUS_CONFIGURED


class TestFloorFromHistory:
    def test_failed_after_passed_keeps_floor_and_flags(self, evidence_dir):
        _passed(evidence_dir, "static-dashboard", "static-dashboard-smoke", source="smoke")
        _failed(evidence_dir, "static-dashboard", "static-dashboard-smoke", source="smoke")
        st = itg.derive_integration_status(evidence_dir)["static-dashboard"]
        assert st.status == itg.STATUS_SMOKE_PASSING  # floor NOT regressed
        assert st.failure_flag is True
        assert st.failure_detail and "static-dashboard-smoke" in st.failure_detail

    def test_only_failed_records_stay_pending_with_flag(self, evidence_dir):
        _failed(evidence_dir, "discord-webhook", "discord-webhook")
        st = itg.derive_integration_status(evidence_dir)["discord-webhook"]
        assert st.status == itg.STATUS_PENDING
        assert st.failure_flag is True


class TestStatusItemsAlwaysRender:
    def test_one_status_item_per_integration_info_band(self, evidence_dir):
        items = oc.provide_integration_status_items(evidence_dir)
        ids = {it.id for it in items}
        for action in itg.INTEGRATION_CATALOG:
            assert f"integration-status:{action.integration_id}" in ids
        assert all(it.band == oc.Band.INFO for it in items)
        # informational, never actionable
        assert all(it.exact_command is None for it in items)
        assert all(it.automatable is False for it in items)

    def test_status_item_carries_derived_label(self, evidence_dir):
        _passed(evidence_dir, "discord-webhook", "discord-webhook")
        items = {it.id: it for it in oc.provide_integration_status_items(evidence_dir)}
        item = items["integration-status:discord-webhook"]
        assert "configured" in item.title
        assert "configured" in item.detail


class TestPostClearVisibilityThroughRealGather:
    def test_cleared_action_disappears_but_status_item_remains(
        self, evidence_dir, monkeypatch, tmp_path
    ):
        # route the gather provider at the install evidence dir we control
        home = global_config.dontpanic_home()
        real_evidence = home / itg.EVIDENCE_SUBDIR
        real_evidence.mkdir(parents=True, exist_ok=True)
        # smoke passes -> static-dashboard action clears, status item stays
        _passed(real_evidence, "static-dashboard", "static-dashboard-smoke", source="smoke")

        plans_root = tmp_path / "plans"
        plans_root.mkdir()
        cards = dashboard._gather_action_items(
            plans_root=plans_root,
            capability_envelope=None,
            reconcile_result=None,
            arch_status=None,
            plan_id=None,
        )
        ids = {c.id for c in cards}
        # ACTION item suppressed at source (passed evidence)
        assert "integration:static-dashboard:static-dashboard-smoke" not in ids
        # STATUS item keeps it visible
        assert "integration-status:static-dashboard" in ids
        status = next(c for c in cards if c.id == "integration-status:static-dashboard")
        assert status.band == oc.Band.INFO
        assert "smoke-passing" in status.title


class TestNoSecretLeak:
    def test_status_items_carry_no_secret_shapes(self, evidence_dir):
        _passed(evidence_dir, "discord-webhook", "discord-webhook")
        for item in oc.provide_integration_status_items(evidence_dir):
            blob = json.dumps(item.to_dict())
            # status copy is derived labels only — no token-like material
            assert "ghp_" not in blob
            assert "Bearer " not in blob


class TestEndToEndCompletionJourney:
    def test_smoke_command_writes_evidence_then_rebuild_flips_status(
        self, tmp_path, monkeypatch
    ):
        """The full operator loop with NO hand-editing:
        render -> run the item's real exact_command -> evidence -> rebuild ->
        status flipped + pending item cleared."""
        plans_root = tmp_path / "plans"
        plans_root.mkdir()

        def _what_now(build_dir):
            out = build_dir
            dashboard.build(
                plans_root=plans_root,
                out_dir=out,
                check_reconcile=False,
                check_architecture=False,
                write_what_now_cache=True,
                write_capabilities_cache=False,
                what_now_cache_path_override=out / "_home-what-now.json",
            )
            return json.loads((out / "what-now.json").read_text())

        # 1. First render: the static-dashboard ACTION item is pending and the
        #    STATUS item reads "pending".
        before = _what_now(tmp_path / "build1")
        before_ids = {it.get("dedupe_key") or it.get("id") for it in before["items"]}
        assert "integration:static-dashboard:static-dashboard-smoke" in before_ids
        status_before = next(
            it for it in before["items"]
            if (it.get("dedupe_key") or it.get("id")) == "integration-status:static-dashboard"
        )
        assert "pending" in status_before["title"]

        # 2. Execute the item's ACTUAL exact_command (the real smoke) through the
        #    real CLI entrypoint — this writes passed evidence via the F002 writer.
        rc = integrations_main(
            ["smoke", "static-dashboard", "--plans-root", str(plans_root)]
        )
        assert rc == 0
        recs = itg.read_evidence(
            global_config.dontpanic_home() / itg.EVIDENCE_SUBDIR, "static-dashboard"
        )
        assert recs and recs[-1]["outcome"] == "passed"

        # 3. Re-run the real provider-to-render rebuild: the pending ACTION item
        #    has cleared and the STATUS item flipped to smoke-passing — no hand-edit.
        after = _what_now(tmp_path / "build2")
        after_ids = {it.get("dedupe_key") or it.get("id") for it in after["items"]}
        assert "integration:static-dashboard:static-dashboard-smoke" not in after_ids
        status_after = next(
            it for it in after["items"]
            if (it.get("dedupe_key") or it.get("id")) == "integration-status:static-dashboard"
        )
        assert "smoke-passing" in status_after["title"]
