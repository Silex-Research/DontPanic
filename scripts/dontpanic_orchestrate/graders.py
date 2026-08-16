"""Plan 2026-08-09-004 F001 — grader contract.

Graders read a trial's artifacts and return typed results. They never write,
never re-invoke the supervisor, and never treat silence as a pass.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class GraderVerdict(Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class GraderResult:
    verdict: GraderVerdict
    reason: str
    artifact: str
    grader_id: str
    component: str

    def __post_init__(self) -> None:
        if not self.component:
            raise ValueError("GraderResult.component is required")
        if not self.grader_id:
            raise ValueError("GraderResult.grader_id is required")
        if not self.reason:
            raise ValueError("GraderResult.reason is required")


@dataclass(frozen=True)
class TrialRecord:
    id: str
    expected_terminal: str


@dataclass(frozen=True)
class TrialArtifacts:
    root: Path

    def path(self, name: str) -> Path:
        return self.root / name


@dataclass(frozen=True)
class GradeSummary:
    passed: bool
    failed: bool
    not_applicable: bool


def aggregate(results: Sequence[GraderResult]) -> GradeSummary:
    """Distinguish not-applicable from pass. Absence is never success."""
    if not results:
        return GradeSummary(passed=False, failed=False, not_applicable=True)
    verdicts = {r.verdict for r in results}
    return GradeSummary(
        passed=verdicts == {GraderVerdict.PASS},
        failed=GraderVerdict.FAIL in verdicts,
        not_applicable=verdicts == {GraderVerdict.NOT_APPLICABLE},
    )


_PLAN_REQUIRED_KEYS: tuple[str, ...] = (
    "id",
    "title",
    "type",
    "status",
    "date",
    "description",
)


def _frontmatter(text: str) -> dict[str, object]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    block = text[3:end]
    out: dict[str, object] = {}
    for line in block.splitlines():
        if ":" not in line or line.startswith(" ") or line.startswith("\t"):
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip().strip('"')
    return out


def schema_grader(trial: TrialRecord, artifacts: TrialArtifacts) -> Iterable[GraderResult]:
    """F002 — required frontmatter keys present. Does not write."""
    _ = trial
    plan = artifacts.path("plan.md")
    if not plan.is_file():
        yield GraderResult(
            verdict=GraderVerdict.NOT_APPLICABLE,
            reason="no plan.md in trial artifacts",
            artifact="(none)",
            grader_id="schema",
            component="harness",
        )
        return
    meta = _frontmatter(plan.read_text())
    missing = [key for key in _PLAN_REQUIRED_KEYS if not meta.get(key)]
    if missing:
        yield GraderResult(
            verdict=GraderVerdict.FAIL,
            reason=f"plan.md missing required frontmatter key: {missing[0]}",
            artifact="plan.md",
            grader_id="schema",
            component="system",
        )
        return
    yield GraderResult(
        verdict=GraderVerdict.PASS,
        reason="plan.md carries required frontmatter keys",
        artifact="plan.md",
        grader_id="schema",
        component="system",
    )


def evidence_grader(trial: TrialRecord, artifacts: TrialArtifacts) -> Iterable[GraderResult]:
    """F002 — a feature flipped to passing must carry verifier, time, evidence."""
    import json

    _ = trial
    path = artifacts.path("features.json")
    if not path.is_file():
        yield GraderResult(
            verdict=GraderVerdict.NOT_APPLICABLE,
            reason="no features.json in trial artifacts",
            artifact="(none)",
            grader_id="evidence",
            component="harness",
        )
        return
    data = json.loads(path.read_text())
    features = data.get("features") or []
    for feature in features:
        if not feature.get("passes"):
            continue
        refs = feature.get("evidence_refs") or []
        if not refs or not feature.get("verified_by") or not feature.get("verified_at"):
            yield GraderResult(
                verdict=GraderVerdict.FAIL,
                reason=(
                    f"{feature.get('id', '?')} is passes=true without "
                    "verified_by, verified_at, and a non-empty evidence_refs"
                ),
                artifact="features.json",
                grader_id="evidence",
                component="system",
            )
            return
    yield GraderResult(
        verdict=GraderVerdict.PASS,
        reason="every passing feature carries verifier, timestamp, and evidence",
        artifact="features.json",
        grader_id="evidence",
        component="system",
    )


def gate_agreement_grader(
    trial: TrialRecord, artifacts: TrialArtifacts
) -> Iterable[GraderResult]:
    """F003 — cleared gates and the event log name the same set."""
    import json

    _ = trial
    state_path = artifacts.path("gate-state.json")
    log_path = artifacts.path("events.jsonl")
    if not state_path.is_file() or not log_path.is_file():
        yield GraderResult(
            verdict=GraderVerdict.NOT_APPLICABLE,
            reason="gate-state.json or events.jsonl missing",
            artifact="(none)",
            grader_id="gate_agreement",
            component="harness",
        )
        return
    state = json.loads(state_path.read_text())
    cleared = {str(g) for g in (state.get("cleared_gates") or [])}
    logged: set[str] = set()
    for line in log_path.read_text().splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("event") == "gate_cleared" and entry.get("gate"):
            logged.add(str(entry["gate"]))
    extra_state = sorted(cleared - logged)
    extra_log = sorted(logged - cleared)
    if extra_state:
        yield GraderResult(
            verdict=GraderVerdict.FAIL,
            reason=f"gate-state cleared {extra_state} with no matching event",
            artifact="gate-state.json",
            grader_id="gate_agreement",
            component="system",
        )
        return
    if extra_log:
        yield GraderResult(
            verdict=GraderVerdict.FAIL,
            reason=f"event log cleared {extra_log} with no matching gate-state entry",
            artifact="events.jsonl",
            grader_id="gate_agreement",
            component="system",
        )
        return
    yield GraderResult(
        verdict=GraderVerdict.PASS,
        reason="cleared gates and event log agree",
        artifact="gate-state.json",
        grader_id="gate_agreement",
        component="system",
    )


def target_boundary_grader(
    trial: TrialRecord, artifacts: TrialArtifacts
) -> Iterable[GraderResult]:
    """F003 — writes must land inside a repository the plan declared."""
    import json

    _ = trial
    declared_path = artifacts.path("declared_repos.json")
    written_path = artifacts.path("written_files.json")
    if not declared_path.is_file() or not written_path.is_file():
        yield GraderResult(
            verdict=GraderVerdict.NOT_APPLICABLE,
            reason="declared_repos.json or written_files.json missing",
            artifact="(none)",
            grader_id="target_boundary",
            component="harness",
        )
        return
    declared = [str(r) for r in json.loads(declared_path.read_text())]
    written = [str(p) for p in json.loads(written_path.read_text())]
    for path in written:
        if not any(token in path for token in declared):
            yield GraderResult(
                verdict=GraderVerdict.FAIL,
                reason=f"wrote outside declared repositories: {path}",
                artifact=path,
                grader_id="target_boundary",
                component="system",
            )
            return
    yield GraderResult(
        verdict=GraderVerdict.PASS,
        reason="every write landed inside a declared repository",
        artifact="written_files.json",
        grader_id="target_boundary",
        component="system",
    )


def operational_validity_grader(
    trial: TrialRecord, artifacts: TrialArtifacts
) -> Iterable[GraderResult]:
    """F004 — token shape and handler dry-run are two separate verdicts."""
    import json
    import shlex

    from dontpanic_orchestrate import command_validation, completion_gate

    _ = trial
    path = artifacts.path("rendered_commands.json")
    if not path.is_file():
        yield GraderResult(
            verdict=GraderVerdict.NOT_APPLICABLE,
            reason="no rendered_commands.json",
            artifact="(none)",
            grader_id="operational_token",
            component="harness",
        )
        return
    commands = json.loads(path.read_text())
    for raw in commands:
        try:
            tokens = shlex.split(str(raw))
        except ValueError:
            yield GraderResult(
                verdict=GraderVerdict.FAIL,
                reason=f"unparseable command: {raw}",
                artifact=str(raw),
                grader_id="operational_token",
                component="system",
            )
            continue
        if tokens and tokens[0] in {"dontpanic", "jarvis"}:
            tokens = tokens[1:]
        token_result = command_validation.validate_command_tokens(tokens)
        yield GraderResult(
            verdict=GraderVerdict.PASS if token_result.ok else GraderVerdict.FAIL,
            reason=(
                "token shape accepted"
                if token_result.ok
                else f"token shape rejected: {token_result}"
            ),
            artifact=str(raw),
            grader_id="operational_token",
            component="system",
        )
        if tokens[:2] == ["plan", "close"]:
            try:
                completion_gate.close_plan(artifacts.root, dry_run=True)
            except completion_gate.CompletionGateError as exc:
                yield GraderResult(
                    verdict=GraderVerdict.FAIL,
                    reason=f"handler refused dry-run: {exc}",
                    artifact=str(raw),
                    grader_id="operational_dry_run",
                    component="system",
                )
            else:
                yield GraderResult(
                    verdict=GraderVerdict.PASS,
                    reason="close_plan accepted the command in dry-run",
                    artifact=str(raw),
                    grader_id="operational_dry_run",
                    component="system",
                )
        else:
            yield GraderResult(
                verdict=GraderVerdict.NOT_APPLICABLE,
                reason="no safe dry-run handler for this command",
                artifact=str(raw),
                grader_id="operational_dry_run",
                component="harness",
            )


JUDGE_RUBRIC_VERSION = "judge-rubric-v0"


def _invoke_judge_model(prompt: str) -> str:
    """Opt-in only. Tests monkeypatch this; default run never calls it."""
    raise RuntimeError("judge model is disabled unless explicitly enabled")


def judge_grader(
    trial: TrialRecord,
    artifacts: TrialArtifacts,
    *,
    enabled: bool = False,
    deterministic_mismatch: bool = False,
) -> Iterable[GraderResult]:
    """F005 — narrative judge. Off by default. Never required for a default run."""
    import json

    _ = trial
    if not enabled:
        yield GraderResult(
            verdict=GraderVerdict.NOT_APPLICABLE,
            reason=(
                "judge disabled; dimensions not evaluated: "
                "decision rationale, audit summary / structured verdict"
            ),
            artifact=JUDGE_RUBRIC_VERSION,
            grader_id="judge",
            component="harness",
        )
        return
    if deterministic_mismatch:
        yield GraderResult(
            verdict=GraderVerdict.FAIL,
            reason="deterministic verdict-mismatch detector is authoritative",
            artifact=JUDGE_RUBRIC_VERSION,
            grader_id="judge_authoritative",
            component="system",
        )
    decisions = artifacts.path("decisions.jsonl")
    if decisions.is_file():
        for line in decisions.read_text().splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            rationale = str(entry.get("rationale") or "")
            answer = str(entry.get("answer") or "")
            restates = rationale.strip().rstrip(".") == answer.strip().rstrip(".")
            yield GraderResult(
                verdict=GraderVerdict.FAIL if restates else GraderVerdict.PASS,
                reason=(
                    f"{JUDGE_RUBRIC_VERSION}: rationale restates the decision"
                    if restates
                    else f"{JUDGE_RUBRIC_VERSION}: rationale gives a reason"
                ),
                artifact=JUDGE_RUBRIC_VERSION,
                grader_id="judge",
                component="system",
            )
    audit = artifacts.path("audit.json")
    if audit.is_file() and not deterministic_mismatch:
        payload = json.loads(audit.read_text())
        narrative = str(payload.get("narrative_verdict") or "")
        structured = str(payload.get("structured_status") or "")
        agree = narrative == structured
        yield GraderResult(
            verdict=GraderVerdict.PASS if agree else GraderVerdict.FAIL,
            reason=f"{JUDGE_RUBRIC_VERSION}: narrative vs structured",
            artifact=JUDGE_RUBRIC_VERSION,
            grader_id="judge",
            component="system",
        )


@dataclass(frozen=True)
class JudgeLabel:
    id: str
    labeled_by: str
    labeled_at: str
    human_verdict: str
    text: str
    decision: str = ""


@dataclass(frozen=True)
class JudgeDivergence:
    id: str
    human_verdict: str
    judge_verdict: str
    human_reason: str
    judge_reason: str


@dataclass(frozen=True)
class CalibrationReport:
    sample_size: int
    agreement_rate: float
    labels: tuple[JudgeLabel, ...]
    divergent: tuple[JudgeDivergence, ...]
    text: str


def _judge_rationale(text: str, decision: str) -> tuple[str, str]:
    if decision and text.strip().rstrip(".") == decision.strip().rstrip("."):
        return "restatement", "rationale restates the decision"
    return "reason", "rationale gives a reason"


def calibrate_judge(labels_path: Path) -> CalibrationReport:
    """F006 — agreement of the heuristic judge against a labeled subset."""
    import json

    raw = json.loads(Path(labels_path).read_text())
    labels = tuple(
        JudgeLabel(
            id=str(item["id"]),
            labeled_by=str(item["labeled_by"]),
            labeled_at=str(item["labeled_at"]),
            human_verdict=str(item["human_verdict"]),
            text=str(item.get("text") or ""),
            decision=str(item.get("decision") or ""),
        )
        for item in raw.get("labels") or []
    )
    divergent: list[JudgeDivergence] = []
    agree = 0
    for label in labels:
        judge_verdict, judge_reason = _judge_rationale(label.text, label.decision)
        if judge_verdict == label.human_verdict:
            agree += 1
        else:
            divergent.append(
                JudgeDivergence(
                    id=label.id,
                    human_verdict=label.human_verdict,
                    judge_verdict=judge_verdict,
                    human_reason=f"human labeled {label.human_verdict}",
                    judge_reason=judge_reason,
                )
            )
    n = len(labels)
    rate = (agree / n) if n else 0.0
    pct = f"{rate:.0%}"
    text = (
        f"Agreement rate {pct} on a labeled set of {n}. "
        "An agreement rate over a subset this size is an indication, not a guarantee."
    )
    return CalibrationReport(
        sample_size=n,
        agreement_rate=rate,
        labels=labels,
        divergent=tuple(divergent),
        text=text,
    )


def silent_grader(trial: TrialRecord, artifacts: TrialArtifacts) -> Iterable[GraderResult]:
    """F001 fixture grader: no opinion. Concrete graders arrive in F002–F004."""
    _ = (trial, artifacts)
    yield GraderResult(
        verdict=GraderVerdict.NOT_APPLICABLE,
        reason="no opinion — interface fixture",
        artifact="(none)",
        grader_id="silent",
        component="harness",
    )
