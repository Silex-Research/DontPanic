"""Plan 2026-06-02-001 F003 — renderer parity from the ActionItem spine.

Three operator surfaces render the SAME control-plane action contract
(:class:`operator_console.ActionItem`):

  * the **dashboard build JSON** (:func:`render_dashboard` /
    :func:`render_dashboard_json`),
  * the **CLI what-now/JSON** (:func:`render_cli_what_now`),
  * the **agent-brief managed actions block** (:func:`render_agent_brief_block`).

None of them constructs ActionItems independently: each takes a
``Sequence[ActionItem]`` produced upstream by the spine producers / projections
(provider functions, ``Guidance.to_action_items``,
``_rendered_to_action_item_dict``) and only renders it. This is the
"no surface computes action state independently" invariant the feature names.

The render boundary — :func:`prepare_for_render` — is single-sourced so the
three surfaces cannot drift:

  1. **Dedupe by ``dedupe_key``** (CP-D002 identity authority — never the
     id-prefix). The single response-level dashboard affordance carries a
     constant ``dedupe_key`` (``operations:dashboard-affordance``), so dedupe
     collapses it to ONE entry per response (D013 — the dashboard hint appears
     once, not per action item).
  2. **Scrub + brand-normalize at the boundary.** Every human-facing string is
     passed through :func:`state_projection.scrub_secrets` (D004/D011/D020 —
     secret-shaped substrings become ``[REDACTED]``) and
     :func:`event_copy.normalize_brand_drift` (D010 — legacy ``jarvis*`` brand
     strings become ``dontpanic`` equivalents). Source bodies are never edited;
     translation happens only here at the render boundary.

Because all three renderers go through :func:`prepare_for_render`, the same
action (matched by ``dedupe_key``) renders with identical title / band /
exact_command on every surface.
"""
from __future__ import annotations

import datetime as _dt
import json
from collections.abc import Iterable, Sequence
from typing import Any

from dontpanic_orchestrate import event_copy as _event_copy
from dontpanic_orchestrate import operator_console as _oc
from dontpanic_orchestrate import state_projection as _sp

# The human-facing string fields a renderer shows. Each is scrubbed for
# secret shapes and brand-normalized at the boundary. Non-string / structural
# fields (id, source, band, automatable, audience, reversible, …) pass through
# unchanged.
_RENDER_STRING_FIELDS: tuple[str, ...] = (
    "title",
    "detail",
    "exact_command",
    "human_required_reason",
    "plain_consequence",
    "evidence_uri",
)


def scrub_render_text(value: str | None) -> str | None:
    """Apply the two boundary transforms a rendered string must pass through:
    secret-shape scrubbing (D004/D011/D020) then brand-drift normalization
    (D010). ``None`` passes through unchanged so callers need not guard."""
    return _event_copy.normalize_brand_drift(_sp.scrub_secrets(value))


def _dedupe_by_key(items: Iterable[_oc.ActionItem]) -> tuple[_oc.ActionItem, ...]:
    """Collapse items sharing a ``dedupe_key`` to one (last writer wins,
    CP-D002), then apply the deterministic spine ordering so every surface
    sees the same item set in the same order."""
    merged: dict[str, _oc.ActionItem] = {}
    for item in items:
        merged[item.dedupe_key] = item
    return _oc._sort(merged.values())


def action_view(item: _oc.ActionItem) -> dict[str, Any]:
    """Project one ActionItem to its render-ready dict.

    The shape is the full F001 ``ActionItem.to_dict()`` envelope (so the
    dashboard JSON schema is unchanged) with every human-facing string scrubbed
    + brand-normalized at the boundary.
    """
    d = item.to_dict()
    for field in _RENDER_STRING_FIELDS:
        d[field] = scrub_render_text(d.get(field))
    return d


def prepare_for_render(
    items: Sequence[_oc.ActionItem] | Iterable[_oc.ActionItem],
) -> list[dict[str, Any]]:
    """The single render boundary: dedupe by ``dedupe_key`` (D013), then scrub +
    brand-normalize (D004/D010). Returns render-ready dicts in deterministic
    order. All three surface renderers go through this so they cannot drift."""
    return [action_view(it) for it in _dedupe_by_key(items)]


def _is_dashboard_hint(view: dict[str, Any]) -> bool:
    """True when a render view IS the single response-level dashboard affordance
    (D013). Identified by its stable ``dedupe_key`` so the CLI text renderer can
    emit it once as a trailing hint rather than as an ordinary action row."""
    from dontpanic_orchestrate import operations_guidance as _og

    return view.get("dedupe_key") == _og.DASHBOARD_AFFORDANCE_ITEM_ID


# ── surface 1: dashboard build JSON ──────────────────────────────────────────


def render_dashboard(
    items: Sequence[_oc.ActionItem] | Iterable[_oc.ActionItem],
    *,
    captured_at: _dt.datetime | None = None,
) -> dict[str, Any]:
    """Render the dashboard build JSON envelope from the spine.

    Same compact F001 schema the dashboard already consumes
    (``schema_version`` / ``captured_at`` / ``items``), but built through the
    shared scrub+dedupe boundary. The post-scrub
    :func:`operator_console._assert_no_secret_shapes` is belt-and-suspenders:
    after :func:`prepare_for_render` it must always pass, so a raise here means
    a non-string field carried a secret shape — a real bug worth surfacing.
    """
    payload = {
        "schema_version": _oc.SCHEMA_VERSION,
        "captured_at": _oc._now_iso(captured_at),
        "items": prepare_for_render(items),
    }
    _oc._assert_no_secret_shapes(payload)
    return payload


def render_dashboard_json(
    items: Sequence[_oc.ActionItem] | Iterable[_oc.ActionItem],
    *,
    captured_at: _dt.datetime | None = None,
) -> str:
    """String form of :func:`render_dashboard` — byte-stable for identical
    inputs (sorted keys, fixed indent)."""
    return (
        json.dumps(
            render_dashboard(items, captured_at=captured_at),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )


# ── surface 2: CLI what-now / JSON ───────────────────────────────────────────


def render_cli_what_now(
    items: Sequence[_oc.ActionItem] | Iterable[_oc.ActionItem],
    *,
    fmt: str = "text",
    captured_at: _dt.datetime | None = None,
) -> str:
    """Render the CLI ``what-now`` surface from the spine.

    ``fmt="json"`` emits the identical dashboard envelope (so the human CLI and
    the machine dashboard agree byte-for-byte on the item set). ``fmt="text"``
    prints one row per action in band order, with the single dashboard hint
    appended once at the end (D013), never repeated per item.
    """
    if fmt == "json":
        return render_dashboard_json(items, captured_at=captured_at)

    views = prepare_for_render(items)
    lines: list[str] = ["what-now:"]
    if not views:
        lines.append("  No actions — proceed with the normal workflow.")
        return "\n".join(lines) + "\n"

    actions = [v for v in views if not _is_dashboard_hint(v)]
    for i, v in enumerate(actions, 1):
        auto = " [auto]" if v["automatable"] else ""
        lines.append(f"  {i}. {v['title']}  (band: {v['band']}){auto}")
        if v["exact_command"]:
            lines.append(f"     $ {v['exact_command']}")
        elif v["human_required_reason"]:
            lines.append(f"     (human action required: {v['human_required_reason']})")

    hints = [v for v in views if _is_dashboard_hint(v)]
    if hints:
        hint = hints[0]
        lines.append("")
        lines.append(f"  Dashboard: {hint['title']}")
        if hint["exact_command"]:
            lines.append(f"     $ {hint['exact_command']}")
    return "\n".join(lines) + "\n"


# ── surface 3: agent-brief managed actions block ─────────────────────────────


# Marker name the onboarding/agent-brief surface uses for the live actions
# block. Distinct from the byte-stable operating-brief block so the two never
# collide; the actions block is regenerated per render and is NOT part of the
# deterministic onboarding hash.
ACTIONS_BLOCK_NAME = "dontpanic-actions"


def render_agent_brief_block(
    items: Sequence[_oc.ActionItem] | Iterable[_oc.ActionItem],
) -> str:
    """Render the agent-brief managed actions block from the spine.

    A compact Markdown section an interactive/onboarding agent reads to see the
    current operator actions — the same dedupe_key-keyed item set the dashboard
    and CLI render, scrubbed at the same boundary. One line per action in band
    order; the single dashboard hint (constant dedupe_key) renders once.
    """
    views = prepare_for_render(items)
    lines: list[str] = ["# DontPanic — current actions", ""]
    if not views:
        lines.append("No actions pending — operate via the canonical workflow.")
        return "\n".join(lines) + "\n"
    for v in views:
        cmd = f" — `{v['exact_command']}`" if v["exact_command"] else ""
        lines.append(f"- [{v['band']}] {v['title']}{cmd}")
    return "\n".join(lines) + "\n"


__all__ = [
    "ACTIONS_BLOCK_NAME",
    "action_view",
    "prepare_for_render",
    "render_agent_brief_block",
    "render_cli_what_now",
    "render_dashboard",
    "render_dashboard_json",
    "scrub_render_text",
]
