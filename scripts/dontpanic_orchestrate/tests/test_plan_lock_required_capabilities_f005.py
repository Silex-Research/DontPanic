"""Plan 2026-05-21-001 F005 — advisory required-capabilities matches/skips tests.

Run: PYTHONPATH=scripts pytest \
  scripts/dontpanic_orchestrate/tests/test_plan_lock_required_capabilities_f005.py -q

Acceptance covered:
  (a) external_refs → Linear: matches[] entry with source='external_ref',
      setup_required, setup_doc, owner_boundary, and status populated.
  (b) surfaces/web → firebase-dashboard advisory: matches[] entry with
      source='surface' even when plan declares no external_refs.
  (c) No capability matches → sidecar emits when external_refs present,
      matches[] is empty when surfaces/skills do not bind to any manifest.
  (d) Writer failure never blocks lock — exercised end-to-end via
      ``_plan_lock_main`` (return code 0, status flipped, advisory
      warning printed). Wrapper re-raise is pinned separately so the
      lock-flow catch stays the single source of truth.
  (e) Pure function: infer_advisory_capabilities() returns ([], []) for an
      empty plan.
  (f) Status mapping uses the F005 vocabulary
      (unknown|verified|missing_config|not_registered).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import capabilities as cap  # noqa: E402
from dontpanic_orchestrate import capabilities_lock_sidecar as sidecar  # noqa: E402
from dontpanic_orchestrate import external_refs_sync as ers  # noqa: E402
from dontpanic_orchestrate.capabilities_status import CapabilityStatus  # noqa: E402
from dontpanic_orchestrate.integrations.pm_tool_models import (  # noqa: E402
    PMIssue,
    PMStatus,
)
from dontpanic_orchestrate.integrations.pm_tool_sync import (  # noqa: E402
    ExternalSyncRecord,
    make_pushed_record,
)
from dontpanic_orchestrate.skill_applicability import (  # noqa: E402
    ApplicabilityReport,
    ExternalCli,
    Match,
)

REPO_ROOT = HERE.parents[3]


# ───────────────────────────  helpers / fakes  ───────────────────────────


class _FakeHook:
    def __init__(self, scheme: str = "linear", service: str = "linear") -> None:
        self.service_name = service
        self.uri_scheme = scheme

    def read_issue(self, uri: str) -> PMIssue:
        return PMIssue(
            id=uri.rsplit("/", 1)[-1],
            project_id="TEAM-1",
            title="Stub",
            status=PMStatus.IN_PROGRESS,
            uri=uri,
        )

    def push_status(
        self, uri: str, new_status: PMStatus, dry_run: bool = False
    ) -> ExternalSyncRecord:
        return make_pushed_record(
            ref_uri=uri,
            kind="pm_issue",
            intended_status=new_status,
            response={"ok": True},
        )


def _write_fixture_plan(
    plan_dir: Path,
    *,
    surfaces_yaml: str = "",
    external_refs_yaml: str = "",
    requires_capabilities_yaml: str = "",
    plan_id: str = "2026-05-21-001-feat-fixture-f005",
) -> None:
    """Write a draft plan.md fixture with optional frontmatter blocks."""

    plan_dir.mkdir(parents=True, exist_ok=True)
    body = (
        "---\n"
        f"id: {plan_id}\n"
        "title: F005 advisory required-capabilities fixture\n"
        "type: feat\n"
        "tier: local\n"
        "status: draft\n"
        "date: '2026-05-21'\n"
        "description: Fixture plan for F005 sidecar tests with ample length to satisfy schema.\n"
    )
    if surfaces_yaml:
        body += "surfaces:\n" + surfaces_yaml
    if external_refs_yaml:
        body += "external_refs:\n" + external_refs_yaml
    if requires_capabilities_yaml:
        body += "requires_capabilities:\n" + requires_capabilities_yaml
    body += "---\n\n# Fixture\n\n## Target\n\n```yaml\ntarget_env: dev\ntarget_project: none\n```\n"
    (plan_dir / "plan.md").write_text(body, encoding="utf-8")


def _resolver_with_linear() -> ers.AdapterResolver:
    resolver = ers.AdapterResolver()
    resolver.register(_FakeHook(), capability_id="linear")
    return resolver


@pytest.fixture
def capability_index() -> cap.CapabilityIndex:
    return cap.load_capabilities(REPO_ROOT)


@pytest.fixture(autouse=True)
def _isolate_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the F002 cache constant at a tmp path so tests never hit the
    operator's real ``~/.dontpanic/capabilities-status.json``."""

    isolated = tmp_path / "capabilities-status.json"
    monkeypatch.setattr(sidecar, "DEFAULT_CACHE_PATH", isolated)
    return isolated


# ───────────────────────────  pure inference  ─────────────────────────────


def test_infer_advisory_empty_returns_empty(
    capability_index: cap.CapabilityIndex,
) -> None:
    """(e) Pure function: empty inputs → empty matches and skips."""

    matches, skips = sidecar.infer_advisory_capabilities(
        surfaces=[],
        external_refs=[],
        applicability_report=None,
        capability_index=capability_index,
    )
    assert matches == []
    assert skips == []


def test_infer_advisory_external_ref_linear_uses_singular_source(
    capability_index: cap.CapabilityIndex,
) -> None:
    """(a) external_refs → Linear; source is the singular F005 vocab
    'external_ref' (not the F003 plural 'external_refs')."""

    resolver = _resolver_with_linear()
    refs = [
        {"kind": "pm_issue", "uri": "linear://issue/ABC-1", "sync": "none"},
    ]
    matches, skips = sidecar.infer_advisory_capabilities(
        surfaces=[],
        external_refs=refs,
        applicability_report=None,
        capability_index=capability_index,
        resolver=resolver,
    )
    assert skips == []
    assert len(matches) == 1
    m = matches[0]
    assert m["capability_id"] == "linear"
    assert m["source"] == "external_ref"
    assert m["setup_required"] is True
    assert "USE_CASES.md" in m["setup_doc"]
    assert m["external_ref_uris"] == ["linear://issue/ABC-1"]
    # Owner boundary echoes the manifest, not the F003 cache view.
    assert "dontpanic_core" in m["owner_boundary"]
    assert "adapter" in m["owner_boundary"]
    assert "operator" in m["owner_boundary"]
    # Status is one of the F005 vocab values.
    assert m["status"] in {"unknown", "verified", "missing_config", "not_registered"}


def test_infer_advisory_surface_web_yields_firebase_dashboard(
    capability_index: cap.CapabilityIndex,
) -> None:
    """(b) surfaces/web → firebase-dashboard advisory with source='surface'."""

    matches, skips = sidecar.infer_advisory_capabilities(
        surfaces=["web"],
        external_refs=[],
        applicability_report=None,
        capability_index=capability_index,
    )
    assert skips == []
    ids = {m["capability_id"]: m for m in matches}
    assert "firebase-dashboard" in ids
    fb = ids["firebase-dashboard"]
    assert fb["source"] == "surface"
    assert fb["surface_names"] == ["web"]
    assert fb["setup_required"] is True
    setup_doc = fb["setup_doc"]
    assert setup_doc.endswith(".md")
    assert not setup_doc.startswith("/")
    assert (HERE.parents[3] / setup_doc).is_file()


def test_infer_advisory_external_ref_outranks_surface(
    capability_index: cap.CapabilityIndex,
) -> None:
    """Precedence: an explicit external_ref binding beats a surface hint
    when both target the same capability_id. The single-valued ``source``
    field reflects that — no multi-source widening per F005 spec."""

    resolver = _resolver_with_linear()
    refs = [
        {"kind": "pm_issue", "uri": "linear://issue/ABC-1", "sync": "none"},
    ]
    # Construct a surface that would *also* match if linear had a surface
    # hint — none exists in the table today, but the precedence rule is
    # the same. We assert linear stays source='external_ref' regardless.
    matches, _ = sidecar.infer_advisory_capabilities(
        surfaces=["web"],
        external_refs=refs,
        applicability_report=None,
        capability_index=capability_index,
        resolver=resolver,
    )
    by_id = {m["capability_id"]: m for m in matches}
    assert by_id["linear"]["source"] == "external_ref"


def test_infer_advisory_skill_command_binds_to_capability(
    capability_index: cap.CapabilityIndex,
) -> None:
    """Skill applicability matches with external_cli.command='claude' bind
    to ``agent-claude-cli`` (which lists 'claude' in requires.commands)."""

    report = ApplicabilityReport(
        schema_version="1.0",
        plan_id="fixture",
        plan_surfaces=[],
        plan_goal_type=None,
        matches=[
            Match(
                skill_name="some-claude-skill",
                matched_surfaces=["infra"],
                matched_goal_types=[],
                rationale="matched",
                provenance="external",
                external_cli=ExternalCli(
                    provider="anthropic",
                    name="Claude",
                    command="claude",
                    version_pin="any",
                ),
            )
        ],
        skipped=[],
    )
    matches, _ = sidecar.infer_advisory_capabilities(
        surfaces=[],
        external_refs=[],
        applicability_report=report,
        capability_index=capability_index,
    )
    ids = {m["capability_id"]: m for m in matches}
    assert "agent-claude-cli" in ids
    assert ids["agent-claude-cli"]["source"] == "skill"
    assert ids["agent-claude-cli"]["skill_names"] == ["some-claude-skill"]


def test_infer_advisory_status_verified_from_ready_cache(
    capability_index: cap.CapabilityIndex,
) -> None:
    """(f) ready status → ``verified`` in F005 vocabulary."""

    status_data = {
        "linear": {"status": CapabilityStatus.READY.value},
    }
    resolver = _resolver_with_linear()
    matches, _ = sidecar.infer_advisory_capabilities(
        surfaces=[],
        external_refs=[
            {"kind": "pm_issue", "uri": "linear://issue/X-1", "sync": "none"},
        ],
        applicability_report=None,
        capability_index=capability_index,
        status_data=status_data,
        resolver=resolver,
    )
    assert matches[0]["status"] == "verified"


def test_infer_advisory_status_missing_config_from_needs_setup(
    capability_index: cap.CapabilityIndex,
) -> None:
    """(f) needs_setup status → ``missing_config`` in F005 vocabulary."""

    status_data = {
        "firebase-dashboard": {"status": CapabilityStatus.NEEDS_SETUP.value},
    }
    matches, _ = sidecar.infer_advisory_capabilities(
        surfaces=["web"],
        external_refs=[],
        applicability_report=None,
        capability_index=capability_index,
        status_data=status_data,
    )
    fb = {m["capability_id"]: m for m in matches}["firebase-dashboard"]
    assert fb["status"] == "missing_config"


def test_infer_advisory_status_not_registered_when_adapter_absent(
    capability_index: cap.CapabilityIndex,
) -> None:
    """(f) service_adapter / external_adapter manifest with no registered
    adapter → status='not_registered'. linear is a service_adapter."""

    # Resolver is empty — no adapter registered with capability_id=linear.
    empty_resolver = ers.AdapterResolver()
    # Force an external_ref with explicit capability_id so the resolver's
    # URI-scheme lookup doesn't matter — we want the not_registered probe.
    refs = [
        {
            "kind": "pm_issue",
            "uri": "linear://issue/X-1",
            "sync": "none",
            "capability_id": "linear",
        }
    ]
    matches, _ = sidecar.infer_advisory_capabilities(
        surfaces=[],
        external_refs=refs,
        applicability_report=None,
        capability_index=capability_index,
        status_data={"linear": {"status": CapabilityStatus.READY.value}},
        resolver=empty_resolver,
    )
    # not_registered overrides the ready status — adapter absence beats
    # readiness pipeline for adapter-kind capabilities.
    assert matches[0]["status"] == "not_registered"


# ───────────────────────────  emit_required_capabilities  ─────────────────


def test_emit_with_surface_only_creates_sidecar(
    tmp_path: Path,
    capability_index: cap.CapabilityIndex,
    _isolate_cache: Path,
) -> None:
    """(b) Plan with surfaces only (no external_refs/requires_capabilities)
    still emits a sidecar when a surface hint yields a match."""

    plan_dir = tmp_path / "plan"
    _write_fixture_plan(plan_dir, surfaces_yaml="  - web\n")
    out = sidecar.emit_required_capabilities(
        plan_dir, capability_index=capability_index, resolver=ers.AdapterResolver()
    )
    assert out is not None and out.is_file()
    payload = json.loads(out.read_text())
    assert "matches" in payload and "skips" in payload
    ids = {m["capability_id"]: m for m in payload["matches"]}
    assert "firebase-dashboard" in ids
    assert ids["firebase-dashboard"]["source"] == "surface"
    assert ids["firebase-dashboard"]["surface_names"] == ["web"]


def test_emit_with_no_inputs_returns_none(
    tmp_path: Path, capability_index: cap.CapabilityIndex
) -> None:
    """(c) No surfaces, no external_refs, no requires_capabilities, no
    applicability report → no sidecar, no I/O."""

    plan_dir = tmp_path / "plan"
    _write_fixture_plan(plan_dir)
    out = sidecar.emit_required_capabilities(
        plan_dir,
        capability_index=capability_index,
        resolver=ers.AdapterResolver(),
    )
    assert out is None
    assert not (plan_dir / sidecar.SIDECAR_RELPATH).exists()


def test_emit_external_refs_linear_includes_matches_and_skips(
    tmp_path: Path, capability_index: cap.CapabilityIndex, _isolate_cache: Path
) -> None:
    """(a) external_refs Linear scheme + registered adapter → sidecar
    contains both required_capabilities[] (F003) and matches[] (F005)."""

    plan_dir = tmp_path / "plan"
    _write_fixture_plan(
        plan_dir,
        external_refs_yaml=("  - kind: pm_issue\n    uri: linear://issue/ABC-1\n    sync: none\n"),
    )
    resolver = _resolver_with_linear()
    out = sidecar.emit_required_capabilities(
        plan_dir, capability_index=capability_index, resolver=resolver
    )
    assert out is not None
    payload = json.loads(out.read_text())
    # F003 view still present.
    assert payload["required_capabilities"][0]["capability_id"] == "linear"
    # F005 view also present.
    assert isinstance(payload["matches"], list)
    assert isinstance(payload["skips"], list)
    linear_match = next(m for m in payload["matches"] if m["capability_id"] == "linear")
    assert linear_match["source"] == "external_ref"
    assert linear_match["setup_required"] is True
    assert "USE_CASES.md" in linear_match["setup_doc"]


def test_emit_sidecar_schema_includes_f005_top_level_keys(
    tmp_path: Path, capability_index: cap.CapabilityIndex, _isolate_cache: Path
) -> None:
    """F005 step 4 — sidecar JSON includes schema_version, plan_id,
    generated_at, matches[], and skips[]."""

    plan_dir = tmp_path / "plan"
    _write_fixture_plan(
        plan_dir,
        surfaces_yaml="  - web\n",
    )
    out = sidecar.emit_required_capabilities(
        plan_dir, capability_index=capability_index, resolver=ers.AdapterResolver()
    )
    assert out is not None
    payload = json.loads(out.read_text())
    for key in ("schema_version", "plan_id", "generated_at", "matches", "skips"):
        assert key in payload, f"missing top-level key {key!r} in sidecar"
    assert payload["plan_id"] == "2026-05-21-001-feat-fixture-f005"


def test_lock_flow_swallows_writer_failure_and_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    _isolate_cache: Path,
) -> None:
    """(d) Lock-flow proof: when the F005 sidecar emitter raises, the
    outer ``_plan_lock_main`` try/except swallows the exception so the
    lock still flips plan.md status from draft → active. Exercises the
    actual CLI lock path (not just the wrapper) per F005 acceptance #3
    — sidecar emission never blocks lock."""

    from dontpanic_orchestrate import cli

    plan_dir = tmp_path / "plan"
    _write_fixture_plan(plan_dir, surfaces_yaml="  - web\n")

    def _boom(*_args, **_kwargs):
        raise RuntimeError("synthetic writer failure")

    monkeypatch.setattr(
        "dontpanic_orchestrate.capabilities_lock_sidecar.emit_required_capabilities",
        _boom,
    )

    rc = cli._plan_lock_main([str(plan_dir)])

    # Lock returns 0 (success) despite the emitter raising.
    assert rc == 0, "lock must succeed despite F005 emitter failure"

    # plan.md status flipped draft → active — the lock mutation happened
    # before the sidecar emitter even ran, and the exception did not roll
    # it back.
    plan_md_text = (plan_dir / "plan.md").read_text(encoding="utf-8")
    assert "status: active" in plan_md_text
    assert "status: draft" not in plan_md_text

    # No sidecar file written — the boom fired before the writer.
    assert not (plan_dir / sidecar.SIDECAR_RELPATH).exists()

    # Operator sees the advisory warning chip on stderr.
    captured = capsys.readouterr()
    assert "[required-capabilities] WARN" in captured.err
    assert "synthetic writer failure" in captured.err


def test_lock_flow_writes_required_capabilities_sidecar_for_matching_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    capability_index: cap.CapabilityIndex,
    _isolate_cache: Path,
) -> None:
    """Positive CLI lock-path proof: a matching plan writes the sidecar.

    This exercises ``_plan_lock_main`` end-to-end rather than calling
    ``emit_required_capabilities()`` directly, so the test proves the
    actual lock flow flips status, validates external_refs, invokes the
    sidecar emitter, and writes ``evidence/required-capabilities.json``
    with a populated ``matches[]`` entry.
    """

    from dontpanic_orchestrate import cli

    plan_dir = tmp_path / "plan"
    _write_fixture_plan(
        plan_dir,
        external_refs_yaml=("  - kind: pm_issue\n    uri: linear://issue/ABC-1\n    sync: none\n"),
    )
    resolver = _resolver_with_linear()
    monkeypatch.setattr(cli, "_CAPABILITY_INDEX_FACTORY", lambda: capability_index)
    monkeypatch.setattr(cli, "_RESOLVER_FACTORY", lambda: resolver)

    rc = cli._plan_lock_main([str(plan_dir)])

    assert rc == 0
    sidecar_path = plan_dir / sidecar.SIDECAR_RELPATH
    assert sidecar_path.is_file()
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert any(
        m["capability_id"] == "linear" and m["source"] == "external_ref" for m in payload["matches"]
    )
    assert any(r["capability_id"] == "linear" for r in payload["required_capabilities"])
    assert "status: active" in (plan_dir / "plan.md").read_text(encoding="utf-8")
    captured = capsys.readouterr()
    assert "[required-capabilities]" in captured.out
    assert "required-capabilities.json" in captured.out


def test_cli_wrapper_reraises_writer_failure_by_design(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Companion contract test: the wrapper
    ``_emit_required_capabilities_sidecar`` deliberately does NOT catch
    emitter failures itself — the outer ``_plan_lock_main`` flow owns the
    try/except (covered end-to-end by
    :func:`test_lock_flow_swallows_writer_failure_and_succeeds`). This
    test pins the design so a future refactor that pushes the catch into
    the wrapper makes a conscious choice rather than a silent shift."""

    from dontpanic_orchestrate import cli

    plan_dir = tmp_path / "plan"
    _write_fixture_plan(plan_dir, surfaces_yaml="  - web\n")

    def _boom(*_args, **_kwargs):
        raise RuntimeError("synthetic writer failure")

    monkeypatch.setattr(
        "dontpanic_orchestrate.capabilities_lock_sidecar.emit_required_capabilities",
        _boom,
    )
    with pytest.raises(RuntimeError, match="synthetic writer failure"):
        cli._emit_required_capabilities_sidecar(plan_dir, applicability_report=None)


def test_emit_with_explicit_capability_id_unknown_creates_skip_entry(
    tmp_path: Path, capability_index: cap.CapabilityIndex, _isolate_cache: Path
) -> None:
    """An external_ref whose capability_id has no manifest match produces
    a skip[] entry rather than blocking. Demonstrates the skips[] shape."""

    plan_dir = tmp_path / "plan"
    _write_fixture_plan(
        plan_dir,
        external_refs_yaml=(
            "  - kind: pm_issue\n    uri: linear://issue/ABC-1\n    sync: none\n"
            "    capability_id: nonexistent-capability\n"
        ),
    )
    out = sidecar.emit_required_capabilities(
        plan_dir, capability_index=capability_index, resolver=ers.AdapterResolver()
    )
    assert out is not None
    payload = json.loads(out.read_text())
    skip_ids = {s["capability_id"] for s in payload["skips"]}
    assert "nonexistent-capability" in skip_ids
