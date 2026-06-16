"""F003 — agent-surface EvidenceSource adapters (CLI / MCP / contract-check).

Pinned: fixed CLI argv constant + offline guard + stdout schema (cli_agent);
in-process MCP tools/list + pinned read-only status tool (agent_mcp_tool);
post-bump schema contract-check (service_batch). Successful refs carry the
shared typed fields; typed-skips carry availability=unavailable +
data_provenance=degraded + degraded_mode + note + artifact body. No
secret-shaped data; harness dispatch stays source-agnostic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))  # dontpanic_orchestrate on path

from runtime_evidence import agent_sources as a  # noqa: E402
from runtime_evidence.harness import EvidenceCollector  # noqa: E402

JOURNEY = "agent-readiness"


def _read(plan_dir, ref):
    return (Path(plan_dir) / ref.uri).read_text()


# --- pinned constants ---------------------------------------------------------

def test_cli_argv_and_pinned_constants_are_fixed():
    assert a.CLI_ADAPTER_ARGV == ("dontpanic", "doctor", "--json")
    assert a.CLI_OFFLINE_ENV == "DONTPANIC_OFFLINE"
    assert a.MCP_READONLY_TOOL == "status"
    assert a.CONTRACT_TARGET_MODULES == (
        "features_model", "objective_contract_model", "experience_readiness")


# --- CLI transcript -----------------------------------------------------------

def test_cli_success_emits_typed_cli_agent_ref(tmp_path):
    seen = {}

    def runner(argv):
        seen["argv"] = argv
        return 0, '{"ok": true}'

    src = a.cli_transcript_source(tmp_path, runner=runner, env={a.CLI_OFFLINE_ENV: "1"})
    refs = src.collect(JOURNEY)
    assert seen["argv"] == a.CLI_ADAPTER_ARGV  # ran the pinned argv
    assert len(refs) == 1
    r = refs[0]
    assert r.evidence_class == "cli_transcript"
    assert r.surface_class == "cli_agent"
    assert r.availability == "available"
    assert r.consumer_family == "agent"
    assert r.data_provenance == "real"
    assert r.data_source == "dontpanic_cli"
    assert "DONTPANIC_OFFLINE=1" in _read(tmp_path, r)


def test_cli_offline_guard_unset_yields_typed_skip(tmp_path):
    src = a.cli_transcript_source(tmp_path, runner=lambda argv: (0, '{"ok": true}'), env={})
    (r,) = src.collect(JOURNEY)
    assert r.availability == "unavailable"
    assert r.data_provenance == "degraded"
    assert r.degraded_mode == "offline_guard_unset"
    assert r.note and r.surface_class == "cli_agent"
    body = _read(tmp_path, r)
    # D029: reason location explicit + asserted; ref degraded_mode/note CONSISTENT with body
    assert "reason:" in body
    assert f"degraded_mode: {r.degraded_mode}" in body
    assert r.note in body


def test_cli_contract_unmet_and_absent_yield_typed_skips(tmp_path):
    bad = a.cli_transcript_source(tmp_path, runner=lambda argv: (0, "not json"),
                                  env={a.CLI_OFFLINE_ENV: "1"})
    (r1,) = bad.collect(JOURNEY)
    assert r1.degraded_mode == "cli_contract_unmet" and r1.availability == "unavailable"

    def absent(argv):
        raise FileNotFoundError(argv[0])

    miss = a.cli_transcript_source(tmp_path, runner=absent, env={a.CLI_OFFLINE_ENV: "1"})
    (r2,) = miss.collect(JOURNEY)
    assert r2.degraded_mode == "cli_absent"


def test_cli_secret_shaped_stdout_is_rejected_not_written(tmp_path):
    leak = a.cli_transcript_source(
        tmp_path, runner=lambda argv: (0, '{"ok": true, "tok": "ghp_' + "a" * 36 + '"}'),
        env={a.CLI_OFFLINE_ENV: "1"})
    with pytest.raises(a.SecretShapedArtifact):
        leak.collect(JOURNEY)


# --- MCP transcript (real in-process mcp_server) ------------------------------

def test_mcp_success_via_in_process_server_lists_status_tool(tmp_path):
    src = a.mcp_transcript_source(tmp_path)  # default real dispatch
    (r,) = src.collect(JOURNEY)
    assert r.evidence_class == "tool_call_transcript"
    assert r.surface_class == "agent_mcp_tool"
    assert r.availability == "available" and r.consumer_family == "agent"
    assert r.data_provenance == "real"
    import json
    body = json.loads(_read(tmp_path, r))
    # D045: tools/list AND an actual status tool invocation (request+response) recorded
    assert a.MCP_READONLY_TOOL in body["tools_list"]["tool_names"]
    assert body["status_call"]["request"]["params"]["name"] == a.MCP_READONLY_TOOL
    assert body["status_call"]["request"]["method"] == "tools/call"
    assert "response" in body["status_call"]


def test_mcp_status_tool_absent_yields_typed_skip(tmp_path):
    def dispatch(_msg):
        return {"result": {"tools": [{"name": "something_else"}]}}

    src = a.mcp_transcript_source(tmp_path, dispatch=dispatch)
    (r,) = src.collect(JOURNEY)
    assert r.degraded_mode == "status_tool_absent" and r.availability == "unavailable"


def test_mcp_status_call_error_yields_typed_skip(tmp_path):
    # tools/list lists status, but the status call returns an error envelope
    def dispatch(msg):
        if msg["method"] == "tools/list":
            return {"result": {"tools": [{"name": a.MCP_READONLY_TOOL}]}}
        return {"result": {"isError": True, "content": []}}

    src = a.mcp_transcript_source(tmp_path, dispatch=dispatch)
    (r,) = src.collect(JOURNEY)
    assert r.degraded_mode == "status_call_errored" and r.availability == "unavailable"


# --- contract-check -----------------------------------------------------------

def test_contract_check_success_emits_service_batch_ref(tmp_path):
    src = a.contract_check_source(tmp_path)
    (r,) = src.collect(JOURNEY)
    assert r.evidence_class == "contract_check"
    assert r.surface_class == "service_batch"
    assert r.availability == "available" and r.consumer_family == "agent"
    body = _read(tmp_path, r)
    assert "rejects_family_contradiction" in body


# --- harness source-agnostic dispatch (registration, not name) ---------------

def test_harness_dispatches_all_three_sources_by_registration(tmp_path):
    sources = [
        a.cli_transcript_source(tmp_path, runner=lambda argv: (0, '{"ok": true}'),
                                env={a.CLI_OFFLINE_ENV: "1"}),
        a.mcp_transcript_source(tmp_path),
        a.contract_check_source(tmp_path),
    ]
    refs = EvidenceCollector(tmp_path).collect(JOURNEY, sources=sources)
    classes = {r.evidence_class for r in refs}
    assert {"cli_transcript", "tool_call_transcript", "contract_check"} <= classes
    # every successful ref is bound to an agent surface with the shared fields
    for r in refs:
        if r.availability == "available":
            assert r.surface_class in {"cli_agent", "agent_mcp_tool", "service_batch"}
            assert r.consumer_family == "agent" and r.data_source
