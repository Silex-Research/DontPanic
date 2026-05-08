"""F003 — patch_completeness_gate (supervisor enforcement).

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_patch_completeness_gate.py

Covers:
  - PatchCompletenessError rendering (per-finding line shape; block-only).
  - validate_reason: layer-B defense-in-depth >=8 char check.
  - enforce(): block path, allow-incomplete-patch override, Mode 5
    promotion, unrelated-dirty note, dry-run carve-out, clean-patch
    regression, missing git-state sidecar (best-effort no-op).
  - Signoff block recording shape under each override.
  - F001/F002 source surfaces remain frozen (grep guard).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate.patch_completeness import (  # noqa: E402
    CompletenessReport,
    Finding,
)
from dontpanic_orchestrate.patch_completeness_gate import (  # noqa: E402
    MIN_REASON_LEN,
    PatchCompletenessError,
    enforce,
    validate_reason,
)

# ──────────────────────────────  fixtures  ──────────────────────────────


def _sidecar(plan_dir: Path, *, iteration: int, role: str, state: dict) -> Path:
    evidence = plan_dir / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    p = evidence / f"git-state-{iteration}-{role}.json"
    p.write_text(json.dumps(state) + "\n")
    return p


def _state(
    *,
    staged: list[dict] | None = None,
    unstaged_modified: list[dict] | None = None,
    untracked: list[str] | None = None,
) -> dict:
    return {
        "staged": staged or [],
        "unstaged_modified": unstaged_modified or [],
        "untracked": untracked or [],
        "deleted_staged": [],
        "deleted_unstaged": [],
    }


def _write(repo: Path, path: str, content: str) -> None:
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(content)


# ──────────────────────────────  validate_reason  ──────────────────────────────


def test_validate_reason_accepts_none() -> None:
    assert validate_reason(None, flag="--allow-incomplete-patch") is None


def test_validate_reason_accepts_long_enough() -> None:
    reason = "x" * MIN_REASON_LEN
    assert validate_reason(reason, flag="--allow-incomplete-patch") == reason


@pytest.mark.parametrize("short", ["", "wip", "fix", " " * 16, "  fix  "])
def test_validate_reason_rejects_short_or_whitespace(short: str) -> None:
    with pytest.raises(ValueError, match="at least 8"):
        validate_reason(short, flag="--allow-incomplete-patch")


# ──────────────────────────────  PatchCompletenessError rendering  ──────────────────────────────


def test_patch_completeness_error_renders_one_line_per_block_finding() -> None:
    report = CompletenessReport(
        schema_version="1.0",
        status="fail",
        findings=[
            Finding(
                mode="test_imports_uncommitted",
                files=["needs.py"],
                reason="r1",
                severity="block",
                recommendation="Run: git add needs.py",
            ),
            Finding(
                mode="unstaged_dirty_state",
                files=["wip.py"],
                reason="r2",
                severity="info",  # info entries must NOT render
                recommendation="advisory",
            ),
        ],
        files=["needs.py", "wip.py"],
    )
    err = PatchCompletenessError(report, Path("/tmp"))
    rendered = str(err)
    assert "test_imports_uncommitted | block | needs.py | r1 | Run: git add needs.py" in rendered
    assert "unstaged_dirty_state" not in rendered
    assert ">=8 chars" in rendered


# ──────────────────────────────  enforce(): no sidecar  ──────────────────────────────


def test_enforce_returns_none_when_sidecar_missing(tmp_path: Path) -> None:
    """No F001 sidecar → gate is silently best-effort no-op (mirrors F001)."""
    out = enforce(
        tmp_path,
        plan_id="2026-test",
        iteration=0,
        role="implementer",
        audit_paths=[],
        affected_paths=None,
        repo_root=tmp_path,
        dry_run=False,
    )
    assert out is None
    assert not (tmp_path / "audit").exists()
    assert not (tmp_path / "INBOX.md").exists()


# ──────────────────────────────  enforce(): clean-patch regression  ──────────────────────────────


def test_enforce_clean_patch_returns_pass_block(tmp_path: Path) -> None:
    _sidecar(tmp_path, iteration=0, role="implementer", state=_state())
    block = enforce(
        tmp_path,
        plan_id="2026-test",
        iteration=0,
        role="implementer",
        audit_paths=[],
        affected_paths=None,
        repo_root=tmp_path,
        dry_run=False,
    )
    assert block is not None
    assert block["status"] == "pass"
    assert block["findings"] == []
    assert "override_flag" not in block
    # Persisted report lands in audit/.
    assert (tmp_path / "audit" / "patch-completeness-0.json").exists()


# ──────────────────────────────  enforce(): block path  ──────────────────────────────


def test_enforce_block_path_raises_and_writes_inbox(tmp_path: Path) -> None:
    """Mode 3 violation + no override + non-dry-run → raise + INBOX entry."""
    _write(tmp_path, "tests/test_new.py", "def test_x(): assert True\n")
    _sidecar(
        tmp_path,
        iteration=0,
        role="implementer",
        state=_state(untracked=["tests/test_new.py"]),
    )

    with pytest.raises(PatchCompletenessError) as exc_info:
        enforce(
            tmp_path,
            plan_id="2026-test",
            iteration=0,
            role="implementer",
            audit_paths=[],
            affected_paths=None,
            repo_root=tmp_path,
            dry_run=False,
        )
    assert exc_info.value.report.status == "fail"
    # Audit report persisted.
    audit_blob = json.loads((tmp_path / "audit" / "patch-completeness-0.json").read_text())
    assert audit_blob["status"] == "fail"
    # INBOX entry emitted.
    inbox_text = (tmp_path / "INBOX.md").read_text()
    assert "breaker:patch_incomplete" in inbox_text
    assert "test_new.py" in inbox_text


# ──────────────────────────────  enforce(): allow-incomplete-patch override  ──────────────────────────────


def test_enforce_override_allows_signoff_and_records_reason(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_new.py", "def test_x(): assert True\n")
    _sidecar(
        tmp_path,
        iteration=0,
        role="implementer",
        state=_state(untracked=["tests/test_new.py"]),
    )
    reason = "intentional smoke-test override; PR #123"

    block = enforce(
        tmp_path,
        plan_id="2026-test",
        iteration=0,
        role="implementer",
        audit_paths=[],
        affected_paths=None,
        repo_root=tmp_path,
        allow_incomplete_patch_reason=reason,
        dry_run=False,
    )
    assert block is not None
    assert block["status"] == "fail"  # findings still report fail status
    assert block["override_flag"] == "allow_incomplete_patch"
    assert block["override_reason"] == reason  # verbatim
    # No INBOX entry on override path.
    assert not (tmp_path / "INBOX.md").exists()
    # Findings recorded verbatim.
    assert any(f["mode"] == "test_file_untracked" for f in block["findings"])


def test_enforce_override_rejects_short_reason_at_layer_b(tmp_path: Path) -> None:
    """Programmatic invocation with reason < 8 chars must raise ValueError."""
    _sidecar(tmp_path, iteration=0, role="implementer", state=_state())
    with pytest.raises(ValueError, match="at least 8"):
        enforce(
            tmp_path,
            plan_id="2026-test",
            iteration=0,
            role="implementer",
            audit_paths=[],
            affected_paths=None,
            repo_root=tmp_path,
            allow_incomplete_patch_reason="wip",  # too short
            dry_run=False,
        )


# ──────────────────────────────  enforce(): Mode 5 promotion  ──────────────────────────────


def test_enforce_mode5_promotes_to_block_when_outside_touched_no_note(tmp_path: Path) -> None:
    _write(tmp_path, "lib/parallel_wip.py", "wip = True\n")
    _write(tmp_path, "lib/intended.py", "x = 1\n")
    _sidecar(
        tmp_path,
        iteration=0,
        role="implementer",
        state=_state(
            unstaged_modified=[
                {"path": "lib/parallel_wip.py", "status": "M"},
                {"path": "lib/intended.py", "status": "M"},
            ]
        ),
    )
    with pytest.raises(PatchCompletenessError) as exc_info:
        enforce(
            tmp_path,
            plan_id="2026-test",
            iteration=0,
            role="implementer",
            audit_paths=[],
            affected_paths=["lib/intended.py"],  # parallel_wip is OUTSIDE
            repo_root=tmp_path,
            dry_run=False,
        )
    promoted = exc_info.value.report
    mode5 = next(f for f in promoted.findings if f.mode == "unstaged_dirty_state")
    assert mode5.severity == "block"
    assert "lib/parallel_wip.py" in mode5.reason


def test_enforce_mode5_stays_info_with_unrelated_dirty_state_note(tmp_path: Path) -> None:
    _write(tmp_path, "lib/parallel_wip.py", "wip = True\n")
    _sidecar(
        tmp_path,
        iteration=0,
        role="implementer",
        state=_state(unstaged_modified=[{"path": "lib/parallel_wip.py", "status": "M"}]),
    )
    note = "WIP on parallel plan #2026-05-09-002"
    block = enforce(
        tmp_path,
        plan_id="2026-test",
        iteration=0,
        role="implementer",
        audit_paths=[],
        affected_paths=[],
        repo_root=tmp_path,
        unrelated_dirty_state_note=note,
        dry_run=False,
    )
    assert block is not None
    # Status must be 'pass' (Mode 5 alone is info, no other findings).
    assert block["status"] == "pass"
    assert block["unrelated_dirty_state_note"] == note
    assert "lib/parallel_wip.py" in block["unrelated_dirty_files"]
    mode5 = next(f for f in block["findings"] if f["mode"] == "unstaged_dirty_state")
    assert mode5["severity"] == "info"


def test_enforce_mode5_stays_info_when_all_dirty_files_are_in_touched_set(tmp_path: Path) -> None:
    """When every Mode 5 file is in touched_files, no promotion needed even
    without --unrelated-dirty-state-note."""
    _write(tmp_path, "lib/intended.py", "x = 1\n")
    _sidecar(
        tmp_path,
        iteration=0,
        role="implementer",
        state=_state(unstaged_modified=[{"path": "lib/intended.py", "status": "M"}]),
    )
    block = enforce(
        tmp_path,
        plan_id="2026-test",
        iteration=0,
        role="implementer",
        audit_paths=[],
        affected_paths=["lib/intended.py"],
        repo_root=tmp_path,
        dry_run=False,
    )
    assert block is not None
    assert block["status"] == "pass"  # Mode 5 stays info, no other findings
    mode5 = next(f for f in block["findings"] if f["mode"] == "unstaged_dirty_state")
    assert mode5["severity"] == "info"


# ──────────────────────────────  enforce(): dry-run carve-out (D009)  ──────────────────────────────


def test_enforce_dry_run_does_not_raise_on_block_status(tmp_path: Path) -> None:
    """D009: dry-run runs the gate, persists the report, but never raises."""
    _write(tmp_path, "tests/test_new.py", "def test_x(): assert True\n")
    _sidecar(
        tmp_path,
        iteration=0,
        role="implementer",
        state=_state(untracked=["tests/test_new.py"]),
    )

    block = enforce(
        tmp_path,
        plan_id="2026-test",
        iteration=0,
        role="implementer",
        audit_paths=[],
        affected_paths=None,
        repo_root=tmp_path,
        dry_run=True,
    )
    assert block is not None
    assert block["status"] == "fail"
    # Findings visible.
    modes = {f["mode"] for f in block["findings"]}
    assert "test_file_untracked" in modes
    # Report persisted to audit/ in dry-run too.
    assert (tmp_path / "audit" / "patch-completeness-0.json").exists()
    # NO INBOX entry on dry-run.
    assert not (tmp_path / "INBOX.md").exists()


# ──────────────────────────────  evidence_refs threading  ──────────────────────────────


def test_enforce_uses_evidence_refs_from_audit_envelopes(tmp_path: Path) -> None:
    """evidence_refs[*].uri from envelopes must enter the touched_files set,
    so a file cited as evidence is NOT flagged as 'unrelated dirty'."""
    _write(tmp_path, "lib/cited.py", "x = 1\n")
    _sidecar(
        tmp_path,
        iteration=0,
        role="implementer",
        state=_state(unstaged_modified=[{"path": "lib/cited.py", "status": "M"}]),
    )
    # Synthetic audit envelope with evidence_refs pointing at cited.py.
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    env = audit_dir / "claude-implementer-F001-i0.json"
    env.write_text(
        json.dumps(
            {"evidence_refs": [{"uri": "lib/cited.py", "kind": "patch", "sha256": "x" * 64}]}
        )
    )

    block = enforce(
        tmp_path,
        plan_id="2026-test",
        iteration=0,
        role="implementer",
        audit_paths=[env],
        affected_paths=None,
        repo_root=tmp_path,
        dry_run=False,
    )
    assert block is not None
    # Mode 5 stays info (cited.py is now in touched_files via evidence_refs).
    mode5 = next(f for f in block["findings"] if f["mode"] == "unstaged_dirty_state")
    assert mode5["severity"] == "info"
    assert block["status"] == "pass"


# ──────────────────────────────  F001/F002 surface freeze  ──────────────────────────────


_F001_SHA_AT_F003_LANDING = None  # populated below
_F002_SHA_AT_F003_LANDING = None  # populated below


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_f001_module_unchanged_by_f003() -> None:
    """F003 must not modify F001's pure surface. We don't pin a specific sha
    here (the file evolves with project formatting passes), but assert F003's
    module text contains no edits to F001 — the gate IMPORTS F001 but does
    not duplicate or override its symbols.
    """
    f003_src = (HERE.parents[1] / "patch_completeness_gate.py").read_text()
    # F003 must reach F001 only via imports of git_state — never reach into
    # internals or shadow the public API.
    assert "from dontpanic_orchestrate import" in f003_src
    assert "def parse_porcelain" not in f003_src
    assert "def capture(" not in f003_src


def test_f002_pure_surface_unchanged_by_f003() -> None:
    """F003 imports F002's check() + dataclasses but must not redefine them."""
    f003_src = (HERE.parents[1] / "patch_completeness_gate.py").read_text()
    assert "def check(" not in f003_src
    assert "@dataclass" not in f003_src
    assert "_GENERATED_ARTIFACT_PATTERNS" not in f003_src


def test_f002_module_purity_still_holds() -> None:
    """Re-run F002's purity contract from F003's vantage point — guards
    against a future refactor that imports F003 *into* F002."""
    f002_src = (HERE.parents[1] / "patch_completeness.py").read_text()
    forbidden = ["subprocess.run", "logging.getLogger", "print(", "patch_completeness_gate"]
    for needle in forbidden:
        assert needle not in f002_src, f"F002 must not contain {needle!r}"


# ──────────────────────────────  signoff block schema sanity  ──────────────────────────────


# ──────────────────────────────  CLI argparse layer-A  ──────────────────────────────


def test_cli_validator_accepts_long_reason() -> None:
    from dontpanic_orchestrate.cli import _validate_patch_reason

    coerce = _validate_patch_reason("--allow-incomplete-patch")
    reason = "intentional override under operator approval"
    assert coerce(reason) == reason


@pytest.mark.parametrize("short", ["", "wip", "fix", "       ", "  short"])
def test_cli_validator_rejects_short_reason(short: str) -> None:
    """Layer A: argparse-level rejection produces ArgumentTypeError → exit 2."""
    import argparse

    from dontpanic_orchestrate.cli import _validate_patch_reason

    coerce = _validate_patch_reason("--allow-incomplete-patch")
    with pytest.raises(argparse.ArgumentTypeError, match="at least 8"):
        coerce(short)


def test_cli_validator_two_layer_consistency() -> None:
    """Layer A (argparse) + Layer B (validate_reason) must reject the same set
    of inputs and accept the same set. Defense-in-depth requires both."""
    import argparse

    from dontpanic_orchestrate.cli import _validate_patch_reason

    coerce = _validate_patch_reason("--allow-incomplete-patch")
    accepted = ["intentional override", "smoke-test signoff", "x" * MIN_REASON_LEN]
    rejected = ["", "wip", "fix", "  fix  ", " " * MIN_REASON_LEN]
    for a in accepted:
        # Layer A accepts.
        assert coerce(a) == a
        # Layer B accepts.
        assert validate_reason(a, flag="--allow-incomplete-patch") == a
    for r in rejected:
        # Layer A rejects.
        with pytest.raises(argparse.ArgumentTypeError):
            coerce(r)
        # Layer B rejects.
        with pytest.raises(ValueError):
            validate_reason(r, flag="--allow-incomplete-patch")


# ──────────────────────────────  signoff_writer recording  ──────────────────────────────


def test_signoff_writer_attaches_patch_completeness_block(tmp_path: Path) -> None:
    """build_signoff_dict accepts patch_completeness kwarg and attaches it
    AFTER schema validation (D004 — no schema bump)."""
    from dontpanic_orchestrate import signoff_writer

    # Minimal valid envelope to satisfy build_signoff_dict's audit_paths req.
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    fake_envelope = audit_dir / "claude-implementer-F001-i0.json"
    fake_envelope.write_text(
        json.dumps(
            {
                "audit_status": "signed_off",
                "evidence_refs": [],
            }
        )
    )

    block = {
        "status": "fail",
        "findings": [
            {
                "mode": "test_file_untracked",
                "files": ["tests/test_x.py"],
                "reason": "r",
                "severity": "block",
                "recommendation": "Run: git add tests/test_x.py",
            }
        ],
        "files": ["tests/test_x.py"],
        "override_flag": "allow_incomplete_patch",
        "override_reason": "intentional override for smoke test",
    }
    payload = signoff_writer.build_signoff_dict(
        plan_id="2026-05-01-004-test",
        tier="local",
        iteration=0,
        agents_in_panel=["claude", "codex"],
        audit_paths=[fake_envelope],
        plan_dir=tmp_path,
        volley_status="signed_off",
        patch_completeness=block,
    )
    assert payload["patch_completeness"] == block
    # Sanity: the block sits as a sibling key, not embedded inside another field.
    assert "patch_completeness" in payload
    # Round-trip the payload through JSON to confirm serializable.
    rt = json.loads(json.dumps(payload))
    assert rt["patch_completeness"] == block


def test_signoff_writer_passthrough_when_block_is_none(tmp_path: Path) -> None:
    """When no patch_completeness block is supplied (legacy callers), payload
    is unchanged — backward-compat for plans that don't run F003 yet."""
    from dontpanic_orchestrate import signoff_writer

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    fake_envelope = audit_dir / "claude-implementer-F001-i0.json"
    fake_envelope.write_text(json.dumps({"audit_status": "signed_off"}))

    payload = signoff_writer.build_signoff_dict(
        plan_id="2026-05-01-004-test",
        tier="local",
        iteration=0,
        agents_in_panel=["claude", "codex"],
        audit_paths=[fake_envelope],
        plan_dir=tmp_path,
        volley_status="signed_off",
    )
    assert "patch_completeness" not in payload


# ──────────────────────────────  signoff block schema sanity  ──────────────────────────────


def test_signoff_block_shape_when_overridden(tmp_path: Path) -> None:
    """Acceptance (7): override path records full provenance verbatim."""
    _write(tmp_path, "tests/test_new.py", "def test_x(): assert True\n")
    _sidecar(
        tmp_path,
        iteration=0,
        role="implementer",
        state=_state(untracked=["tests/test_new.py"]),
    )
    reason = "intentional override under operator approval"
    block = enforce(
        tmp_path,
        plan_id="2026-test",
        iteration=0,
        role="implementer",
        audit_paths=[],
        affected_paths=None,
        repo_root=tmp_path,
        allow_incomplete_patch_reason=reason,
        dry_run=False,
    )
    assert set(block.keys()) >= {"status", "findings", "files", "override_flag", "override_reason"}
    # JSON round-trip sanity on the block alone.
    rt = json.loads(json.dumps(block))
    assert rt == block
