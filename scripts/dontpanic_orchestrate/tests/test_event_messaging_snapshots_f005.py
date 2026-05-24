"""Plan 2026-05-24-004 F005 — cross-channel snapshot fixtures.

Pins ``(event_kind × primary channel)`` output for every ``live`` /
``dashboard_action`` kind so regressions in copy, embed colors, brand-drift
normalization, sidecar shape, or terminal title surface as a snapshot diff
the operator reviews in code review.

Channels per disposition:

  - ``live``              → Discord embed JSON + INBOX markdown block +
                            terminal headline payload + dashboard sidecar
                            JSONL line (all 4).
  - ``dashboard_action``  → INBOX markdown block + dashboard sidecar JSONL
                            line (2).

Cross-channel parity for the six highest-value kinds (gate_hit,
breaker_tripped, volley_terminal signed-off + non-signed-off,
no_progress_classification, verdict_mismatch) is achieved by the LIVE
disposition path naturally — each of those six kinds pins all four
channels in the same snapshot file.

## Regenerating snapshots

Re-run this module with ``pytest --snapshot-update`` (preferred — matches
the convention used by snapshot plugins like syrupy / pytest-snapshot).
The diff against the previous snapshot files is the artifact a reviewer
inspects in the PR.

    python -m pytest --snapshot-update \\
        scripts/dontpanic_orchestrate/tests/test_event_messaging_snapshots_f005.py

The legacy env var ``DONTPANIC_SNAPSHOT_UPDATE=1`` still works for any
scripts already wired to it (see ``conftest.snapshot_update``).

## Sanitization sweep (F005 acceptance #4)

The final test in this module walks every snapshot fixture and asserts
no string matches any of the 9 secret-shape regexes from
``scripts/sanitization_check.SECRET_REGEXES``. A leaked secret in a
pinned snapshot is a hard test failure — fixture content is the same
"durable artifact" boundary that F004 sidecar writes use, so we mirror
raise-mode there.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))
sys.path.insert(0, str(HERE.parents[3] / "scripts"))

from dontpanic_orchestrate import (  # noqa: E402
    event_copy,
    inbox,
    notify_discord,
    notify_event,
    operator_console,
)
from dontpanic_orchestrate.state_projection import scrub_secrets  # noqa: E402
from sanitization_check import SECRET_REGEXES  # noqa: E402


SNAPSHOTS_DIR = HERE.parent / "fixtures" / "event_messaging_snapshots"

# Pinned timestamp + plan id so snapshots are byte-deterministic across
# hosts / dates. Choosing 2026-05-24 (plan creation date) keeps the
# fixture content thematically tied to the plan itself.
FIXED_NOW = dt.datetime(2026, 5, 24, 0, 0, 0, tzinfo=dt.timezone.utc)
FIXED_ISO = FIXED_NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
FIXED_PLAN_ID = "2026-05-24-004-feat-event-messaging-v1"
FIXED_FEATURE_ID = "F005"
FIXED_EVIDENCE = "/tmp/INBOX.md"


# ─── Per-kind constructor fixtures ──────────────────────────────────────────
#
# Each entry pins the minimal NotifyEvent constructor kwargs needed to
# exercise the kind's translation template. ``inbox_event`` is the
# translation-table key (D017); ``kind`` is the NotifyEvent.kind verbatim
# (some kinds share a kind with multiple inbox_events, e.g. volley_terminal
# signed-off vs blocked).
#
# Snapshot file = ``fixtures/event_messaging_snapshots/{NAME}.json``.


def _ev(**kwargs: Any) -> notify_event.NotifyEvent:
    """Build a NotifyEvent with shared defaults filled in."""
    base: dict[str, Any] = {
        "plan_id": FIXED_PLAN_ID,
        "feature_id": FIXED_FEATURE_ID,
        "body": "snapshot fixture body",
        "evidence_uri": FIXED_EVIDENCE,
        "timestamp": FIXED_NOW,
    }
    base.update(kwargs)
    return notify_event.NotifyEvent(**base)


# Each fixture is a callable so we can name + parametrize cleanly while
# keeping the constructor call site readable per-kind.
KIND_BUILDERS: dict[str, "callable"] = {
    # ── LIVE — operator-actionable (cross-channel parity for the high-value six)
    "gate_hit": lambda: _ev(
        kind="gate_paused",
        severity="action_required",
        inbox_event="gate_hit",
        subtype="pre_impl",
        target_env="dev",
        technical_metadata={"gate": "pre_impl", "stage": "pre_impl"},
    ),
    "breaker_tripped": lambda: _ev(
        kind="breaker_tripped",
        severity="escalation",
        inbox_event="breaker_tripped",
        breaker_kind="no_progress",
    ),
    "breaker_patch_incomplete_legacy": lambda: _ev(
        # D009 legacy colon-key — normalizes internally to breaker_tripped
        # + breaker_kind=patch_incomplete at render time. INBOX event name
        # stays as-is at the emit site; rendered output uses the normalized
        # form. Pinning this snapshot guards the normalization.
        kind="breaker_tripped",
        severity="escalation",
        inbox_event="breaker:patch_incomplete",
    ),
    "volley_terminal_signed_off": lambda: _ev(
        kind="volley_terminal",
        severity="action_required",
        inbox_event="volley_terminal",
        iteration_count=2,
        technical_metadata={
            "final_status": "signed_off",
            "rounds": 2,
        },
    ),
    "volley_terminal_blocked": lambda: _ev(
        kind="volley_terminal",
        severity="action_required",
        inbox_event="volley_terminal",
        iteration_count=3,
        technical_metadata={
            "final_status": "stopped_no_progress",
            "rounds": 3,
        },
    ),
    "no_progress_classification": lambda: _ev(
        kind="no_progress_classification",
        severity="action_required",
        inbox_event="no_progress_classification",
        aggregate_class="implementation_defect",
        blocking=True,
    ),
    "verdict_mismatch": lambda: _ev(
        kind="verdict_mismatch",
        severity="action_required",
        inbox_event="verdict_mismatch",
        iteration_count=1,
        technical_metadata={
            "narrative_verdict": "signed_off",
            "structured_status": "needs_changes",
            "audit_path": "/tmp/audit/envelope.json",
        },
    ),
    # ── LIVE — remaining kinds (each gets all 4 channels too)
    "volley_start": lambda: _ev(
        kind="volley_start",
        severity="info",
        inbox_event="volley_start",
        iteration_count=3,
        technical_metadata={"implementer": "claude", "auditor": "codex"},
    ),
    "calibration_required": lambda: _ev(
        kind="calibration_required",
        severity="action_required",
        inbox_event="calibration_required",
        technical_metadata={"agent": "claude", "window": "7d"},
    ),
    "architecture_regen_failed": lambda: _ev(
        kind="architecture_regen_failed",
        severity="info",
        inbox_event="architecture_regen_failed",
        technical_metadata={"error_type": "GitInvocationError"},
    ),
    "environmental_blocker_short_circuit": lambda: _ev(
        kind="environmental_blocker_short_circuit",
        severity="action_required",
        inbox_event="environmental_blocker_short_circuit",
        aggregate_class="environmental_reproduction_failure",
        blocking=False,
        iteration_count=1,
    ),
    "gate_state_reconciliation_failed": lambda: _ev(
        kind="gate_state_reconciliation_failed",
        severity="escalation",
        inbox_event="gate_state_reconciliation_failed",
        subtype="pre_impl",
        technical_metadata={
            "contradiction_kind": "stale_clearance",
            "gate": "pre_impl",
            "stage": "pre_impl",
        },
    ),
    "verdict_blocked_reconciled": lambda: _ev(
        kind="verdict_blocked_reconciled",
        severity="action_required",
        inbox_event="verdict_blocked_reconciled",
        aggregate_class="environmental_reproduction_failure",
        blocking=False,
        iteration_count=1,
        technical_metadata={"original_verdict": "blocked"},
    ),
    # ── DASHBOARD_ACTION — sidecar + INBOX annotation only
    "quota_warn": lambda: _ev(
        kind="quota_warn",
        severity="action_required",
        inbox_event="quota_warn",
        technical_metadata={
            "agent": "claude",
            "percent_weekly": 80,
            "threshold": 75,
        },
    ),
    "unit_mismatch": lambda: _ev(
        kind="unit_mismatch",
        severity="action_required",
        inbox_event="unit_mismatch",
        technical_metadata={
            "agent": "claude",
            "window": "7d",
            "cap_unit": "tokens",
            "observed_unit": "messages",
        },
    ),
    "config_required": lambda: _ev(
        kind="config_required",
        severity="action_required",
        inbox_event="config_required",
        technical_metadata={"cause": "no_cap_for_signal"},
    ),
}


# ─── per-channel renderers (deterministic, no I/O outside tmp_path) ─────────


def _render_discord(event: notify_event.NotifyEvent, rendered: Any) -> dict:
    """Build the Discord payload exactly as the live sink would."""
    return notify_discord._build_payload(event, rendered=rendered)


def _render_inbox_block(
    event: notify_event.NotifyEvent,
    rendered: Any,
    tmp_path: Path,
) -> str:
    """Call ``inbox.append_rendered_annotation`` and return the appended block.

    Using the production writer (rather than rebuilding the markdown) keeps
    the snapshot pinned to the live output an operator would actually see.
    """
    plan_dir = tmp_path / "plan_dir"
    plan_dir.mkdir(parents=True, exist_ok=True)
    inbox.append_rendered_annotation(
        plan_dir,
        plan_id=event.plan_id,
        rendered=rendered,
        timestamp=FIXED_ISO,
    )
    inbox_path = inbox.inbox_path(plan_dir)
    raw = inbox_path.read_text()
    # Slice out only the rendered annotation block (the preamble is the
    # file header; everything after is the block we just appended).
    marker = f"<!-- rendered annotation {FIXED_ISO} -->"
    idx = raw.find(marker)
    assert idx >= 0, "rendered annotation marker missing"
    return raw[idx:].rstrip("\n") + "\n"


def _render_terminal_payload(
    event: notify_event.NotifyEvent, rendered: Any
) -> dict:
    """Mirror ``notify.notify_event`` payload assembly without actually
    shelling out to the terminal-notifier binary.

    Pinning the payload (title / subtitle / message / group) instead of
    the binary invocation keeps the snapshot host-portable while still
    catching brand-drift, headline truncation, and sanitization regressions.
    """
    headline = (getattr(rendered, "headline", "") or "")[:140]
    return {
        "title": scrub_secrets(f"DontPanic [{event.plan_id}]") or "",
        "subtitle": scrub_secrets(event.kind) or "",
        "message": scrub_secrets(headline) or "",
        "group": event.plan_id,
    }


def _render_sidecar_line(rendered: Any) -> dict:
    """Project a RenderedEvent into the sidecar JSONL entry an operator
    would read from ``~/.dontpanic/dashboard/event-actions.jsonl``."""
    return operator_console._rendered_to_action_item_dict(
        rendered,
        source=operator_console.SOURCE_SUPERVISOR,
        updated_at=FIXED_ISO,
    )


def _build_snapshot(name: str, tmp_path: Path) -> dict | None:
    """Render every channel applicable to ``name``'s disposition.

    Returns ``None`` when the kind does not render (defensive — a kind in
    KIND_BUILDERS whose disposition flips to inbox_only / audit_only
    would surface as a None and the test would fail loudly).
    """
    event = KIND_BUILDERS[name]()
    rendered = event_copy.render(event)
    if rendered is None:
        return None
    disposition_value = rendered.disposition.value
    snapshot: dict[str, Any] = {
        "fixture": name,
        "disposition": disposition_value,
        "inbox_event_at_emit": (
            getattr(event, "inbox_event", None) or getattr(event, "kind", None)
        ),
        "rendered": {
            "band": rendered.band,
            "title": rendered.title,
            "detail": rendered.detail,
            "exact_command": rendered.exact_command,
            "evidence_uri": rendered.evidence_uri,
            "technical_metadata": dict(rendered.technical_metadata),
        },
        "channels": {},
    }
    if disposition_value == "live":
        snapshot["channels"]["discord_embed"] = _render_discord(event, rendered)
        snapshot["channels"]["terminal_payload"] = _render_terminal_payload(
            event, rendered
        )
    # Both LIVE and DASHBOARD_ACTION pin INBOX + sidecar.
    snapshot["channels"]["inbox_block"] = _render_inbox_block(
        event, rendered, tmp_path
    )
    snapshot["channels"]["dashboard_sidecar"] = _render_sidecar_line(rendered)
    return snapshot


# ─── snapshot driver ────────────────────────────────────────────────────────


def _snapshot_path(name: str) -> Path:
    return SNAPSHOTS_DIR / f"{name}.json"


def _format_snapshot(snapshot: dict) -> str:
    """Stable, diff-friendly JSON for review in PR diffs."""
    return json.dumps(snapshot, indent=2, sort_keys=True) + "\n"


@pytest.fixture(autouse=True)
def _quiet_notify_discord(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silence the notify_discord webhook-URL warn-once across tests so the
    snapshot run is clean even when no webhook env is configured."""
    notify_discord.reset_warning_cache()
    yield
    notify_discord.reset_warning_cache()


@pytest.mark.parametrize("name", sorted(KIND_BUILDERS.keys()))
def test_kind_renders_to_pinned_snapshot(
    name: str, tmp_path: Path, snapshot_update: bool
) -> None:
    """One snapshot per (kind × channels-it-renders-to).

    Disposition routing:

      LIVE              → discord_embed + terminal_payload + inbox_block +
                          dashboard_sidecar (4 channels)
      DASHBOARD_ACTION  → inbox_block + dashboard_sidecar (2 channels)

    Acceptance #1 + cross-channel parity for the six highest-value kinds
    are both satisfied by the LIVE branch (those six are all LIVE).
    """
    snapshot = _build_snapshot(name, tmp_path)
    assert snapshot is not None, (
        f"render({name!r}) returned None — kind disposition may have flipped "
        f"to inbox_only/audit_only; remove from KIND_BUILDERS or restore "
        f"its live/dashboard_action template."
    )

    snapshot_path = _snapshot_path(name)
    if snapshot_update:
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(_format_snapshot(snapshot), encoding="utf-8")
        return

    assert snapshot_path.is_file(), (
        f"missing snapshot fixture at {snapshot_path}; regenerate with "
        f"`pytest --snapshot-update`"
    )
    expected = json.loads(snapshot_path.read_text(encoding="utf-8"))
    actual = json.loads(_format_snapshot(snapshot))
    assert actual == expected, (
        f"snapshot drift for {name}; review the diff and re-run with "
        f"`pytest --snapshot-update` if the change is intentional."
    )


def test_all_live_and_dashboard_action_kinds_are_covered() -> None:
    """Totality: every LIVE / DASHBOARD_ACTION inbox_event has a snapshot.

    Per acceptance (1) snapshot fixtures must be pinned for every kind that
    renders. The renderable set is exactly the LIVE + DASHBOARD_ACTION rows
    in :data:`event_copy.DISPOSITION_TABLE`. The legacy ``breaker:patch_incomplete``
    key normalizes onto ``breaker_tripped`` — both snapshots are pinned
    explicitly so the normalization path stays exercised.
    """
    renderable = {
        kind
        for kind, disp in event_copy.DISPOSITION_TABLE.items()
        if disp
        in (event_copy.Disposition.LIVE, event_copy.Disposition.DASHBOARD_ACTION)
    }
    fixture_inbox_events = set()
    for name, builder in KIND_BUILDERS.items():
        ev = builder()
        fixture_inbox_events.add(ev.inbox_event)
    missing = renderable - fixture_inbox_events
    assert not missing, (
        f"snapshot coverage gap — these LIVE/DASHBOARD_ACTION inbox_events "
        f"have no fixture builder: {sorted(missing)}. Add an entry to "
        f"KIND_BUILDERS so its rendered output is pinned."
    )


def test_cross_channel_parity_for_high_value_kinds(tmp_path: Path) -> None:
    """Acceptance #1 explicit clause — six highest-value kinds × 4 channels.

    Per plan.md F005 step 2 these are: gate_hit, breaker_tripped,
    volley_terminal (both variants), no_progress_classification, verdict_mismatch.
    All six are LIVE, so their snapshot must include all four channels.
    """
    high_value_names = (
        "gate_hit",
        "breaker_tripped",
        "volley_terminal_signed_off",
        "volley_terminal_blocked",
        "no_progress_classification",
        "verdict_mismatch",
    )
    expected_channels = {
        "discord_embed",
        "terminal_payload",
        "inbox_block",
        "dashboard_sidecar",
    }
    for name in high_value_names:
        snapshot = _build_snapshot(name, tmp_path / name)
        assert snapshot is not None, name
        actual_channels = set(snapshot["channels"].keys())
        assert actual_channels == expected_channels, (
            f"{name} missing channels for cross-channel parity: "
            f"{expected_channels - actual_channels}"
        )


# ─── sanitization sweep over fixture content (F005 acceptance #4) ───────────


def _walk_strings(node: Any):
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_strings(v)
    elif isinstance(node, str):
        yield node


def test_no_secret_shapes_in_any_pinned_snapshot() -> None:
    """F005 acceptance #4 — extend F004 raise-mode to fixture content.

    Walks every pinned snapshot file and asserts no string matches any of
    the 9 secret-shape regexes from ``sanitization_check.SECRET_REGEXES``.
    A leak in a snapshot fixture is a hard failure — fixtures are durable
    artifacts and an operator who runs the snapshot suite must not see
    secret-shaped content surface from frozen test data.
    """
    if not SNAPSHOTS_DIR.is_dir():
        pytest.skip(
            "snapshot fixtures missing — run `pytest --snapshot-update` first"
        )
    leaks: list[tuple[Path, str, str]] = []
    for path in sorted(SNAPSHOTS_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for value in _walk_strings(payload):
            for rx in SECRET_REGEXES:
                if rx.search(value):
                    leaks.append((path, rx.pattern, value[:80]))
    assert not leaks, (
        "secret-shape leaks in pinned snapshot fixtures: "
        + "; ".join(f"{p.name}: pattern={pat!r}, value={val!r}" for p, pat, val in leaks)
    )
