"""Plan 2026-05-22-003 F002 — read-only MCP capability status projection.

Covers the F002 acceptance contract:

  (1) Tool is registered on the MCP surface and is read-only.
  (2) Output envelope matches the V0b CLI JSON shape (schema_version,
      generated_at, advisory_notes, capabilities[]).
  (3) Optional capability_id narrows to a single capability or returns a
      structured unknown-id error.
  (4) Optional profile filtering matches CLI behavior (caps not in the
      profile are dropped from the response).
  (5) No setup/mutation action is exposed (no `setup`, `confirm`,
      `apply`, etc. fields; no cache-write side-effects).
  (6) No secret-value invariant: even when env vars hold sentinel
      secrets, only the *names* surface in `missing`/`configured`.

Run: PYTHONPATH=scripts pytest \\
    scripts/dontpanic_orchestrate/tests/test_capabilities_mcp_f002.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import (  # noqa: E402
    capabilities_status as cs,
)
from dontpanic_orchestrate import mcp_server  # noqa: E402
from dontpanic_orchestrate.capabilities import load_capabilities  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_NAME = "capabilities.get_status"


# ──────────────────────────────  fixtures  ──────────────────────────────


@pytest.fixture
def no_cache_writes(tmp_path, monkeypatch):
    """Trip-wire fixture: if the MCP tool ever calls
    :func:`capabilities_status.write_cache`, the test fails. Also points
    the default cache path inside ``tmp_path`` so any errant write would
    not touch the operator's real ``~/.dontpanic/`` cache.
    """
    def _fail(*_args, **_kwargs):  # pragma: no cover — must NOT fire
        raise AssertionError(
            "capabilities.get_status MCP tool must never write the status "
            "cache (acceptance #5 — no mutation)."
        )

    monkeypatch.setattr(
        "dontpanic_orchestrate.capabilities_status.write_cache", _fail
    )
    monkeypatch.setattr(
        "dontpanic_orchestrate.capabilities_status.DEFAULT_CACHE_PATH",
        tmp_path / "capabilities-status.json",
    )
    yield


# ──────────────────────────────  tool surface  ──────────────────────────────


class TestToolRegistration:
    def test_tool_is_registered(self):
        assert TOOL_NAME in mcp_server.list_tool_names()

    def test_tool_description_advertises_read_only(self):
        td = mcp_server.TOOLS[TOOL_NAME]
        text = td.description.lower()
        assert "read-only" in text
        # The description must call out that secrets are NOT exposed —
        # otherwise an agent reader cannot tell whether values are safe
        # to forward (acceptance #6).
        assert "secret" in text or "secret values" in text
        # And must call out that setup/mutation is NOT exposed
        # (acceptance #5).
        assert "setup" in text or "mutation" in text

    def test_input_schema_only_accepts_documented_fields(self):
        schema = mcp_server.tool_schema(TOOL_NAME)
        # Pydantic v2 schemas use "properties" + "additionalProperties".
        props = set(schema.get("properties", {}).keys())
        assert props == {"capability_id", "profile"}
        # extra="forbid" surfaces here as additionalProperties=False.
        assert schema.get("additionalProperties") is False

    def test_input_validation_rejects_unknown_field(self):
        with pytest.raises(mcp_server.MCPError) as exc:
            mcp_server.dispatch_tool(TOOL_NAME, {"confirm": True})
        assert exc.value.code == mcp_server.ERR_INVALID_PARAMS

    @pytest.mark.parametrize(
        "forbidden_field",
        ["setup", "confirm", "apply", "execute", "run_setup", "mutate"],
    )
    def test_no_mutation_field_accepted(self, forbidden_field):
        """Acceptance #5: the tool surface must not expose any
        setup/mutation field. Unknown fields fail input validation —
        documented here so a future drift towards a mutating shape
        breaks loudly."""
        with pytest.raises(mcp_server.MCPError) as exc:
            mcp_server.dispatch_tool(TOOL_NAME, {forbidden_field: True})
        assert exc.value.code == mcp_server.ERR_INVALID_PARAMS


# ──────────────────────────────  full-status envelope  ──────────────────────────────


class TestFullStatusEnvelope:
    def test_full_envelope_matches_cli_shape(self, no_cache_writes):
        out = mcp_server.dispatch_tool(TOOL_NAME, {})
        assert out["schema_version"] == cs.SCHEMA_VERSION
        assert isinstance(out["generated_at"], str)
        assert "capabilities" in out
        assert isinstance(out["capabilities"], list)
        assert "advisory_notes" in out
        # All checked-in manifests (original four + four operator_surface kinds) must surface.
        ids = {c["capability_id"] for c in out["capabilities"]}
        assert ids == {
            "agent-claude-cli",
            "discord-notify",
            "firebase-dashboard",
            "linear",
            "antigravity",
            "claude_desktop",
            "codex_app",
            "cursor",
        }

    def test_envelope_keys_match_cli_render_json(self, no_cache_writes):
        """Acceptance #2: MCP output must be byte-equivalent to the CLI's
        ``render_json`` envelope for the same inputs (no duplicate JSON
        shape — D-style invariant for the read-only projection)."""
        out = mcp_server.dispatch_tool(TOOL_NAME, {})

        # Build the same envelope from the CLI surface and compare keys
        # on the per-capability records. ``generated_at`` will drift
        # between the two calls, so we compare structural keys only.
        envelope = cs.run_status(capability_index=load_capabilities(REPO_ROOT))
        cli_json = json.loads(cs.render_json(envelope))

        assert set(out.keys()) == set(cli_json.keys())
        out_caps_by_id = {c["capability_id"]: c for c in out["capabilities"]}
        cli_caps_by_id = {c["capability_id"]: c for c in cli_json["capabilities"]}
        assert set(out_caps_by_id.keys()) == set(cli_caps_by_id.keys())
        for cap_id, cap in out_caps_by_id.items():
            assert set(cap.keys()) == set(cli_caps_by_id[cap_id].keys()), (
                f"MCP capability {cap_id} drifted from CLI shape: "
                f"{set(cap.keys()) ^ set(cli_caps_by_id[cap_id].keys())}"
            )

    def test_each_capability_has_v0b_required_fields(self, no_cache_writes):
        out = mcp_server.dispatch_tool(TOOL_NAME, {})
        required_keys = {
            "capability_id",
            "status",
            "owner_boundary",
            "configured",
            "missing",
            "automatable",
            "human_required",
            "pending_probes",
            "next_actions",
            "advisory_notes",
        }
        for cap in out["capabilities"]:
            assert required_keys.issubset(cap.keys()), (
                f"capability {cap['capability_id']} is missing keys: "
                f"{required_keys - set(cap.keys())}"
            )
            assert cap["status"] in cs.CAPABILITY_STATUS_VALUES


# ──────────────────────────────  capability_id narrowing  ──────────────────────────────


class TestCapabilityIdNarrowing:
    def test_known_capability_id_narrows_envelope(self, no_cache_writes):
        out = mcp_server.dispatch_tool(
            TOOL_NAME, {"capability_id": "firebase-dashboard"}
        )
        assert len(out["capabilities"]) == 1
        assert out["capabilities"][0]["capability_id"] == "firebase-dashboard"
        # Schema metadata still present at envelope level.
        assert out["schema_version"] == cs.SCHEMA_VERSION

    def test_unknown_capability_id_returns_structured_error(self, no_cache_writes):
        with pytest.raises(mcp_server.MCPError) as exc:
            mcp_server.dispatch_tool(
                TOOL_NAME, {"capability_id": "does-not-exist"}
            )
        assert exc.value.code == mcp_server.ERR_INVALID_PARAMS
        assert exc.value.data is not None
        assert exc.value.data.get("reason") == "unknown_capability"
        assert exc.value.data.get("capability_id") == "does-not-exist"

    def test_unknown_capability_message_includes_did_you_mean(self, no_cache_writes):
        """Acceptance #3: unknown id should be a *clear* error — the
        underlying envelope filter already produces a 'did you mean'
        suggestion; the MCP surface must not swallow it."""
        with pytest.raises(mcp_server.MCPError) as exc:
            mcp_server.dispatch_tool(
                TOOL_NAME, {"capability_id": "firebase-dashbord"}  # typo
            )
        assert exc.value.code == mcp_server.ERR_INVALID_PARAMS
        assert "firebase-dashboard" in exc.value.message


# ──────────────────────────────  profile filtering  ──────────────────────────────


class TestProfileFiltering:
    def test_profile_firebase_dashboard_drops_other_capabilities(
        self, no_cache_writes
    ):
        out = mcp_server.dispatch_tool(
            TOOL_NAME, {"profile": "firebase-dashboard"}
        )
        ids = {c["capability_id"] for c in out["capabilities"]}
        # Only firebase-dashboard declares the firebase-dashboard
        # profile in default_in_profiles.
        assert ids == {"firebase-dashboard"}

    def test_profile_core_only_returns_core_default_capabilities(
        self, no_cache_writes
    ):
        """Only manifests that declare ``core`` in default_in_profiles
        survive a ``profile=core`` filter. In the checked-in manifest
        set, that's just agent-claude-cli."""
        out = mcp_server.dispatch_tool(TOOL_NAME, {"profile": "core"})
        ids = {c["capability_id"] for c in out["capabilities"]}
        assert ids == {"agent-claude-cli"}

    def test_profile_match_matches_cli_run_status(self, no_cache_writes):
        """Acceptance #4: profile filtering must match the CLI's behavior
        (which is run_status(profile=...))."""
        out = mcp_server.dispatch_tool(TOOL_NAME, {"profile": "core"})
        envelope = cs.run_status(
            capability_index=load_capabilities(REPO_ROOT), profile="core"
        )
        assert sorted(c["capability_id"] for c in out["capabilities"]) == sorted(
            c.capability_id for c in envelope.capabilities
        )

    def test_unknown_profile_returns_empty_capability_list(self, no_cache_writes):
        """An unknown profile name matches no manifest — the response is
        a well-formed envelope with an empty capabilities list (NOT an
        error). Matches CLI behavior."""
        out = mcp_server.dispatch_tool(
            TOOL_NAME, {"profile": "totally-made-up-profile"}
        )
        assert out["capabilities"] == []
        assert out["schema_version"] == cs.SCHEMA_VERSION

    def test_profile_and_capability_id_compose(self, no_cache_writes):
        """capability_id narrowing applies to the profile-filtered set."""
        out = mcp_server.dispatch_tool(
            TOOL_NAME,
            {"profile": "firebase-dashboard", "capability_id": "firebase-dashboard"},
        )
        assert len(out["capabilities"]) == 1
        assert out["capabilities"][0]["capability_id"] == "firebase-dashboard"


# ──────────────────────────────  no-secret-value invariant  ──────────────────────────────


class TestNoSecretValueInvariant:
    """Acceptance #6: the envelope must never carry secret values, only
    the *names* of unresolved env/auth/config tokens. We verify by
    setting a sentinel value into a known env var and confirming the
    sentinel never appears anywhere in the returned envelope."""

    def test_env_var_values_never_leak_into_envelope(
        self, no_cache_writes, monkeypatch
    ):
        sentinel = "SENTINEL_SECRET_VALUE_8a4f2c9b_DO_NOT_LEAK"
        # DONTPANIC_FIREBASE_PROJECT is the env var the firebase-dashboard
        # manifest declares as required. If the envelope ever serializes
        # env-var *values* (it shouldn't), the sentinel will surface.
        monkeypatch.setenv("DONTPANIC_FIREBASE_PROJECT", sentinel)

        out = mcp_server.dispatch_tool(TOOL_NAME, {})
        as_json = json.dumps(out)
        assert sentinel not in as_json, (
            "MCP envelope leaked an env-var value — only token *names* are "
            "permitted in the projection (acceptance #6)."
        )

        # And the env var name itself MUST appear (as a resolved token).
        firebase = next(
            c for c in out["capabilities"]
            if c["capability_id"] == "firebase-dashboard"
        )
        assert "DONTPANIC_FIREBASE_PROJECT" in firebase["configured"]


# ──────────────────────────────  read-only / no-mutation invariant  ──────────────────────────────


class TestReadOnlyInvariant:
    def test_tool_does_not_write_cache(self, no_cache_writes):
        """The ``no_cache_writes`` fixture patches
        :func:`capabilities_status.write_cache` to fail the test if it
        ever runs. Calling the tool must succeed without tripping it."""
        out = mcp_server.dispatch_tool(TOOL_NAME, {})
        assert "capabilities" in out  # sanity — the tool actually ran.

    def test_tool_does_not_register_a_supervisor(self, no_cache_writes):
        """The read-only tool must not register a supervisor entry (only
        the dispatch tool does). We rely on the autouse
        ``_isolate_jarvis_state`` fixture to redirect the registry into
        per-test paths, and assert no entries land there.
        """
        from dontpanic_orchestrate import active_supervisors

        mcp_server.dispatch_tool(TOOL_NAME, {})
        assert active_supervisors.list_active() == []

    def test_tool_does_not_clear_any_gate(self, no_cache_writes, tmp_path):
        """The tool must not mutate gate-pause state. We pre-create a
        plan dir with no cleared gates and confirm none flip after the
        tool runs.
        """
        from dontpanic_orchestrate import gate_pause

        # We don't need a registered plan for this — gate-pause state is
        # plan-dir-local. Just create a synthetic dir.
        plan_dir = tmp_path / "synthetic-plan"
        plan_dir.mkdir()
        assert not gate_pause.is_gate_cleared(plan_dir, "pre_impl")
        mcp_server.dispatch_tool(TOOL_NAME, {})
        assert not gate_pause.is_gate_cleared(plan_dir, "pre_impl")


# ──────────────────────────────  JSON-RPC envelope  ──────────────────────────────


class TestJsonRpcEnvelope:
    def test_jsonrpc_call_returns_text_content_block(self, no_cache_writes):
        resp = mcp_server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": TOOL_NAME, "arguments": {}},
            }
        )
        assert resp["result"]["isError"] is False
        block = resp["result"]["content"][0]
        assert block["type"] == "text"
        parsed = json.loads(block["text"])
        assert parsed["schema_version"] == cs.SCHEMA_VERSION

    def test_jsonrpc_unknown_capability_returns_error_envelope(
        self, no_cache_writes
    ):
        resp = mcp_server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": TOOL_NAME,
                    "arguments": {"capability_id": "does-not-exist"},
                },
            }
        )
        assert "error" in resp
        assert resp["error"]["code"] == mcp_server.ERR_INVALID_PARAMS
        assert resp["error"]["data"]["reason"] == "unknown_capability"
