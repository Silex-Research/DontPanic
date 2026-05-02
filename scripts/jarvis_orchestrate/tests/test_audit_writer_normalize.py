"""F002 — audit_writer.write target-context prelude normalization.

Run: PYTHONPATH=scripts pytest scripts/jarvis_orchestrate/tests/test_audit_writer_normalize.py
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from jarvis_orchestrate import audit_writer, circuit_breakers  # noqa: E402
from jarvis_orchestrate.target_context_prelude import (  # noqa: E402
    PRELUDE_TEMPLATE,
    TargetContextError,
    render_prelude,
    resolve_repo,
)

REPO_ROOT = HERE.parents[3]
PLAN_DIR = REPO_ROOT / "docs" / "plans" / "2026-05-01-005-feat-target-context-platform-fix"
FIXTURES_DIR = PLAN_DIR / "evidence" / "f001" / "fixtures"

# F002's hard contract: the canonical D001 header (line + newline). Presence
# detection now uses parse_prelude_block (full canonical block: header + 4
# field lines + trailing blank). F002 does NOT validate prelude VALUES.
PRELUDE_HEADER = "## Target context\n"

# Real historical audit envelope without the canonical prelude — used in the
# forward-only proof. Picked because (a) it predates F002, (b) sits in a
# committed plan dir so the path is stable, (c) lacks `## Target context\n`.
HISTORICAL_AUDIT = (
    REPO_ROOT
    / "docs"
    / "plans"
    / "2026-04-29-001-feat-changelog-skill"
    / "audit"
    / "claude-implementer-i0.json"
)


# ──────────────────────────────  fixture-prep helpers  ──────────────────────────────


def _load_fixture(name: str, *, agent: str = "claude") -> dict[str, Any]:
    """Load a F001 fixture and prep it for audit_writer.write.

    The fixtures use ``agent: "fixture-agent"`` (not in the Pydantic Agent
    enum) and carry a ``_fixture_notes`` field (Audit model is `extra=forbid`).
    Both are sanitized so the dict survives ``Audit.model_validate``.
    The ``audit_id`` is rebuilt to match the substituted agent so the
    error-message regex test sees a coherent id.
    """
    raw = json.loads((FIXTURES_DIR / name).read_text())
    raw.pop("_fixture_notes", None)
    raw["agent"] = agent
    parts = raw["audit_id"].split("#")
    if len(parts) == 3:
        parts[1] = agent
        raw["audit_id"] = "#".join(parts)
    return raw


def _expected_serialized(audit: dict[str, Any]) -> bytes:
    """Mirror audit_writer.write's serialization for byte-equality checks."""
    return (json.dumps(audit, indent=2, ensure_ascii=False, sort_keys=False) + "\n").encode("utf-8")


def _audit_filename(audit: dict[str, Any]) -> str:
    return f"{audit['agent']}-{audit['agent_role']}-i{audit.get('iteration', 0)}.json"


# ──────────────────────────────  case-a / case-b positive  ──────────────────────────────


def test_case_a_summary_lacks_prelude_writer_injects(tmp_path: Path) -> None:
    """case-a: implementer envelope, struct valid, summary lacks prelude → inject."""
    audit = _load_fixture("case-a-implementer-missing-prelude.json", agent="claude")
    body_before = audit["summary"]
    assert not body_before.lstrip().startswith(PRELUDE_HEADER)

    out = audit_writer.write(audit, tmp_path)
    assert out.exists()

    persisted = json.loads(out.read_text())
    assert persisted["summary"].startswith(PRELUDE_HEADER), persisted["summary"][:80]

    # The non-prelude body must equal the source verbatim — F002 only
    # PREPENDS, never edits the rest of the summary.
    repo = resolve_repo(audit["target_context"])
    rendered = render_prelude({**audit["target_context"], "repo": repo})
    assert persisted["summary"] == rendered + body_before


def test_case_a_idempotence_double_persist(tmp_path: Path) -> None:
    """3b: persist case-a, capture bytes, persist resulting envelope AGAIN
    to a different tmp_path; the second-pass output bytes equal the first.
    The injected prelude is never doubled."""
    pass1_dir = tmp_path / "pass1"
    pass2_dir = tmp_path / "pass2"
    pass1_dir.mkdir()
    pass2_dir.mkdir()

    audit = _load_fixture("case-a-implementer-missing-prelude.json", agent="claude")
    out1 = audit_writer.write(audit, pass1_dir)
    bytes1 = out1.read_bytes()

    # Re-load the persisted envelope and re-write to a different dir.
    reloaded = json.loads(out1.read_text())
    out2 = audit_writer.write(reloaded, pass2_dir)
    bytes2 = out2.read_bytes()

    assert bytes1 == bytes2, "double-persist of case-a must be byte-identical"
    # Sanity: parsed summary contains exactly ONE canonical header.
    persisted = json.loads(bytes2)
    assert persisted["summary"].count(PRELUDE_HEADER) == 1


def test_case_b_auditor_summary_lacks_prelude_writer_injects(tmp_path: Path) -> None:
    """case-b: auditor self-finding, struct valid, summary lacks canonical prelude
    (uses legacy `Repo:/Env:/Project:` block) → F002 prepends the canonical header."""
    audit = _load_fixture("case-b-auditor-self-finding.json", agent="codex")
    body_before = audit["summary"]
    assert not body_before.lstrip().startswith(PRELUDE_HEADER)

    out = audit_writer.write(audit, tmp_path)
    assert out.exists()

    persisted = json.loads(out.read_text())
    assert persisted["summary"].startswith(PRELUDE_HEADER), persisted["summary"][:80]
    # Body preserved verbatim
    assert persisted["summary"].endswith(body_before)


def test_case_b_idempotence_double_persist(tmp_path: Path) -> None:
    pass1_dir = tmp_path / "pass1"
    pass2_dir = tmp_path / "pass2"
    pass1_dir.mkdir()
    pass2_dir.mkdir()

    audit = _load_fixture("case-b-auditor-self-finding.json", agent="codex")
    out1 = audit_writer.write(audit, pass1_dir)
    reloaded = json.loads(out1.read_text())
    out2 = audit_writer.write(reloaded, pass2_dir)

    assert out1.read_bytes() == out2.read_bytes()


# ──────────────────────────────  case-c golden no-op  ──────────────────────────────


def test_case_c_f001_fixture_byte_equality(tmp_path: Path) -> None:
    """Acceptance #3a: case-c (already-canonical prelude + valid struct)
    is a STRICT no-op. Asserts byte-equality against the original F001
    case-c fixture with the documented sanitization transform applied —
    NOT a separate F002-owned golden file.

    Sanitization transform (documented in `_load_fixture`):
      1. Drop `_fixture_notes` (Audit model has `extra=forbid`).
      2. Substitute `agent="fixture-agent"` → `"claude"` (real Agent enum).
      3. Rebuild `audit_id` to match substituted agent so the
         `<plan>#<agent>#<iter>` shape is coherent.

    The expected serialized bytes are computed by `_expected_serialized`
    which mirrors `audit_writer.write`'s exact serialization
    (`json.dumps(..., indent=2, ensure_ascii=False, sort_keys=False) + "\\n"`).
    Strict byte-equality between expected and persisted proves F002 is
    a no-op when the canonical prelude is already present and the
    target_context struct validates — no re-rendering, no key reorder,
    no whitespace drift.
    """
    audit = _load_fixture("case-c-golden-valid-struct-valid-prelude.json", agent="claude")
    summary_before = audit["summary"]
    assert summary_before.startswith(PRELUDE_HEADER), (
        "F001 case-c fixture must already carry the canonical prelude"
    )
    expected_bytes = _expected_serialized(audit)

    out = audit_writer.write(audit, tmp_path)
    actual_bytes = out.read_bytes()

    assert actual_bytes == expected_bytes, (
        f"case-c byte-equality vs F001 fixture (sanitized) failed:\n"
        f"expected({len(expected_bytes)}b) != actual({len(actual_bytes)}b)"
    )
    persisted = json.loads(actual_bytes)
    assert persisted["summary"] == summary_before
    assert persisted["summary"].count(PRELUDE_HEADER) == 1


def test_case_c_idempotence_double_persist(tmp_path: Path) -> None:
    """Double-persist case-c: bytes_2 must equal bytes_1 AND equal the
    expected-serialized form of the F001 fixture (sanitized)."""
    pass1_dir = tmp_path / "pass1"
    pass2_dir = tmp_path / "pass2"
    pass1_dir.mkdir()
    pass2_dir.mkdir()

    audit = _load_fixture("case-c-golden-valid-struct-valid-prelude.json", agent="claude")
    expected_bytes = _expected_serialized(audit)

    out1 = audit_writer.write(audit, pass1_dir)
    bytes1 = out1.read_bytes()
    assert bytes1 == expected_bytes

    out2 = audit_writer.write(json.loads(out1.read_text()), pass2_dir)
    bytes2 = out2.read_bytes()
    assert bytes1 == bytes2


# ──────────────────────────────  case-g value-mismatch no-op  ──────────────────────────────


def test_case_g_value_mismatch_no_op(tmp_path: Path) -> None:
    """case-g: prelude is PRESENT (header line) but its env value mismatches
    the struct. F002 is presence-only — it MUST no-op. F003's classifier is
    where value-mismatch becomes an i1 finding."""
    audit = _load_fixture("case-g-prelude-value-mismatch.json", agent="claude")
    summary_before = audit["summary"]
    expected_bytes = _expected_serialized(audit)

    out = audit_writer.write(audit, tmp_path)

    persisted = json.loads(out.read_text())
    # Summary unchanged (no second prelude prepended on top of the existing one)
    assert persisted["summary"] == summary_before
    # Still exactly one canonical header
    assert persisted["summary"].count(PRELUDE_HEADER) == 1
    # File bytes match the unchanged-summary serialization
    assert out.read_bytes() == expected_bytes


# ──────────────────────────────  case-d/e/f error paths (no-partial-artifact)  ──────────────────────────────


@pytest.mark.parametrize(
    ("fixture_name", "case"),
    [
        ("case-d-struct-absent.json", "d"),
        ("case-e-struct-invalid-empty-env.json", "e"),
        ("case-f-commands-without-target.json", "f"),
    ],
)
def test_invalid_struct_raises_no_partial_artifact(
    tmp_path: Path, fixture_name: str, case: str
) -> None:
    """5a-5d: persist case-d/e/f → TargetContextError; expected file does
    NOT exist after the raise; no `.tmp` / `.partial` siblings either."""
    audit = _load_fixture(fixture_name, agent="claude")
    expected_filename = _audit_filename(audit)

    with pytest.raises(TargetContextError):
        audit_writer.write(audit, tmp_path)

    # File must not exist (no half-write, no zero-byte placeholder).
    audit_dir = tmp_path / "audit"
    target_path = audit_dir / expected_filename
    assert target_path.exists() is False, f"{case}: envelope file leaked despite raise"

    # No sibling/temp artifacts in tmp_path or its audit/ subdir.
    if audit_dir.exists():
        leftover = sorted(p.name for p in audit_dir.iterdir())
        assert leftover == [], f"{case}: unexpected artifacts in audit/ → {leftover}"
    leaked_top = sorted(
        p.name
        for p in tmp_path.iterdir()
        # tmp_path is a clean dir; every entry is suspicious
    )
    assert leaked_top in ([], ["audit"]), f"{case}: stray files at plan_dir level → {leaked_top}"


# ──────────────────────────────  error-message context (audit_id + plan_id)  ──────────────────────────────


def test_error_message_carries_audit_id_and_plan_id(tmp_path: Path) -> None:
    """Acceptance #7: error messages include both `audit_id` and `plan_id`,
    verified by regex."""
    audit = _load_fixture("case-d-struct-absent.json", agent="claude")
    audit_id = audit["audit_id"]
    plan_id = audit["task_id"]

    with pytest.raises(TargetContextError) as exc_info:
        audit_writer.write(audit, tmp_path)

    msg = str(exc_info.value)
    pattern = rf"envelope {re.escape(audit_id)} for plan {re.escape(plan_id)}: "
    assert re.search(pattern, msg), msg


# ──────────────────────────────  logging  ──────────────────────────────


def test_log_info_on_injection(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Acceptance #8: INFO log line on injection."""
    audit = _load_fixture("case-a-implementer-missing-prelude.json", agent="claude")
    audit_id = audit["audit_id"]

    with caplog.at_level(logging.INFO, logger="jarvis_orchestrate.audit_writer"):
        audit_writer.write(audit, tmp_path)

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any(
        "injected target-context prelude" in r.message and audit_id in r.message
        for r in info_records
    ), [r.message for r in info_records]


def test_log_warning_on_validation_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Acceptance #8: WARNING log line on validation failure."""
    audit = _load_fixture("case-d-struct-absent.json", agent="claude")

    with caplog.at_level(logging.WARNING, logger="jarvis_orchestrate.audit_writer"):
        with pytest.raises(TargetContextError):
            audit_writer.write(audit, tmp_path)

    warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("envelope" in r.message and "for plan" in r.message for r in warn_records), [
        r.message for r in warn_records
    ]


def test_no_log_on_no_op(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Acceptance #8: no log on no-op (case-c is the canonical no-op shape)."""
    audit = _load_fixture("case-c-golden-valid-struct-valid-prelude.json", agent="claude")

    with caplog.at_level(logging.DEBUG, logger="jarvis_orchestrate.audit_writer"):
        audit_writer.write(audit, tmp_path)

    audit_writer_records = [
        r for r in caplog.records if r.name == "jarvis_orchestrate.audit_writer"
    ]
    assert audit_writer_records == [], (
        "no-op must produce no log line",
        [r.message for r in audit_writer_records],
    )


# ──────────────────────────────  forward-only proof (D007)  ──────────────────────────────


def test_forward_only_no_walk_of_historical_files(tmp_path: Path) -> None:
    """Acceptance #4: F002 must NOT walk historical envelopes.

    Strengthened proof per i1 auditor's exact text — a synthetic
    supervisor read-only inspection cycle. The supervisor reads prior
    audit JSON in two well-defined places that DO NOT call
    `audit_writer.write`:

      * ``circuit_breakers.check_diminishing_returns(audit_paths)``
      * ``circuit_breakers.check_convergence_collapse(audit_paths)``

    Both are invoked from ``supervisor.dispatch_volley`` after each
    auditor round to decide whether to trip a breaker (see
    ``supervisor.py`` lines 1093 / 1109). They `json.loads` each path
    and read fields off the dict — pure read-only inspection. We point
    them at the copied historical envelope (no canonical prelude) and
    assert both bytes AND mtime are unchanged on the original AND the
    copy. mtime stability proves we did not even touch the file (a
    write-and-restore would change mtime even if bytes happened to
    match).

    Auditor-readable structural supplement is in
    ``test_audit_writer_source_has_no_directory_walks``: search
    `audit_writer.py` for `glob` / `rglob` / `os.walk` / `iterdir`.
    """
    assert HISTORICAL_AUDIT.exists(), f"missing historical fixture: {HISTORICAL_AUDIT}"
    historical_bytes_before = HISTORICAL_AUDIT.read_bytes()
    historical_mtime_before = HISTORICAL_AUDIT.stat().st_mtime_ns
    assert b"## Target context" not in historical_bytes_before, (
        "historical fixture must lack the canonical prelude for this test"
    )

    copy_path = tmp_path / "audit" / "claude-implementer-i0.json"
    copy_path.parent.mkdir(parents=True)
    copy_path.write_bytes(historical_bytes_before)
    copy_mtime_before = copy_path.stat().st_mtime_ns

    # Synthetic supervisor read-only inspection cycle. These are the two
    # supervisor-internal helpers that read prior audit JSON files
    # (see supervisor.dispatch_volley around the per-iteration breaker
    # checks); both `json.loads(p.read_text())` each path and return a
    # (tripped, reason) tuple — they never call `audit_writer.write`.
    # Pointing them at the copied historical envelope exercises the
    # exact read path the supervisor uses, and the copy must remain
    # byte-and-mtime untouched.
    dr_tripped, _ = circuit_breakers.check_diminishing_returns([copy_path])
    cc_tripped, _ = circuit_breakers.check_convergence_collapse([copy_path])
    assert dr_tripped is False  # one envelope is below DIMINISHING_RETURNS_MIN_ROUNDS
    assert cc_tripped is False  # one envelope is below CONVERGENCE_COLLAPSE_WINDOW

    # Strong forward-only proof: audit_writer.write IS exercised in this
    # test, but on an UNRELATED envelope going to a separate plan dir.
    # F002 normalizes only what flows through `write`; the historical
    # envelope is a peer file that must be untouched even while the
    # write path is active in the same process.
    unrelated_audit = _load_fixture("case-c-golden-valid-struct-valid-prelude.json", agent="claude")
    unrelated_dir = tmp_path / "unrelated_plan_dir"
    unrelated_out = audit_writer.write(unrelated_audit, unrelated_dir)
    assert unrelated_out.exists()  # confirms write actually ran

    # Historical file at the original path is byte-and-mtime untouched.
    assert HISTORICAL_AUDIT.read_bytes() == historical_bytes_before
    assert HISTORICAL_AUDIT.stat().st_mtime_ns == historical_mtime_before, (
        "historical envelope mtime changed — F002 must not touch historical files"
    )
    # The tmp copy is also byte-and-mtime untouched after BOTH the
    # supervisor read-only cycle AND the unrelated-envelope write.
    assert copy_path.read_bytes() == historical_bytes_before
    assert copy_path.stat().st_mtime_ns == copy_mtime_before, (
        "tmp copy mtime changed — F002 write path must not touch peer files"
    )


def test_audit_writer_source_has_no_directory_walks() -> None:
    """Forward-only structural proof: audit_writer.py contains no glob
    walks of plan directories, no rglob, no os.walk, no migration script
    surface. Auditor reads the source; this test makes the property
    machine-checkable."""
    src = Path(audit_writer.__file__).read_text()
    forbidden = ("glob(", "rglob(", "os.walk", "iterdir(")
    hits = [pat for pat in forbidden if pat in src]
    assert hits == [], (
        f"audit_writer.py must not walk the filesystem (F002 D007 forward-only) — found {hits}"
    )


# ──────────────────────────────  PRELUDE_TEMPLATE / header sanity  ──────────────────────────────


def test_prelude_header_constant_matches_template_first_line() -> None:
    """The presence-detection header used by _normalize_summary must match
    the canonical template's first line + newline. Catches drift if D001
    is ever amended without the writer being updated."""
    assert PRELUDE_TEMPLATE.startswith(PRELUDE_HEADER)
