"""Plan 2026-05-24-004 F003 — render() + dispatch + sidecar + INBOX tests.

Coverage required by F003 acceptance #10 + the iter-1 audit addendum:

  - routing per disposition: LIVE, DASHBOARD_ACTION, INBOX_ONLY, AUDIT_ONLY.
  - dual-merge-path coverage: ``dashboard.build()`` AND
    ``operator_console.write_cache()`` both call
    ``merge_with_event_sidecar`` so the served what-now never goes stale.
  - brand-drift normalization fires at the render boundary.
  - D009 breaker normalization is restricted to ``breaker:patch_incomplete``;
    unknown ``breaker:*`` falls through (render returns None).
  - INBOX is NOT double-written — ``append_rendered_annotation`` appends only
    the rendered block, never a raw entry.
  - F003 audit finding (i1): dispatch_event passes the already-produced
    RenderedEvent to both sinks; sinks do NOT re-render via ``event_copy``
    when the kwarg is provided.

Tests intentionally mock at module boundaries (urlopen / terminal-notifier
binary / write paths) — no real network, no operator $HOME pollution
(autouse conftest redirects DONTPANIC_HOME / JARVIS_HOME).
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import (  # noqa: E402
    dashboard,
    event_copy,
    inbox,
    notify,
    notify_discord,
    notify_event,
    operator_console,
)


# ─── helpers ────────────────────────────────────────────────────────────────


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _make_event(
    *,
    kind: str = "gate_paused",
    inbox_event: str = "gate_hit",
    severity: str = "action_required",
    plan_id: str = "p1",
    feature_id: str | None = "F001",
    body: str = "x",
    evidence_uri: str | None = "/tmp/INBOX.md",
    breaker_kind: str | None = None,
    subtype: str | None = None,
    technical_metadata: dict[str, Any] | None = None,
) -> notify_event.NotifyEvent:
    return notify_event.NotifyEvent(
        kind=kind,
        severity=severity,
        plan_id=plan_id,
        feature_id=feature_id,
        body=body,
        evidence_uri=evidence_uri,
        timestamp=_now(),
        inbox_event=inbox_event,
        breaker_kind=breaker_kind,
        subtype=subtype,
        technical_metadata=technical_metadata or {},
    )


# ─── routing per disposition ───────────────────────────────────────────────


class TestRoutingPerDisposition:
    """Acceptance #10: route each disposition to its correct sink set.

    Matrix per plan.md § Implementation Strategy:
      LIVE              → discord + terminal + sidecar + INBOX annotation
      DASHBOARD_ACTION  → sidecar + INBOX annotation only
      INBOX_ONLY        → raw INBOX entry only (no rendering)
      AUDIT_ONLY        → durable INBOX entry; not rendered, not sidecar'd
    """

    def test_live_disposition_renders_and_fans_all_sinks(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # ``gate_hit`` is LIVE per DISPOSITION_TABLE.
        ev = _make_event(
            inbox_event="gate_hit",
            subtype="pre_impl",
            technical_metadata={"gate": "pre_impl", "stage": "pre_impl"},
        )
        # Silence terminal binary lookup so notify.notify returns False
        # deterministically; we just want to confirm notify_event was invoked.
        monkeypatch.setattr(notify, "_binary_path", lambda: None)
        monkeypatch.setenv("DONTPANIC_NOTIFY_LEVEL", "verbose")
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", "https://example.invalid/webhook/x/y")
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        # Capture sink invocations.
        terminal_calls: list[Any] = []
        discord_calls: list[Any] = []

        def fake_terminal(event: Any, **kwargs: Any) -> bool:
            terminal_calls.append((event, kwargs))
            return True

        def fake_discord(event: Any, **kwargs: Any) -> bool:
            discord_calls.append((event, kwargs))
            return True

        monkeypatch.setattr(notify_event.notify, "notify_event", fake_terminal)
        monkeypatch.setattr(notify_event.notify_discord, "notify", fake_discord)

        result = notify_event.dispatch_event(ev, plan_dir=plan_dir)

        assert result["terminal"] is True
        assert result["discord"] is True
        assert result["sidecar"] is True
        assert result["inbox_annotation"] is True
        # F003 (i1): the sink received the rendered argument so it does not
        # re-render — the architectural contract this test exists to enforce.
        assert len(terminal_calls) == 1
        assert "rendered" in terminal_calls[0][1]
        assert terminal_calls[0][1]["rendered"] is not None
        assert len(discord_calls) == 1
        assert "rendered" in discord_calls[0][1]
        assert discord_calls[0][1]["rendered"] is not None

    def test_dashboard_action_skips_live_sinks(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # ``quota_warn`` is DASHBOARD_ACTION.
        ev = _make_event(
            kind="quota_warn",
            inbox_event="quota_warn",
            severity="action_required",
            technical_metadata={
                "agent": "claude",
                "window": "7d",
                "percent_weekly": 80,
                "threshold": 75,
            },
        )
        monkeypatch.setattr(notify, "_binary_path", lambda: None)
        monkeypatch.setenv("DONTPANIC_NOTIFY_LEVEL", "verbose")
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", "https://example.invalid/webhook/x/y")
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()

        terminal_calls: list[Any] = []
        discord_calls: list[Any] = []
        monkeypatch.setattr(notify_event.notify, "notify_event", lambda *a, **k: terminal_calls.append((a, k)) or True)
        monkeypatch.setattr(notify_event.notify_discord, "notify", lambda *a, **k: discord_calls.append((a, k)) or True)

        result = notify_event.dispatch_event(ev, plan_dir=plan_dir)

        # DASHBOARD_ACTION must NOT reach terminal or Discord.
        assert terminal_calls == []
        assert discord_calls == []
        assert result["terminal"] is False
        assert result["discord"] is False
        # But the sidecar + INBOX annotation must fire so the dashboard
        # surfaces the ActionItem.
        assert result["sidecar"] is True
        assert result["inbox_annotation"] is True

    def test_inbox_only_returns_none_from_render(self) -> None:
        # ``error`` and ``defer_tripped`` are INBOX_ONLY — render must skip.
        for inbox_event in ("error", "defer_tripped", "blocked_no_findings"):
            ev = _make_event(inbox_event=inbox_event)
            assert event_copy.render(ev) is None, (
                f"render({inbox_event!r}) must return None for INBOX_ONLY"
            )

    def test_audit_only_returns_none_from_render(self) -> None:
        # ``gate_cleared``, ``resumed`` etc. are AUDIT_ONLY.
        for inbox_event in ("gate_cleared", "resumed", "defer_cleared"):
            ev = _make_event(inbox_event=inbox_event)
            assert event_copy.render(ev) is None, (
                f"render({inbox_event!r}) must return None for AUDIT_ONLY"
            )

    def test_inbox_only_does_not_reach_live_sinks(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Regression for F003 audit i0 finding: a known INBOX_ONLY kind
        must not fall through to the legacy fan-out path."""
        monkeypatch.setattr(notify, "_binary_path", lambda: None)
        monkeypatch.setenv("DONTPANIC_NOTIFY_LEVEL", "verbose")
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", "https://example.invalid/webhook/x/y")
        terminal_calls: list[Any] = []
        discord_calls: list[Any] = []
        monkeypatch.setattr(notify_event.notify, "notify_event", lambda *a, **k: terminal_calls.append((a, k)) or True)
        monkeypatch.setattr(notify_event.notify_discord, "notify", lambda *a, **k: discord_calls.append((a, k)) or True)

        ev = _make_event(kind="error", inbox_event="error", severity="info", evidence_uri=None)
        result = notify_event.dispatch_event(ev, plan_dir=tmp_path)

        assert terminal_calls == []
        assert discord_calls == []
        assert result == {
            "terminal": False,
            "discord": False,
            "sidecar": False,
            "inbox_annotation": False,
        }


# ─── breaker normalization (finding 3) ─────────────────────────────────────


class TestBreakerNormalization:
    """D009 + iter-1 audit: only ``breaker:patch_incomplete`` normalizes."""

    def test_breaker_patch_incomplete_renders_via_breaker_tripped(self) -> None:
        ev = _make_event(
            kind="breaker_tripped",
            inbox_event="breaker:patch_incomplete",
            severity="escalation",
            evidence_uri="/tmp/INBOX.md",
        )
        rendered = event_copy.render(ev)
        assert rendered is not None
        # The normalized form sets breaker_kind=patch_incomplete in the tech
        # metadata so the template renders the kind.
        assert rendered.technical_metadata.get("breaker_kind") == "patch_incomplete"
        # The exact command must reference the authorized breaker kind.
        assert rendered.exact_command is not None
        assert "patch_incomplete" in rendered.exact_command

    def test_unknown_breaker_colon_kind_renders_none(self) -> None:
        """The auditor's exact regression: ``breaker:not_real`` previously
        rendered live with a fake ``dontpanic approve p breaker:not_real``.
        After normalization tightening, the disposition table lookup misses
        and render returns None."""
        ev = _make_event(
            kind="breaker_tripped",
            inbox_event="breaker:not_real",
            severity="escalation",
            evidence_uri="/tmp/INBOX.md",
        )
        assert event_copy.render(ev) is None

    def test_unknown_breaker_colon_kind_does_not_reach_live_sinks(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(notify, "_binary_path", lambda: None)
        monkeypatch.setenv("DONTPANIC_NOTIFY_LEVEL", "verbose")
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", "https://example.invalid/webhook/x/y")
        terminal_calls: list[Any] = []
        discord_calls: list[Any] = []
        monkeypatch.setattr(notify_event.notify, "notify_event", lambda *a, **k: terminal_calls.append((a, k)) or True)
        monkeypatch.setattr(notify_event.notify_discord, "notify", lambda *a, **k: discord_calls.append((a, k)) or True)

        ev = _make_event(
            kind="breaker_tripped",
            inbox_event="breaker:not_real",
            severity="escalation",
            evidence_uri="/tmp/INBOX.md",
        )
        # Unknown inbox_event falls through legacy fan-out, but render
        # returns None and the sink doesn't get a rendered RenderedEvent.
        # The legacy fan-out still fires (kind is unknown to DISPOSITION_TABLE
        # so it's treated as an ad-hoc event for backward compat). What MUST
        # NOT happen is a *rendered* fake-command going to the sinks.
        notify_event.dispatch_event(ev, plan_dir=tmp_path)
        # If terminal/discord fired via legacy fallback, the rendered kwarg
        # must be None — no fake breaker:not_real command was synthesized.
        for _, kwargs in terminal_calls + discord_calls:
            # Legacy fallback calls notify.notify_event(event) and
            # notify_discord.notify(event) WITHOUT a rendered kwarg.
            assert "rendered" not in kwargs or kwargs.get("rendered") is None

    def test_normalize_inbox_event_only_matches_patch_incomplete(self) -> None:
        # Internal helper invariant — direct unit test.
        assert event_copy._normalize_inbox_event("breaker:patch_incomplete") == (
            "breaker_tripped",
            "patch_incomplete",
        )
        assert event_copy._normalize_inbox_event("breaker:not_real") == (
            "breaker:not_real",
            None,
        )
        assert event_copy._normalize_inbox_event("breaker:") == (
            "breaker:",
            None,
        )


# ─── brand-drift normalization ─────────────────────────────────────────────


class TestBrandDriftNormalization:
    """D010: legacy ``jarvis`` strings rewritten at render boundary."""

    def test_normalize_brand_drift_rewrites_canonical_phrases(self) -> None:
        assert event_copy.normalize_brand_drift("Run `jarvis approve foo`") == (
            "Run `dontpanic approve foo`"
        )
        assert (
            event_copy.normalize_brand_drift("Try jarvis-orchestrate approve")
            == "Try dontpanic approve"
        )
        assert event_copy.normalize_brand_drift("Jarvis [plan-001]") == (
            "DontPanic [plan-001]"
        )
        assert event_copy.normalize_brand_drift(None) is None

    def test_render_normalizes_brand_drift_in_output(self) -> None:
        """Even if a template (hypothetically) emitted legacy brand strings,
        the normalizer would rewrite them. Validate by injecting a forged
        template that contains the legacy phrase and re-rendering."""
        # Simulate a brand-drifted action by monkey-patching one template.
        original = event_copy._TEMPLATES["gate_hit"]
        forged = event_copy._Template(
            band=original.band,
            headline="Jarvis [{plan_label}] needs approval",
            why=original.why,
            action="jarvis approve {plan_id} {gate}",
        )
        with patch.dict(
            event_copy._TEMPLATES, {"gate_hit": forged}
        ), patch.object(
            event_copy,
            "TRANSLATION_TABLE",
            {**event_copy.TRANSLATION_TABLE, "gate_hit": forged},
        ):
            ev = _make_event(
                inbox_event="gate_hit",
                subtype="pre_impl",
                technical_metadata={"gate": "pre_impl", "stage": "pre_impl"},
            )
            rendered = event_copy.render(ev)
        assert rendered is not None
        assert "Jarvis" not in rendered.title
        assert "DontPanic" in rendered.title
        # exact_command may collapse to None if the validator rejects the
        # rewritten form; if it survives, it must be brand-normalized.
        if rendered.exact_command is not None:
            assert "jarvis" not in rendered.exact_command
            assert rendered.exact_command.startswith("dontpanic approve")


# ─── honest-commands rule (D008) ────────────────────────────────────────────


class TestHonestCommandsRule:
    @pytest.mark.parametrize(
        ("final_status", "expected_title_fragment", "expects_command"),
        [
            ("signed_off", "AI work finished", False),
            ("stopped_no_progress", "Blocked work", True),
        ],
    )
    def test_volley_terminal_copy_branches_on_final_status(
        self,
        final_status: str,
        expected_title_fragment: str,
        expects_command: bool,
    ) -> None:
        ev = _make_event(
            kind="volley_terminal",
            inbox_event="volley_terminal",
            severity="info" if final_status == "signed_off" else "action_required",
            evidence_uri="/tmp/signoff.json",
            technical_metadata={
                "final_status": final_status,
                "rounds": 2,
            },
        )

        rendered = event_copy.render(ev)

        assert rendered is not None
        assert expected_title_fragment in rendered.title
        if final_status == "signed_off":
            assert rendered.band == "ready"
            assert "Blocked work" not in rendered.title
            assert "resume" not in (rendered.detail or "").lower()
            assert rendered.exact_command is None
        else:
            assert rendered.band == "needs_action"
            assert rendered.exact_command is not None
            assert "dontpanic resume" in rendered.exact_command
        assert (rendered.exact_command is not None) is expects_command

    def test_verdict_mismatch_renders_with_none_command(self) -> None:
        ev = _make_event(
            kind="verdict_mismatch",
            inbox_event="verdict_mismatch",
            severity="action_required",
            technical_metadata={
                "narrative_verdict": "blocked",
                "structured_status": "signed_off",
                "iteration_label": "2",
            },
        )
        rendered = event_copy.render(ev)
        assert rendered is not None
        assert rendered.exact_command is None, (
            "D008: verdict_mismatch must have exact_command=None"
        )

    def test_gate_state_reconciliation_failed_command_is_none(self) -> None:
        ev = _make_event(
            kind="gate_state_reconciliation_failed",
            inbox_event="gate_state_reconciliation_failed",
            severity="action_required",
            technical_metadata={
                "contradiction_kind": "missing_pre_impl",
                "gate": "pre_impl",
                "stage": "pre_impl",
            },
        )
        rendered = event_copy.render(ev)
        assert rendered is not None
        assert rendered.exact_command is None

    def test_signed_off_volley_terminal_reaches_sinks_as_finished_copy(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        terminal_calls: list[Any] = []
        discord_calls: list[Any] = []
        monkeypatch.setattr(
            notify_event.notify,
            "notify_event",
            lambda *a, **k: terminal_calls.append((a, k)) or True,
        )
        monkeypatch.setattr(
            notify_event.notify_discord,
            "notify",
            lambda *a, **k: discord_calls.append((a, k)) or True,
        )
        ev = _make_event(
            kind="volley_terminal",
            inbox_event="volley_terminal",
            severity="info",
            evidence_uri="/tmp/signoff.json",
            technical_metadata={
                "final_status": "signed_off",
                "rounds": 1,
            },
        )

        result = notify_event.dispatch_event(ev, plan_dir=tmp_path)

        assert result["terminal"] is True
        assert result["discord"] is True
        assert len(terminal_calls) == 1
        assert len(discord_calls) == 1
        terminal_rendered = terminal_calls[0][1]["rendered"]
        discord_rendered = discord_calls[0][1]["rendered"]
        for rendered in (terminal_rendered, discord_rendered):
            assert rendered.title.startswith("AI work finished")
            assert rendered.band == "ready"
            assert rendered.exact_command is None
            assert "Blocked work" not in rendered.title


# ─── dual-merge-path coverage (D019) ────────────────────────────────────────


class _FakeRendered:
    """Cheap RenderedEvent stand-in for sidecar JSONL round-trips."""

    band = "needs_action"
    title = "Test title"
    detail = "Test detail"
    exact_command = "dontpanic approve p1 pre_impl"
    evidence_uri = "/tmp/INBOX.md"

    def __init__(self, plan_id: str = "p1", inbox_event: str = "gate_hit") -> None:
        self.technical_metadata = {
            "plan_id": plan_id,
            "inbox_event": inbox_event,
            "feature_id": "F001",
        }


class TestDualMergePath:
    """D019: BOTH dashboard.build() AND operator_console.write_cache() must
    invoke ``merge_with_event_sidecar`` or the served what-now goes stale."""

    def test_write_cache_merges_event_sidecar_by_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sidecar = tmp_path / "event-actions.jsonl"
        monkeypatch.setattr(
            operator_console, "default_event_sidecar_path", lambda: sidecar
        )
        # Seed the sidecar with one rendered entry.
        operator_console.write_event_action_sidecar(_FakeRendered(), path=sidecar)
        assert sidecar.is_file()

        cache_path = tmp_path / "what-now.json"
        operator_console.write_cache(items=(), path=cache_path)
        payload = json.loads(cache_path.read_text())
        ids = [it["id"] for it in payload["items"]]
        assert any("gate_hit" in i for i in ids), (
            f"write_cache must merge sidecar items; got ids={ids}"
        )

    def test_write_cache_can_skip_merge_for_pure_provider_output(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sidecar = tmp_path / "event-actions.jsonl"
        monkeypatch.setattr(
            operator_console, "default_event_sidecar_path", lambda: sidecar
        )
        operator_console.write_event_action_sidecar(_FakeRendered(), path=sidecar)

        cache_path = tmp_path / "what-now.json"
        operator_console.write_cache(
            items=(), path=cache_path, merge_event_sidecar=False
        )
        payload = json.loads(cache_path.read_text())
        assert payload["items"] == []

    def test_dashboard_build_calls_merge_with_event_sidecar(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Dashboard.build() must invoke merge_with_event_sidecar before
        writing the out_dir copy of what-now.json. We capture the call by
        patching the merge helper and inspecting whether build() called it
        even when provider items are empty."""
        called: dict[str, Any] = {"count": 0, "items": None}
        real_merge = operator_console.merge_with_event_sidecar

        def tracking_merge(items, *args, **kwargs):
            called["count"] += 1
            called["items"] = list(items) if items else []
            return real_merge(items, *args, **kwargs)

        monkeypatch.setattr(operator_console, "merge_with_event_sidecar", tracking_merge)
        # Repoint the dashboard module's binding too — it imports the symbol
        # via ``from dontpanic_orchestrate import operator_console`` so it
        # reads through ``operator_console.merge_with_event_sidecar``.
        monkeypatch.setattr(
            dashboard.operator_console, "merge_with_event_sidecar", tracking_merge
        )

        plans_root = tmp_path / "plans"
        plans_root.mkdir()
        out_dir = tmp_path / "out"
        # Avoid blowing up on optional subsystems — pass minimal config.
        dashboard.build(
            plans_root=plans_root,
            out_dir=out_dir,
            redact_level="sanitized",
            plan_id=None,
            warn=lambda _msg: None,
            write_what_now_cache=True,
            check_architecture=False,
            check_reconcile=False,
            write_capabilities_cache=False,
            what_now_cache_path_override=tmp_path / "home-cache.json",
        )
        # Both call paths fire: once from dashboard.build (out_dir merge)
        # and once from write_cache (home-cache merge, since we passed the
        # already-merged list with merge_event_sidecar=False inside build).
        assert called["count"] >= 1, "dashboard.build did not call merge_with_event_sidecar"

    def test_sidecar_write_then_merge_round_trip(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A RenderedEvent → write_event_action_sidecar → merge_with_event_sidecar
        round-trips into an ActionItem in the merged list."""
        sidecar = tmp_path / "event-actions.jsonl"
        operator_console.write_event_action_sidecar(_FakeRendered(), path=sidecar)
        merged = operator_console.merge_with_event_sidecar(
            (), sidecar_path=sidecar
        )
        assert len(merged) == 1
        assert merged[0].title == "Test title"
        assert merged[0].exact_command == "dontpanic approve p1 pre_impl"

    def test_provider_items_win_on_id_conflict(
        self,
        tmp_path: Path,
    ) -> None:
        sidecar = tmp_path / "event-actions.jsonl"
        operator_console.write_event_action_sidecar(_FakeRendered(), path=sidecar)

        # Provider emits an ActionItem with the SAME id the sidecar will project.
        provider_item = operator_console.ActionItem(
            id="supervisor:gate_hit:p1:F001",
            source=operator_console.SOURCE_SUPERVISOR,
            band=operator_console.Band.NEEDS_ACTION,
            title="Provider title",
            detail=None,
            exact_command=None,
            automatable=False,
            human_required_reason="provider win",
            evidence_uri=None,
            updated_at="2026-05-24T12:00:00Z",
        )
        merged = operator_console.merge_with_event_sidecar(
            (provider_item,), sidecar_path=sidecar
        )
        # Same id → provider wins; sidecar advisory entry is dropped.
        assert len(merged) == 1
        assert merged[0].title == "Provider title"


# ─── INBOX append_rendered_annotation isolation ─────────────────────────────


class TestInboxAnnotationDoesNotDuplicate:
    """D018: append_rendered_annotation must append ONLY the rendered block;
    it never writes a raw INBOX entry — that's append_event's job."""

    def test_annotation_does_not_emit_an_inbox_entry(
        self,
        tmp_path: Path,
    ) -> None:
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        # First, write a raw entry the way an emit site would.
        inbox.append_event(
            plan_dir,
            event="gate_hit",
            plan_id="p1",
            body="Gate pause body",
            gate="pre_impl",
        )
        entries_before = inbox.read_events(plan_dir)
        assert len(entries_before) == 1
        # Now append the rendered annotation — it MUST NOT produce a new entry.
        inbox.append_rendered_annotation(
            plan_dir,
            plan_id="p1",
            rendered=_FakeRendered(),
        )
        entries_after = inbox.read_events(plan_dir)
        assert len(entries_after) == 1, (
            "append_rendered_annotation must not create a parseable INBOX entry"
        )
        # But the markdown body should now contain the rendered title.
        body = (plan_dir / "INBOX.md").read_text()
        assert "Test title" in body
        assert "Technical details" in body

    def test_annotation_with_no_rendered_is_noop(
        self,
        tmp_path: Path,
    ) -> None:
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        inbox.append_rendered_annotation(plan_dir, plan_id="p1", rendered=None)
        # No INBOX.md should be created from a None-rendered call.
        assert not (plan_dir / "INBOX.md").is_file()


# ─── sink rendered-arg architectural contract (finding 1) ───────────────────


class TestSinksConsumeRenderedKwarg:
    """The whole point of finding 1: dispatch_event passes the rendered
    event to both sinks; sinks honor it and do NOT re-render via
    event_copy when ``rendered`` is provided."""

    def test_terminal_sink_uses_rendered_arg_without_calling_render(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        def capture(title: str, message: str, **kwargs: Any) -> bool:
            captured["title"] = title
            captured["message"] = message
            return True

        monkeypatch.setattr(notify, "notify", capture)

        # Build the rendered event first using the real renderer, then
        # patch event_copy.render to fail loudly. notify.notify_event with
        # ``rendered=`` provided must NOT re-enter event_copy.render — both
        # notify.py and notify_discord.py import event_copy lazily so the
        # module-level patch is observed when the sink reaches for it.
        ev = _make_event(
            inbox_event="gate_hit",
            subtype="pre_impl",
            technical_metadata={"gate": "pre_impl", "stage": "pre_impl"},
        )
        rendered = event_copy.render(ev)
        assert rendered is not None

        def explode(*_args: Any, **_kwargs: Any):
            raise AssertionError(
                "event_copy.render must NOT be called when rendered=... is "
                "passed to the sink — finding 1 of the F003 audit"
            )

        monkeypatch.setattr(event_copy, "render", explode)

        notify.notify_event(ev, rendered=rendered)
        # And the message body must come from the rendered headline.
        assert captured["message"] == rendered.headline[:140]
        assert captured["title"] == "DontPanic [p1]"

    def test_discord_sink_uses_rendered_arg_without_calling_render(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", "https://example.invalid/webhook/x/y")
        captured: dict[str, Any] = {}

        def fake_urlopen(req: Any, *_: Any, **__: Any):
            captured["body"] = json.loads(req.data.decode("utf-8"))

            class _Ctx:
                def __enter__(self_inner):
                    class _R:
                        status = 204

                        def getcode(self_r):  # noqa: ARG002
                            return 204

                    return _R()

                def __exit__(self_inner, *_args):
                    return False

            return _Ctx()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

        # Build a real rendered first; then patch event_copy.render to fail.
        ev = _make_event(
            inbox_event="gate_hit",
            subtype="pre_impl",
            technical_metadata={"gate": "pre_impl", "stage": "pre_impl"},
        )
        rendered = event_copy.render(ev)
        assert rendered is not None

        def explode(*_args: Any, **_kwargs: Any):
            raise AssertionError(
                "event_copy.render must NOT be called when rendered=... is "
                "passed to the Discord sink — finding 1 of the F003 audit"
            )

        monkeypatch.setattr(event_copy, "render", explode)

        assert notify_discord.notify(ev, rendered=rendered) is True
        # The embed must reflect the rendered event (not the legacy
        # content fallback shape).
        assert "embeds" in captured["body"]
        assert captured["body"]["embeds"][0]["title"] == rendered.title


# ─── translation-table totality (finding 4) ─────────────────────────────────


class TestTranslationTableTotality:
    """F003 audit i0 finding #4: the auditor flagged that DISPOSITION_TABLE
    (27 keys) has more entries than TRANSLATION_TABLE (15). The intentional
    split is: only LIVE + DASHBOARD_ACTION dispositions need rendered copy.
    INBOX_ONLY + AUDIT_ONLY skip rendering (render() returns None).

    These tests document and enforce that intentional subset so a future
    edit that adds a LIVE/DASHBOARD_ACTION kind without a template fails
    loudly here instead of producing a silent KeyError at dispatch time."""

    def test_every_live_or_dashboard_action_kind_has_a_template(self) -> None:
        """Renderable dispositions (LIVE / DASHBOARD_ACTION) MUST have a
        translation entry; render() routes through it when dispatch fires."""
        renderable = {
            kind
            for kind, disp in event_copy.DISPOSITION_TABLE.items()
            if disp in {event_copy.Disposition.LIVE, event_copy.Disposition.DASHBOARD_ACTION}
        }
        # D009 normalization: breaker:patch_incomplete is rendered via the
        # breaker_tripped template, so a literal TRANSLATION_TABLE entry for
        # the colon-key is NOT required.
        renderable_unnormalized = renderable - {"breaker:patch_incomplete"}
        missing = renderable_unnormalized - set(event_copy.TRANSLATION_TABLE.keys())
        assert not missing, (
            f"Renderable kinds without a translation template: {sorted(missing)}. "
            "Either add a _Template entry or downgrade the disposition."
        )

    def test_inbox_only_and_audit_only_kinds_render_to_none(self) -> None:
        """Explicit per-kind regression covering EVERY INBOX_ONLY +
        AUDIT_ONLY entry — closes the auditor's complaint that the prior
        test only sampled a few."""
        non_renderable = [
            kind
            for kind, disp in event_copy.DISPOSITION_TABLE.items()
            if disp in {event_copy.Disposition.INBOX_ONLY, event_copy.Disposition.AUDIT_ONLY}
        ]
        # Sanity-check we're covering more than a handful.
        assert len(non_renderable) >= 10
        for kind in non_renderable:
            ev = _make_event(inbox_event=kind, kind=kind, severity="info", evidence_uri=None)
            assert event_copy.render(ev) is None, (
                f"render({kind!r}) must return None — disposition is non-renderable"
            )

    def test_translation_table_keys_are_subset_of_disposition_table(self) -> None:
        """Every template key must correspond to a disposition entry; a
        stray template (e.g. typo) would never be reachable via render()."""
        # error is INBOX_ONLY but has a defensive template (documented in
        # event_copy.py); allow it as an explicitly-permitted exception.
        template_keys = set(event_copy.TRANSLATION_TABLE.keys())
        disposition_keys = set(event_copy.DISPOSITION_TABLE.keys())
        stray = template_keys - disposition_keys
        assert not stray, (
            f"Templates without a disposition entry: {sorted(stray)}. "
            "Add the kind to DISPOSITION_TABLE or remove the template."
        )

    def test_unknown_kind_falls_through_unrendered(self) -> None:
        """Defense in depth: a NotifyEvent.inbox_event that's not in
        DISPOSITION_TABLE renders to None — render() does not raise."""
        ev = _make_event(
            kind="totally_made_up",
            inbox_event="totally_made_up",
            severity="info",
            evidence_uri=None,
        )
        assert event_copy.render(ev) is None


# ─── Discord payload serialization parity (finding 3) ──────────────────────


class TestDiscordPayloadSerializationMatchesEnforcement:
    """F003 audit i0 finding #3: notify() was sending ``json.dumps(payload)``
    (ASCII-escaped), but ``_enforce_payload_total_limit`` measured
    ``json.dumps(payload, ensure_ascii=False)``. A measured 1237-char body
    ballooned to 5232 chars on the actual send path. After the fix the two
    serializations must match."""

    def test_send_path_serialization_matches_measurement_serialization(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", "https://example.invalid/webhook/x/y")
        captured_body: dict[str, Any] = {}

        def fake_urlopen(req: Any, *_: Any, **__: Any):
            captured_body["bytes"] = req.data

            class _Ctx:
                def __enter__(self_inner):
                    class _R:
                        status = 204

                        def getcode(self_r):  # noqa: ARG002
                            return 204

                    return _R()

                def __exit__(self_inner, *_args):
                    return False

            return _Ctx()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

        # Build a RenderedEvent with non-ASCII glyphs in the user-facing
        # fields (title + detail) so ASCII-escaping would inflate the wire
        # body length and reveal the bug.
        ev = _make_event(
            inbox_event="gate_hit",
            subtype="pre_impl",
            technical_metadata={"gate": "pre_impl", "stage": "pre_impl"},
        )
        rendered = event_copy.RenderedEvent(
            band="needs_action",
            title="Approval needed — 🚧 αβγ",
            detail="Setup drift × 100 — αβγδε",
            exact_command="dontpanic approve p1 pre_impl",
            evidence_uri="/tmp/INBOX.md",
            disposition=event_copy.Disposition.LIVE,
            technical_metadata={"plan_id": "p1", "inbox_event": "gate_hit"},
        )

        assert notify_discord.notify(ev, rendered=rendered) is True
        # The bytes sent must equal what _build_payload + the same
        # ensure_ascii=False serialization _enforce_payload_total_limit
        # measures against.
        sent_bytes = captured_body["bytes"]
        decoded = sent_bytes.decode("utf-8")
        assert "🚧" in decoded, (
            "non-ASCII payload must survive as UTF-8, not be \\uXXXX-escaped"
        )
        # Sanity-check: the wire bytes for this payload are the same as a
        # fresh ensure_ascii=False reserialize of the parsed JSON.
        reparsed = json.loads(decoded)
        re_encoded = json.dumps(reparsed, ensure_ascii=False).encode("utf-8")
        assert len(sent_bytes) == len(re_encoded), (
            "send-path serialization must equal the ensure_ascii=False shape "
            "the enforcement helper measures against"
        )

    def test_payload_under_discord_limit_after_enforcement(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DONTPANIC_DISCORD_WEBHOOK_URL", "https://example.invalid/webhook/x/y")
        captured_body: dict[str, Any] = {}

        def fake_urlopen(req: Any, *_: Any, **__: Any):
            captured_body["len"] = len(req.data)

            class _Ctx:
                def __enter__(self_inner):
                    class _R:
                        status = 204

                        def getcode(self_r):  # noqa: ARG002
                            return 204

                    return _R()

                def __exit__(self_inner, *_args):
                    return False

            return _Ctx()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

        # Force a near-limit-sized body via a long fabricated detail.
        ev = _make_event(
            inbox_event="gate_hit",
            subtype="pre_impl",
            technical_metadata={
                "gate": "pre_impl",
                "stage": "pre_impl",
            },
        )
        # Manually construct a rendered event with an oversized detail so
        # _enforce_payload_total_limit must trim.
        oversized = event_copy.RenderedEvent(
            band="needs_action",
            title="Approval needed on p1",
            detail="x" * 6000,  # well past the 2000-char total limit
            exact_command="dontpanic approve p1 pre_impl",
            evidence_uri="/tmp/INBOX.md",
            disposition=event_copy.Disposition.LIVE,
            technical_metadata={"plan_id": "p1", "inbox_event": "gate_hit"},
        )
        assert notify_discord.notify(ev, rendered=oversized) is True
        # The sent payload length must be at or below Discord's 2000-char
        # total limit (the wire length, not the pre-enforcement length).
        assert captured_body["len"] <= 2000, (
            f"Discord payload exceeded 2000-char limit "
            f"after enforcement: {captured_body['len']} bytes"
        )
