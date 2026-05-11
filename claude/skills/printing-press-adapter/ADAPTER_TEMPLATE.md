# printing-press-adapter — Adapter Template

Drop this skeleton into
`scripts/dontpanic_orchestrate/adapters/<service>_adapter.py` and
fill the four blanks at the top: `SERVICE_NAME`, `PP_BINARY_PATH`,
`REDACT_LEVEL`, and the mutation policy. The skeleton subprocess-
spawns the Printing Press-emitted MCP binary, proxies JSON-RPC tool
calls over its stdio, decorates every response with DontPanic's
redaction middleware **and a post-redaction sanitization check**,
and hard-rejects any tool call that would mutate without
`confirm: true`.

The response pipeline is two-stage by directive:

1. **Redact** — `apply_redact(payload, level)` annotates the payload
   with the applied tier and recursively walks it. This is the
   policy seam: the real redact module ships in plan 003 F006.
2. **Sanitize** — `sanitize_response(payload, level)` runs *after*
   redaction on every code path (success, no-response, invalid JSON,
   mutation-rejection). It scans the post-redacted payload for
   telltale secret-shaped substrings (bearer tokens, API keys, PEM
   blocks) and raises `SanitizationFailed` if any survived the
   redact pass — i.e., redaction is treated as a soft transform and
   sanitization is the hard backstop that fails closed.

The split is deliberate: redact may be lenient (it preserves shape
for downstream consumers), so sanitize is non-optional and runs even
on synthetic error envelopes. Both stages MUST execute on every
response that crosses the adapter boundary.

The body below is a **single Python module** — the acceptance test
extracts it and runs `ast.parse` to confirm it is syntactically
valid. It is deliberately a skeleton: no live invocation, no token
handling, no network calls. F003's dogfood is where it goes live.

## Module skeleton

```python
"""DontPanic-side adapter for an external service wrapped via CLI Printing Press.

This module is a TEMPLATE. Copy it to
``scripts/dontpanic_orchestrate/adapters/<service>_adapter.py`` and replace
the four placeholders marked ``TODO`` below. The adapter:

  (i)   spawns the PP-emitted MCP binary as a subprocess
        (stdin/stdout JSON-RPC, per the MCP spec),
  (ii)  forwards each agent-issued tool call to the subprocess,
  (iii) decorates every tool response with DontPanic's redact_level
        middleware, then runs a post-redaction sanitization check
        (fails closed on any surviving secret-shaped substring)
        before returning it to the caller,
  (iv)  rejects any tool call whose tool name is in MUTATING_TOOLS unless
        the caller passes ``confirm: true`` in the call arguments
        (v0 hard-rejects regardless — approval-gate templating is v2),
  (v)   registers itself in ``~/.dontpanic/adapters.json`` on first import.

The PP binary itself is generated, version-pinned at plan-lock time, and
treated as opaque. This module is the trust layer: redaction, mutation
gate, and registry entry are DontPanic's responsibility per the
projection contract in ``docs/STATE_PROJECTION.md``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ────────────────────────────  fill these in  ────────────────────────────

# TODO: human-readable service slug, also the registry key.
SERVICE_NAME: str = "<service>"

# TODO: absolute path to the PP-emitted MCP binary for this service.
# Convention: ``~/.dontpanic/adapters/<service>/<service>-pp-mcp``.
PP_BINARY_PATH: Path = Path.home() / ".dontpanic" / "adapters" / SERVICE_NAME / f"{SERVICE_NAME}-pp-mcp"

# TODO: redaction tier applied to every tool response. Choose the
# strictest tier compatible with the operator's intended use. Per
# the projection contract, valid tiers are: "public", "internal",
# "secret". v0 adapters default to "internal".
REDACT_LEVEL: str = "internal"

# TODO: list of tool names emitted by the PP binary that mutate the
# target. v0 of this skill is read-only, so this list should normally
# be empty. If the operator has any reason to declare a mutating
# tool, v0 still hard-rejects every call to it — the list exists so
# the adapter can surface a clearer error message than "unknown tool".
MUTATING_TOOLS: frozenset[str] = frozenset()


# ────────────────────────────  registry entry  ────────────────────────────

ADAPTERS_REGISTRY: Path = Path.home() / ".dontpanic" / "adapters.json"
PER_SERVICE_CONFIG: Path = Path.home() / ".dontpanic" / "adapters" / f"{SERVICE_NAME}.json"


def register_adapter() -> None:
    """Idempotently add this adapter to ``~/.dontpanic/adapters.json``.

    The registry is operator-edited JSON; this function only inserts
    a sentinel entry pointing at the module + per-service config. It
    never overwrites a pre-existing entry — the operator owns the
    final shape of their registry.
    """

    ADAPTERS_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    if ADAPTERS_REGISTRY.exists():
        try:
            registry = json.loads(ADAPTERS_REGISTRY.read_text())
        except json.JSONDecodeError:
            registry = {}
    else:
        registry = {}

    adapters = registry.setdefault("adapters", {})
    if SERVICE_NAME in adapters:
        return

    adapters[SERVICE_NAME] = {
        "module": f"dontpanic_orchestrate.adapters.{SERVICE_NAME}_adapter",
        "config_path": str(PER_SERVICE_CONFIG),
        "binary_path": str(PP_BINARY_PATH),
        "redact_level": REDACT_LEVEL,
        "mutating_tools": sorted(MUTATING_TOOLS),
        "version_pin_source": "per_service_config.pp_version",
    }
    ADAPTERS_REGISTRY.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n")


# ────────────────────────────  middleware  ────────────────────────────


class MutationRejected(Exception):
    """Raised when a caller invokes a mutating tool in v0. Hard-reject."""


class SanitizationFailed(Exception):
    """Raised when a post-redaction sanitization check finds a
    secret-shaped substring that the redact pass did not strip.

    This is the hard backstop: redaction is permitted to be lenient
    (it preserves payload shape for downstream consumers), so the
    sanitizer fails closed if any telltale token pattern survives.
    """


def apply_redact(payload: Any, level: str) -> Any:
    """Apply the DontPanic redact_level middleware to a tool response payload.

    v0 placeholder: the real implementation lives in
    ``dontpanic_orchestrate.redact`` (plan 2026-05-09-003 F006). This
    function is the seam — when the redact module ships, swap the
    import here. Until then, the placeholder is a deep copy that
    annotates the payload with the applied tier so downstream
    consumers can confirm middleware ran.
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


# Secret-shaped substrings the sanitizer refuses to let cross the
# adapter boundary even after redaction has run. The list is
# deliberately narrow: it codifies the shapes DontPanic considers
# unrecoverable leaks (live token material), not every PII shape —
# PII tiering is the redact module's job, not the sanitizer's.
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
    where a secret-shaped substring survived. Pure read; no mutation."""

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
    """Run the post-redaction sanitization check on every response.

    Invariants:

    - Runs *after* ``apply_redact`` on every code path (success,
      no-response, invalid JSON, future error envelopes). The two
      stages are not interchangeable: redact may be lenient,
      sanitize fails closed.
    - Read-only: never mutates the payload. If a check fails, the
      adapter aborts the call by raising ``SanitizationFailed``
      rather than returning a partially-cleaned payload.
    - Annotates the payload's ``_sanitized_at`` boundary on dict
      payloads so downstream consumers can confirm the check ran.
      Non-dict payloads (lists, scalars) pass through unchanged on
      success.
    """

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
    """Compose the two-stage response pipeline. Used by every code
    path in ``call_tool`` (success, no-response, invalid JSON) so the
    invariant `redact → sanitize` is upheld in one place."""

    return sanitize_response(apply_redact(payload, level), level)


def reject_if_mutating(tool_name: str, arguments: dict[str, Any]) -> None:
    """Hard-reject any call to a mutating tool in v0.

    Approval-gate templating is reserved for v2 of this skill. Until
    v2 lands, the adapter is read-only by directive: even an explicit
    ``confirm: true`` argument is rejected. The ``confirm`` channel is
    plumbed only so the v2 wrapper can later swap this rejection for
    a templated gate without changing the call signature.
    """

    if tool_name not in MUTATING_TOOLS:
        return
    raise MutationRejected(
        f"Tool {tool_name!r} mutates the target service. "
        f"v0 of the printing-press-adapter skill is read-only. "
        f"File a v2 expansion plan to add approval-gate templating "
        f"before wrapping mutating endpoints."
    )


# ────────────────────────────  subprocess proxy  ────────────────────────────


@dataclass
class PrintingPressProcess:
    """Wraps the PP-emitted MCP binary as a long-lived subprocess.

    The binary speaks line-delimited JSON-RPC over stdio (the MCP
    transport). This class owns lifecycle: spawn on first call, kill
    on ``close()``. It does not parse JSON-RPC envelopes — those are
    forwarded as-is, except that every *response* payload is passed
    through ``apply_redact`` before returning to the caller.
    """

    binary_path: Path
    redact_level: str = REDACT_LEVEL
    _process: subprocess.Popen[bytes] | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def _ensure_started(self) -> subprocess.Popen[bytes]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        # shell=False is required (see shared/conventions/security for the
        # subprocess invariants the supervisor checks).
        self._process = subprocess.Popen(
            [str(self.binary_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=os.environ.copy(),
        )
        return self._process

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Forward a single tool call to the PP binary and return the
        redacted + sanitized response payload.

        Every code path in this method goes through
        ``redact_and_sanitize``: the two-stage pipeline of
        ``apply_redact`` then ``sanitize_response``. Synthetic error
        envelopes (no-response, invalid JSON) get the same treatment
        as normal success payloads so the invariant holds across all
        outcomes.

        Pseudocode flow — real JSON-RPC framing lives in the matching
        MCP client helper (added by F003 dogfood):

            envelope = {"method": "tools/call",
                        "params": {"name": tool_name, "arguments": arguments}}
            self._write(envelope)
            response = self._read()
            return redact_and_sanitize(response.get("result"), self.redact_level)
        """

        reject_if_mutating(tool_name, arguments)
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


# ────────────────────────────  module entry  ────────────────────────────


_PROCESS_SINGLETON: PrintingPressProcess | None = None


def get_process() -> PrintingPressProcess:
    """Lazy singleton — the subprocess starts on first tool call, not
    at module import. Keeps import side-effect free aside from the
    registry write, which is itself idempotent."""

    global _PROCESS_SINGLETON
    if _PROCESS_SINGLETON is None:
        _PROCESS_SINGLETON = PrintingPressProcess(
            binary_path=PP_BINARY_PATH, redact_level=REDACT_LEVEL
        )
    return _PROCESS_SINGLETON


def call(tool_name: str, **arguments: Any) -> Any:
    """Public entry point used by the rest of DontPanic.

    Example::

        from dontpanic_orchestrate.adapters import <service>_adapter as svc
        result = svc.call("list_issues", project_id="abc123")
    """

    return get_process().call_tool(tool_name, dict(arguments))


# Register on import. Idempotent; safe to call once per process.
register_adapter()
```

## How the four required behaviors map onto the skeleton

| Required behavior | Skeleton location |
|---|---|
| (i) Spawn PP MCP binary as subprocess | `PrintingPressProcess._ensure_started` |
| (ii) Inject redact_level middleware on every response | `apply_redact`, invoked via `redact_and_sanitize` inside `call_tool` |
| (ii-b) Post-redaction sanitization check on every response | `sanitize_response` (raises `SanitizationFailed` fail-closed), invoked via `redact_and_sanitize` on success / no-response / invalid-JSON paths |
| (iii) Reject mutating tool calls in v0 | `reject_if_mutating`, called before subprocess write |
| (iv) Register in `~/.dontpanic/adapters.json` | `register_adapter`, executed at module-import time |

## What this skeleton deliberately does NOT do (F003 / v2 territory)

- **No real JSON-RPC envelope handling.** The framing in `call_tool`
  is illustrative; F003's dogfood replaces it with a proper MCP
  client helper.
- **No token loading.** OAuth and API-key flows live in F003's
  per-service config (`~/.dontpanic/adapters/<service>.json`), never
  in source.
- **No approval-gate templating.** v0 rejects every mutating tool
  call. v2 of this skill adds per-tool gate declarations.
- **No streaming response support.** v0 handles request/response
  tools only; long-lived MCP streams are v2.
- **No multi-service composition.** Each adapter is a leaf module;
  cross-service joins are v2.

## Test hooks F003 will add

- Smoke test: spawn the PP binary, issue one read tool call, assert
  the response carries the `_redact_level` and `_sanitized_at`
  annotations and contains no raw token strings.
- Negative test: invoke a tool name added to `MUTATING_TOOLS` and
  assert `MutationRejected` is raised before any subprocess write.
- Sanitizer fail-closed test: feed a synthetic post-redacted payload
  containing a bearer-token-shaped substring to `sanitize_response`
  and assert `SanitizationFailed` is raised with the offending path
  reported; assert `redact_and_sanitize` propagates the same
  exception (i.e., never returns a partially-cleaned payload).
- Registry test: import the module twice in the same process and
  assert `~/.dontpanic/adapters.json` is written exactly once and
  preserves any operator-added keys.

These tests are out of scope for F001 — the F001 acceptance is just
that this module is syntactically valid Python.
