"""Opt-in CLI evidence producers — `dontpanic evidence run` and `evidence capture`.

Plan PR#74: explicit opt-in command recording and capture per the
locked brainstorm `docs/brainstorms/2026-09-06-command-evidence-capture.md`.

Public entry points:
    evidence_main(argv) -> int
    evidence_run_main(argv) -> int
    evidence_capture_main(argv) -> int

CLI forms:
    dontpanic evidence run PLAN --feature F --iteration N --cwd ROOT
        --timeout-seconds N --confirm -- COMMAND ARG...
    dontpanic evidence capture PLAN --journey NAME --source NAME
        --config FILE --confirm

Both commands require `--confirm` for side effects; dry-run validates
inputs without execution or publication.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


INVOCATION_RECORD_DIR = "evidence/invocations"
CAPTURE_MANIFEST_DIR = "evidence/captures"

MIN_TIMEOUT_SECONDS = 10
MAX_TIMEOUT_SECONDS = 7200
DEFAULT_TIMEOUT_SECONDS = 600

OUTPUT_CAP_BYTES = 1024 * 100
OUTPUT_CAP_LINES = 500

SENSITIVE_ENV_PREFIXES = (
    "AWS_SECRET",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "FIREBASE",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "DATABASE_PASSWORD",
    "DB_PASSWORD",
    "SECRET",
    "PASSWORD",
    "API_KEY",
    "PRIVATE_KEY",
    "TOKEN",
)


class EvidenceRunError(ValueError):
    """Raised when evidence run validation fails before execution."""


class EvidenceCaptureError(ValueError):
    """Raised when evidence capture validation fails before publication."""


class InvocationRecord(BaseModel):
    """One command execution record written to evidence/invocations/."""

    model_config = ConfigDict(extra="forbid")

    invocation_id: str = Field(..., min_length=1)
    plan_id: str = Field(..., min_length=1)
    feature_id: str = Field(..., min_length=1)
    iteration: int = Field(..., ge=0)
    argv_display: list[str] = Field(..., min_length=1)
    argv_digest: str = Field(..., min_length=1)
    canonical_cwd: str = Field(..., min_length=1)
    code_revision: str | None = None
    dirty_diff_hash: str | None = None
    started_at: str = Field(..., min_length=1)
    ended_at: str | None = None
    exit_code: int | None = None
    timed_out: bool = False
    cancelled: bool = False
    spawn_error: str | None = None
    stdout_hash: str | None = None
    stderr_hash: str | None = None
    stdout_excerpt: str | None = None
    stderr_excerpt: str | None = None
    status: str = Field(..., pattern="^(started|completed|incomplete)$")


class CaptureManifest(BaseModel):
    """Manifest for an evidence capture run."""

    model_config = ConfigDict(extra="forbid")

    capture_id: str = Field(..., min_length=1)
    plan_id: str = Field(..., min_length=1)
    journey: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)
    captured_at: str = Field(..., min_length=1)
    config_path: str | None = None
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    skipped_sources: list[dict[str, str]] = Field(default_factory=list)
    status: str = Field(..., pattern="^(completed|skipped|error)$")


def _resolve_plan_dir(plan_arg: str) -> Path:
    """Resolve a plan ID or path to a plan directory."""
    p = Path(plan_arg)
    if p.is_dir():
        return p.resolve()
    cwd_match = Path.cwd() / "docs" / "plans" / plan_arg
    if cwd_match.is_dir():
        return cwd_match.resolve()
    raise EvidenceRunError(f"plan not found: {plan_arg}")


def _load_plan_features(plan_dir: Path) -> tuple[str, list[str]]:
    """Load plan ID and feature IDs from plan directory."""
    plan_md = plan_dir / "plan.md"
    features_json = plan_dir / "features.json"

    if not plan_md.is_file():
        raise EvidenceRunError(f"plan.md not found in {plan_dir}")
    if not features_json.is_file():
        raise EvidenceRunError(f"features.json not found in {plan_dir}")

    text = plan_md.read_text()
    if not text.startswith("---"):
        raise EvidenceRunError(f"plan.md missing frontmatter: {plan_md}")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise EvidenceRunError(f"malformed frontmatter in {plan_md}")

    import yaml

    fm = yaml.safe_load(parts[1])
    plan_id = fm.get("id")
    if not plan_id:
        raise EvidenceRunError(f"plan.md missing id in frontmatter: {plan_md}")

    features_data = json.loads(features_json.read_text())
    feature_ids = [f["id"] for f in features_data.get("features", [])]

    return plan_id, feature_ids


def _validate_cwd_containment(plan_dir: Path, cwd: Path) -> Path:
    """Validate that cwd is contained within reasonable bounds (no traversal)."""
    cwd_resolved = cwd.resolve()

    repo_root = plan_dir
    for _ in range(5):
        if (repo_root / ".git").exists():
            break
        parent = repo_root.parent
        if parent == repo_root:
            break
        repo_root = parent

    plan_root = plan_dir.resolve()
    home = Path.home().resolve()

    if ".." in str(cwd):
        raise EvidenceRunError(f"cwd contains path traversal component: {cwd}")

    if cwd_resolved.is_relative_to(repo_root):
        return cwd_resolved
    if cwd_resolved.is_relative_to(home):
        return cwd_resolved
    if cwd_resolved.is_relative_to(Path("/tmp")):
        return cwd_resolved

    raise EvidenceRunError(
        f"cwd {cwd} is not within repo root {repo_root}, home {home}, or /tmp"
    )


def _get_git_revision(cwd: Path) -> tuple[str | None, str | None]:
    """Get current git revision and dirty diff hash."""
    try:
        rev_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=5,
        )
        revision = rev_result.stdout.strip() if rev_result.returncode == 0 else None

        diff_result = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if diff_result.returncode == 0 and diff_result.stdout:
            dirty_hash = hashlib.sha256(diff_result.stdout.encode()).hexdigest()[:16]
        else:
            dirty_hash = None

        return revision, dirty_hash
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None, None


def _redact_argv(argv: list[str]) -> list[str]:
    """Redact sensitive arguments from argv for display."""
    redacted: list[str] = []
    skip_next = False

    for i, arg in enumerate(argv):
        if skip_next:
            redacted.append("[REDACTED]")
            skip_next = False
            continue

        lower = arg.lower()
        is_sensitive_flag = any(
            f in lower
            for f in ("--secret", "--token", "--password", "--api-key", "--key=")
        )

        if is_sensitive_flag:
            if "=" in arg:
                key, _ = arg.split("=", 1)
                redacted.append(f"{key}=[REDACTED]")
            else:
                redacted.append(arg)
                skip_next = True
        else:
            looks_like_token = (
                len(arg) > 20
                and any(c.isalnum() for c in arg)
                and ("ghp_" in arg or "sk-" in arg or "Bearer" in arg)
            )
            if looks_like_token:
                redacted.append("[REDACTED]")
            else:
                redacted.append(arg)

    return redacted


def _hash_content(content: bytes) -> str:
    """Return sha256 hash of content."""
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _excerpt_output(output: bytes, max_bytes: int = OUTPUT_CAP_BYTES) -> str:
    """Return a redacted, truncated excerpt of output."""
    try:
        text = output.decode("utf-8", errors="replace")
    except Exception:
        text = output.hex()[:max_bytes]

    lines = text.split("\n")
    if len(lines) > OUTPUT_CAP_LINES:
        lines = lines[:OUTPUT_CAP_LINES] + [f"... ({len(lines) - OUTPUT_CAP_LINES} more lines)"]

    excerpt = "\n".join(lines)
    if len(excerpt) > max_bytes:
        excerpt = excerpt[:max_bytes] + f"... (truncated at {max_bytes} bytes)"

    from dontpanic_orchestrate.state_projection import scrub_secrets

    return scrub_secrets(excerpt) or excerpt


def _filter_env_for_subprocess() -> dict[str, str]:
    """Return a filtered environment dict that excludes sensitive vars."""
    env = dict(os.environ)
    filtered: dict[str, str] = {}

    for key, value in env.items():
        is_sensitive = any(
            key.upper().startswith(prefix) or key.upper().endswith(prefix)
            for prefix in SENSITIVE_ENV_PREFIXES
        )
        if not is_sensitive:
            filtered[key] = value

    return filtered


def _write_invocation_record(plan_dir: Path, record: InvocationRecord) -> Path:
    """Write an invocation record to the plan's evidence directory."""
    out_dir = plan_dir / INVOCATION_RECORD_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{record.invocation_id}.json"
    out_path.write_text(json.dumps(record.model_dump(), indent=2) + "\n")
    return out_path


def _run_command(
    argv: list[str],
    cwd: Path,
    timeout_seconds: int,
) -> tuple[int | None, bytes, bytes, bool, bool, str | None]:
    """Execute command and return (exit_code, stdout, stderr, timed_out, cancelled, spawn_error)."""
    env = _filter_env_for_subprocess()

    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except (FileNotFoundError, OSError) as exc:
        return None, b"", f"{type(exc).__name__}: {exc}".encode(), False, False, str(exc)

    pgid = proc.pid
    timed_out = False
    cancelled = False

    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(pgid, signal.SIGTERM)
        except OSError:
            pass
        try:
            stdout, stderr = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except OSError:
                pass
            stdout, stderr = proc.communicate()
    except KeyboardInterrupt:
        cancelled = True
        try:
            os.killpg(pgid, signal.SIGTERM)
        except OSError:
            pass
        stdout, stderr = proc.communicate()

    return proc.returncode, stdout or b"", stderr or b"", timed_out, cancelled, None


def evidence_run_main(argv: list[str] | None = None) -> int:
    """Entry point for `dontpanic evidence run`.

    Exit codes:
        0 — command executed successfully (exit 0)
        1 — command executed with non-zero exit
        2 — usage error / validation failure
        3 — execution error (timeout, spawn failure, etc.)
    """
    if argv is None:
        argv = sys.argv[1:]

    try:
        sep_idx = argv.index("--")
        pre_sep = argv[:sep_idx]
        command = argv[sep_idx + 1 :]
    except ValueError:
        pre_sep = argv
        command = []

    parser = argparse.ArgumentParser(
        prog="dontpanic evidence run",
        description="Record a command execution as evidence for a plan feature.",
    )
    parser.add_argument("plan", help="Plan ID or path")
    parser.add_argument("--feature", "-f", required=True, help="Feature ID (e.g. F001)")
    parser.add_argument("--iteration", "-i", type=int, required=True, help="Iteration number")
    parser.add_argument("--cwd", type=Path, default=None, help="Working directory for command")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Command timeout (default {DEFAULT_TIMEOUT_SECONDS}, range {MIN_TIMEOUT_SECONDS}-{MAX_TIMEOUT_SECONDS})",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Execute the command (dry-run without this flag)",
    )

    args = parser.parse_args(pre_sep)
    args.command = command

    if not args.command:
        print("error: no command specified (use -- COMMAND ARG...)", file=sys.stderr)
        return 2

    if not (MIN_TIMEOUT_SECONDS <= args.timeout_seconds <= MAX_TIMEOUT_SECONDS):
        print(
            f"error: --timeout-seconds must be between {MIN_TIMEOUT_SECONDS} and {MAX_TIMEOUT_SECONDS}",
            file=sys.stderr,
        )
        return 2

    try:
        plan_dir = _resolve_plan_dir(args.plan)
    except EvidenceRunError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        plan_id, feature_ids = _load_plan_features(plan_dir)
    except EvidenceRunError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.feature not in feature_ids:
        print(
            f"error: feature {args.feature!r} not found in plan {plan_id}; "
            f"available: {', '.join(feature_ids)}",
            file=sys.stderr,
        )
        return 2

    if args.iteration < 0:
        print(f"error: iteration must be >= 0, got {args.iteration}", file=sys.stderr)
        return 2

    cwd = args.cwd or Path.cwd()
    try:
        cwd = _validate_cwd_containment(plan_dir, cwd)
    except EvidenceRunError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    invocation_id = f"inv-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    argv_display = _redact_argv(args.command)
    argv_digest = hashlib.sha256(" ".join(args.command).encode()).hexdigest()[:16]
    revision, dirty_hash = _get_git_revision(cwd)

    print(f"Plan: {plan_id}")
    print(f"Feature: {args.feature}")
    print(f"Iteration: {args.iteration}")
    print(f"Command: {' '.join(argv_display)}")
    print(f"CWD: {cwd}")
    print(f"Timeout: {args.timeout_seconds}s")
    print(f"Revision: {revision or 'unknown'}")
    if dirty_hash:
        print(f"Dirty hash: {dirty_hash}")

    if not args.confirm:
        print("\n[dry-run] Would execute command and record evidence.")
        print("Add --confirm to execute.")
        return 0

    started_at = datetime.now(timezone.utc).isoformat()

    initial_record = InvocationRecord(
        invocation_id=invocation_id,
        plan_id=plan_id,
        feature_id=args.feature,
        iteration=args.iteration,
        argv_display=argv_display,
        argv_digest=argv_digest,
        canonical_cwd=str(cwd),
        code_revision=revision,
        dirty_diff_hash=dirty_hash,
        started_at=started_at,
        status="started",
    )

    record_path = _write_invocation_record(plan_dir, initial_record)
    print(f"\nStarted: {record_path}")

    exit_code, stdout, stderr, timed_out, cancelled, spawn_error = _run_command(
        args.command, cwd, args.timeout_seconds
    )

    ended_at = datetime.now(timezone.utc).isoformat()

    final_record = InvocationRecord(
        invocation_id=invocation_id,
        plan_id=plan_id,
        feature_id=args.feature,
        iteration=args.iteration,
        argv_display=argv_display,
        argv_digest=argv_digest,
        canonical_cwd=str(cwd),
        code_revision=revision,
        dirty_diff_hash=dirty_hash,
        started_at=started_at,
        ended_at=ended_at,
        exit_code=exit_code,
        timed_out=timed_out,
        cancelled=cancelled,
        spawn_error=spawn_error,
        stdout_hash=_hash_content(stdout) if stdout else None,
        stderr_hash=_hash_content(stderr) if stderr else None,
        stdout_excerpt=_excerpt_output(stdout) if stdout else None,
        stderr_excerpt=_excerpt_output(stderr) if stderr else None,
        status="completed" if exit_code is not None else "incomplete",
    )

    _write_invocation_record(plan_dir, final_record)
    print(f"Completed: {record_path}")

    if spawn_error:
        print(f"\nSpawn error: {spawn_error}", file=sys.stderr)
        return 3

    if timed_out:
        print(f"\nCommand timed out after {args.timeout_seconds}s", file=sys.stderr)
        return 3

    if cancelled:
        print("\nCommand cancelled by user", file=sys.stderr)
        return 3

    print(f"\nExit code: {exit_code}")
    if exit_code == 0:
        return 0
    return 1


def _load_journeys_from_plan(plan_dir: Path) -> list[str]:
    """Load journey names from plan's objective contract if present."""
    plan_md = plan_dir / "plan.md"
    if not plan_md.is_file():
        return []

    text = plan_md.read_text()
    if not text.startswith("---"):
        return []

    import yaml

    parts = text.split("---", 2)
    if len(parts) < 3:
        return []

    fm = yaml.safe_load(parts[1])
    links = fm.get("links", {})
    contract_ref = links.get("objective_contract")
    if not contract_ref:
        return []

    contract_path = plan_dir / contract_ref
    if not contract_path.is_file():
        return []

    try:
        contract = json.loads(contract_path.read_text())
        journeys = contract.get("user_journeys", [])
        return [j.get("name") for j in journeys if j.get("name")]
    except (json.JSONDecodeError, KeyError):
        return []


def evidence_capture_main(argv: list[str] | None = None) -> int:
    """Entry point for `dontpanic evidence capture`.

    Exit codes:
        0 — capture completed successfully
        1 — capture completed with skips
        2 — usage error / validation failure
        3 — capture error
    """
    parser = argparse.ArgumentParser(
        prog="dontpanic evidence capture",
        description="Capture runtime evidence for a plan journey.",
    )
    parser.add_argument("plan", help="Plan ID or path")
    parser.add_argument("--journey", "-j", required=True, help="Journey name from objective contract")
    parser.add_argument("--source", "-s", required=True, help="Evidence source (web, ios, android, backend)")
    parser.add_argument("--config", "-c", type=Path, help="Source-specific config file (project-scoped only)")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Execute capture (dry-run without this flag)",
    )

    args = parser.parse_args(argv)

    valid_sources = {"web", "ios", "android", "backend", "harness"}
    if args.source not in valid_sources:
        print(
            f"error: --source must be one of {', '.join(sorted(valid_sources))}; got {args.source!r}",
            file=sys.stderr,
        )
        return 2

    try:
        plan_dir = _resolve_plan_dir(args.plan)
    except EvidenceRunError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        plan_id, _ = _load_plan_features(plan_dir)
    except EvidenceRunError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    journeys = _load_journeys_from_plan(plan_dir)

    if journeys and args.journey not in journeys:
        print(
            f"error: journey {args.journey!r} not found in plan contract; "
            f"available: {', '.join(journeys)}",
            file=sys.stderr,
        )
        return 2

    if args.config:
        config_path = args.config.resolve()
        if not config_path.is_file():
            print(f"error: config file not found: {config_path}", file=sys.stderr)
            return 2

        repo_root = plan_dir
        for _ in range(5):
            if (repo_root / ".git").exists():
                break
            parent = repo_root.parent
            if parent == repo_root:
                break
            repo_root = parent

        if not config_path.is_relative_to(repo_root):
            print(
                f"error: config file must be project-scoped (within {repo_root}); "
                f"got {config_path}",
                file=sys.stderr,
            )
            return 2

    print(f"Plan: {plan_id}")
    print(f"Journey: {args.journey}")
    print(f"Source: {args.source}")
    if args.config:
        print(f"Config: {args.config}")

    if not args.confirm:
        print("\n[dry-run] Would capture evidence for journey.")
        print("Add --confirm to execute.")
        return 0

    capture_id = f"cap-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    capture_dir = plan_dir / CAPTURE_MANIFEST_DIR / capture_id
    capture_dir.mkdir(parents=True, exist_ok=True)

    evidence_refs: list[dict[str, Any]] = []
    skipped_sources: list[dict[str, str]] = []
    status = "completed"

    try:
        from dontpanic_orchestrate.runtime_evidence.harness import (
            EvidenceCollector,
            EvidenceSourceError,
        )

        collector = EvidenceCollector(plan_dir)

        if args.source == "web":
            from dontpanic_orchestrate.runtime_evidence.web import WebEvidenceCollector
            from dontpanic_orchestrate.runtime_evidence.harness import web_source

            web_collector = WebEvidenceCollector(plan_dir)

            config_data = {}
            if args.config:
                config_data = json.loads(args.config.read_text())

            base_url = config_data.get("base_url", "http://localhost:3000")
            session_config = config_data.get("session", {})

            source = web_source(web_collector, base_url, session_config)
            refs = collector.collect(args.journey, sources=[source])

            for ref in refs:
                evidence_refs.append(ref.model_dump())

        elif args.source == "harness":
            refs = collector.collect(args.journey, sources=[])
            for ref in refs:
                evidence_refs.append(ref.model_dump())
                if "skip" in ref.uri:
                    skipped_sources.append({"source": args.source, "reason": ref.note or "unknown"})

        else:
            skipped_sources.append({
                "source": args.source,
                "reason": f"adapter for {args.source} not yet integrated",
            })
            status = "skipped"

    except EvidenceSourceError as exc:
        skipped_sources.append({"source": args.source, "reason": str(exc)})
        status = "error"
    except ImportError as exc:
        skipped_sources.append({"source": args.source, "reason": f"import error: {exc}"})
        status = "error"
    except Exception as exc:
        skipped_sources.append({"source": args.source, "reason": f"unexpected: {type(exc).__name__}: {exc}"})
        status = "error"

    if skipped_sources and status == "completed":
        status = "skipped"

    manifest = CaptureManifest(
        capture_id=capture_id,
        plan_id=plan_id,
        journey=args.journey,
        source=args.source,
        captured_at=datetime.now(timezone.utc).isoformat(),
        config_path=str(args.config) if args.config else None,
        evidence_refs=evidence_refs,
        skipped_sources=skipped_sources,
        status=status,
    )

    manifest_path = capture_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest.model_dump(), indent=2, default=str) + "\n")

    print(f"\nCapture ID: {capture_id}")
    print(f"Manifest: {manifest_path}")
    print(f"Evidence refs: {len(evidence_refs)}")
    print(f"Skipped: {len(skipped_sources)}")
    print(f"Status: {status}")

    if status == "error":
        return 3
    if status == "skipped":
        return 1
    return 0


def evidence_main(argv: list[str] | None = None) -> int:
    """Entry point for `dontpanic evidence` subcommand router.

    Routes to:
        evidence run ...
        evidence capture ...
    """
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        print("usage: dontpanic evidence {run,capture} ...")
        print()
        print("Opt-in evidence producers for command recording and capture.")
        print()
        print("subcommands:")
        print("  run       Record a command execution as evidence")
        print("  capture   Capture runtime evidence for a journey")
        print()
        print("Run `dontpanic evidence <subcommand> --help` for details.")
        return 0 if argv and argv[0] in ("-h", "--help") else 2

    subcmd = argv[0]
    rest = argv[1:]

    if subcmd == "run":
        return evidence_run_main(rest)
    elif subcmd == "capture":
        return evidence_capture_main(rest)
    else:
        print(f"error: unknown subcommand {subcmd!r}; use 'run' or 'capture'", file=sys.stderr)
        return 2


__all__ = [
    "CaptureManifest",
    "EvidenceCaptureError",
    "EvidenceRunError",
    "InvocationRecord",
    "evidence_capture_main",
    "evidence_main",
    "evidence_run_main",
]
