"""Showcase artifact generator (Plan 2026-05-19-005 F001).

For each target in the showcase config, invokes the relevant capability
(architecture.regen / doctor validate-plans-strict / doctor
architecture-drift) against the target's external checkout, runs the
:class:`Redactor` over the rendered output, and writes atomically to
``docs/showcase/<repo_key>-<artifact>.{html,json}``.

Missing target checkouts are reported as ``skipped`` and the loop
continues — operators running on fresh clones shouldn't need every
sibling repo present to get partial output.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from dontpanic_orchestrate import architecture as _architecture
from dontpanic_orchestrate.showcase import config as _config
from dontpanic_orchestrate.showcase.redactor import RedactorError, redact_and_validate

# Repo root (DontPanic itself — where docs/showcase/ lives). Resolved
# lazily by the generator entry so tests can override via env var.
_DEFAULT_SHOWCASE_HOME_ENV = "DONTPANIC_SHOWCASE_HOME"


def _dontpanic_repo_root() -> Path:
    """Live DontPanic checkout root (where doctor + crawler live). Not
    overridable — these are import-time module sources, not output paths."""
    here = Path(__file__).resolve()
    return here.parents[3]


def _default_showcase_home() -> Path:
    """Repo root for showcase OUTPUT (docs/showcase/ lives under this).
    Honors ``DONTPANIC_SHOWCASE_HOME`` for test isolation — only affects
    where the generator WRITES artifacts, not where it loads the doctor
    module from."""
    override = os.environ.get(_DEFAULT_SHOWCASE_HOME_ENV)
    if override:
        return Path(override).resolve()
    return _dontpanic_repo_root()


_DOCTOR_MODULE_NAME = "dontpanic_doctor_showcase"


def _load_doctor():
    """Load scripts/dontpanic_doctor.py under a private module name so
    the showcase generator's import doesn't collide with any other
    module-level state the doctor might pull in during a test sweep."""
    if _DOCTOR_MODULE_NAME in sys.modules:
        return sys.modules[_DOCTOR_MODULE_NAME]
    doctor_path = _dontpanic_repo_root() / "scripts" / "dontpanic_doctor.py"
    spec = importlib.util.spec_from_file_location(_DOCTOR_MODULE_NAME, doctor_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load doctor module from {doctor_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_DOCTOR_MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


@dataclass(frozen=True)
class ArtifactResult:
    """Per-(target, artifact-kind) outcome."""

    repo_key: str
    artifact: str  # "architecture" | "validate_plans_strict" | "drift"
    status: str  # "success" | "skipped" | "failed"
    elapsed_s: float
    paths: tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["paths"] = list(self.paths)
        return d


@dataclass(frozen=True)
class TargetResult:
    repo_key: str
    label: str
    status: str  # "success" | "skipped" | "partial" | "failed"
    artifacts: tuple[ArtifactResult, ...]
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_key": self.repo_key,
            "label": self.label,
            "status": self.status,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ShowcaseRun:
    targets: tuple[TargetResult, ...]
    showcase_dir: str
    overall_exit: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "targets": [t.to_dict() for t in self.targets],
            "showcase_dir": self.showcase_dir,
            "overall_exit": self.overall_exit,
        }


def _atomic_write(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically (tmp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_name, path)
    except Exception:
        # Best effort: clean up the tmp file on any failure so we don't
        # litter docs/showcase/ with .tmp residue.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _emit_atomic(
    path: Path,
    content: str,
    *,
    repo_root: Path,
    repo_key: str,
    artifact: str,
) -> str:
    """Redact, validate, and write ``content`` to ``path``. Returns the
    final path as a string (for ArtifactResult.paths)."""
    redacted = redact_and_validate(
        content,
        repo_root=repo_root,
        repo_key=repo_key,
        artifact=artifact,
    )
    _atomic_write(path, redacted)
    return str(path.relative_to(_default_showcase_home())) if path.is_absolute() and path.is_relative_to(_default_showcase_home()) else str(path)


def _generate_architecture(
    target: _config.TargetSpec, showcase_dir: Path
) -> ArtifactResult:
    """Generate architecture JSON + HTML for ``target`` and write into
    ``showcase_dir`` as ``<repo_key>-architecture.{json,html}``."""
    artifact = "architecture"
    started = time.monotonic()
    json_out = showcase_dir / f"{target.repo_key}-architecture.json"
    html_out = showcase_dir / f"{target.repo_key}-architecture.html"

    # Stage to a temp dir so the architecture module's own atomic semantics
    # don't pollute docs/showcase/ with un-redacted content.
    try:
        with tempfile.TemporaryDirectory(prefix=f"showcase-arch-{target.repo_key}-") as tmp:
            tmp_dir = Path(tmp)
            tmp_json = tmp_dir / "architecture.json"
            _architecture.regen(
                target.repo_root,
                output_path=tmp_json,
                with_html=True,
                html_path=tmp_dir / "architecture.html",
            )
            json_content = tmp_json.read_text(encoding="utf-8")
            html_content = (tmp_dir / "architecture.html").read_text(encoding="utf-8")
            _emit_atomic(
                json_out,
                json_content,
                repo_root=target.repo_root,
                repo_key=target.repo_key,
                artifact=artifact,
            )
            _emit_atomic(
                html_out,
                html_content,
                repo_root=target.repo_root,
                repo_key=target.repo_key,
                artifact=artifact,
            )
    except RedactorError as exc:
        return ArtifactResult(
            repo_key=target.repo_key,
            artifact=artifact,
            status="failed",
            elapsed_s=round(time.monotonic() - started, 3),
            reason=f"redactor: {exc}",
        )
    except Exception as exc:  # noqa: BLE001 — surface any architecture failure
        return ArtifactResult(
            repo_key=target.repo_key,
            artifact=artifact,
            status="failed",
            elapsed_s=round(time.monotonic() - started, 3),
            reason=f"{exc.__class__.__name__}: {exc}",
        )

    return ArtifactResult(
        repo_key=target.repo_key,
        artifact=artifact,
        status="success",
        elapsed_s=round(time.monotonic() - started, 3),
        paths=(
            str(json_out.relative_to(_default_showcase_home())),
            str(html_out.relative_to(_default_showcase_home())),
        ),
    )


def _generate_validate_plans(
    target: _config.TargetSpec, showcase_dir: Path
) -> ArtifactResult:
    artifact = "validate_plans_strict"
    started = time.monotonic()
    out_path = showcase_dir / f"{target.repo_key}-validate-plans.json"
    doctor = _load_doctor()

    plans_root = target.repo_root / "docs" / "plans"
    if not plans_root.is_dir():
        return ArtifactResult(
            repo_key=target.repo_key,
            artifact=artifact,
            status="skipped",
            elapsed_s=round(time.monotonic() - started, 3),
            reason=f"no plans dir at {plans_root}",
        )

    try:
        results = doctor.validate_plans_strict(plans_root=plans_root, strict=False)
    except Exception as exc:  # noqa: BLE001
        return ArtifactResult(
            repo_key=target.repo_key,
            artifact=artifact,
            status="failed",
            elapsed_s=round(time.monotonic() - started, 3),
            reason=f"{exc.__class__.__name__}: {exc}",
        )

    summary = results[0]
    payload = {
        "repo_key": target.repo_key,
        "label": target.label,
        "plans_root": str(plans_root),
        "summary": {
            "name": summary.name,
            "ok": summary.ok,
            "warn": summary.warn,
            "message": summary.message,
        },
        "per_plan": summary.details or [],
        "findings": [
            {
                "name": r.name,
                "ok": r.ok,
                "warn": r.warn,
                "message": r.message,
                "remediation": r.remediation,
            }
            for r in results[1:]
        ],
    }
    json_content = json.dumps(payload, indent=2, sort_keys=True) + "\n"

    try:
        _emit_atomic(
            out_path,
            json_content,
            repo_root=target.repo_root,
            repo_key=target.repo_key,
            artifact=artifact,
        )
    except RedactorError as exc:
        return ArtifactResult(
            repo_key=target.repo_key,
            artifact=artifact,
            status="failed",
            elapsed_s=round(time.monotonic() - started, 3),
            reason=f"redactor: {exc}",
        )

    return ArtifactResult(
        repo_key=target.repo_key,
        artifact=artifact,
        status="success",
        elapsed_s=round(time.monotonic() - started, 3),
        paths=(str(out_path.relative_to(_default_showcase_home())),),
    )


def _generate_drift(target: _config.TargetSpec, showcase_dir: Path) -> ArtifactResult:
    artifact = "drift"
    started = time.monotonic()
    out_path = showcase_dir / f"{target.repo_key}-drift.json"
    doctor = _load_doctor()

    architecture_json = target.repo_root / "docs" / "architecture" / "architecture.json"
    try:
        result = doctor.check_architecture_drift(
            repo_root=target.repo_root,
            architecture_path=architecture_json,
            strict=False,
        )
    except Exception as exc:  # noqa: BLE001
        return ArtifactResult(
            repo_key=target.repo_key,
            artifact=artifact,
            status="failed",
            elapsed_s=round(time.monotonic() - started, 3),
            reason=f"{exc.__class__.__name__}: {exc}",
        )

    detail = (result.details or [{}])[0]
    payload = {
        "repo_key": target.repo_key,
        "label": target.label,
        "architecture_path": str(architecture_json),
        "state": detail.get("state"),
        "ok": result.ok,
        "warn": result.warn,
        "message": result.message,
        "recommendation": detail.get("recommendation"),
        "stored_fingerprint": detail.get("stored_fingerprint"),
        "current_fingerprint": detail.get("current_fingerprint"),
        "changed_files": detail.get("changed_files", {"added": [], "removed": [], "modified": []}),
        "changed_files_total": detail.get("changed_files_total", 0),
        "unchanged_files": detail.get("unchanged_files", 0),
        "drift_pct": detail.get("drift_pct"),
        "missing_required": detail.get("missing_required", []),
    }
    json_content = json.dumps(payload, indent=2, sort_keys=True) + "\n"

    try:
        _emit_atomic(
            out_path,
            json_content,
            repo_root=target.repo_root,
            repo_key=target.repo_key,
            artifact=artifact,
        )
    except RedactorError as exc:
        return ArtifactResult(
            repo_key=target.repo_key,
            artifact=artifact,
            status="failed",
            elapsed_s=round(time.monotonic() - started, 3),
            reason=f"redactor: {exc}",
        )

    return ArtifactResult(
        repo_key=target.repo_key,
        artifact=artifact,
        status="success",
        elapsed_s=round(time.monotonic() - started, 3),
        paths=(str(out_path.relative_to(_default_showcase_home())),),
    )


_ARTIFACT_DISPATCH = {
    "architecture": _generate_architecture,
    "validate_plans_strict": _generate_validate_plans,
    "drift": _generate_drift,
}


def _classify_target_status(artifacts: tuple[ArtifactResult, ...]) -> str:
    if not artifacts:
        return "skipped"
    if all(a.status == "skipped" for a in artifacts):
        return "skipped"
    if any(a.status == "failed" for a in artifacts):
        # Distinguish total-failure from partial when some succeeded.
        if any(a.status == "success" for a in artifacts):
            return "partial"
        return "failed"
    return "success"


def generate(
    *,
    targets: Iterable[_config.TargetSpec],
    showcase_dir: Path | None = None,
) -> ShowcaseRun:
    """Run the showcase generation loop over ``targets``.

    Returns a :class:`ShowcaseRun`. Exit code semantics:
      - 0: all attempted artifacts succeeded OR cleanly skipped (missing
        target / unsupported artifact kind)
      - 1: at least one artifact failed during generation (real defect)
      - 2: unrecoverable env blocker — docs/showcase/ not writable.
    """
    showcase_home = _default_showcase_home()
    out_dir = showcase_dir or (showcase_home / "docs" / "showcase")
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        # Probe writability — fail loud if docs/showcase/ is read-only.
        probe = out_dir / ".showcase-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return ShowcaseRun(
            targets=tuple(),
            showcase_dir=str(out_dir),
            overall_exit=2,
        )

    target_results: list[TargetResult] = []
    any_failed = False
    for target in targets:
        if not target.repo_root.is_dir():
            target_results.append(
                TargetResult(
                    repo_key=target.repo_key,
                    label=target.label,
                    status="skipped",
                    artifacts=tuple(),
                    reason=f"target not found at {target.repo_root}; skipping",
                )
            )
            continue

        artifacts: list[ArtifactResult] = []
        # Iterate in stable order so chip output + JSON shape don't churn.
        for kind in ("architecture", "validate_plans_strict", "drift"):
            if kind not in target.supported_artifacts:
                continue
            fn = _ARTIFACT_DISPATCH[kind]
            artifacts.append(fn(target, out_dir))

        status = _classify_target_status(tuple(artifacts))
        if status in ("failed", "partial"):
            any_failed = True
        target_results.append(
            TargetResult(
                repo_key=target.repo_key,
                label=target.label,
                status=status,
                artifacts=tuple(artifacts),
            )
        )

    return ShowcaseRun(
        targets=tuple(target_results),
        showcase_dir=str(out_dir),
        overall_exit=1 if any_failed else 0,
    )


def filter_targets(
    config_list: list[_config.TargetSpec],
    *,
    target_key: str | None = None,
    all_flag: bool = False,
) -> list[_config.TargetSpec]:
    """Resolve the active target list from the config + CLI flags.

    ``target_key`` filters to a single repo. Otherwise every target in
    ``config_list`` is returned — ``--all`` is the default invocation
    and is equivalent to "no --target". ``all_flag`` is accepted for
    CLI ergonomics but currently has no semantic effect: the contract
    is "--all == every configured target", which matches the bare
    ``regen`` invocation.
    """
    by_key = {t.repo_key: t for t in config_list}
    if target_key:
        if target_key not in by_key:
            available = ", ".join(sorted(by_key))
            raise KeyError(f"unknown target {target_key!r}; available: {available}")
        return [by_key[target_key]]
    return list(config_list)


def render_text(run: ShowcaseRun) -> str:
    """Pretty terminal output. One header line per target + one chip per
    artifact (status + elapsed_s)."""
    lines = []
    for t in run.targets:
        lines.append(f"[{t.status:<7}] {t.label} ({t.repo_key})")
        if t.reason and t.status == "skipped":
            lines.append(f"    ↳ {t.reason}")
        for a in t.artifacts:
            chip = {
                "success": "✓",
                "skipped": "·",
                "failed": "✗",
            }.get(a.status, "?")
            reason = f"  ↳ {a.reason}" if a.reason else ""
            lines.append(f"    {chip} {a.artifact:<24} {a.elapsed_s:>6.2f}s{reason}")
    lines.append("")
    lines.append(f"showcase_dir={run.showcase_dir}")
    return "\n".join(lines)


def render_json(run: ShowcaseRun) -> str:
    return json.dumps(run.to_dict(), indent=2, sort_keys=True)
