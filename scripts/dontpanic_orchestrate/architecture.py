"""dontpanic architecture — crawler + CLI for a stable architecture snapshot.

Plan 2026-05-19-004 F001. Walks ``scripts/dontpanic_orchestrate/``,
``claude/shared/``, and ``docs/plans/`` and emits
``docs/architecture/architecture.json`` — a version-stamped, fingerprinted
machine contract for downstream consumers (F002 HTML, F003 doctor drift
probe, F004 supervisor regen hook, F005 pre-commit hook, and Plan 4.5's
``dontpanic new`` context gatherer, which falls back gracefully when this
file is absent or stale).

Invariants:
- Idempotent: same source → byte-identical JSON. ``generated_at`` /
  ``computed_at`` are reused from the existing file when the source
  fingerprint matches.
- Stable key order: ``json.dumps(..., sort_keys=True)`` plus sorted
  module / schema / plan lists.
- No random IDs, no per-module timestamps.
- Bounded output (~200KB cap). When tripped, list-valued sections are
  truncated and ``truncated``/``truncation_marker`` are populated.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = "1.0"
DEFAULT_OUTPUT_REL = Path("docs/architecture/architecture.json")
DEFAULT_SIZE_CAP_BYTES = 200_000

# Files we never want to fingerprint or include in module-walks. Keep this
# list short and obvious — it's the only place these patterns live.
_SKIP_DIR_NAMES = frozenset({"__pycache__", ".git", ".mypy_cache", ".pytest_cache"})
_SKIP_FILE_SUFFIXES = (".pyc", ".pyo")
_SKIP_FILE_NAMES = frozenset({".DS_Store"})

# Tests live next to the module they exercise, but their imports/symbol set
# is noise for a high-signal module map. The fingerprint still covers them.
_MODULE_EXCLUDE_DIR_NAMES = frozenset({"tests"})

# Under each plan dir, only these files contribute to the architecture
# snapshot (and therefore the fingerprint). Audit artifacts, evidence,
# event logs, and gate state churn during normal volley operation; if we
# hashed them, `architecture status` would report drift the instant the
# next audit landed. The plan inventory only consumes plan.md +
# features.json, so those are also the only files that should drive
# fingerprint changes for the plans surface.
_PLAN_FINGERPRINT_FILES = ("plan.md", "features.json")


@dataclass(frozen=True)
class CrawlRoots:
    repo_root: Path
    modules_root: Path
    schemas_root: Path
    plans_root: Path
    version_file: Path
    validator_file: Path

    @classmethod
    def from_repo(cls, repo_root: Path) -> "CrawlRoots":
        repo_root = repo_root.resolve()
        return cls(
            repo_root=repo_root,
            modules_root=repo_root / "scripts" / "dontpanic_orchestrate",
            schemas_root=repo_root / "claude" / "shared" / "schemas" / "v1.0",
            plans_root=repo_root / "docs" / "plans",
            version_file=repo_root / "claude" / "shared" / "VERSION",
            validator_file=repo_root / "claude" / "shared" / "schemas" / "v1.0" / "validate.py",
        )


def _should_skip_dir(name: str) -> bool:
    return name in _SKIP_DIR_NAMES or name.endswith(".egg-info")


def _should_skip_file(path: Path) -> bool:
    if path.name in _SKIP_FILE_NAMES:
        return True
    return any(path.name.endswith(suf) for suf in _SKIP_FILE_SUFFIXES)


def _walk_files(root: Path) -> list[Path]:
    """Yield files under ``root`` in deterministic (sorted) order.

    Skips ``__pycache__``, ``*.pyc``, ``.DS_Store``, etc. Returns absolute
    paths. Missing roots yield an empty list — callers can crawl optional
    surfaces without guarding each one.
    """
    if not root.is_dir():
        return []
    out: list[Path] = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if entry.is_dir():
            if _should_skip_dir(entry.name):
                continue
            out.extend(_walk_files(entry))
        elif entry.is_file():
            if _should_skip_file(entry):
                continue
            out.append(entry)
    return out


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65_536), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


class Crawler:
    """Snapshot the DontPanic codebase + plan inventory.

    Construct with a repo root (or pre-built ``CrawlRoots``). Call
    :meth:`snapshot` to produce a structured dict; serialize via
    :func:`render_snapshot` for the stable on-disk form.
    """

    def __init__(
        self,
        repo_root: Path | str | None = None,
        *,
        roots: CrawlRoots | None = None,
        size_cap_bytes: int = DEFAULT_SIZE_CAP_BYTES,
    ) -> None:
        if roots is None:
            if repo_root is None:
                raise ValueError("Crawler requires repo_root or roots")
            roots = CrawlRoots.from_repo(Path(repo_root))
        self.roots = roots
        self.size_cap_bytes = size_cap_bytes

    # ── Fingerprint ────────────────────────────────────────────────────
    def _fingerprint_files(self) -> list[Path]:
        files: list[Path] = []
        # Modules + schemas: full walk (skip-list filters out __pycache__ etc).
        for root in (self.roots.modules_root, self.roots.schemas_root):
            files.extend(_walk_files(root))
        # VERSION file: schemas section reads this per-schema entry, so a
        # bump must trigger drift. Auditor caught this gap on the first
        # dispatch (Plan 4 F001 i1 finding: source_fingerprint excluded
        # claude/shared/VERSION even though snapshot consumed it).
        if self.roots.version_file.is_file():
            files.append(self.roots.version_file)
        # Plans: only the files the snapshot inventory actually consumes —
        # plan.md and features.json per plan dir. Including audit/, evidence/,
        # INBOX.md, events.jsonl, gate-state.json, decisions.jsonl, etc.
        # would cause `architecture status` to flip to stale the moment the
        # next audit landed, producing false drift signal for downstream
        # consumers (Plan 4.5 context gatherer, F003 doctor probe).
        files.extend(self._plan_fingerprint_files())
        # Stable order across roots by relative path.
        files.sort(key=lambda p: _rel(p, self.roots.repo_root))
        return files

    def _plan_fingerprint_files(self) -> list[Path]:
        if not self.roots.plans_root.is_dir():
            return []
        out: list[Path] = []
        for entry in sorted(self.roots.plans_root.iterdir(), key=lambda p: p.name):
            if not entry.is_dir():
                continue
            for fname in _PLAN_FINGERPRINT_FILES:
                candidate = entry / fname
                if candidate.is_file():
                    out.append(candidate)
        return out

    def fingerprint(self, *, computed_at: str | None = None) -> dict[str, Any]:
        files = self._fingerprint_files()
        per_file: dict[str, str] = {}
        h = hashlib.sha256()
        for path in files:
            rel = _rel(path, self.roots.repo_root)
            file_hash = _sha256_file(path)
            per_file[rel] = file_hash
            h.update(rel.encode("utf-8"))
            h.update(b":")
            h.update(file_hash.encode("ascii"))
            h.update(b"\n")
        return {
            "algo": "sha256",
            "files_count": len(files),
            "file_hashes_root": h.hexdigest(),
            # Per-file map enables exact added/removed/modified diffs (F001
            # finding #2 from i0 audit). Sorted-on-output by render_snapshot
            # (sort_keys=True) so this stays deterministic.
            "file_hashes": per_file,
            "computed_at": computed_at or _utc_now_iso(),
        }

    # ── Modules (Python AST) ───────────────────────────────────────────
    def crawl_modules(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not self.roots.modules_root.is_dir():
            return out
        for path in _walk_files(self.roots.modules_root):
            if path.suffix != ".py":
                continue
            # Skip test directories — they're covered by the fingerprint
            # but not by the module map (low signal-to-noise for the
            # architecture surface).
            rel_parts = path.relative_to(self.roots.modules_root).parts
            if any(part in _MODULE_EXCLUDE_DIR_NAMES for part in rel_parts):
                continue
            entry = _parse_module(path, self.roots.modules_root, self.roots.repo_root)
            if entry is not None:
                out.append(entry)
        out.sort(key=lambda e: e["path"])
        return out

    # ── Schemas (claude/shared) ────────────────────────────────────────
    def crawl_schemas(self) -> list[dict[str, Any]]:
        if not self.roots.schemas_root.is_dir():
            return []
        version = _read_version(self.roots.version_file)
        validator_present = self.roots.validator_file.is_file()
        out: list[dict[str, Any]] = []
        for path in _walk_files(self.roots.schemas_root):
            if path.suffix != ".json":
                continue
            out.append(
                {
                    "path": _rel(path, self.roots.repo_root),
                    "name": path.stem,
                    "version": version,
                    "validator_present": validator_present,
                }
            )
        out.sort(key=lambda e: e["path"])
        return out

    # ── Plans ──────────────────────────────────────────────────────────
    def crawl_plans(self) -> list[dict[str, Any]]:
        if not self.roots.plans_root.is_dir():
            return []
        out: list[dict[str, Any]] = []
        for entry in sorted(self.roots.plans_root.iterdir(), key=lambda p: p.name):
            if not entry.is_dir():
                continue
            plan_md = entry / "plan.md"
            features_json = entry / "features.json"
            if not plan_md.is_file():
                continue
            plan_id, title, status = _parse_plan_frontmatter(plan_md)
            features_count = _read_features_count(features_json)
            out.append(
                {
                    "id": plan_id or entry.name,
                    "title": title or entry.name,
                    "status": status or "unknown",
                    "features_count": features_count,
                }
            )
        out.sort(key=lambda e: e["id"])
        return out

    # ── Snapshot composition ───────────────────────────────────────────
    def snapshot(self, *, now: str | None = None) -> dict[str, Any]:
        generated_at = now or _utc_now_iso()
        fingerprint = self.fingerprint(computed_at=generated_at)
        modules = self.crawl_modules()
        schemas = self.crawl_schemas()
        plans = self.crawl_plans()
        snap: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated_at,
            "source_fingerprint": fingerprint,
            "modules": modules,
            "schemas": schemas,
            "plans": plans,
        }
        snap = _maybe_truncate(snap, cap=self.size_cap_bytes)
        return snap


# ── Parsing helpers ────────────────────────────────────────────────────


def _parse_module(path: Path, modules_root: Path, repo_root: Path) -> dict[str, Any] | None:
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        # Stable but informative: still surface the file, mark it
        # unparseable so downstream tools don't silently lose it.
        return {
            "path": _rel(path, repo_root),
            "name": _module_name(path, modules_root),
            "public_symbols": [],
            "imports": [],
            "summary": "(unparseable: SyntaxError)",
        }

    public_symbols: list[str] = []
    imports: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                public_symbols.append(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    public_symbols.append(target.id)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)

    return {
        "path": _rel(path, repo_root),
        "name": _module_name(path, modules_root),
        "public_symbols": sorted(set(public_symbols)),
        "imports": sorted(imports),
        "summary": _docstring_summary(tree),
    }


def _module_name(path: Path, modules_root: Path) -> str:
    rel = path.relative_to(modules_root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    base = modules_root.name
    return ".".join([base, *parts]) if parts else base


def _docstring_summary(tree: ast.Module) -> str:
    doc = ast.get_docstring(tree) or ""
    for line in doc.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _parse_plan_frontmatter(plan_md: Path) -> tuple[str | None, str | None, str | None]:
    text = plan_md.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return None, None, None
    end = text.find("\n---", 3)
    if end == -1:
        return None, None, None
    raw = text[3:end].strip()
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return None, None, None
    if not isinstance(data, dict):
        return None, None, None
    plan_id = data.get("id") if isinstance(data.get("id"), str) else None
    title = data.get("title") if isinstance(data.get("title"), str) else None
    status = data.get("status") if isinstance(data.get("status"), str) else None
    return plan_id, title, status


def _read_features_count(features_json: Path) -> int:
    if not features_json.is_file():
        return 0
    try:
        data = json.loads(features_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    feats = data.get("features") if isinstance(data, dict) else None
    return len(feats) if isinstance(feats, list) else 0


def _read_version(version_file: Path) -> str | None:
    if not version_file.is_file():
        return None
    try:
        return version_file.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


# ── Output / idempotency ───────────────────────────────────────────────


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _maybe_truncate(snap: dict[str, Any], *, cap: int) -> dict[str, Any]:
    serialized = render_snapshot(snap)
    if len(serialized) <= cap:
        return snap
    # Sections are dropped in order from cheapest-to-lose to most-valuable:
    # plans (id/title only) → schemas → modules. We don't actually drop
    # them; we trim each list until under cap, leaving a marker.
    modules = list(snap.get("modules", []))
    schemas = list(snap.get("schemas", []))
    plans = list(snap.get("plans", []))
    truncated = False
    marker_parts: list[str] = []

    def _serialize(m, s, p) -> int:
        snap["modules"] = m
        snap["schemas"] = s
        snap["plans"] = p
        return len(render_snapshot(snap))

    while _serialize(modules, schemas, plans) > cap:
        if len(plans) > 5:
            plans = plans[: max(5, len(plans) // 2)]
            truncated = True
            continue
        if len(schemas) > 5:
            schemas = schemas[: max(5, len(schemas) // 2)]
            truncated = True
            continue
        if len(modules) > 5:
            modules = modules[: max(5, len(modules) // 2)]
            truncated = True
            continue
        break  # cap may be smaller than the floor; just stop
    if truncated:
        marker_parts.append(
            f"truncated to fit ~{cap} bytes: "
            f"modules={len(modules)} schemas={len(schemas)} plans={len(plans)}"
        )
        snap["truncated"] = True
        snap["truncation_marker"] = "; ".join(marker_parts)
    snap["modules"] = modules
    snap["schemas"] = schemas
    snap["plans"] = plans
    return snap


def render_snapshot(snap: dict[str, Any]) -> str:
    """Serialize a snapshot dict to its canonical on-disk JSON form.

    Stable across runs: sort_keys=True, fixed 2-space indent, single
    trailing newline. Callers should write the returned string verbatim.
    """
    body = json.dumps(snap, sort_keys=True, indent=2, ensure_ascii=False)
    return body + "\n"


def _load_existing(output_path: Path) -> dict[str, Any] | None:
    if not output_path.is_file():
        return None
    try:
        return json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _preserve_timestamps(new: dict[str, Any], prior: dict[str, Any] | None) -> dict[str, Any]:
    """Reuse ``generated_at`` / ``computed_at`` from a prior write when the
    fingerprint root is unchanged. Keeps regen byte-identical when source
    hasn't moved (acceptance #4)."""
    if prior is None:
        return new
    new_fp = new.get("source_fingerprint", {})
    prior_fp = prior.get("source_fingerprint", {})
    if not isinstance(prior_fp, dict):
        return new
    if new_fp.get("file_hashes_root") != prior_fp.get("file_hashes_root"):
        return new
    if isinstance(prior.get("generated_at"), str):
        new["generated_at"] = prior["generated_at"]
    if isinstance(prior_fp.get("computed_at"), str):
        new["source_fingerprint"]["computed_at"] = prior_fp["computed_at"]
    return new


# ── Public API: regen / status / diff ──────────────────────────────────


def regen(
    repo_root: Path | str,
    *,
    output_path: Path | None = None,
    size_cap_bytes: int = DEFAULT_SIZE_CAP_BYTES,
    now: str | None = None,
) -> Path:
    """Crawl + write the architecture snapshot. Returns the output path."""
    repo_root = Path(repo_root).resolve()
    out = output_path or (repo_root / DEFAULT_OUTPUT_REL)
    out.parent.mkdir(parents=True, exist_ok=True)
    crawler = Crawler(repo_root, size_cap_bytes=size_cap_bytes)
    snap = crawler.snapshot(now=now)
    prior = _load_existing(out)
    snap = _preserve_timestamps(snap, prior)
    out.write_text(render_snapshot(snap), encoding="utf-8")
    return out


def status(
    repo_root: Path | str,
    *,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Compute drift state by comparing current fingerprint to the stored one.

    Returns a dict with ``state`` ∈ {``fresh``, ``stale``, ``absent``},
    plus ``stored_fingerprint`` / ``current_fingerprint`` (root hash) and
    ``output_path``.
    """
    repo_root = Path(repo_root).resolve()
    out = output_path or (repo_root / DEFAULT_OUTPUT_REL)
    crawler = Crawler(repo_root)
    current = crawler.fingerprint()
    prior = _load_existing(out)
    if prior is None:
        return {
            "state": "absent",
            "output_path": str(out),
            "current_fingerprint": current["file_hashes_root"],
            "stored_fingerprint": None,
            "files_count_current": current["files_count"],
            "files_count_stored": None,
        }
    prior_fp = prior.get("source_fingerprint") or {}
    stored_root = prior_fp.get("file_hashes_root")
    state = "fresh" if stored_root == current["file_hashes_root"] else "stale"
    return {
        "state": state,
        "output_path": str(out),
        "current_fingerprint": current["file_hashes_root"],
        "stored_fingerprint": stored_root,
        "files_count_current": current["files_count"],
        "files_count_stored": prior_fp.get("files_count"),
    }


def diff(
    repo_root: Path | str,
    *,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Machine-readable diff: which files changed since the stored snapshot.

    Without re-serializing the full crawler output. Returns:
        {
          "state": "fresh"|"stale"|"absent",
          "added": [...], "removed": [...], "modified": [...],
          "stored_fingerprint": "...", "current_fingerprint": "..."
        }

    The file lists are populated only when a stored snapshot exists; for
    ``absent`` they're empty (caller should regen first).
    """
    repo_root = Path(repo_root).resolve()
    out = output_path or (repo_root / DEFAULT_OUTPUT_REL)
    crawler = Crawler(repo_root)
    current = crawler.fingerprint()
    current_root = current["file_hashes_root"]
    current_map: dict[str, str] = current["file_hashes"]

    prior = _load_existing(out)
    if prior is None:
        return {
            "state": "absent",
            "added": [],
            "removed": [],
            "modified": [],
            "stored_fingerprint": None,
            "current_fingerprint": current_root,
        }
    prior_fp = prior.get("source_fingerprint") or {}
    stored_root = prior_fp.get("file_hashes_root")
    if stored_root == current_root:
        return {
            "state": "fresh",
            "added": [],
            "removed": [],
            "modified": [],
            "stored_fingerprint": stored_root,
            "current_fingerprint": current_root,
        }
    # Exact diff: per-file hash map from the stored snapshot lets us
    # compute added/removed/modified as set ops + content compares.
    # When file_hashes is missing (e.g., a v0 snapshot from before the
    # field was added), fall back to a stale-no-detail signal — the
    # caller should regen to pick up the per-file map.
    stored_map = prior_fp.get("file_hashes")
    if not isinstance(stored_map, dict):
        return {
            "state": "stale",
            "added": [],
            "removed": [],
            "modified": [],
            "stored_fingerprint": stored_root,
            "current_fingerprint": current_root,
            "detail_available": False,
        }
    stored_keys = set(stored_map.keys())
    current_keys = set(current_map.keys())
    added = sorted(current_keys - stored_keys)
    removed = sorted(stored_keys - current_keys)
    modified = sorted(
        path for path in current_keys & stored_keys if current_map[path] != stored_map[path]
    )
    return {
        "state": "stale",
        "added": added,
        "removed": removed,
        "modified": modified,
        "stored_fingerprint": stored_root,
        "current_fingerprint": current_root,
    }


# ── CLI ────────────────────────────────────────────────────────────────


_HELP = """dontpanic architecture — codebase snapshot + drift surface.

Subcommands:
  regen   Crawl source + plans → docs/architecture/architecture.json (default).
  status  Print drift state (fresh/stale/absent) without regenerating.
  diff    Emit machine-readable JSON diff vs. the stored snapshot.

The JSON is the agent-facing contract; HTML (F002) is a separate command.
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dontpanic architecture",
        description=_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="subcommand")
    p_regen = sub.add_parser("regen", help="Regenerate the architecture snapshot")
    p_regen.add_argument("--repo-root", type=Path, default=None)
    p_regen.add_argument("--output", type=Path, default=None)

    p_status = sub.add_parser("status", help="Print drift state without regenerating")
    p_status.add_argument("--repo-root", type=Path, default=None)
    p_status.add_argument("--output", type=Path, default=None)
    p_status.add_argument("--json", action="store_true", help="Emit JSON instead of text")

    p_diff = sub.add_parser("diff", help="Machine-readable diff vs. stored snapshot")
    p_diff.add_argument("--repo-root", type=Path, default=None)
    p_diff.add_argument("--output", type=Path, default=None)
    return parser


def _resolve_repo_root(arg: Path | None) -> Path:
    if arg is not None:
        return arg.resolve()
    # Walk up from this file to find the repo root (the dir holding both
    # ``scripts/dontpanic_orchestrate`` and ``claude/shared``).
    here = Path(__file__).resolve()
    for candidate in (here.parents[2], Path.cwd()):
        if (candidate / "scripts" / "dontpanic_orchestrate").is_dir():
            return candidate
    return Path.cwd()


def cli_main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    sub = args.subcommand or "regen"
    repo_root = _resolve_repo_root(getattr(args, "repo_root", None))
    output = getattr(args, "output", None)

    if sub == "regen":
        out = regen(repo_root, output_path=output)
        print(f"[architecture] wrote {out}")
        return 0
    if sub == "status":
        result = status(repo_root, output_path=output)
        if getattr(args, "json", False):
            print(json.dumps(result, sort_keys=True, indent=2))
        else:
            print(f"[architecture] state={result['state']}")
            print(f"[architecture] stored={result['stored_fingerprint']}")
            print(f"[architecture] current={result['current_fingerprint']}")
            print(f"[architecture] path={result['output_path']}")
        # absent / stale exit 0 (advisory by default — F003 will add --strict)
        return 0
    if sub == "diff":
        result = diff(repo_root, output_path=output)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover - manual invocation
    raise SystemExit(cli_main())
