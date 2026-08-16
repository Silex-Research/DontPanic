"""Scenario file loader and JSON Schema validation (plan 2026-08-09-003 F001).

A scenario is a self-contained directory: the JSON file plus the plan
fixture it names. Fixtures resolve relative to the scenario file so a
copied directory still loads.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent / "schema" / "scenario.schema.json"
DEFAULT_SCENARIO_PATH = (
    Path(__file__).resolve().parent
    / "scenarios"
    / "2026-05-19-901-feat-smoke-synthetic"
    / "scenario.json"
)


class ScenarioLoadError(ValueError):
    """Raised when a scenario file fails schema or fixture validation."""

    def __init__(
        self,
        message: str,
        *,
        key: str | None = None,
        pointer: str | None = None,
    ) -> None:
        self.key = key
        self.pointer = pointer
        super().__init__(message)


@dataclass(frozen=True)
class ScriptedReply:
    agent: str
    role: str
    iteration: int
    summary: str
    success: bool = True
    raw_response: str = ""
    malformed: str | None = None
    quota_consumed: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Perturbation:
    kind: str
    call_index: int
    role: str | None = None
    agent: str | None = None
    exit_code: int | None = None


@dataclass(frozen=True)
class ExpectedState:
    terminal_state: str
    internals: dict[str, Any] | None = None


@dataclass(frozen=True)
class Scenario:
    id: str
    source_path: Path
    plan_id: str
    plan_fixture: Path
    features_fixture: Path
    feature_id: str
    feature_count: int
    max_iterations: int
    replies: tuple[ScriptedReply, ...]
    perturbations: tuple[Perturbation, ...]
    expected: ExpectedState
    suite: str | None = None
    source_incident: str | None = None
    source_date: str | None = None
    intended_behavior: str | None = None
    expected_current_behavior: str | None = None
    expected_to_fail: bool = False
    expected_to_fail_reason: str | None = None

    def reply_for(
        self, agent: str, role: str, iteration: int
    ) -> ScriptedReply | None:
        exact = [
            r
            for r in self.replies
            if r.agent == agent and r.role == role and r.iteration == iteration
        ]
        if exact:
            return exact[0]
        prior = [
            r
            for r in self.replies
            if r.agent == agent and r.role == role and r.iteration <= iteration
        ]
        if not prior:
            return None
        return max(prior, key=lambda r: r.iteration)


def _load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text())


def _raise_schema_error(
    source: Path,
    *,
    message: str,
    key: str | None,
    pointer: str,
    required: bool,
) -> None:
    named = key or "unknown"
    raise ScenarioLoadError(
        f"{source}: missing required key '{named}'" if required else f"{source}: {message}",
        key=named,
        pointer=pointer,
    )


def _validate_object(
    payload: Any,
    schema: dict[str, Any],
    *,
    source: Path,
    pointer: str,
) -> None:
    if schema.get("type") == "object":
        if not isinstance(payload, dict):
            _raise_schema_error(
                source,
                message=f"{pointer or '$'} must be an object",
                key=None,
                pointer=pointer or "$",
                required=False,
            )
        for key in schema.get("required") or []:
            if key not in payload:
                _raise_schema_error(
                    source,
                    message=f"missing required key '{key}'",
                    key=str(key),
                    pointer=pointer or "$",
                    required=True,
                )
        properties = schema.get("properties") or {}
        for key, value in payload.items():
            if key in properties:
                child = f"{pointer}/{key}" if pointer else f"/{key}"
                _validate_object(value, properties[key], source=source, pointer=child)
        return
    if schema.get("type") == "array":
        if not isinstance(payload, list):
            _raise_schema_error(
                source,
                message=f"{pointer} must be an array",
                key=pointer.rsplit("/", 1)[-1] or None,
                pointer=pointer,
                required=False,
            )
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(payload):
                _validate_object(
                    item, item_schema, source=source, pointer=f"{pointer}/{index}"
                )
        return
    expected = schema.get("type")
    if expected == "string" and not isinstance(payload, str):
        _raise_schema_error(
            source,
            message=f"{pointer} must be a string",
            key=pointer.rsplit("/", 1)[-1] or None,
            pointer=pointer,
            required=False,
        )
    if expected == "integer" and not isinstance(payload, int):
        _raise_schema_error(
            source,
            message=f"{pointer} must be an integer",
            key=pointer.rsplit("/", 1)[-1] or None,
            pointer=pointer,
            required=False,
        )
    if expected == "boolean" and not isinstance(payload, bool):
        _raise_schema_error(
            source,
            message=f"{pointer} must be a boolean",
            key=pointer.rsplit("/", 1)[-1] or None,
            pointer=pointer,
            required=False,
        )
    allowed = schema.get("enum")
    if allowed is not None and payload not in allowed:
        _raise_schema_error(
            source,
            message=f"{pointer} must be one of {allowed}",
            key=pointer.rsplit("/", 1)[-1] if pointer else None,
            pointer=pointer,
            required=False,
        )


def _validate_schema(payload: Any, source: Path) -> None:
    schema = _load_schema()
    try:
        import jsonschema
    except ImportError:
        _validate_object(payload, schema, source=source, pointer="")
        return
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if not errors:
        return
    err = errors[0]
    key: str | None = None
    if err.validator == "required" and err.validator_value:
        missing = err.message.split("'")
        if len(missing) >= 2:
            key = missing[1]
    elif err.path:
        key = str(list(err.path)[-1])
    pointer = "/" + "/".join(str(p) for p in err.absolute_path)
    _raise_schema_error(
        source,
        message=f"{err.message} (key={key or 'unknown'}, pointer={pointer})",
        key=key,
        pointer=pointer,
        required=err.validator == "required",
    )


def _parse_plan_id(plan_path: Path, features_path: Path) -> tuple[str, int, str]:
    feature_count = 0
    feature_id = "F001"
    plan_id = ""
    if features_path.is_file():
        features = json.loads(features_path.read_text())
        plan_id = str(features.get("task_id") or "")
        items: Sequence[Any] = features.get("features") or []
        feature_count = len(items)
        if items and isinstance(items[0], dict) and items[0].get("id"):
            feature_id = str(items[0]["id"])
    if not plan_id:
        text = plan_path.read_text()
        for line in text.splitlines():
            if line.startswith("id:"):
                plan_id = line.split(":", 1)[1].strip()
                break
    if not plan_id:
        raise ScenarioLoadError(
            f"{plan_path}: could not determine plan id",
            key="plan_fixture",
        )
    return plan_id, feature_count, feature_id


def load_scenario(path: Path | str) -> Scenario:
    """Load and validate a scenario file. Fixtures resolve relative to it."""
    source = Path(path).resolve()
    if not source.is_file():
        raise ScenarioLoadError(
            f"scenario path does not exist: {source}",
            key="scenario",
        )
    try:
        payload = json.loads(source.read_text())
    except json.JSONDecodeError as exc:
        raise ScenarioLoadError(f"{source}: malformed JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ScenarioLoadError(f"{source}: scenario root must be an object")
    _validate_schema(payload, source)

    base = source.parent
    plan_rel = str(payload["plan_fixture"])
    plan_fixture = (base / plan_rel).resolve()
    if not plan_fixture.is_file():
        raise ScenarioLoadError(
            f"fixture path does not exist: {plan_fixture}",
            key="plan_fixture",
        )
    features_rel = str(payload.get("features_fixture") or "./features.json")
    features_fixture = (base / features_rel).resolve()
    if not features_fixture.is_file():
        raise ScenarioLoadError(
            f"fixture path does not exist: {features_fixture}",
            key="features_fixture",
        )

    plan_id, feature_count, default_feature = _parse_plan_id(
        plan_fixture, features_fixture
    )
    replies = tuple(
        ScriptedReply(
            agent=str(item["agent"]),
            role=str(item["role"]),
            iteration=int(item["iteration"]),
            summary=str(item["summary"]),
            success=bool(item.get("success", True)),
            raw_response=str(item.get("raw_response") or ""),
            malformed=item.get("malformed"),
            quota_consumed={
                "tokens_in": int((item.get("quota_consumed") or {}).get("tokens_in") or 0),
                "tokens_out": int(
                    (item.get("quota_consumed") or {}).get("tokens_out") or 0
                ),
            },
        )
        for item in payload["replies"]
    )
    perturbations = tuple(
        Perturbation(
            kind=str(item["kind"]),
            call_index=int(item["call_index"]),
            role=item.get("role"),
            agent=item.get("agent"),
            exit_code=item.get("exit_code"),
        )
        for item in (payload.get("perturbations") or [])
    )
    expected_raw = payload["expected"]
    expected = ExpectedState(
        terminal_state=str(expected_raw["terminal_state"]),
        internals=expected_raw.get("internals"),
    )
    return Scenario(
        id=str(payload["id"]),
        source_path=source,
        plan_id=plan_id,
        plan_fixture=plan_fixture,
        features_fixture=features_fixture,
        feature_id=str(payload.get("feature_id") or default_feature),
        feature_count=feature_count,
        max_iterations=int(payload.get("max_iterations") or 1),
        replies=replies,
        perturbations=perturbations,
        expected=expected,
        suite=payload.get("suite"),
        source_incident=payload.get("source_incident"),
        source_date=payload.get("source_date"),
        intended_behavior=payload.get("intended_behavior"),
        expected_current_behavior=payload.get("expected_current_behavior"),
        expected_to_fail=bool(payload.get("expected_to_fail", False)),
        expected_to_fail_reason=payload.get("expected_to_fail_reason"),
    )
