"""Plan 2026-06-02-001 F003 — renderer parity acceptance.

One fixed ActionItem set is fed through all THREE surface renderers
(:mod:`action_renderers`):

  * the dashboard build JSON (:func:`render_dashboard`),
  * the CLI what-now / JSON (:func:`render_cli_what_now`),
  * the agent-brief managed actions block (:func:`render_agent_brief_block`).

The acceptance clauses asserted here:

  (a) the same action (matched by ``dedupe_key``) appears in each surface with
      consistent title / band / exact_command;
  (b) it is deduped ONCE — two items sharing a ``dedupe_key`` collapse, and the
      single response-level dashboard hint renders once per response (D013);
  (c) secret-shaped substrings are scrubbed at the render boundary on every
      surface, and legacy brand strings are normalized (D004/D010);
  (d) no renderer constructs ActionItems independently of the spine — the module
      never mints an ``ActionItem``, it only renders the ones it is handed.

A small live-wiring check proves the dashboard cache (``operator_console.write_cache``)
actually routes through the same scrub boundary.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import json
from pathlib import Path

import pytest

from dontpanic_orchestrate import action_renderers as ar
from dontpanic_orchestrate import operations_guidance as og
from dontpanic_orchestrate import operator_console as oc

_NOW = _dt.datetime(2026, 6, 3, 12, 0, 0, tzinfo=_dt.timezone.utc)
_ISO = "2026-06-03T12:00:00Z"

# A canonical GitHub-PAT-shaped secret (ghp_ + 36 base62 chars) — matches the
# shared SECRET_REGEXES, so the render boundary must scrub it to [REDACTED].
_SECRET = "ghp_" + "a" * 30 + "b1c2d3"

_GATE_KEY = "gate:p1:pre_merge"
_APPROVE_CMD = "dontpanic approve p1 pre_merge"


def _gate_item(item_id: str, title: str) -> oc.ActionItem:
    return oc.ActionItem(
        id=item_id,
        source=oc.SOURCE_GATE,
        band=oc.Band.NEEDS_ACTION,
        title=title,
        # Carries BOTH a secret shape (must scrub) and a legacy brand string
        # `jarvis approve` (must normalize) so one detail exercises both boundary
        # transforms.
        detail=f"token {_SECRET} leaked; then run jarvis approve cleanup",
        exact_command=_APPROVE_CMD,
        automatable=False,
        human_required_reason="gate approval",
        evidence_uri=None,
        updated_at=_ISO,
        dedupe_key=_GATE_KEY,
        reversible=False,
        plain_consequence="Approves the pre_merge gate.",
    )


def _fixed_item_set() -> list[oc.ActionItem]:
    """The fixed ActionItem set fed through all three renderers.

    Includes a deliberate duplicate (same ``dedupe_key`` as the gate item, id
    + title differ) to prove dedup, an architecture info item, and the single
    response-level dashboard affordance (constant ``dedupe_key`` → renders once,
    D013)."""
    gate = _gate_item(_GATE_KEY, f"Approve gate — secret {_SECRET}")
    # Same dedupe_key, DIFFERENT id/title → must collapse to one. Ordered BEFORE
    # the canonical gate so last-writer-wins keeps `gate`.
    gate_dup = dataclasses.replace(
        gate, id="supervisor:gate_hit:p1", title=f"DUPLICATE {_SECRET}"
    )
    arch = oc.ActionItem(
        id="architecture:stale",
        source=oc.SOURCE_ARCHITECTURE,
        band=oc.Band.INFO,
        title="Architecture snapshot stale",
        detail=None,
        exact_command="dontpanic architecture regen",
        automatable=True,
        human_required_reason=None,
        evidence_uri=None,
        updated_at=_ISO,
        dedupe_key="architecture:stale",
        reversible=True,
        plain_consequence="Regenerates the architecture snapshot.",
    )
    affordance = og.DashboardAffordance(is_running=False).to_action_item(updated_at=_ISO)
    return [gate_dup, gate, arch, affordance]


def _count_key(views: list[dict], key: str) -> int:
    return sum(1 for v in views if v["dedupe_key"] == key)


# ─── (a)+(b) same action, consistent fields, deduped once ───────────────────


def test_same_action_renders_consistently_across_surfaces() -> None:
    items = _fixed_item_set()

    dash = ar.render_dashboard(items, captured_at=_NOW)
    cli_json = json.loads(ar.render_cli_what_now(items, fmt="json", captured_at=_NOW))
    cli_text = ar.render_cli_what_now(items, fmt="text", captured_at=_NOW)
    brief = ar.render_agent_brief_block(items)

    # Dashboard build JSON and CLI/JSON render the IDENTICAL spine item list.
    assert dash["items"] == cli_json["items"]

    # (b) deduped once: the gate dedupe_key collapses the duplicate to one entry.
    assert _count_key(dash["items"], _GATE_KEY) == 1
    # D013: the single dashboard affordance appears once per response.
    assert _count_key(dash["items"], og.DASHBOARD_AFFORDANCE_ITEM_ID) == 1

    # (a) the gate action carries consistent title / band / exact_command.
    gate_view = next(v for v in dash["items"] if v["dedupe_key"] == _GATE_KEY)
    assert gate_view["band"] == "needs_action"
    assert gate_view["exact_command"] == _APPROVE_CMD
    # Title was scrubbed at the boundary (secret → [REDACTED]) — same scrubbed
    # title on every surface.
    assert gate_view["title"] == "Approve gate — secret [REDACTED]"

    # The two text surfaces carry the SAME scrubbed title + band + exact_command
    # for the matched action — FULL parity by dedupe_key across all three
    # renderers (codex F003 i0 finding: band parity, not just title/command).
    # The band renders in each surface's own idiom: the dashboard JSON as a
    # field (asserted above), the CLI text as `(band: …)`, the agent brief as
    # `[…]`.
    band = gate_view["band"]
    assert f"(band: {band})" in cli_text
    assert f"[{band}]" in brief
    for surface in (cli_text, brief):
        assert gate_view["title"] in surface
        assert gate_view["exact_command"] in surface


# ─── (c) secrets scrubbed + brand normalized at the boundary, every surface ──


def test_secret_scrubbed_and_brand_normalized_on_every_surface() -> None:
    items = _fixed_item_set()

    dash_str = json.dumps(ar.render_dashboard(items, captured_at=_NOW))
    cli_json_str = ar.render_cli_what_now(items, fmt="json", captured_at=_NOW)
    cli_text = ar.render_cli_what_now(items, fmt="text", captured_at=_NOW)
    brief = ar.render_agent_brief_block(items)

    for surface in (dash_str, cli_json_str, cli_text, brief):
        assert _SECRET not in surface, "secret shape leaked past the render boundary"
        assert "[REDACTED]" in surface, "secret was not scrubbed at the boundary"

    # Brand normalization (D010): the gate detail's `jarvis approve` is rewritten
    # to `dontpanic approve` at the boundary; source bodies are untouched.
    gate_view = next(
        v
        for v in ar.render_dashboard(items)["items"]
        if v["dedupe_key"] == _GATE_KEY
    )
    assert "jarvis approve" not in gate_view["detail"]
    assert "dontpanic approve" in gate_view["detail"]


def test_dedupe_collapses_to_one_regardless_of_input_order() -> None:
    # Order independence: whichever duplicate is last wins, but the COUNT is
    # always one — the boundary keys on dedupe_key, never on id or list order.
    base = _fixed_item_set()
    forward = ar.prepare_for_render(base)
    reversed_views = ar.prepare_for_render(list(reversed(base)))
    assert _count_key(forward, _GATE_KEY) == 1
    assert _count_key(reversed_views, _GATE_KEY) == 1
    # Same distinct dedupe_key set both ways.
    assert {v["dedupe_key"] for v in forward} == {v["dedupe_key"] for v in reversed_views}


def test_empty_input_is_a_clean_no_op_on_every_surface() -> None:
    assert ar.render_dashboard([])["items"] == []
    assert json.loads(ar.render_cli_what_now([], fmt="json"))["items"] == []
    assert "No actions" in ar.render_cli_what_now([], fmt="text")
    assert "No actions pending" in ar.render_agent_brief_block([])


# ─── (d) no renderer constructs ActionItems independently of the spine ──────


def test_renderers_never_construct_action_items() -> None:
    # Structural invariant: the renderer module only RENDERS the items it is
    # handed — it never mints an ActionItem of its own. (The spine producers /
    # projections are the sole constructors; the renderers are pure consumers.)
    src = Path(ar.__file__).read_text(encoding="utf-8")
    assert "ActionItem(" not in src, (
        "action_renderers must not construct ActionItems — it renders the spine"
    )


def test_renderers_accept_the_spine_contract_directly() -> None:
    # Each renderer consumes a Sequence[ActionItem] produced upstream by a real
    # spine projection (Guidance.to_action_items) — no independent action state.
    guidance = og.build_guidance(
        "p1",
        feature_id="F001",
        signoff=og.SignoffState(
            feature_id="F001", verdict="signed_off", pre_merge_cleared=True
        ),
    )
    items = guidance.to_action_items(updated_at=_ISO)
    assert items, "fixture guidance should project at least one ActionItem"
    # All three render without error from the projected items.
    dash = ar.render_dashboard(items)
    cli = ar.render_cli_what_now(items, fmt="json")
    brief = ar.render_agent_brief_block(items)
    assert dash["items"]
    assert json.loads(cli)["items"] == dash["items"]
    assert brief.strip()


# ─── live wiring: the dashboard cache routes through the scrub boundary ─────


def test_dashboard_build_writes_what_now_through_the_render_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The REAL ``dashboard.build`` write path of ``out_dir/what-now.json`` must
    route through the shared render boundary — not ``operator_console.render_json``.

    codex F003 i1 (high): ``dashboard.py`` previously wrote what-now.json via
    ``operator_console.render_json(merged_items)``, which only serialized
    ``ActionItem.to_dict()`` and never deduped / scrubbed / brand-normalized — so
    the served dashboard state diverged from CLI/JSON and the agent brief. This
    test feeds the same fixed ActionItem set through the actual build and asserts
    the written file is byte-identical to the CLI/JSON surface and carries the
    same scrubbed, deduped, brand-normalized item set as text + agent brief.
    """
    from dontpanic_orchestrate import dashboard as _dashboard

    items = _fixed_item_set()
    # Inject the fixed set at the spine seam the build reads from, and make the
    # sidecar merge a no-op so the written file reflects exactly this set (the
    # boundary transform under test, not sidecar provenance).
    monkeypatch.setattr(_dashboard, "_gather_action_items", lambda **_: list(items))
    monkeypatch.setattr(oc, "merge_with_event_sidecar", lambda its: list(its))

    out_dir = tmp_path / "dash"
    out_dir.mkdir()
    report = _dashboard.build(
        out_dir=out_dir,
        write_what_now_cache=True,
        write_capabilities_cache=False,
        check_reconcile=False,
        check_architecture=False,
        what_now_cache_path_override=tmp_path / "home-what-now.json",
    )

    written = (out_dir / "what-now.json").read_text(encoding="utf-8")
    payload = json.loads(written)
    # 1. The written build JSON is byte-identical to the CLI/JSON surface.
    #    build() stamps captured_at from live time; pin the comparison render to
    #    the written file's own captured_at so the assertion tests boundary
    #    parity, not whether both calls landed in the same wall-clock second.
    built_captured_at = _dt.datetime.strptime(
        payload["captured_at"], "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=_dt.timezone.utc)
    assert written == ar.render_cli_what_now(
        items, fmt="json", captured_at=built_captured_at
    )
    # 2. Secret scrubbed + duplicate collapsed in the ACTUAL written file.
    assert _SECRET not in written
    assert "[REDACTED]" in written
    assert _count_key(payload["items"], _GATE_KEY) == 1
    # 3. D013: single dashboard affordance once in the written response.
    from dontpanic_orchestrate import operations_guidance as _og

    assert _count_key(payload["items"], _og.DASHBOARD_AFFORDANCE_ITEM_ID) == 1
    # 4. Cross-surface parity by dedupe_key: the same gate action with the same
    #    scrubbed title + band + exact_command appears in CLI text + agent brief.
    gate_view = next(v for v in payload["items"] if v["dedupe_key"] == _GATE_KEY)
    cli_text = ar.render_cli_what_now(items, fmt="text", captured_at=_NOW)
    brief = ar.render_agent_brief_block(items)
    for surface in (cli_text, brief):
        assert gate_view["title"] in surface
        assert gate_view["exact_command"] in surface
        assert _SECRET not in surface
    assert "what-now cache skipped" not in " ".join(report.warnings)


def test_write_cache_scrubs_at_the_render_boundary(tmp_path: Path) -> None:
    secret_item = _gate_item(_GATE_KEY, f"gate {_SECRET}")
    cache = tmp_path / "what-now.json"
    # write_cache previously raised on a secret shape (durable cache invariant);
    # under F003 it routes through the shared scrub boundary, so the secret is
    # redacted in the written cache rather than leaking or crashing the build.
    oc.write_cache([secret_item], path=cache, captured_at=_NOW, merge_event_sidecar=False)
    written = cache.read_text(encoding="utf-8")
    assert _SECRET not in written
    assert "[REDACTED]" in written
    payload = json.loads(written)
    assert payload["schema_version"] == oc.SCHEMA_VERSION
    assert _count_key(payload["items"], _GATE_KEY) == 1


# ─── (c′) CLI-LEVEL parity: the real `what-now --format json` code path ──────
# codex audit i2 (high/security + medium/test_coverage): the helper-renderer
# parity test above does NOT exercise cli._what_now_main, whose JSON assembly
# previously emitted guidance.to_dict() (unsanitized) and leaked secrets/brands.
# This test drives the real CLI entrypoint end-to-end.


class _StubGuidance:
    """Minimal stand-in for operations_guidance.Guidance: only to_action_items()
    is consumed by the fixed CLI JSON path. to_dict() intentionally still carries
    the secret so this test would FAIL against the old leaky `guidance.to_dict()`
    assembly (regression guard)."""

    def to_action_items(self):
        return [_gate_item(_GATE_KEY, f"Approve gate — secret {_SECRET}")]

    def to_dict(self):
        return {"recommendation": f"legacy leak {_SECRET}; run jarvis approve x"}


def test_cli_what_now_json_path_scrubs_secrets_and_brands(monkeypatch, capsys) -> None:
    from dontpanic_orchestrate import cli, operations_guidance

    monkeypatch.setattr(cli, "_resolve_plan_dir", lambda _p: Path("/tmp/does-not-matter"))

    class _LP:
        plan_id = "p1"

    monkeypatch.setattr(cli.plan_loader, "load", lambda _d: _LP())
    monkeypatch.setattr(
        operations_guidance, "collect_state", lambda *a, **k: _StubGuidance()
    )

    rc = cli._what_now_main(["p1", "--feature", "F001", "--format", "json"])
    assert rc == 0
    out = capsys.readouterr().out

    # (c′) the real CLI JSON surface scrubs the secret shape and normalizes the
    # legacy brand on EVERY field — no leak from the formerly-unsanitized
    # guidance.to_dict() (which leaked via the top-level recommendation string).
    assert _SECRET not in out
    assert "[REDACTED]" in out
    assert "jarvis" not in out.lower()
    payload = json.loads(out)
    # Back-compat: the legacy guidance shape is preserved (recommendation kept)
    # but scrubbed in place — the fix sanitizes, it does not drop the contract.
    assert "recommendation" in payload
    assert _SECRET not in payload["recommendation"]
    # The canonical spine list is appended and carries the gate action.
    assert any(it["dedupe_key"] == _GATE_KEY for it in payload["action_items"])
