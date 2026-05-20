"""Plan 2026-05-19-002 F004 — HTML install report (Thariq pattern).

Pure transform from the F001 ``dontpanic doctor --profile=<name> --json``
envelope (and optionally the F003 ``dontpanic smoke --mode=mocked --json``
envelope) into a single-page, self-contained HTML5 document.

Design constraints (mirror Plan 4 F002 ``architecture_html.py`` at commit
6032046):

* No JS framework. No external CSS. No external fonts. The rendered file
  must open cleanly under ``file://`` on any device with no network.
* Mobile-first layout: single column under 800px, two-column on wider
  viewports. Copy-paste-friendly ``<code>`` blocks for ``fix_command``.
* Validator (``_validate_doctor_payload`` + ``_validate_smoke_payload``)
  type-checks input shapes up front. Any mismatch raises
  :class:`InstallReportError` with an operator-actionable message naming
  the offending field and the regen command.
* Defense-in-depth ``html.escape`` at every interpolation seam — even
  after validator rejection of malformed payloads, the renderer NEVER
  trusts probe names, fix commands, or surface names. This mirrors the
  Plan 4 F002 D004 pattern (commit 6032046) where the validator is the
  primary defense and escape is the secondary one.
"""

from __future__ import annotations

import html
import shlex
from pathlib import Path
from typing import Any

DEFAULT_REPORT_REL = Path("docs/install-report.html")

# Top-level keys the doctor envelope must carry. Matches the F001 schema
# doc at evidence/doctor-json-envelope-schema-v1.md.
_DOCTOR_REQUIRED_KEYS = (
    "schema_version",
    "profile",
    "generated_at",
    "exit_code",
    "prereq_probes",
)

# Per-probe required keys. Subset of the F001 schema — these are the
# fields the renderer actually interpolates. Missing fields surface as a
# rejection with the field name so the operator can fix forward.
_PROBE_REQUIRED_KEYS = (
    "name",
    "status",
    "severity_reason",
    "fix_url",
    "fix_command",
)

# Top-level keys the smoke envelope must carry. Matches the F003 schema
# emitted by ``SmokeResult.to_json`` — every field below drives report
# semantics (``exit_code`` → verdict chip, ``volley_status`` → smoke chip,
# etc.) so any drift here needs operator triage rather than a silent
# render with degraded fidelity.
_SMOKE_REQUIRED_KEYS = (
    "schema_version",
    "mode",
    "plan_id",
    "elapsed_s",
    "exit_code",
    "volley_status",
    "error",
    "supervisor_surfaces",
)

# Per-surface required keys.
_SURFACE_REQUIRED_KEYS = ("name", "status", "elapsed_s", "error", "evidence")

# URL schemes allowed in rendered hrefs. Anything else (``javascript:``,
# ``data:``, ``file:``, vendor schemes) is downgraded to inert escaped
# text by ``_safe_href`` so a malicious or buggy upstream cannot turn
# fix_url into an active vector.
_SAFE_URL_SCHEMES = ("http://", "https://")

# Status ordering for the "what's next" panel and the grouped checklist —
# highest-priority remediation surface first.
_STATUS_PRIORITY = ("fail", "warn", "advisory", "pass")

_VALID_PROBE_STATUSES = frozenset(_STATUS_PRIORITY)
_VALID_SURFACE_STATUSES = frozenset({"pass", "fail", "skipped"})

# Top-level verdict chips. Driven by doctor.exit_code + smoke.exit_code.
_VERDICT_READY = "ready"
_VERDICT_FIXES_NEEDED = "fixes-needed"
_VERDICT_BLOCKED = "blocked"

# Default external links surfaced in the footer.
_README_URL = "https://github.com/Silex-Research/DontPanic#readme"
_HERMES_CHEATSHEET_URL = "https://github.com/Silex-Research/DontPanic/blob/main/docs/cheatsheets/hermes.md"


# ── errors ───────────────────────────────────────────────────────────────


class InstallReportError(RuntimeError):
    """Raised when a payload fails the renderer's shape check.

    Messages always name the offending field and point to the regen
    command — operators can fix forward without grepping docs.
    """


# ── validators ───────────────────────────────────────────────────────────


def _doctor_regen_hint(profile: str | None) -> str:
    p = profile if isinstance(profile, str) and profile else "<name>"
    return (
        f"Re-run `python3 scripts/dontpanic_doctor.py --profile={p} --json` "
        "and retry."
    )


def _smoke_regen_hint() -> str:
    return "Re-run `python3 -m dontpanic_orchestrate smoke --mode=mocked --json` and retry."


def _require_dict(value: Any, *, label: str, hint: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InstallReportError(
            f"{label} top-level value is {type(value).__name__}, expected object. {hint}"
        )
    return value


def _require_keys(
    payload: dict[str, Any], required: tuple[str, ...], *, label: str, hint: str
) -> None:
    missing = [k for k in required if k not in payload]
    if missing:
        raise InstallReportError(
            f"{label} missing required field(s): {missing}. {hint}"
        )


def _require_type(
    value: Any, expected: type | tuple[type, ...], *, label: str, hint: str
) -> None:
    # ``bool`` is a subclass of ``int`` — guard against accepting True/False
    # where an int probe count is expected.
    if expected is int and isinstance(value, bool):
        raise InstallReportError(
            f"{label} is {type(value).__name__}, expected int. {hint}"
        )
    if not isinstance(value, expected):
        # Build a friendly name for the expected type(s).
        if isinstance(expected, tuple):
            names = " | ".join(t.__name__ for t in expected)
        else:
            names = expected.__name__
        raise InstallReportError(
            f"{label} is {type(value).__name__}, expected {names}. {hint}"
        )


def _validate_doctor_payload(payload: Any) -> dict[str, Any]:
    """Type-check the F001 doctor envelope. Returns the validated dict.

    Raises :class:`InstallReportError` on any shape mismatch, naming the
    offending field. Validator runs once at the start of
    :func:`render_install_report` — escape (below) is the defense-in-depth
    layer should any malformed input bypass this check.
    """

    hint = _doctor_regen_hint(None)
    data = _require_dict(payload, label="doctor payload", hint=hint)
    _require_keys(data, _DOCTOR_REQUIRED_KEYS, label="doctor payload", hint=hint)
    _require_type(data["schema_version"], str, label="doctor.schema_version", hint=hint)
    _require_type(data["profile"], str, label="doctor.profile", hint=hint)
    # Re-derive the regen hint now that we know the profile name.
    hint = _doctor_regen_hint(data["profile"])
    _require_type(data["generated_at"], str, label="doctor.generated_at", hint=hint)
    _require_type(data["exit_code"], int, label="doctor.exit_code", hint=hint)
    if data["exit_code"] not in (0, 1, 2):
        raise InstallReportError(
            f"doctor.exit_code is {data['exit_code']!r}, expected 0|1|2. {hint}"
        )
    _require_type(
        data["prereq_probes"], list, label="doctor.prereq_probes", hint=hint
    )
    for idx, probe in enumerate(data["prereq_probes"]):
        ploc = f"doctor.prereq_probes[{idx}]"
        _require_dict(probe, label=ploc, hint=hint)
        _require_keys(probe, _PROBE_REQUIRED_KEYS, label=ploc, hint=hint)
        _require_type(probe["name"], str, label=f"{ploc}.name", hint=hint)
        _require_type(probe["status"], str, label=f"{ploc}.status", hint=hint)
        if probe["status"] not in _VALID_PROBE_STATUSES:
            raise InstallReportError(
                f"{ploc}.status is {probe['status']!r}, expected one of "
                f"{sorted(_VALID_PROBE_STATUSES)}. {hint}"
            )
        _require_type(
            probe["severity_reason"], str, label=f"{ploc}.severity_reason", hint=hint
        )
        _require_type(probe["fix_url"], str, label=f"{ploc}.fix_url", hint=hint)
        _require_type(probe["fix_command"], list, label=f"{ploc}.fix_command", hint=hint)
        for j, token in enumerate(probe["fix_command"]):
            _require_type(
                token, str, label=f"{ploc}.fix_command[{j}]", hint=hint
            )
    return data


def _validate_smoke_payload(payload: Any) -> dict[str, Any]:
    """Type-check the F003 smoke envelope. Returns the validated dict.

    Validates every semantics-bearing field, not just the keys the
    renderer interpolates directly. ``exit_code`` is the most critical
    field — it drives ``_compute_verdict`` (and therefore the verdict
    chip operators rely on) so a stringified ``"2"`` must reject rather
    than silently render as ``ready``.
    """

    hint = _smoke_regen_hint()
    data = _require_dict(payload, label="smoke payload", hint=hint)
    _require_keys(data, _SMOKE_REQUIRED_KEYS, label="smoke payload", hint=hint)
    _require_type(data["schema_version"], str, label="smoke.schema_version", hint=hint)
    _require_type(data["mode"], str, label="smoke.mode", hint=hint)
    _require_type(data["plan_id"], str, label="smoke.plan_id", hint=hint)
    _require_type(
        data["elapsed_s"], (int, float), label="smoke.elapsed_s", hint=hint
    )
    _require_type(data["exit_code"], int, label="smoke.exit_code", hint=hint)
    if data["exit_code"] not in (0, 1, 2):
        raise InstallReportError(
            f"smoke.exit_code is {data['exit_code']!r}, expected 0|1|2. {hint}"
        )
    if data["volley_status"] is not None:
        _require_type(
            data["volley_status"], str, label="smoke.volley_status", hint=hint
        )
    if data["error"] is not None:
        _require_type(data["error"], str, label="smoke.error", hint=hint)
    _require_type(
        data["supervisor_surfaces"],
        list,
        label="smoke.supervisor_surfaces",
        hint=hint,
    )
    for idx, surface in enumerate(data["supervisor_surfaces"]):
        sloc = f"smoke.supervisor_surfaces[{idx}]"
        _require_dict(surface, label=sloc, hint=hint)
        _require_keys(surface, _SURFACE_REQUIRED_KEYS, label=sloc, hint=hint)
        _require_type(surface["name"], str, label=f"{sloc}.name", hint=hint)
        _require_type(surface["status"], str, label=f"{sloc}.status", hint=hint)
        if surface["status"] not in _VALID_SURFACE_STATUSES:
            raise InstallReportError(
                f"{sloc}.status is {surface['status']!r}, expected one of "
                f"{sorted(_VALID_SURFACE_STATUSES)}. {hint}"
            )
        _require_type(
            surface["elapsed_s"], (int, float),
            label=f"{sloc}.elapsed_s", hint=hint,
        )
        if surface["error"] is not None:
            _require_type(
                surface["error"], str, label=f"{sloc}.error", hint=hint
            )
        if surface["evidence"] is not None:
            _require_type(
                surface["evidence"], str, label=f"{sloc}.evidence", hint=hint
            )
    return data


# ── URL safety ───────────────────────────────────────────────────────────


def _safe_href(url: str) -> str | None:
    """Return the URL if its scheme is http/https, else ``None``.

    Defense against ``javascript:`` / ``data:`` / vendor-scheme href
    injection via ``fix_url``. Validator rejection of malformed types is
    the primary defense; this scheme allowlist is the secondary one. When
    a URL is rejected here, callers render it as inert escaped text
    (still surfaced to the operator, just not clickable).
    """
    if not isinstance(url, str):
        return None
    lowered = url.strip().lower()
    for scheme in _SAFE_URL_SCHEMES:
        if lowered.startswith(scheme):
            return url
    return None


# ── public transform ─────────────────────────────────────────────────────


def render_install_report(
    doctor_payload: dict[str, Any],
    smoke_payload: dict[str, Any] | None = None,
) -> str:
    """Pure transform — payload dicts → single-page HTML5 string.

    ``smoke_payload`` is optional; when ``None`` the smoke section is
    omitted entirely (mirrors the case where the operator runs
    ``dontpanic doctor --profile=core --report`` without a paired smoke
    run). Validator rejection of either payload raises
    :class:`InstallReportError`.
    """

    doctor = _validate_doctor_payload(doctor_payload)
    smoke = _validate_smoke_payload(smoke_payload) if smoke_payload is not None else None

    profile = doctor["profile"]
    # generated_at is required by the validator (F004-i1 fix); the
    # validator above guarantees it's present + str-typed.
    generated_at = doctor["generated_at"]
    schema_version = doctor["schema_version"]
    probes: list[dict[str, Any]] = list(doctor["prereq_probes"])
    verdict = _compute_verdict(doctor, smoke)

    parts: list[str] = []
    parts.append("<!doctype html>")
    parts.append('<html lang="en">')
    parts.append("<head>")
    parts.append('<meta charset="utf-8">')
    parts.append(
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
    )
    title = html.escape(f"DontPanic install status — profile={profile}")
    parts.append(f"<title>{title}</title>")
    parts.append(_STYLE_BLOCK)
    parts.append("</head>")
    parts.append("<body>")
    parts.append(
        _render_header(
            profile=profile,
            generated_at=generated_at,
            schema_version=schema_version,
            verdict=verdict,
        )
    )
    parts.append('<main class="container">')
    parts.append(_render_whats_next(probes, verdict))
    parts.append(_render_checklist(probes, profile))
    if smoke is not None:
        parts.append(_render_smoke_section(smoke))
    parts.append("</main>")
    parts.append(_render_footer(profile))
    parts.append("</body></html>")
    return "\n".join(parts) + "\n"


# ── verdict ──────────────────────────────────────────────────────────────


def _compute_verdict(
    doctor: dict[str, Any], smoke: dict[str, Any] | None
) -> str:
    """Map exit codes → operator-facing verdict chip.

    Doctor exit 2 wins (FAIL means blocked). Doctor exit 1 → fixes-needed.
    Doctor exit 0 with a smoke supervisor-defect (exit 1) means the
    install env looks fine but supervisor plumbing failed — operator-
    actionable "fixes-needed" rather than "blocked", since the doctor
    surface itself is green. Doctor 0 + smoke env-blocker (exit 2) maps
    back to "blocked" because the install itself can't host smoke.
    """
    doctor_exit = doctor["exit_code"]
    if doctor_exit == 2:
        return _VERDICT_BLOCKED
    if doctor_exit == 1:
        return _VERDICT_FIXES_NEEDED
    if smoke is None:
        return _VERDICT_READY
    smoke_exit = smoke.get("exit_code")
    if smoke_exit == 2:
        return _VERDICT_BLOCKED
    if smoke_exit == 1:
        return _VERDICT_FIXES_NEEDED
    return _VERDICT_READY


# ── HTML pieces ──────────────────────────────────────────────────────────


_STYLE_BLOCK = """<style>
:root {
  --bg: #0f172a;
  --bg-panel: #1e293b;
  --fg: #e2e8f0;
  --fg-muted: #94a3b8;
  --accent: #38bdf8;
  --accent-2: #f472b6;
  --good: #22c55e;
  --warn: #facc15;
  --bad: #ef4444;
  --info: #60a5fa;
  --border: #334155;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--fg);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  line-height: 1.5; }
header.top { padding: 1.25rem 1rem; border-bottom: 1px solid var(--border);
  background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); }
header.top h1 { margin: 0 0 0.25rem; font-size: 1.5rem; letter-spacing: -0.01em; }
header.top .meta { color: var(--fg-muted); font-size: 0.875rem; }
header.top .meta code { background: rgba(56,189,248,0.1); padding: 0.1rem 0.4rem;
  border-radius: 3px; color: var(--accent); font-size: 0.8rem; }
.verdict-chip { display: inline-block; margin-top: 0.6rem; padding: 0.35rem 0.85rem;
  border-radius: 999px; font-weight: 700; font-size: 0.85rem;
  font-family: ui-monospace, "SF Mono", Menlo, monospace; letter-spacing: 0.02em; }
.verdict-ready { background: rgba(34,197,94,0.18); color: var(--good);
  border: 1px solid var(--good); }
.verdict-fixes-needed { background: rgba(250,204,21,0.15); color: var(--warn);
  border: 1px solid var(--warn); }
.verdict-blocked { background: rgba(239,68,68,0.18); color: var(--bad);
  border: 1px solid var(--bad); }
main.container { padding: 1rem; max-width: 1200px; margin: 0 auto; }
section { margin-bottom: 2.5rem; }
section h2 { font-size: 1.25rem; border-bottom: 1px solid var(--border);
  padding-bottom: 0.5rem; margin: 0 0 1rem; color: var(--accent); }
section .lede { color: var(--fg-muted); font-size: 0.9rem; margin: -0.5rem 0 1rem; }
.panel { background: var(--bg-panel); border: 1px solid var(--border);
  border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 1rem; }
.panel.celebrate { border-color: var(--good); }
.panel.urgent { border-color: var(--bad); }
.panel h3 { margin: 0 0 0.5rem; font-size: 1.05rem; }
.panel .why { color: var(--fg-muted); font-size: 0.9rem; margin: 0.25rem 0; }
pre.code { background: rgba(15,23,42,0.7); border: 1px solid var(--border);
  border-radius: 4px; padding: 0.65rem 0.85rem; overflow-x: auto;
  font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 0.85rem;
  color: var(--fg); margin: 0.5rem 0; user-select: all; }
.badge { display: inline-block; padding: 0.15rem 0.55rem; border-radius: 4px;
  font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 0.7rem;
  font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase;
  margin-right: 0.4rem; }
.badge.status-pass { background: rgba(34,197,94,0.15); color: var(--good); }
.badge.status-fail { background: rgba(239,68,68,0.18); color: var(--bad); }
.badge.status-warn { background: rgba(250,204,21,0.15); color: var(--warn); }
.badge.status-advisory { background: rgba(96,165,250,0.15); color: var(--info); }
.badge.status-skipped { background: rgba(148,163,184,0.15); color: var(--fg-muted); }
.probe { background: var(--bg-panel); border: 1px solid var(--border);
  border-radius: 6px; padding: 0.75rem 1rem; margin-bottom: 0.65rem; }
.probe .name { font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-size: 0.95rem; color: var(--fg); font-weight: 600; }
.probe .reason { color: var(--fg-muted); font-size: 0.85rem; margin: 0.3rem 0; }
.probe .docs { color: var(--accent); font-size: 0.8rem; word-break: break-all; }
.docs-unsafe { color: var(--fg-muted); font-family: ui-monospace, "SF Mono", Menlo, monospace;
  text-decoration: line-through; word-break: break-all; }
.probe.fail { border-left: 3px solid var(--bad); }
.probe.warn { border-left: 3px solid var(--warn); }
.probe.advisory { border-left: 3px solid var(--info); }
.probe.pass { border-left: 3px solid var(--good); }
.group-heading { color: var(--fg-muted); font-size: 0.8rem;
  text-transform: uppercase; letter-spacing: 0.08em; margin: 1.25rem 0 0.5rem; }
.surfaces { display: grid; grid-template-columns: 1fr; gap: 0.5rem; }
.surface { display: flex; align-items: center; gap: 0.6rem;
  background: var(--bg-panel); border: 1px solid var(--border);
  border-radius: 6px; padding: 0.5rem 0.85rem; }
.surface .name { font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-size: 0.85rem; }
.surface .elapsed { margin-left: auto; color: var(--fg-muted); font-size: 0.75rem;
  font-family: ui-monospace, "SF Mono", Menlo, monospace; }
.surface .err { color: var(--fg-muted); font-size: 0.78rem; margin-top: 0.3rem;
  font-style: italic; }
footer.bottom { padding: 1rem; color: var(--fg-muted); font-size: 0.8rem;
  text-align: center; border-top: 1px solid var(--border); }
footer.bottom a { color: var(--accent); }
@media (min-width: 800px) {
  header.top { padding: 2rem; }
  header.top h1 { font-size: 2rem; }
  main.container { padding: 2rem; display: grid; grid-template-columns: 1fr 1fr;
    gap: 2rem; }
  main.container > section:nth-of-type(1) { grid-column: 1 / -1; }
  .surfaces { grid-template-columns: 1fr 1fr; }
}
</style>"""


def _render_header(
    *,
    profile: str,
    generated_at: str,
    schema_version: str,
    verdict: str,
) -> str:
    chip_cls = {
        _VERDICT_READY: "verdict-ready",
        _VERDICT_FIXES_NEEDED: "verdict-fixes-needed",
        _VERDICT_BLOCKED: "verdict-blocked",
    }.get(verdict, "verdict-fixes-needed")
    chip_label = {
        _VERDICT_READY: "ready",
        _VERDICT_FIXES_NEEDED: "fixes needed",
        _VERDICT_BLOCKED: "blocked",
    }.get(verdict, verdict)
    return (
        '<header class="top">'
        f"<h1>DontPanic install status — profile={html.escape(profile)}</h1>"
        '<div class="meta">'
        f"schema v{html.escape(schema_version)} · "
        f"generated <code>{html.escape(generated_at)}</code>"
        "</div>"
        f'<div class="verdict-chip {chip_cls}">{html.escape(chip_label)}</div>'
        "</header>"
    )


def _render_whats_next(probes: list[dict[str, Any]], verdict: str) -> str:
    """Highest-priority remediation panel, or all-green celebration."""

    fails = [p for p in probes if p["status"] == "fail"]
    warns = [p for p in probes if p["status"] == "warn"]
    if fails:
        target = fails[0]
        panel_cls = "panel urgent"
        heading = "What to fix first"
        marker = "FAIL"
    elif warns:
        target = warns[0]
        panel_cls = "panel"
        heading = "Next item to clear"
        marker = "WARN"
    else:
        # All-green celebration. Acceptance #3 + #6 — "all green" variant.
        msg = (
            "all green — environment ready"
            if verdict == _VERDICT_READY
            else "no remaining doctor blockers"
        )
        return (
            '<section id="whats-next">'
            "<h2>What's next</h2>"
            '<div class="panel celebrate">'
            f"<h3>✓ {html.escape(msg)}</h3>"
            '<p class="why">'
            "Your prereq probes are clean. "
            "Re-run <code>dontpanic doctor --profile=core</code> any time "
            "the environment changes."
            "</p>"
            "</div>"
            "</section>"
        )

    # F004-i1 fix: use shlex.join so argv tokens containing spaces or
    # shell metacharacters render as copy-paste-safe (e.g.
    # ['python', '-c', 'print(1)'] → "python -c 'print(1)'" not
    # "python -c print(1)").
    cmd = shlex.join(target["fix_command"]) if target["fix_command"] else ""
    return (
        '<section id="whats-next">'
        "<h2>What's next</h2>"
        f'<div class="{panel_cls}">'
        f'<h3><span class="badge status-{html.escape(target["status"])}">{html.escape(marker)}</span>'
        f'<code>{html.escape(target["name"])}</code></h3>'
        f'<p class="why">{html.escape(target["severity_reason"])}</p>'
        f'<pre class="code">{html.escape(cmd)}</pre>'
        + _render_docs_line(target.get("fix_url") or "")
        + "</div>"
        "</section>"
    )


def _render_docs_line(fix_url: str) -> str:
    """Render the ``docs: <link>`` line if ``fix_url`` is present.

    Anchors only render for http/https URLs (see :func:`_safe_href`).
    Unsafe schemes (e.g. ``javascript:``) are downgraded to inert escaped
    text inside a ``<span>`` so the operator still sees the value but the
    document cannot execute it.
    """
    if not fix_url:
        return ""
    safe = _safe_href(fix_url)
    if safe is not None:
        return (
            f'<p class="docs">docs: <a href="{html.escape(safe, quote=True)}">'
            f"{html.escape(safe)}</a></p>"
        )
    return (
        f'<p class="docs">docs: <span class="docs-unsafe">'
        f"{html.escape(fix_url)}</span></p>"
    )


def _render_checklist(probes: list[dict[str, Any]], profile: str) -> str:
    """Per-profile prereq checklist grouped by effective status."""

    grouped: dict[str, list[dict[str, Any]]] = {s: [] for s in _STATUS_PRIORITY}
    for p in probes:
        grouped.setdefault(p["status"], []).append(p)

    body_parts: list[str] = []
    for status in _STATUS_PRIORITY:
        entries = grouped.get(status) or []
        if not entries:
            continue
        body_parts.append(
            f'<div class="group-heading">{html.escape(status)} ({len(entries)})</div>'
        )
        for probe in entries:
            body_parts.append(_render_probe_card(probe))

    if not body_parts:
        body_parts.append("<p>No probes reported.</p>")

    return (
        '<section id="checklist">'
        f"<h2>Prereq checklist — profile={html.escape(profile)}</h2>"
        '<p class="lede">Each probe is grouped by its effective status under '
        "the selected profile. Fix commands are copy-paste-ready.</p>"
        + "".join(body_parts)
        + "</section>"
    )


def _render_probe_card(probe: dict[str, Any]) -> str:
    status = probe["status"]
    name = probe["name"]
    reason = probe["severity_reason"]
    fix_cmd_list = probe.get("fix_command") or []
    # F004-i1 fix: shlex.join keeps copy-paste-safe quoting for argv
    # tokens with spaces or shell metacharacters.
    fix_cmd = shlex.join(fix_cmd_list) if fix_cmd_list else ""
    fix_url = probe.get("fix_url") or ""

    code_block = (
        f'<pre class="code">{html.escape(fix_cmd)}</pre>' if fix_cmd else ""
    )
    docs_line = _render_docs_line(fix_url)

    return (
        f'<article class="probe {html.escape(status)}">'
        f'<div><span class="badge status-{html.escape(status)}">{html.escape(status)}</span>'
        f'<span class="name">{html.escape(name)}</span></div>'
        f'<p class="reason">{html.escape(reason)}</p>'
        f"{code_block}"
        f"{docs_line}"
        "</article>"
    )


def _render_smoke_section(smoke: dict[str, Any]) -> str:
    surfaces = smoke.get("supervisor_surfaces") or []
    mode = str(smoke.get("mode", "mocked"))
    plan_id = str(smoke.get("plan_id", "(unknown)"))
    volley = smoke.get("volley_status")
    err = smoke.get("error")

    rows: list[str] = []
    for surface in surfaces:
        status = surface["status"]
        sname = surface["name"]
        elapsed = surface.get("elapsed_s")
        err_msg = surface.get("error")
        elapsed_str = ""
        if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool):
            elapsed_str = f"{float(elapsed):.3f}s"
        err_html = (
            f'<div class="err">{html.escape(str(err_msg))}</div>' if err_msg else ""
        )
        rows.append(
            f'<div class="surface">'
            f'<span class="badge status-{html.escape(status)}">{html.escape(status)}</span>'
            f'<span class="name">{html.escape(sname)}</span>'
            + (
                f'<span class="elapsed">{html.escape(elapsed_str)}</span>'
                if elapsed_str
                else ""
            )
            + "</div>"
            + err_html
        )

    volley_chip = (
        f'<span class="badge status-{"pass" if volley == "signed_off" else "fail"}">'
        f"volley={html.escape(str(volley))}</span>"
        if volley is not None
        else ""
    )

    return (
        '<section id="smoke">'
        "<h2>Supervisor smoke — named surfaces</h2>"
        '<p class="lede">'
        f"mode=<code>{html.escape(mode)}</code> · "
        f"plan=<code>{html.escape(plan_id)}</code> · "
        f"{volley_chip}"
        "</p>"
        + (
            f'<p class="why">{html.escape(str(err))}</p>'
            if err
            else ""
        )
        + f'<div class="surfaces">{"".join(rows)}</div>'
        "</section>"
    )


def _render_footer(profile: str) -> str:
    regen_cmd = f"dontpanic doctor --profile={profile} --report"
    return (
        '<footer class="bottom">'
        f"Regenerate locally: <code>{html.escape(regen_cmd)}</code>. "
        f'<a href="{html.escape(_README_URL, quote=True)}">README</a> · '
        f'<a href="{html.escape(_HERMES_CHEATSHEET_URL, quote=True)}">Hermes cheat sheet</a>. '
        "This file is gitignored — regenerate on demand."
        "</footer>"
    )


# ── file-level helper ────────────────────────────────────────────────────


def write_install_report(
    doctor_payload: dict[str, Any],
    smoke_payload: dict[str, Any] | None,
    out_path: Path,
) -> Path:
    """Render and write the install report to ``out_path``.

    Returns the path written. Used by the doctor + init CLI flags. The
    parent directory is created if missing.
    """

    rendered = render_install_report(doctor_payload, smoke_payload)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    return out_path
