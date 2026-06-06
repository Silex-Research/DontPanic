"""Plan 2026-06-05-002 F004 + F005 — QA sufficiency contract doc structure.

F005 (surface-agnostic model) + F004 (dashboard read-only-UI instance) ship as one doc.
This guards the doc enumerates the surface classes, the governs-not-executes boundary,
the iOS/Android UI-journey rule, and the dashboard worked-instance citing F003.
"""

from __future__ import annotations

from pathlib import Path

_DOC = Path(__file__).resolve().parents[3] / "docs/qa-sufficiency-contract.md"


def _text() -> str:
    return _DOC.read_text(encoding="utf-8").lower()


def test_doc_exists() -> None:
    assert _DOC.is_file()


def test_enumerates_all_surface_classes() -> None:
    body = _text()
    for surface in (
        "read-only ui",
        "interactive ui",
        "mobile app",
        "command (cli)",
        "agent / mcp tool",
        "mutation",
        "external integration",
        "service / batch",
    ):
        assert surface in body, surface


def test_states_governs_not_executes_boundary() -> None:
    body = _text()
    assert "governs" in body and "execute" in body
    # The plan must NAME the proof; DontPanic does not run the foreign surface itself.
    assert "name the entering-surface" in body
    assert "advisory in v0" in body


def test_includes_ios_android_ui_journey_rule() -> None:
    body = _text()
    assert "ios" in body and "android" in body
    assert "simulator" in body and "emulator" in body
    assert "not only viewmodel" in body


def test_marks_dashboard_instance_and_cites_f003() -> None:
    body = _text()
    assert "read-only-ui instance" in body or "read-only ui" in body
    assert "dashboard-journey.test.js" in body  # the F003 exemplar entering-surface test
    assert "no copied harnesses" in body
