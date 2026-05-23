"""Plan 2026-05-23-002 F001 — install snapshot primitive tests.

Coverage:

  1. Model shape — required fields present, ``extra='forbid'`` rejects
     unknowns.
  2. No secret-shaped field names anywhere in the snapshot schema.
  3. Deterministic fingerprints — re-running ``build_snapshot`` against
     the same capability index yields byte-identical bodies modulo
     ``generated_at``.
  4. Write mode is 0o600 with ``--yes``.
  5. ``dontpanic init`` writes the snapshot after a successful
     walk + smoke.
  6. ``reconcile baseline`` preview (no ``--yes``) does NOT touch disk.
  7. ``reconcile baseline --yes`` writes the snapshot at mode 0o600.
  8. ``--format=json`` emits the snapshot body as JSON on stdout.
  9. Missing capabilities directory raises ``CapabilityLoadError``.
"""

from __future__ import annotations

import json
import stat
from unittest import mock

import pytest
from pydantic import ValidationError

from dontpanic_orchestrate import install_snapshot as snap
from dontpanic_orchestrate import reconcile
from dontpanic_orchestrate.capabilities import load_capabilities

# ── 1. model shape ────────────────────────────────────────────────────────


def test_snapshot_required_fields_present(tmp_path, monkeypatch):
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))
    s = snap.build_snapshot(profile="core", mcp_tool_names=("a", "b"))
    payload = s.model_dump(mode="json")
    for field in (
        "schema_version",
        "generated_at",
        "dontpanic_version",
        "profile",
        "agent_manifest_schema_version",
        "mcp_tool_names",
        "capability_ids",
        "capabilities",
    ):
        assert field in payload, f"missing required field {field!r}"
    assert s.schema_version == snap.SCHEMA_VERSION
    assert s.profile == "core"
    assert s.mcp_tool_names == ("a", "b")
    assert tuple(s.capability_ids) == tuple(c.capability_id for c in s.capabilities)
    # Every capability fingerprint carries the three identity pieces.
    for cap in s.capabilities:
        assert cap.capability_id
        assert len(cap.manifest_fingerprint) == 64  # sha256 hex
        assert len(cap.setup_steps_fingerprint) == 64
        assert isinstance(cap.setup_step_ids, tuple)


def test_snapshot_rejects_unknown_field():
    """extra='forbid' on every snapshot model."""
    with pytest.raises(ValidationError):
        snap.InstallSnapshot.model_validate(
            {
                "schema_version": snap.SCHEMA_VERSION,
                "generated_at": "2026-05-23T00:00:00Z",
                "dontpanic_version": "0.1.0",
                "profile": "core",
                "agent_manifest_schema_version": "1.0",
                "mcp_tool_names": [],
                "capability_ids": [],
                "capabilities": [],
                "unknown_field": "oops",
            }
        )


# ── 2. no-secret invariant ────────────────────────────────────────────────


def test_snapshot_schema_has_no_credential_shaped_fields():
    forbidden = ("_token", "_key", "_secret")
    for model in (
        snap.InstallSnapshot,
        snap.CapabilityFingerprint,
        snap.StatusCacheMeta,
    ):
        for name in model.model_fields:
            for substring in forbidden:
                assert substring not in name, (
                    f"{model.__name__}.{name} contains forbidden {substring!r}"
                )


# ── 3. deterministic fingerprints ─────────────────────────────────────────


def test_build_snapshot_is_deterministic_modulo_generated_at(tmp_path, monkeypatch):
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))
    index = load_capabilities()
    s1 = snap.build_snapshot(
        profile="core",
        capability_index=index,
        mcp_tool_names=("x", "y"),
        now_iso="2026-05-23T00:00:00Z",
    )
    s2 = snap.build_snapshot(
        profile="core",
        capability_index=index,
        mcp_tool_names=("x", "y"),
        now_iso="2026-05-23T00:00:00Z",
    )
    assert s1.model_dump() == s2.model_dump()

    s3 = snap.build_snapshot(
        profile="core",
        capability_index=index,
        mcp_tool_names=("x", "y"),
        now_iso="2099-01-01T00:00:00Z",
    )
    s1_no_time = {k: v for k, v in s1.model_dump().items() if k != "generated_at"}
    s3_no_time = {k: v for k, v in s3.model_dump().items() if k != "generated_at"}
    assert s1_no_time == s3_no_time
    assert s1.generated_at != s3.generated_at


def test_capability_fingerprint_changes_when_manifest_changes():
    index = load_capabilities()
    first = index.all[0]
    fp_a = snap.capability_fingerprint(first)
    mutated = first.model_copy(update={"summary": first.summary + " (changed)"})
    fp_b = snap.capability_fingerprint(mutated)
    assert fp_a.manifest_fingerprint != fp_b.manifest_fingerprint
    # setup_steps unchanged → fingerprint stable
    assert fp_a.setup_steps_fingerprint == fp_b.setup_steps_fingerprint
    assert fp_a.setup_step_ids == fp_b.setup_step_ids


# ── 4. write mode 0o600 ───────────────────────────────────────────────────


def test_write_snapshot_chmods_to_0600(tmp_path, monkeypatch):
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))
    s = snap.build_snapshot(profile="core", mcp_tool_names=())
    written = snap.write_snapshot(s)
    assert written == tmp_path / snap.SNAPSHOT_FILENAME
    mode = stat.S_IMODE(written.stat().st_mode)
    assert mode == snap.SNAPSHOT_FILE_MODE
    # round-trip read.
    loaded = snap.load_snapshot()
    assert loaded is not None
    assert loaded.profile == "core"


# ── 5. init hook ──────────────────────────────────────────────────────────


def test_init_writes_snapshot_after_successful_walk_and_smoke(tmp_path, monkeypatch, capsys):
    """When the walk and smoke both pass, init writes the snapshot."""
    from dontpanic_orchestrate import smoke as _smoke
    from dontpanic_orchestrate.init import (
        EXIT_READY,
        init_main,
    )

    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))

    # Stub the walker to always return a green result (no probes,
    # exit_code == EXIT_READY). Patch the import seam.
    from dontpanic_orchestrate import init as init_pkg

    class _GreenWalker:
        def __init__(self, **_: object) -> None:
            self.profile = "core"
            self.non_interactive = False

        def run(self) -> init_pkg.WalkResult:
            sweep = mock.Mock()
            sweep.probes = []
            return init_pkg.WalkResult(
                profile="core",
                initial=sweep,
                final=sweep,
                actions=[],
                non_interactive=False,
                aborted=False,
            )

    monkeypatch.setattr(init_pkg, "Walker", _GreenWalker)

    # Stub smoke to always pass.
    def _smoke_pass(*, mode):
        sr = mock.Mock()
        sr.exit_code = _smoke.EXIT_PASS
        sr.to_json = lambda: json.dumps({"exit_code": _smoke.EXIT_PASS})
        return sr

    monkeypatch.setattr(_smoke, "run_smoke", _smoke_pass)

    # --json suppresses the human smoke-text renderer (which would
    # require a fully-populated SmokeResult) and emits a single JSON
    # envelope instead. EXIT_READY + no snapshot when smoke is skipped.
    rc = init_main(["--skip-smoke", "--json"])
    assert rc == EXIT_READY
    assert not (tmp_path / snap.SNAPSHOT_FILENAME).exists()

    # Run again WITHOUT skip-smoke → snapshot written.
    rc = init_main(["--json"])
    assert rc == EXIT_READY
    target = tmp_path / snap.SNAPSHOT_FILENAME
    assert target.is_file()
    assert stat.S_IMODE(target.stat().st_mode) == snap.SNAPSHOT_FILE_MODE


def test_init_surfaces_snapshot_write_failure(tmp_path, monkeypatch):
    """A snapshot write failure must propagate as install failure, not
    silently disappear."""
    from dontpanic_orchestrate import init as init_pkg
    from dontpanic_orchestrate import smoke as _smoke
    from dontpanic_orchestrate.init import (
        EXIT_REMAINING,
        init_main,
    )

    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))

    class _GreenWalker:
        def __init__(self, **_: object) -> None:
            self.profile = "core"
            self.non_interactive = False

        def run(self) -> init_pkg.WalkResult:
            sweep = mock.Mock()
            sweep.probes = []
            return init_pkg.WalkResult(
                profile="core",
                initial=sweep,
                final=sweep,
                actions=[],
                non_interactive=False,
                aborted=False,
            )

    monkeypatch.setattr(init_pkg, "Walker", _GreenWalker)

    def _smoke_pass(*, mode):
        sr = mock.Mock()
        sr.exit_code = _smoke.EXIT_PASS
        sr.to_json = lambda: json.dumps({"exit_code": _smoke.EXIT_PASS})
        return sr

    monkeypatch.setattr(_smoke, "run_smoke", _smoke_pass)

    # Patch build_snapshot to raise — simulates capability dir missing
    # in an otherwise-green install. init MUST exit non-zero.
    def _boom(*args, **kwargs):
        raise snap.CapabilityLoadError("capabilities directory not found")

    monkeypatch.setattr(snap, "build_snapshot", _boom)

    rc = init_main(["--json"])
    assert rc == EXIT_REMAINING
    assert not (tmp_path / snap.SNAPSHOT_FILENAME).exists()


# ── 6 + 7. reconcile baseline preview vs --yes ────────────────────────────


def test_reconcile_baseline_preview_does_not_write(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))
    rc = reconcile.reconcile_main(["baseline", "--profile=core"])
    assert rc == 0
    assert not (tmp_path / snap.SNAPSHOT_FILENAME).exists()
    captured = capsys.readouterr()
    assert "install-snapshot target:" in captured.out
    assert "preview" in captured.err.lower()


def test_reconcile_baseline_yes_writes_with_mode_0600(tmp_path, monkeypatch):
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))
    rc = reconcile.reconcile_main(["baseline", "--profile=core", "--yes"])
    assert rc == 0
    target = tmp_path / snap.SNAPSHOT_FILENAME
    assert target.is_file()
    assert stat.S_IMODE(target.stat().st_mode) == snap.SNAPSHOT_FILE_MODE
    body = json.loads(target.read_text())
    assert body["profile"] == "core"
    assert body["schema_version"] == snap.SCHEMA_VERSION
    # secret-shaped strings should not appear in the on-disk body
    for key in body:
        assert "_token" not in key and "_key" not in key and "_secret" not in key


# ── 8. JSON output ────────────────────────────────────────────────────────


def test_reconcile_baseline_json_emits_valid_envelope(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))
    rc = reconcile.reconcile_main(["baseline", "--profile=core", "--format=json"])
    assert rc == 0
    captured = capsys.readouterr()
    body = json.loads(captured.out)
    assert body["schema_version"] == snap.SCHEMA_VERSION
    assert body["profile"] == "core"
    assert isinstance(body["mcp_tool_names"], list)
    assert isinstance(body["capabilities"], list)
    # Preview-only — no file even with --format=json
    assert not (tmp_path / snap.SNAPSHOT_FILENAME).exists()


# ── 9. missing capabilities dir failure ───────────────────────────────────


def test_build_snapshot_missing_capabilities_dir_raises(tmp_path):
    """An install whose repo lacks ``capabilities/`` must fail loudly so
    ``reconcile baseline`` and ``dontpanic init`` cannot stamp a half-blank
    snapshot."""
    bogus_root = tmp_path / "no-such-repo"
    bogus_root.mkdir()
    with pytest.raises(snap.CapabilityLoadError):
        snap.build_snapshot(profile="core", repo_root=bogus_root)


# ── 10. legacy `.jarvis` / JARVIS_HOME does NOT redirect snapshot ─────────


def test_jarvis_home_does_not_redirect_snapshot_path(tmp_path, monkeypatch):
    """Acceptance: "no migration from `.jarvis` writes secrets" — the
    install snapshot anchors only at the canonical ``~/.dontpanic``
    location. Setting ``JARVIS_HOME`` (or having an existing
    ``~/.jarvis``) must NOT redirect the snapshot.

    Regression guard for the auditor's reproduction:
    ``JARVIS_HOME=/tmp/legacy-only reconcile baseline`` previously
    previewed ``/tmp/legacy-only/install-snapshot.json``.
    """
    legacy_root = tmp_path / "legacy-jarvis"
    legacy_root.mkdir()
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    # Also create a legacy ~/.jarvis under the fake HOME — fall-back
    # precedence in global_config.dontpanic_home() would otherwise pick
    # it up. The snapshot helper must ignore both.
    (fake_home / ".jarvis").mkdir()

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("JARVIS_HOME", str(legacy_root))
    monkeypatch.delenv("DONTPANIC_HOME", raising=False)

    resolved = snap.snapshot_path()
    expected = fake_home / ".dontpanic" / snap.SNAPSHOT_FILENAME
    assert resolved == expected, (
        f"snapshot_path() must anchor on canonical ~/.dontpanic; got {resolved}"
    )
    assert legacy_root not in resolved.parents
    assert (fake_home / ".jarvis") not in resolved.parents


def test_reconcile_baseline_yes_does_not_write_into_jarvis(tmp_path, monkeypatch):
    """End-to-end: `reconcile baseline --yes` on an existing-install
    shape (legacy ``.jarvis`` present, ``JARVIS_HOME`` exported) creates
    the canonical snapshot anchor without writing into ``.jarvis``."""
    legacy_root = tmp_path / "legacy-jarvis"
    legacy_root.mkdir()
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    (fake_home / ".jarvis").mkdir()

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("JARVIS_HOME", str(legacy_root))
    monkeypatch.delenv("DONTPANIC_HOME", raising=False)

    rc = reconcile.reconcile_main(["baseline", "--profile=core", "--yes"])
    assert rc == 0

    canonical_target = fake_home / ".dontpanic" / snap.SNAPSHOT_FILENAME
    assert canonical_target.is_file(), (
        f"expected canonical snapshot at {canonical_target}"
    )
    assert stat.S_IMODE(canonical_target.stat().st_mode) == snap.SNAPSHOT_FILE_MODE
    # Legacy locations must remain untouched.
    assert not (legacy_root / snap.SNAPSHOT_FILENAME).exists()
    assert not (fake_home / ".jarvis" / snap.SNAPSHOT_FILENAME).exists()


def test_reconcile_baseline_missing_capabilities_dir_exits_1(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("DONTPANIC_HOME", str(tmp_path))

    def _boom(*args, **kwargs):
        raise snap.CapabilityLoadError("capabilities directory not found")

    monkeypatch.setattr(reconcile, "build_snapshot", _boom)
    rc = reconcile.reconcile_main(["baseline", "--profile=core", "--yes"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "failed to load capabilities" in captured.err
