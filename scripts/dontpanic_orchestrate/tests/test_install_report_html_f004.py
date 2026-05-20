"""Fixture tests for plan 2026-05-19-002 F004 — install-report HTML renderer.

Mirrors the Plan 4 F002 ``test_architecture_html_f002.py`` patterns (b6–b9):
shape validation, defense-in-depth escape, HTML5 well-formedness.

Covers:
  (1) valid doctor + smoke payload renders complete document with all sections
  (2) doctor-only payload renders cleanly with smoke section omitted
  (3) all-pass payload renders the "celebration" variant
  (4) fail probe payload renders highest-priority fix prominently
  (5) malformed payload raises InstallReportError with actionable message
  (6) injection attempts in probe.name / fix_command are escaped
  (7) mobile-responsive media query is present
  (8) generated HTML is well-formed HTML5 (mirrors Plan 4 F002 b9 assertion)
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

import pytest

from dontpanic_orchestrate.init import report_html


# ── HTML5 well-formedness checker ─────────────────────────────────────────


class _StructuralCounter(HTMLParser):
    """Stdlib-only HTML5 well-formedness probe. Mirrors the helper in
    test_architecture_html_f002.py so the same assertion shape covers the
    install-report renderer."""

    VOID_TAGS = frozenset(
        {
            "area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.tag_open_count: dict[str, int] = {}
        self.tag_close_count: dict[str, int] = {}
        self.unbalanced: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tag_open_count[tag] = self.tag_open_count.get(tag, 0) + 1
        if tag not in self.VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tag_open_count[tag] = self.tag_open_count.get(tag, 0) + 1

    def handle_endtag(self, tag: str) -> None:
        self.tag_close_count[tag] = self.tag_close_count.get(tag, 0) + 1
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            while self.stack and self.stack[-1] != tag:
                self.unbalanced.append(self.stack.pop())
            if self.stack:
                self.stack.pop()
        else:
            self.unbalanced.append(f"closing {tag} without open")


def _assert_well_formed_html(html_doc: str) -> None:
    assert html_doc.lower().lstrip().startswith("<!doctype html>"), (
        "HTML5 documents must start with <!doctype html>"
    )
    parser = _StructuralCounter()
    parser.feed(html_doc)
    parser.close()
    assert not parser.stack, f"unclosed tags at end of doc: {parser.stack}"
    assert not parser.unbalanced, f"unbalanced tags encountered: {parser.unbalanced}"
    for tag in ("html", "head", "body"):
        assert parser.tag_open_count.get(tag, 0) == 1, (
            f"expected exactly one <{tag}>, saw {parser.tag_open_count.get(tag, 0)}"
        )
        assert parser.tag_close_count.get(tag, 0) == 1, (
            f"expected exactly one </{tag}>, saw {parser.tag_close_count.get(tag, 0)}"
        )


# ── builders ──────────────────────────────────────────────────────────────


def _probe(
    *,
    name: str = "python-version",
    status: str = "pass",
    severity_reason: str = "in-profile + ok",
    fix_url: str = "https://www.python.org/downloads/",
    fix_command: list[str] | None = None,
    activation_condition: str = "always",
    activation_resolved: bool = True,
    elapsed_s: float = 0.012,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "severity_reason": severity_reason,
        "version_found": "python 3.12" if status == "pass" else None,
        "fix_url": fix_url,
        "fix_command": fix_command if fix_command is not None else ["echo", "noop"],
        "required_for_profiles": ["core"],
        "activation_condition": activation_condition,
        "activation_resolved": activation_resolved,
        "elapsed_s": elapsed_s,
    }


def _doctor_payload(
    *,
    profile: str = "core",
    exit_code: int = 0,
    probes: list[dict[str, Any]] | None = None,
    generated_at: str = "2026-05-20T03:00:00Z",
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "profile": profile,
        "generated_at": generated_at,
        "exit_code": exit_code,
        "prereq_probes": probes if probes is not None else [_probe()],
        "legacy_checks": [],
    }


def _smoke_payload(
    *,
    exit_code: int = 0,
    volley_status: str | None = "signed_off",
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "mode": "mocked",
        "plan_id": "2026-05-19-901-feat-smoke-synthetic",
        "elapsed_s": 2.345,
        "exit_code": exit_code,
        "volley_status": volley_status,
        "error": None,
        "supervisor_surfaces": [
            {
                "name": "plan_load",
                "status": "pass",
                "elapsed_s": 0.001,
                "error": None,
                "evidence": "plan.md",
            },
            {
                "name": "tmpdir_cleanup",
                "status": "pass",
                "elapsed_s": 0.0,
                "error": None,
                "evidence": "no-leaks",
            },
        ],
    }


# ── (1) full render with both payloads ────────────────────────────────────


def test_1_valid_doctor_plus_smoke_renders_complete_document() -> None:
    doctor = _doctor_payload(
        exit_code=1,
        probes=[
            _probe(name="python-version", status="pass"),
            _probe(
                name="gh-auth-status",
                status="warn",
                severity_reason="out-of-profile + warn-when-active",
                fix_url="https://cli.github.com/manual/gh_auth_login",
                fix_command=["gh", "auth", "login"],
            ),
        ],
    )
    smoke = _smoke_payload()
    out = report_html.render_install_report(doctor, smoke)

    assert isinstance(out, str)
    assert "<!doctype html>" in out.lower()
    assert "DontPanic install status — profile=core" in out
    assert "schema v1.0.0" in out
    # All major sections render.
    assert 'id="whats-next"' in out
    assert 'id="checklist"' in out
    assert 'id="smoke"' in out
    # Smoke surfaces appear.
    assert "plan_load" in out
    assert "tmpdir_cleanup" in out
    # Fix command surfaced in copy-paste-ready code block.
    assert "gh auth login" in out
    # Verdict chip surfaces fixes-needed for exit 1.
    assert "fixes needed" in out


def test_2_doctor_only_payload_renders_with_smoke_section_omitted() -> None:
    doctor = _doctor_payload(exit_code=0)
    out = report_html.render_install_report(doctor, None)

    assert 'id="checklist"' in out
    assert 'id="whats-next"' in out
    # Smoke section omitted entirely.
    assert 'id="smoke"' not in out
    assert "Supervisor smoke" not in out


# ── (3) celebration variant ───────────────────────────────────────────────


def test_3_all_pass_payload_renders_celebration_variant() -> None:
    doctor = _doctor_payload(
        exit_code=0,
        probes=[_probe(name="python-version", status="pass")],
    )
    out = report_html.render_install_report(doctor, _smoke_payload())
    assert "all green" in out or "no remaining doctor blockers" in out
    assert "celebrate" in out  # CSS class applied on the celebration panel.
    assert "ready" in out  # verdict chip


# ── (4) fail probe priority ───────────────────────────────────────────────


def test_4_fail_probe_renders_highest_priority_fix_prominently() -> None:
    doctor = _doctor_payload(
        exit_code=2,
        probes=[
            _probe(
                name="python-version",
                status="fail",
                severity_reason="in-profile + check failed: python 3.9 (need >=3.10)",
                fix_url="https://www.python.org/downloads/",
                fix_command=["echo", "Install Python 3.10+"],
            ),
            _probe(name="claude-cli", status="warn"),
        ],
    )
    out = report_html.render_install_report(doctor, None)
    # Verdict is "blocked" because exit_code == 2.
    assert "blocked" in out
    # "What's next" panel surfaces the FAIL probe first.
    whats_next_idx = out.index('id="whats-next"')
    checklist_idx = out.index('id="checklist"')
    fail_idx = out.index("python-version")
    assert whats_next_idx < fail_idx < checklist_idx
    # urgent panel class on the FAIL surface.
    assert "panel urgent" in out


# ── (5) malformed payloads raise InstallReportError ───────────────────────


def test_5a_missing_top_level_field_raises_install_report_error() -> None:
    payload = {"schema_version": "1.0.0", "profile": "core", "exit_code": 0}
    # prereq_probes missing
    with pytest.raises(report_html.InstallReportError) as excinfo:
        report_html.render_install_report(payload, None)
    msg = str(excinfo.value)
    assert "prereq_probes" in msg
    assert "Re-run" in msg


def test_5b_wrong_type_top_level_raises() -> None:
    payload = _doctor_payload()
    payload["exit_code"] = "two"  # type: ignore[assignment]
    with pytest.raises(report_html.InstallReportError) as excinfo:
        report_html.render_install_report(payload, None)
    assert "doctor.exit_code" in str(excinfo.value)


def test_5c_probe_with_invalid_status_raises() -> None:
    payload = _doctor_payload(probes=[_probe(status="weird")])
    with pytest.raises(report_html.InstallReportError) as excinfo:
        report_html.render_install_report(payload, None)
    assert "status" in str(excinfo.value)


def test_5d_smoke_missing_schema_version_raises() -> None:
    doctor = _doctor_payload()
    bad_smoke = {"supervisor_surfaces": []}
    with pytest.raises(report_html.InstallReportError) as excinfo:
        report_html.render_install_report(doctor, bad_smoke)
    assert "schema_version" in str(excinfo.value)


def test_5e_non_dict_payload_raises() -> None:
    with pytest.raises(report_html.InstallReportError):
        report_html.render_install_report("not a dict", None)  # type: ignore[arg-type]


def test_5f_top_level_exit_code_must_be_int_not_bool() -> None:
    # Boolean is a subclass of int — guard against accidental True/False
    # leaking through.
    payload = _doctor_payload()
    payload["exit_code"] = True  # type: ignore[assignment]
    with pytest.raises(report_html.InstallReportError) as excinfo:
        report_html.render_install_report(payload, None)
    assert "doctor.exit_code" in str(excinfo.value)


def test_5g_smoke_exit_code_must_be_int_not_string() -> None:
    """F004 i0 audit follow-up: a stringified ``exit_code`` must reject,
    not silently render as ``verdict-ready``. The verdict chip is the
    operator's primary signal — a malformed smoke payload that bypasses
    type checks would lie about the install's readiness."""
    doctor = _doctor_payload(exit_code=0)
    bad_smoke = _smoke_payload()
    bad_smoke["exit_code"] = "2"  # type: ignore[assignment]
    with pytest.raises(report_html.InstallReportError) as excinfo:
        report_html.render_install_report(doctor, bad_smoke)
    assert "smoke.exit_code" in str(excinfo.value)


def test_5h_smoke_exit_code_out_of_range_rejects() -> None:
    doctor = _doctor_payload(exit_code=0)
    bad_smoke = _smoke_payload()
    bad_smoke["exit_code"] = 7
    with pytest.raises(report_html.InstallReportError) as excinfo:
        report_html.render_install_report(doctor, bad_smoke)
    assert "smoke.exit_code" in str(excinfo.value)
    assert "0|1|2" in str(excinfo.value)


def test_5i_smoke_missing_exit_code_rejects() -> None:
    doctor = _doctor_payload(exit_code=0)
    bad_smoke = _smoke_payload()
    del bad_smoke["exit_code"]
    with pytest.raises(report_html.InstallReportError) as excinfo:
        report_html.render_install_report(doctor, bad_smoke)
    assert "exit_code" in str(excinfo.value)


def test_5j_smoke_surface_elapsed_s_must_be_numeric() -> None:
    doctor = _doctor_payload(exit_code=0)
    bad_smoke = _smoke_payload()
    bad_smoke["supervisor_surfaces"][0]["elapsed_s"] = "fast"  # type: ignore[index]
    with pytest.raises(report_html.InstallReportError) as excinfo:
        report_html.render_install_report(doctor, bad_smoke)
    assert "elapsed_s" in str(excinfo.value)


# ── (6) injection escape ──────────────────────────────────────────────────


def test_6_injection_attempts_in_probe_fields_are_escaped() -> None:
    """Defense in depth: even if a future bypass let a non-escaped string
    reach the renderer, ``html.escape`` at every interpolation seam keeps
    raw ``<script>`` out of the rendered document. Mirrors Plan 4 F002
    D004 defense-in-depth pattern from commit 6032046."""
    doctor = _doctor_payload(
        probes=[
            _probe(
                name="<script>alert(1)</script>",
                status="fail",
                severity_reason='"); alert(2); //',
                fix_url="javascript:alert(3)",
                fix_command=["<img src=x onerror=alert(4)>", "&", "<b>"],
            )
        ],
        exit_code=2,
    )
    out = report_html.render_install_report(doctor, None)
    # No raw <script> tag from the probe name reaches the document.
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
    # No raw onerror handler from the fix_command tokens.
    assert "<img src=x onerror=alert(4)>" not in out
    assert "&lt;img src=x onerror=alert(4)&gt;" in out
    # The severity_reason quote-escape attempt is rendered as text.
    assert "&quot;); alert(2); //" in out or "&#34;); alert(2); //" in out


def test_6b_injection_in_smoke_surface_name_is_escaped() -> None:
    doctor = _doctor_payload()
    smoke = _smoke_payload()
    smoke["supervisor_surfaces"] = [
        {
            "name": "<script>x</script>",
            "status": "pass",
            "elapsed_s": 0.1,
            "error": None,
            "evidence": None,
        }
    ]
    out = report_html.render_install_report(doctor, smoke)
    assert "<script>x</script>" not in out
    assert "&lt;script&gt;x&lt;/script&gt;" in out


def test_6d_javascript_url_in_fix_url_is_not_rendered_as_active_href() -> None:
    """F004 i0 audit follow-up: the renderer must NOT emit an active
    ``href="javascript:..."`` anchor even when the URL is html.escape'd.
    Escape protects the surrounding markup; it does NOT make
    ``javascript:`` URLs safe — only the scheme allowlist does. Mirrors
    the Plan 4 F002 D004 defense-in-depth pattern: validator drops the
    *type* mismatch, scheme allowlist drops *semantic* mismatch."""
    doctor = _doctor_payload(
        probes=[
            _probe(
                name="malicious-probe",
                status="fail",
                fix_url="javascript:alert(3)",
                fix_command=["echo", "noop"],
            )
        ],
        exit_code=2,
    )
    out = report_html.render_install_report(doctor, None)
    # The href attribute must NOT carry the javascript: URL.
    assert 'href="javascript:alert(3)"' not in out
    assert "href='javascript:alert(3)'" not in out
    assert "href=\"javascript:" not in out
    # Operator still sees the value as inert escaped text (not silently
    # dropped) — that surfaces "this URL was rejected" without hiding it.
    assert "javascript:alert(3)" in out
    assert 'class="docs-unsafe"' in out


def test_6e_data_url_in_fix_url_is_inert() -> None:
    doctor = _doctor_payload(
        probes=[
            _probe(
                name="data-url-probe",
                status="fail",
                fix_url="data:text/html,<script>alert(1)</script>",
            )
        ],
        exit_code=2,
    )
    out = report_html.render_install_report(doctor, None)
    assert "href=\"data:" not in out
    assert "<script>alert(1)</script>" not in out
    assert 'class="docs-unsafe"' in out


def test_6f_https_fix_url_renders_as_active_link() -> None:
    """The allowlist must not over-block — http/https URLs should still
    render as clickable anchors, since copy-paste-friendly docs links are
    a core acceptance for the report."""
    doctor = _doctor_payload(
        probes=[
            _probe(
                name="benign-probe",
                status="warn",
                fix_url="https://example.com/install-guide",
            )
        ],
        exit_code=1,
    )
    out = report_html.render_install_report(doctor, None)
    assert 'href="https://example.com/install-guide"' in out
    assert 'class="docs-unsafe"' not in out


def test_6c_injection_in_profile_name_is_escaped() -> None:
    # Profile name is unconstrained at the renderer boundary (the
    # validator rejects unknown profiles upstream, but the renderer must
    # not assume that — escape unconditionally).
    doctor = _doctor_payload()
    doctor["profile"] = "<script>x</script>"
    out = report_html.render_install_report(doctor, None)
    assert "<title>DontPanic install status — profile=<script>x</script></title>" not in out
    assert "&lt;script&gt;x&lt;/script&gt;" in out


# ── (7) mobile-responsive media query ─────────────────────────────────────


def test_7_mobile_responsive_media_query_present() -> None:
    out = report_html.render_install_report(_doctor_payload(), None)
    # Viewport meta + at least one @media (min-width: ...) breakpoint at 800px.
    assert 'name="viewport"' in out
    assert "@media (min-width: 800px)" in out


# ── (8) well-formed HTML5 ─────────────────────────────────────────────────


def test_8_generated_html_is_well_formed_html5() -> None:
    out = report_html.render_install_report(
        _doctor_payload(
            exit_code=1,
            probes=[
                _probe(name="python-version", status="pass"),
                _probe(name="gh-auth-status", status="warn", fix_command=["gh", "auth", "login"]),
                _probe(name="codex-cli", status="advisory"),
                _probe(name="anthropic-api-network", status="fail"),
            ],
        ),
        _smoke_payload(exit_code=1, volley_status="needs_changes"),
    )
    _assert_well_formed_html(out)


def test_8b_well_formed_with_no_smoke_payload() -> None:
    out = report_html.render_install_report(_doctor_payload(), None)
    _assert_well_formed_html(out)


def test_8c_well_formed_with_empty_probe_list() -> None:
    out = report_html.render_install_report(
        _doctor_payload(probes=[], exit_code=0),
        None,
    )
    _assert_well_formed_html(out)
    assert "all green" in out or "no remaining" in out


# ── (9) file-level write helper ───────────────────────────────────────────


def test_9_write_install_report_writes_file(tmp_path) -> None:
    target = tmp_path / "subdir" / "install-report.html"
    written = report_html.write_install_report(
        _doctor_payload(), _smoke_payload(), target
    )
    assert written == target
    assert target.is_file()
    body = target.read_text(encoding="utf-8")
    assert "<!doctype html>" in body.lower()
    assert "DontPanic install status" in body
