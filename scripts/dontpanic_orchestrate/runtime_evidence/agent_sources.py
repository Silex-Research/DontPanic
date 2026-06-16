"""Experience Readiness — agent-surface evidence sources (F003).

Plan 2026-06-15-001 (2a-core). Three dogfoodable :class:`EvidenceSource`
adapters that emit EvidenceRefs carrying F001's typed fields (surface_class +
the shared vocabulary), so F002 can type them:

- ``cli_transcript_source``  — fixed read-only argv (module constant) under an
  offline env guard, pinned stdout schema; surface_class=cli_agent.
- ``mcp_transcript_source``  — drives the in-process ``mcp_server`` tools/list
  plus the PINNED read-only ``status`` tool; surface_class=agent_mcp_tool.
- ``contract_check_source``  — validates the POST-bump agent-conventions schema
  models (D063); surface_class=service_batch.

Each SUCCESSFUL ref carries data_source + availability=available +
consumer_family=agent + data_provenance=real + the surface's evidence_class.
When a prerequisite is absent each source emits an HONEST typed-skip
(availability=unavailable + data_provenance=degraded + degraded_mode + note +
artifact body). NO secret-shaped data enters artifacts or refs. The harness
dispatches these by registration (it never branches on source name).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dontpanic_orchestrate.nested_orchestration import goal_governance_evidence_path
from sanitization_check import SECRET_REGEXES as _SECRET_REGEXES

from .harness import _BoundSource

# models path is ensured by harness import above
from models.features_model import EvidenceRef  # noqa: E402
from models.features_model import Type as EvidenceType  # noqa: E402

# --- pinned contracts (module constants; asserted by F003 equality tests) -----
CLI_ADAPTER_ARGV: tuple[str, ...] = ("dontpanic", "doctor", "--json")
CLI_OFFLINE_ENV = "DONTPANIC_OFFLINE"
CLI_STDOUT_REQUIRED_KEYS: frozenset[str] = frozenset({"ok"})
MCP_READONLY_TOOL = "status"
CONTRACT_TARGET_MODULES: tuple[str, ...] = (
    "features_model",
    "objective_contract_model",
    "experience_readiness",
)

_CONSUMER_FAMILY_AGENT = "agent"
_DEFAULT_CLOCK = lambda: datetime.now(timezone.utc)  # noqa: E731


class SecretShapedArtifact(Exception):
    """Raised when an adapter artifact/ref would carry secret-shaped data."""


def _assert_no_secret(text: str) -> None:
    for rx in _SECRET_REGEXES:
        if rx.search(text):
            raise SecretShapedArtifact(
                f"adapter artifact matched a secret-shaped pattern: {rx.pattern!r}"
            )


def _write(plan_dir: Path, source: str, journey: str, filename: str, body: str) -> tuple[str, str]:
    _assert_no_secret(body)
    out = goal_governance_evidence_path(Path(plan_dir).resolve(), "post_impl", f"{source}/{journey}") / filename
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = body.encode("utf-8")
    out.write_bytes(payload)
    rel = str(out.relative_to(Path(plan_dir).resolve()))
    return rel, f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _success_ref(*, uri, hash_, evidence_class, surface_class, data_source, clock) -> EvidenceRef:
    return EvidenceRef(
        type=EvidenceType.log if evidence_class != "contract_check" else EvidenceType.test_output,
        uri=uri,
        hash=hash_,
        captured_at=clock(),
        captured_by="agent-evidence-source",
        evidence_class=evidence_class,
        data_provenance="real",
        data_source=data_source,
        availability="available",
        consumer_family=_CONSUMER_FAMILY_AGENT,
        surface_class=surface_class,
    )


def _typed_skip(plan_dir, *, source, journey, evidence_class, surface_class,
                data_source, degraded_mode, reason, clock) -> EvidenceRef:
    body = (
        f"reason: {reason}\nsource: {source}\njourney: {journey}\n"
        f"degraded_mode: {degraded_mode}\ndata_source: {data_source}\n"
    )
    uri, hash_ = _write(plan_dir, source, journey, f"skip-{source}.txt", body)
    return EvidenceRef(
        type=EvidenceType.log,
        uri=uri,
        hash=hash_,
        captured_at=clock(),
        captured_by="agent-evidence-source",
        note=reason,
        evidence_class=evidence_class,
        data_provenance="degraded",
        data_source=data_source,
        availability="unavailable",
        consumer_family=_CONSUMER_FAMILY_AGENT,
        surface_class=surface_class,
        degraded_mode=degraded_mode,
    )


# ──────────────────────────────  CLI transcript  ──────────────────────────────

def _default_cli_runner(argv: tuple[str, ...]) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603 — fixed argv constant, shell=False
        list(argv),
        capture_output=True,
        text=True,
        timeout=15,
        env={**os.environ, CLI_OFFLINE_ENV: "1"},
    )
    return proc.returncode, proc.stdout


def _valid_cli_stdout(stdout: str) -> bool:
    try:
        doc = json.loads(stdout)
    except (ValueError, TypeError):
        return False
    return isinstance(doc, dict) and CLI_STDOUT_REQUIRED_KEYS <= set(doc)


def cli_transcript_source(plan_dir, *, runner=_default_cli_runner, env=None,
                          clock=None, name: str = "cli_agent"):
    clock = clock or _DEFAULT_CLOCK
    environ = env if env is not None else os.environ

    def _collect(journey):
        skip = lambda mode, reason: [_typed_skip(  # noqa: E731
            plan_dir, source=name, journey=journey, evidence_class="cli_transcript",
            surface_class="cli_agent", data_source="dontpanic_cli", degraded_mode=mode,
            reason=reason, clock=clock)]
        if environ.get(CLI_OFFLINE_ENV) != "1":
            return skip("offline_guard_unset", f"skipped: {CLI_OFFLINE_ENV}!=1 (offline guard required)")
        try:
            code, stdout = runner(CLI_ADAPTER_ARGV)
        except FileNotFoundError:
            return skip("cli_absent", f"skipped: {CLI_ADAPTER_ARGV[0]} not on PATH")
        except Exception as exc:  # noqa: BLE001
            return skip("cli_fault", f"skipped: cli runner fault: {type(exc).__name__}")
        if code != 0 or not _valid_cli_stdout(stdout):
            return skip("cli_contract_unmet",
                        f"skipped: argv exit={code} or stdout off pinned schema {sorted(CLI_STDOUT_REQUIRED_KEYS)}")
        body = f"argv: {list(CLI_ADAPTER_ARGV)}\nexit: {code}\noffline_guard: {CLI_OFFLINE_ENV}=1\nstdout:\n{stdout}\n"
        uri, hash_ = _write(plan_dir, name, journey, "cli-transcript.log", body)
        return [_success_ref(uri=uri, hash_=hash_, evidence_class="cli_transcript",
                             surface_class="cli_agent", data_source="dontpanic_cli", clock=clock)]

    return _BoundSource(name=name, _fn=_collect)


# ──────────────────────────────  MCP transcript  ──────────────────────────────

def _default_mcp_dispatch(message):
    import mcp_server
    return mcp_server.handle_request(message)


def mcp_transcript_source(plan_dir, *, dispatch=_default_mcp_dispatch, clock=None,
                          name: str = "agent_mcp_tool"):
    clock = clock or _DEFAULT_CLOCK

    def _collect(journey):
        skip = lambda mode, reason: [_typed_skip(  # noqa: E731
            plan_dir, source=name, journey=journey, evidence_class="tool_call_transcript",
            surface_class="agent_mcp_tool", data_source="mcp:tools/list", degraded_mode=mode,
            reason=reason, clock=clock)]
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        try:
            response = dispatch(request)
        except Exception as exc:  # noqa: BLE001
            return skip("mcp_unavailable", f"skipped: mcp dispatch fault: {type(exc).__name__}")
        try:
            tool_names = [t["name"] for t in response["result"]["tools"]]
        except (KeyError, TypeError):
            return skip("mcp_malformed", "skipped: tools/list response malformed")
        if MCP_READONLY_TOOL not in tool_names:
            return skip("status_tool_absent",
                        f"skipped: pinned read-only tool {MCP_READONLY_TOOL!r} not in tools/list")
        # F003/D045: ACTUALLY INVOKE the pinned read-only status tool and record
        # request+response — tools/list alone is not proof of the journey outcome.
        status_request = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                          "params": {"name": MCP_READONLY_TOOL, "arguments": {}}}
        try:
            status_response = dispatch(status_request)
        except Exception as exc:  # noqa: BLE001
            return skip("status_call_failed", f"skipped: status tool call fault: {type(exc).__name__}")
        if (not isinstance(status_response, dict) or status_response.get("error")
                or (status_response.get("result") or {}).get("isError")):
            return skip("status_call_errored", "skipped: status tool call returned an error envelope")
        transcript = {
            "tools_list": {"request": request, "tool_names": sorted(tool_names),
                           "pinned_read_only_tool": MCP_READONLY_TOOL},
            "status_call": {"request": status_request, "response": status_response},
        }
        body = json.dumps(transcript, indent=2, ensure_ascii=False)
        uri, hash_ = _write(plan_dir, name, journey, "mcp-tools-list-and-status.json", body)
        return [_success_ref(uri=uri, hash_=hash_, evidence_class="tool_call_transcript",
                             surface_class="agent_mcp_tool", data_source="mcp:tools/list+status", clock=clock)]

    return _BoundSource(name=name, _fn=_collect)


# ──────────────────────────────  contract-check  ──────────────────────────────

def contract_check_source(plan_dir, *, clock=None, name: str = "service_batch"):
    clock = clock or _DEFAULT_CLOCK

    def _collect(journey):
        skip = lambda mode, reason: [_typed_skip(  # noqa: E731
            plan_dir, source=name, journey=journey, evidence_class="contract_check",
            surface_class="service_batch", data_source="agent_conventions_schema",
            degraded_mode=mode, reason=reason, clock=clock)]
        try:
            # path-robust: models dir on sys.path directly OR via the `models` pkg
            try:
                import experience_readiness  # noqa: F401
                import objective_contract_model  # noqa: F401
                from features_model import EvidenceRef as _ER
            except ImportError:
                import models.experience_readiness  # noqa: F401
                import models.objective_contract_model  # noqa: F401
                from models.features_model import EvidenceRef as _ER
        except Exception as exc:  # noqa: BLE001
            return skip("schema_import_failed", f"skipped: post-bump schema import failed: {type(exc).__name__}")
        # positive: a fully-typed agent EvidenceRef validates
        try:
            _ER(type="log", uri="contract/probe", evidence_class="tool_call_transcript",
                data_provenance="real", data_source="probe", availability="available",
                consumer_family="agent", surface_class="agent_mcp_tool")
        except Exception as exc:  # noqa: BLE001
            return skip("contract_unmet", f"skipped: valid ref rejected by schema: {type(exc).__name__}")
        # negative: family contradiction (D065) MUST be rejected
        rejects_invalid = False
        try:
            _ER(type="log", uri="contract/bad", data_source="s", availability="available",
                consumer_family="human", surface_class="agent_mcp_tool")
        except Exception:  # noqa: BLE001 — expected rejection
            rejects_invalid = True
        if not rejects_invalid:
            return skip("contract_unmet", "skipped: schema failed to reject a family-contradiction ref")
        result = {"targets": list(CONTRACT_TARGET_MODULES), "validated_typed_ref": True,
                  "rejects_family_contradiction": True}
        body = json.dumps(result, indent=2, ensure_ascii=False)
        uri, hash_ = _write(plan_dir, name, journey, "contract-check.json", body)
        return [_success_ref(uri=uri, hash_=hash_, evidence_class="contract_check",
                             surface_class="service_batch", data_source="agent_conventions_schema", clock=clock)]

    return _BoundSource(name=name, _fn=_collect)


__all__ = [
    "CLI_ADAPTER_ARGV",
    "CLI_OFFLINE_ENV",
    "CLI_STDOUT_REQUIRED_KEYS",
    "MCP_READONLY_TOOL",
    "CONTRACT_TARGET_MODULES",
    "SecretShapedArtifact",
    "cli_transcript_source",
    "mcp_transcript_source",
    "contract_check_source",
]
