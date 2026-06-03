"""F002 — patch-completeness analyzer (pure function).

Spec: plan 2026-05-01-004 F002. Consumes a captured ``GitState`` (from F001) +
``repo_root`` + explicit ``touched_files: set[str]`` and returns a
``CompletenessReport`` describing five detection modes:

  - ``test_imports_uncommitted``  — a test in the read surface imports a module
    that's untracked or unstaged_modified.
  - ``source_imports_uncommitted`` — a non-test source in the read surface
    imports a module that's untracked or unstaged_modified.
  - ``test_file_untracked``       — a test file is itself in untracked or
    unstaged_modified, so a fresh-clone CI run won't discover it.
  - ``generated_artifact_staged`` — a path in ``staged`` matches the
    generated-artifact deny-list.
  - ``unstaged_dirty_state``      — every ``unstaged_modified`` file (advisory
    info; F003 promotes to block when the file is outside ``touched_files`` AND
    no operator note was supplied).

Read surface narrowing (D005): the analyzer parses ASTs only for files in
``touched_files ∪ git_state.staged paths ∪ git_state.unstaged_modified paths``.
The full repo is NEVER walked. F003's caller supplies ``touched_files``.

Purity contract: no global state, no logging, no print, no subprocess. Only
file I/O is reading source files for AST parsing.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

Mode = Literal[
    "test_imports_uncommitted",
    "source_imports_uncommitted",
    "test_file_untracked",
    "generated_artifact_staged",
    "unstaged_dirty_state",
]
Severity = Literal["info", "warn", "block"]
Status = Literal["pass", "warn", "fail"]


SCHEMA_VERSION = "1.0"


# Deny-list of paths whose presence in `staged` indicates an accidentally-
# committed generated/cache artifact. Each entry carries a `# source:` comment
# explaining why the pattern is included; mirrors the security-baseline F001
# pattern-citation discipline.
_GENERATED_ARTIFACT_PATTERNS: frozenset[str] = frozenset(
    {
        # source: Python bytecode cache directory; regenerated on every import,
        # never appropriate in a commit.
        "__pycache__",
        # source: Compiled Python bytecode files; same lifecycle as __pycache__.
        "*.pyc",
        # source: Optimized compiled bytecode (python -O); same lifecycle as .pyc.
        "*.pyo",
        # source: coverage.py session file; ephemeral per test run.
        ".coverage",
        # source: macOS Finder metadata file; never relevant to source control.
        ".DS_Store",
        # source: pytest's last-run / collection cache; ephemeral.
        ".pytest_cache",
        # source: npm/node module tree; reproducible from package-lock.json.
        "node_modules",
        # source: tox virtualenv working directory; reproducible from tox.ini.
        ".tox",
        # source: mypy type-check cache; reproducible on next run.
        ".mypy_cache",
        # source: ruff lint cache; reproducible on next run.
        ".ruff_cache",
    }
)


# ──────────────────────────────  envelope dataclasses  ──────────────────────────────


@dataclass(frozen=True)
class Finding:
    mode: Mode
    files: list[str]
    reason: str
    severity: Severity
    recommendation: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, blob: dict) -> Finding:
        return cls(
            mode=blob["mode"],
            files=list(blob["files"]),
            reason=blob["reason"],
            severity=blob["severity"],
            recommendation=blob["recommendation"],
        )


@dataclass
class CompletenessReport:
    schema_version: str
    status: Status
    findings: list[Finding] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "findings": [f.to_dict() for f in self.findings],
            "files": list(self.files),
        }

    @classmethod
    def from_dict(cls, blob: dict) -> CompletenessReport:
        return cls(
            schema_version=blob["schema_version"],
            status=blob["status"],
            findings=[Finding.from_dict(f) for f in blob.get("findings", [])],
            files=list(blob.get("files", [])),
        )


# ──────────────────────────────  helpers  ──────────────────────────────


_SEVERITY_ORDER: dict[Severity, int] = {"info": 0, "warn": 1, "block": 2}


def compute_status(findings: list[Finding]) -> Status:
    """Map findings → user-facing status. ``info`` does NOT escalate above pass.

    F002 surfaces info-tier findings (Mode 5) so F003 can read + decide; F002
    itself never blocks based on info severity. ``warn`` → ``warn``,
    ``block`` → ``fail`` (rendered as the user-facing label per acceptance #3).
    """
    if not findings:
        return "pass"
    max_idx = max(_SEVERITY_ORDER[f.severity] for f in findings)
    if max_idx == 0:
        return "pass"
    if max_idx == 1:
        return "warn"
    return "fail"


def _is_test_file(rel_path: str) -> bool:
    """Test classification per F002 step: name matches ``test_*.py`` or
    ``*_test.py`` AND lives under a path containing a ``tests`` or ``test``
    segment. Top-level ``test_x.py`` outside any such directory is NOT a test.
    """
    p = Path(rel_path)
    name = p.name
    name_match = (name.startswith("test_") and name.endswith(".py")) or name.endswith("_test.py")
    if not name_match:
        return False
    return any(part in ("tests", "test") for part in p.parts[:-1])


def _matches_denylist(rel_path: str) -> bool:
    parts = Path(rel_path).parts
    name = Path(rel_path).name
    for pattern in _GENERATED_ARTIFACT_PATTERNS:
        if pattern.startswith("*."):
            if name.endswith(pattern[1:]):
                return True
        else:
            if name == pattern or pattern in parts:
                return True
    return False


def _staged_paths(git_state: dict) -> set[str]:
    return {entry["path"] for entry in git_state.get("staged", [])}


def _unstaged_modified_paths(git_state: dict) -> set[str]:
    return {entry["path"] for entry in git_state.get("unstaged_modified", [])}


def _untracked_paths(git_state: dict) -> set[str]:
    return set(git_state.get("untracked", []))


def _read_surface(git_state: dict, touched_files: set[str]) -> set[str]:
    """Files the analyzer is allowed to AST-parse. Touched-set narrowing per D005."""
    return touched_files | _staged_paths(git_state) | _unstaged_modified_paths(git_state)


# ──────────────────────────────  import resolution  ──────────────────────────────


def _resolve_module(repo_root: Path, importing_file: str, module: str, level: int) -> list[str]:
    """Return candidate repo-relative paths a Python import could resolve to.

    For absolute ``import a.b.c`` (level=0): candidates include ``a/b/c.py``,
    ``a/b/c/__init__.py``, ``a/b.py``, ``a/b/__init__.py`` (the last two cover
    ``from a.b import c`` where ``c`` is a name within module ``a/b``).

    For relative ``from .helpers import x`` (level=1): resolve against the
    importing file's package and return analogous candidates.

    Returns an empty list when the module path can't be projected onto a
    repo-relative path (e.g. relative import that escapes the repo root).
    """
    if level > 0:
        anchor = Path(importing_file).parent
        for _ in range(level - 1):
            if anchor == Path("."):
                return []
            anchor = anchor.parent
        package_parts = list(anchor.parts)
    else:
        package_parts = []

    module_parts = module.split(".") if module else []
    full_parts = package_parts + module_parts
    if not full_parts:
        return []

    candidates: list[str] = []
    # `a/b/c.py` and `a/b/c/__init__.py` — c is a submodule
    candidates.append(str(Path(*full_parts).with_suffix(".py")))
    candidates.append(str(Path(*full_parts) / "__init__.py"))
    # `a/b.py` and `a/b/__init__.py` — the last segment is a NAME inside a/b
    if len(full_parts) >= 2:
        parent_parts = full_parts[:-1]
        candidates.append(str(Path(*parent_parts).with_suffix(".py")))
        candidates.append(str(Path(*parent_parts) / "__init__.py"))
    return candidates


def _source_root_prefixes(importing_file: str) -> list[str]:
    """Candidate source-root prefixes under which ``importing_file`` could be
    imported: every ancestor directory of the importing file.

    For ``scripts/dontpanic_orchestrate/plan_review/report.py`` this is
    ``['scripts', 'scripts/dontpanic_orchestrate', 'scripts/dontpanic_orchestrate/plan_review']``.
    A module imported by this file is on disk at ``<root>/<dotted/path.py>`` for
    one of these roots (the package's import root is an ANCESTOR of any file in
    the package). Used to bound suffix matching to plausible roots (F003 D005)."""
    parts = Path(importing_file).parent.parts
    return ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]


def _match_dirty(cand: str, dirty_paths: set[str], importing_file: str) -> set[str]:
    """Return the dirty paths a resolved import candidate matches.

    Plan 2026-06-02-002 F003 (D005 — source-root awareness): a dotted import
    like ``dontpanic_orchestrate.plan_review.sizing_gate`` resolves to the
    repo-relative candidate ``dontpanic_orchestrate/plan_review/sizing_gate.py``,
    but the package lives under a source root on PYTHONPATH (``scripts/``), so
    the real git path is ``scripts/dontpanic_orchestrate/.../sizing_gate.py``.
    Exact equality alone misses it. We additionally accept a match where the
    candidate is prefixed by a SOURCE ROOT — but only a root that is an ANCESTOR
    DIRECTORY OF THE IMPORTING FILE (the package's real import root always is).

    This bound (codex batched-audit i0 finding) prevents the over-reach of a
    bare ``endswith`` suffix test: an unrelated untracked mirror such as
    ``docs/generated/dontpanic_orchestrate/plan_review/sizing_gate.py`` shares
    the candidate's tail but its prefix ``docs/generated`` is NOT an ancestor of
    the importer under ``scripts/``, so it does NOT match (acceptance #3/#4: no
    flagging of unrelated untracked output).

    Guard preserved: prefix matching applies ONLY to multi-segment (package-
    qualified) candidates — a bare ``import sizing_gate`` carries no package
    context, so only exact equality qualifies it."""
    matched: set[str] = set()
    if cand in dirty_paths:
        matched.add(cand)
    if len(Path(cand).parts) >= 2:
        for root in _source_root_prefixes(importing_file):
            prefixed = f"{root}/{cand}"
            if prefixed != cand and prefixed in dirty_paths:
                matched.add(prefixed)
    return matched


def _extract_resolved_imports(
    repo_root: Path, importing_file: str, dirty_paths: set[str]
) -> set[str]:
    """Parse ``importing_file`` and return the subset of imports that resolve to
    a ``dirty_paths`` entry. Resolution failure (third-party / stdlib / unresolvable)
    is silently dropped per the spec. Syntax errors in the file are also silent.
    """
    src_path = repo_root / importing_file
    try:
        source = src_path.read_text()
    except (OSError, UnicodeDecodeError):
        return set()
    try:
        tree = ast.parse(source, filename=str(src_path))
    except SyntaxError:
        return set()

    hits: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for cand in _resolve_module(repo_root, importing_file, alias.name, 0):
                    hits |= _match_dirty(cand, dirty_paths, importing_file)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = node.level or 0
            base_cands = _resolve_module(repo_root, importing_file, module, level)
            for cand in base_cands:
                hits |= _match_dirty(cand, dirty_paths, importing_file)
            # Also try resolving each `from x import name` where `name` is a submodule
            # path: `from x import y` could mean `x/y.py` even if x.py exists.
            for alias in node.names:
                full = f"{module}.{alias.name}" if module else alias.name
                for cand in _resolve_module(repo_root, importing_file, full, level):
                    hits |= _match_dirty(cand, dirty_paths, importing_file)
    return hits


# ──────────────────────────────  per-mode detectors  ──────────────────────────────


def _check_imports(git_state: dict, repo_root: Path, touched_files: set[str]) -> list[Finding]:
    surface = _read_surface(git_state, touched_files)
    dirty = _untracked_paths(git_state) | _unstaged_modified_paths(git_state)
    if not dirty:
        return []

    test_hits: set[str] = set()
    source_hits: set[str] = set()
    for f in sorted(surface):
        resolved = _extract_resolved_imports(repo_root, f, dirty)
        if not resolved:
            continue
        if _is_test_file(f):
            test_hits |= resolved
        else:
            source_hits |= resolved

    findings: list[Finding] = []
    if test_hits:
        findings.append(
            Finding(
                mode="test_imports_uncommitted",
                files=sorted(test_hits),
                reason="A test file in the patch surface imports a module that is untracked or unstaged_modified — fresh-clone CI will fail to import it.",
                severity="block",
                recommendation="Run: git add " + " ".join(sorted(test_hits)),
            )
        )
    if source_hits:
        findings.append(
            Finding(
                mode="source_imports_uncommitted",
                files=sorted(source_hits),
                reason="A source file in the patch surface imports a module that is untracked or unstaged_modified — fresh-clone CI will fail at import time.",
                severity="block",
                recommendation="Run: git add " + " ".join(sorted(source_hits)),
            )
        )
    return findings


def _check_test_file_missing(git_state: dict) -> list[Finding]:
    candidates = sorted(_untracked_paths(git_state) | _unstaged_modified_paths(git_state))
    hits = [p for p in candidates if _is_test_file(p)]
    if not hits:
        return []
    return [
        Finding(
            mode="test_file_untracked",
            files=hits,
            reason="A test file is untracked or unstaged_modified — pytest discovery on a fresh clone will not run it.",
            severity="block",
            recommendation="Run: git add " + " ".join(hits),
        )
    ]


def _check_generated_artifact_staged(git_state: dict) -> list[Finding]:
    hits = sorted(p for p in _staged_paths(git_state) if _matches_denylist(p))
    if not hits:
        return []
    return [
        Finding(
            mode="generated_artifact_staged",
            files=hits,
            reason="A staged path matches the generated/cache deny-list. These files should not be committed; add the pattern to .gitignore if it isn't already.",
            severity="block",
            recommendation="Run: git restore --staged " + " ".join(hits),
        )
    ]


def _check_unstaged_dirty(git_state: dict) -> list[Finding]:
    hits = sorted(_unstaged_modified_paths(git_state))
    if not hits:
        return []
    return [
        Finding(
            mode="unstaged_dirty_state",
            files=hits,
            # F002 emits this as info regardless of touched-set membership; F003
            # owns the touched-set + operator-note logic that promotes to block.
            reason="Unstaged modifications present. F003 will require an operator note when files fall outside touched_files.",
            severity="info",
            recommendation="Run: git add -u for files that should ride along; otherwise pass --unrelated-dirty-state-note <reason> at dispatch time.",
        )
    ]


# ──────────────────────────────  public entry point  ──────────────────────────────


def check(git_state: dict, repo_root: Path, touched_files: set[str]) -> CompletenessReport:
    """Pure-function patch-completeness analyzer. See module docstring for spec."""
    findings: list[Finding] = []
    findings.extend(_check_imports(git_state, repo_root, touched_files))
    findings.extend(_check_test_file_missing(git_state))
    findings.extend(_check_generated_artifact_staged(git_state))
    findings.extend(_check_unstaged_dirty(git_state))

    # Deduplicated union of all files cited in findings, preserving first-seen order.
    seen: set[str] = set()
    files: list[str] = []
    for f in findings:
        for path in f.files:
            if path not in seen:
                seen.add(path)
                files.append(path)

    return CompletenessReport(
        schema_version=SCHEMA_VERSION,
        status=compute_status(findings),
        findings=findings,
        files=files,
    )
