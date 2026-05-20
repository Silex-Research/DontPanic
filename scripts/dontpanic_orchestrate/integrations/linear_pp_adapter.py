"""DontPanic-side adapter for the Linear MCP binary wrapped via Printing Press.

This module is the reference implementation of P10 F001's
``printing-press-adapter`` skill (claude/skills/printing-press-adapter/
ADAPTER_TEMPLATE.md). It owns the trust boundary between the rest of
DontPanic and the PP-emitted Linear MCP binary:

  (i)   spawns the PP-emitted MCP binary as a subprocess
        (stdin/stdout JSON-RPC, per the MCP spec),
  (ii)  forwards each tool call to the subprocess,
  (iii) decorates every tool response with DontPanic's redact_level
        middleware, then runs a post-redaction sanitization check
        (fails closed on any surviving secret-shaped substring)
        before returning it to the caller,
  (iv)  hard-rejects any tool call whose tool name is in MUTATING_TOOLS
        unless P10 v2 approval-gate templating is wired (v0 hard-rejects
        regardless; ``issueUpdate`` is plumbed via a SEPARATE explicit
        ``push_status`` codepath that lives in this module so the v0
        read-only invariant on the generic ``call_tool`` proxy still
        holds),
  (v)   exposes an explicit ``register_adapter()`` helper for writing
        ``$DONTPANIC_HOME/adapters.json`` without import-time mutation.

The PP binary itself is delivered by the P10 F003 dogfood and remains
operator-gated until the single paid ``/printing-press linear`` invocation
runs. Until then, ``LinearPPAdapter`` accepts a constructor-injected
``subprocess_factory`` so fixture tests exercise the same stdio boundary
without touching the real disk path or the operator's paid-call budget.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from dontpanic_orchestrate.global_config import dontpanic_home


# ────────────────────────────  template-required constants  ────────────────────────────

SERVICE_NAME: str = "linear"

REDACT_LEVEL: str = "internal"

# v0 of the PP adapter skill is read-only — every name in this set
# hard-rejects on the generic ``call_tool`` proxy. ``issueUpdate``
# (Linear's status-flip tool) is listed here for completeness; the
# bridge plan's F001 calls it through the EXPLICIT ``push_status``
# codepath below, which the operator opts into per ``external_refs[].sync``.
MUTATING_TOOLS: frozenset[str] = frozenset({"issueUpdate"})


def _pp_binary_path() -> Path:
    return dontpanic_home() / "adapters" / SERVICE_NAME / f"{SERVICE_NAME}-pp-mcp"


def _adapters_registry_path() -> Path:
    return dontpanic_home() / "adapters.json"


def _per_service_config_path() -> Path:
    return dontpanic_home() / "adapters" / f"{SERVICE_NAME}.json"


# Resolved lazily via ``dontpanic_home()`` so tests that set
# ``$DONTPANIC_HOME`` (the per-test isolated dir from conftest) don't
# touch operator-real paths. Module-level names retained for the
# template's public surface; the callable form is what writers use.
PP_BINARY_PATH: Path = _pp_binary_path()
ADAPTERS_REGISTRY: Path = _adapters_registry_path()
PER_SERVICE_CONFIG: Path = _per_service_config_path()


def register_adapter() -> None:
    """Idempotently add this adapter to ``$DONTPANIC_HOME/adapters.json``.

    Mirrors the template's ``register_adapter``. Never overwrites a
    pre-existing entry — operator owns the final shape of the registry.

    Path resolution honors ``dontpanic_home()`` (env-var aware), so
    test runs with ``DONTPANIC_HOME`` pointed at a per-test tmp dir
    never touch the operator's real ``~/.dontpanic`` state. Plan D011.
    """

    registry_path = _adapters_registry_path()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    if registry_path.exists():
        try:
            registry = json.loads(registry_path.read_text())
        except json.JSONDecodeError:
            registry = {}
    else:
        registry = {}

    adapters = registry.setdefault("adapters", {})
    if SERVICE_NAME in adapters:
        return

    adapters[SERVICE_NAME] = {
        "module": f"dontpanic_orchestrate.integrations.{SERVICE_NAME}_pp_adapter",
        "config_path": str(_per_service_config_path()),
        "binary_path": str(_pp_binary_path()),
        "redact_level": REDACT_LEVEL,
        "mutating_tools": sorted(MUTATING_TOOLS),
        "version_pin_source": "per_service_config.pp_version",
    }
    registry_path.write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n"
    )


# ────────────────────────────  middleware  ────────────────────────────


class MutationRejected(Exception):
    """Raised when a caller invokes a mutating tool via the generic
    ``call_tool`` proxy in v0. Hard-reject; no override flag."""


class SanitizationFailed(Exception):
    """Raised when a post-redaction sanitization check finds a
    secret-shaped substring that the redact pass did not strip.

    This is the hard backstop: redaction is permitted to be lenient
    (it preserves payload shape for downstream consumers), so the
    sanitizer fails closed if any telltale token pattern survives.
    """


def apply_redact(payload: Any, level: str) -> Any:
    """Apply the DontPanic redact_level middleware to a tool response.

    v0 placeholder (per template): the real implementation lives in
    ``dontpanic_orchestrate.redact`` (plan 2026-05-09-003 F006). When
    that module ships, the import here swaps over without changing the
    redact/sanitize boundary contract.
    """

    if isinstance(payload, dict):
        return {
            "_redact_level": level,
            "_redacted_at": "adapter_response_boundary",
            **{k: apply_redact(v, level) for k, v in payload.items()},
        }
    if isinstance(payload, list):
        return [apply_redact(item, level) for item in payload]
    return payload


_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"(?i)\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bghp_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
)


def _scan_for_secrets(value: Any, path: str = "$") -> list[str]:
    """Walk a post-redacted payload and return JSON-pointer-ish paths
    where a secret-shaped substring survived. Pure read."""

    hits: list[str] = []
    if isinstance(value, str):
        for pattern in _SECRET_PATTERNS:
            if pattern.search(value):
                hits.append(f"{path} (matched {pattern.pattern!r})")
                break
    elif isinstance(value, dict):
        for key, sub in value.items():
            hits.extend(_scan_for_secrets(sub, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, sub in enumerate(value):
            hits.extend(_scan_for_secrets(sub, f"{path}[{index}]"))
    return hits


def sanitize_response(payload: Any, level: str) -> Any:
    """Post-redaction sanitization check. Fails closed if any
    secret-shaped substring survived the redact pass."""

    leaks = _scan_for_secrets(payload)
    if leaks:
        raise SanitizationFailed(
            "post-redaction sanitizer rejected adapter response; "
            f"secret-shaped substrings survived redaction at: {leaks}"
        )
    if isinstance(payload, dict):
        return {
            "_sanitized_at": "adapter_response_boundary",
            "_sanitizer_redact_level": level,
            **payload,
        }
    return payload


def redact_and_sanitize(payload: Any, level: str) -> Any:
    """Compose the two-stage response pipeline used by every code
    path in ``call_tool`` (success, no-response, invalid JSON)."""

    return sanitize_response(apply_redact(payload, level), level)


def reject_if_mutating(tool_name: str, arguments: dict[str, Any]) -> None:
    """Hard-reject mutating tool calls on the generic ``call_tool``
    proxy. The bridge's explicit ``push_status`` codepath bypasses
    this — the v0 invariant is that READ tools only flow through
    ``call_tool``."""

    if tool_name not in MUTATING_TOOLS:
        return
    raise MutationRejected(
        f"Tool {tool_name!r} mutates the target service. "
        "PP adapter v0 is read-only on the generic call_tool proxy. "
        "Status flips must go through LinearPPAdapter.push_status, "
        "which is opt-in via external_refs[].sync = 'push_status' and "
        "writes a durable ExternalSyncRecord per attempt."
    )


# ────────────────────────────  subprocess proxy  ────────────────────────────


SubprocessFactory = Callable[[Path], "subprocess.Popen[bytes]"]


def _default_subprocess_factory(binary_path: Path) -> "subprocess.Popen[bytes]":
    """Real subprocess spawn — shell=False, env inherited. Tests
    inject a fake factory so this codepath is never touched in unit
    tests (no PP binary required at unit-test time)."""

    return subprocess.Popen(
        [str(binary_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        env=os.environ.copy(),
    )


@dataclass
class LinearPPAdapter:
    """Long-lived subprocess wrapper around the Linear PP MCP binary.

    Constructor-injected ``subprocess_factory`` and ``redact_level``
    keep unit tests pure: tests stub the subprocess with an in-memory
    fake while preserving the redact → sanitize boundary that
    production code traverses. ``call_tool`` and ``push_status`` are
    the only two public codepaths; both route every response through
    ``redact_and_sanitize``.
    """

    binary_path: Path = PP_BINARY_PATH
    redact_level: str = REDACT_LEVEL
    subprocess_factory: SubprocessFactory = field(
        default=_default_subprocess_factory, repr=False
    )
    _process: "subprocess.Popen[bytes] | None" = field(
        default=None, init=False, repr=False
    )
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def _ensure_started(self) -> "subprocess.Popen[bytes]":
        if self._process is not None and self._process.poll() is None:
            return self._process
        self._process = self.subprocess_factory(self.binary_path)
        return self._process

    def _send_and_receive(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> Any:
        """Forward one MCP tool call to the subprocess. Runs every
        result through ``redact_and_sanitize`` — including the
        synthetic no-response / invalid-JSON envelopes so the
        boundary invariant holds on every code path."""

        proc = self._ensure_started()
        assert proc.stdin is not None and proc.stdout is not None
        with self._lock:
            envelope = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }
            proc.stdin.write((json.dumps(envelope) + "\n").encode("utf-8"))
            proc.stdin.flush()
            raw = proc.stdout.readline()
        if not raw:
            return redact_and_sanitize(
                {"error": "pp_binary_no_response"}, self.redact_level
            )
        try:
            response = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return redact_and_sanitize(
                {"error": "pp_binary_invalid_json"}, self.redact_level
            )
        return redact_and_sanitize(response.get("result"), self.redact_level)

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Read-only generic tool proxy. Mutating tool names hard-reject
        here. F001's ``read_issue`` goes through this codepath."""

        reject_if_mutating(tool_name, arguments)
        return self._send_and_receive(tool_name, arguments)

    def push_status(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """Explicit, opt-in mutation codepath used by the bridge's
        ``LinearPMTool.push_status`` after F002's plan-close walker
        has confirmed the operator's ``external_refs[].sync`` opt-in.

        Bypasses ``reject_if_mutating`` because the bridge writes a
        durable ``ExternalSyncRecord`` per attempt (success or failure)
        — that record is the gate, not the read-only proxy guard. v0
        scope: ``issueUpdate`` only; any other ``tool_name`` raises so
        new mutation surfaces can't smuggle in.
        """

        if tool_name != "issueUpdate":
            raise MutationRejected(
                f"push_status only mediates 'issueUpdate' in v0; got {tool_name!r}. "
                "Add the new mutation to a follow-on plan with explicit gate design."
            )
        return self._send_and_receive(tool_name, arguments)

    def close(self) -> None:
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None


__all__ = (
    "SERVICE_NAME",
    "PP_BINARY_PATH",
    "REDACT_LEVEL",
    "MUTATING_TOOLS",
    "LinearPPAdapter",
    "MutationRejected",
    "SanitizationFailed",
    "apply_redact",
    "sanitize_response",
    "redact_and_sanitize",
    "register_adapter",
)
