"""Plan 2026-07-27-001 F002 — doc-drift guard tests.

The guard fails when operator-facing docs (fixed allowlist: README.md and
the capability matrix doc) assert a non-registry agent as a shipped
executor. Source of truth is ``sorted(executors.AGENT_REGISTRY.keys())``.

Cases:

  (a) registered_worker_names() mirrors AGENT_REGISTRY exactly;
  (b) guard FAILS on fixture text that claims gemini is a shipped
      executor (the pre-F001 README checklist line + bare prose claim);
  (c) guard PASSES on the corrected phrasing (operator-only disclaimers
      on the same unit);
  (d) guard is registry-driven: the same "gemini executor" claim stops
      being a violation when gemini is present in the registered set;
  (e) disclaimers are segment-scoped per agent: a disclaimer on one agent
      must not excuse a shipped-executor claim about another agent in the
      same unit, across semicolon, period, comma, dash, AND conjunction
      separators (auditor F002-i0 finding 1, F002-i1 finding 1);
  (f) allowlist is fixed and scan skips allowlisted paths that do not
      exist yet (the matrix doc lands with F003);
  (g) acceptance: the committed repo docs scan clean against the LIVE
      registry;
  (h) watched agents derive from the canonical runtime universe
      (invocation_context.AGENT_RUNTIMES + ollama), not a hard-coded
      trio, so e.g. an OpenCode claim is caught (F002-i1 finding 2).

Historical fixtures (the pre-F001 README text and its correction) pin
``registered=HISTORICAL_REGISTRY`` — the registry as it stood when that
text shipped — so legitimately registering gemini/grok later cannot break
these tests (auditor F002-i0 finding 2). Only the acceptance case (g)
uses the live registry.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

REPO_ROOT = HERE.parents[3]

from dontpanic_orchestrate import doc_drift  # noqa: E402
from dontpanic_orchestrate.executors import AGENT_REGISTRY  # noqa: E402
from dontpanic_orchestrate.invocation_context import AGENT_RUNTIMES  # noqa: E402

# The registry as of the pre-F001 drift incident: only claude and codex
# shipped. Historical-fixture tests pin this so they stay valid even if
# more agents register later.
HISTORICAL_REGISTRY = frozenset({"claude", "codex"})

# The exact checklist line README shipped before F001 corrected it.
PRE_F001_CHECKLIST = (
    "- [x] Single-agent and volley dispatch (Claude, Codex, Gemini, Grok, Ollama executors)\n"
)

BARE_PROSE_CLAIM = "Gemini is a shipped executor and can be dispatched as a worker today.\n"

# Post-F001 phrasing: same topic, disclaimer in the same unit.
CORRECTED_CHECKLIST = (
    "- [x] Single-agent and volley dispatch (registered executors today: "
    "Claude and Codex — Gemini and Grok are operator-only runtimes, Ollama "
    "support is planned; `dontpanic agent status` is the source of truth)\n"
)

CORRECTED_PROSE = (
    "A worker has to be a registered executor — today that's `claude` and\n"
    "`codex`; `gemini` and `grok` are known operator-only runtimes — and an\n"
    "operator-only agent can't be assigned the `implementer` role.\n"
)


def test_registered_worker_names_mirror_registry() -> None:
    names = doc_drift.registered_worker_names()
    assert names == sorted(AGENT_REGISTRY)
    assert names, "registry must not be empty"


def test_guard_fails_on_pre_f001_checklist_line() -> None:
    violations = doc_drift.scan_text(PRE_F001_CHECKLIST, registered=HISTORICAL_REGISTRY)
    agents = {v.agent for v in violations}
    assert {"gemini", "grok", "ollama"} <= agents


def test_guard_fails_on_bare_prose_shipped_executor_claim() -> None:
    violations = doc_drift.scan_text(BARE_PROSE_CLAIM, registered=HISTORICAL_REGISTRY)
    assert [v.agent for v in violations] == ["gemini"]
    assert violations[0].line == 1


def test_guard_passes_on_corrected_checklist_and_prose() -> None:
    assert doc_drift.scan_text(CORRECTED_CHECKLIST, registered=HISTORICAL_REGISTRY) == []
    assert doc_drift.scan_text(CORRECTED_PROSE, registered=HISTORICAL_REGISTRY) == []


@pytest.mark.parametrize(
    "mixed_claim",
    [
        # The auditor's exact bypass probes (F002-i0 finding 1, F002-i1
        # finding 1): every separator between the bare claim and the other
        # agent's disclaimer must isolate the claim.
        "Gemini is a shipped executor; Grok is operator-only\n",
        "Gemini is a shipped executor. Grok is an operator-only runtime.\n",
        "Gemini is a shipped executor, while Grok is operator-only\n",
        "Gemini is a shipped executor — Ollama support is planned.\n",
        "Gemini is a shipped executor while Grok is operator-only\n",
        "Gemini is a shipped executor and Grok is operator-only\n",
        "Gemini is a shipped executor, but Grok is operator-only\n",
        # F002-i2 finding 1: a parenthetical disclaimer about ANOTHER agent
        # must not reclassify the claim segment it interrupts …
        "Gemini is a shipped executor (Grok is operator-only).\n",
        # … and a label apposition binds the agent to its claim label even
        # when a different agent's disclaimer follows.
        "Shipped executors — Gemini — Grok is operator-only.\n",
        "Executors: Gemini; Grok is operator-only.\n",
    ],
)
def test_disclaimer_for_one_agent_does_not_excuse_another(
    mixed_claim: str,
) -> None:
    violations = doc_drift.scan_text(mixed_claim, registered=HISTORICAL_REGISTRY)
    assert [v.agent for v in violations] == ["gemini"]


@pytest.mark.parametrize(
    "suppressed_claim",
    [
        # F002-i3 finding 1: a same-segment status-disclaimer keyword must
        # not suppress an explicit shipped-executor claim — "planned" /
        # "operator surfaces" here qualify the workload, not gemini's
        # dispatchability.
        "Gemini is a shipped executor for planned workflows.\n",
        "Gemini is a shipped executor available on operator surfaces.\n",
        # … and a parenthetical annotation must not excuse a mention whose
        # own clause continues straight into the claim predicate.
        "Gemini (operator-only) is a shipped executor.\n",
    ],
)
def test_status_disclaimer_cannot_suppress_explicit_claim(
    suppressed_claim: str,
) -> None:
    violations = doc_drift.scan_text(suppressed_claim, registered=HISTORICAL_REGISTRY)
    assert [v.agent for v in violations] == ["gemini"]


@pytest.mark.parametrize(
    "contradiction",
    [
        # F002-i4 finding 1: a preceding disclaimer half-clause must not
        # excuse a later shipped-executor claim in the same unit.
        "Gemini cannot be dispatched and is a shipped executor.\n",
        "Gemini is operator-only, but it is a shipped executor.\n",
        "Gemini cannot be dispatched; nevertheless it is a shipped executor.\n",
    ],
)
def test_preceding_disclaimer_cannot_suppress_later_claim(
    contradiction: str,
) -> None:
    violations = doc_drift.scan_text(contradiction, registered=HISTORICAL_REGISTRY)
    assert [v.agent for v in violations] == ["gemini"]


def test_em_dash_apposition_disclaimer_still_counts() -> None:
    # Dashes DO split segments, but the agent names sit in a neutral segment
    # whose nearest non-neutral neighbours are both disclaimers — excused.
    honest = "Operator-only runtimes — Gemini and Grok today — cannot be dispatched as workers.\n"
    assert doc_drift.scan_text(honest, registered=HISTORICAL_REGISTRY) == []


def test_bullet_disclaimer_after_conjunction_still_counts() -> None:
    # README install-bullet style: the agent leads the bullet, the disclaimer
    # arrives after a conjunction-separated neutral segment.
    honest = (
        "- **gemini CLI** — multimodal and long-context review as an "
        "operator-only runtime (not a dispatchable executor)\n"
    )
    assert doc_drift.scan_text(honest, registered=HISTORICAL_REGISTRY) == []


def test_unowned_attributive_disclaimer_still_excuses() -> None:
    # F002-i2 finding 1 counterweight: a disclaimer that names NO other agent
    # (the README diagram's "(operator-only)" annotation) attaches to the
    # mention it annotates even when a claim sits on the far side.
    honest = "Registered workers: Claude and Codex; Gemini (operator-only) also runs the CLI.\n"
    assert doc_drift.scan_text(honest, registered=HISTORICAL_REGISTRY) == []


def test_guard_watches_all_canonical_non_registry_runtimes() -> None:
    # F002-i1 finding 2: the auditor's exact bypass probe — opencode is a
    # canonical runtime with no executor, so the bare claim must flag.
    violations = doc_drift.scan_text(
        "OpenCode is a shipped executor.\n", registered=HISTORICAL_REGISTRY
    )
    assert [v.agent for v in violations] == ["opencode"]


def test_watched_agents_derive_from_canonical_runtime_universe() -> None:
    # Watched = canonical runtime universe + ollama (documented as planned),
    # never a hard-coded subset. Registry members are subtracted at scan time.
    assert set(doc_drift.WATCHED_AGENTS) == {*AGENT_RUNTIMES, "ollama"}
    assert {"opencode", "aider", "cursor", "antigravity"} <= set(doc_drift.WATCHED_AGENTS)


def test_guard_is_registry_driven_not_name_driven() -> None:
    # If gemini ever lands in AGENT_REGISTRY, the same claim is no longer
    # drift — the guard must relax without a code change here.
    violations = doc_drift.scan_text(BARE_PROSE_CLAIM, registered={"claude", "codex", "gemini"})
    assert violations == []


def test_allowlist_is_fixed_and_missing_paths_are_skipped(
    tmp_path: Path,
) -> None:
    assert doc_drift.DOC_ALLOWLIST == (
        "README.md",
        "docs/AGENT_CAPABILITY_MATRIX.md",
        "docs/CONFIGURATION.md",
    )
    (tmp_path / "README.md").write_text(PRE_F001_CHECKLIST, encoding="utf-8")
    # Other allowlisted paths intentionally absent (matrix lands with F003;
    # CONFIGURATION is optional for this fixture — missing paths are skipped).
    violations = doc_drift.scan_allowlisted_docs(tmp_path, registered=HISTORICAL_REGISTRY)
    assert violations
    assert {v.path for v in violations} == {"README.md"}


def test_repo_docs_scan_clean_against_live_registry() -> None:
    violations = doc_drift.scan_allowlisted_docs(REPO_ROOT)
    assert violations == [], "\n".join(str(v) for v in violations)
