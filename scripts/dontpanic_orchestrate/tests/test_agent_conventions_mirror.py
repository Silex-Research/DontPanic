"""Guard the packaged agent-conventions mirror and schema imports."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
PACKAGE_DIR = SCRIPTS_DIR / "dontpanic_orchestrate"
SOURCE_SCHEMAS_DIR = REPO_ROOT / "claude/shared/schemas/v1.0"
MIRROR_SCHEMAS_DIR = PACKAGE_DIR / "agent_conventions/schemas/v1_0"
sys.path.insert(0, str(SCRIPTS_DIR))

import dontpanic_orchestrate  # noqa: E402


def test_agent_conventions_sync_check_is_clean() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/sync_agent_conventions.py", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"sync check exited {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_schema_and_model_mirror_matches_source() -> None:
    source_schemas = sorted(SOURCE_SCHEMAS_DIR.glob("*.schema.json"))
    assert source_schemas, f"no source schemas found in {SOURCE_SCHEMAS_DIR}"
    for source in source_schemas:
        mirrored = MIRROR_SCHEMAS_DIR / source.name
        assert mirrored.is_file(), f"missing mirrored schema: {mirrored.name}"
        assert mirrored.read_bytes() == source.read_bytes(), (
            f"schema mirror differs from source: {source.name}"
        )

    source_modules = {
        path.stem
        for path in (SOURCE_SCHEMAS_DIR / "models").glob("*.py")
        if path.stem != "__init__"
    }
    mirrored_modules = {
        path.stem
        for path in (MIRROR_SCHEMAS_DIR / "models").glob("*.py")
        if path.stem != "__init__"
    }
    assert mirrored_modules == source_modules, (
        f"model module names differ: source={sorted(source_modules)}, "
        f"mirror={sorted(mirrored_modules)}"
    )


def _defines_name(tree: ast.AST, name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Store):
            return True
        if isinstance(node, ast.arg) and node.arg == name:
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                return True
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound_name = alias.asname or alias.name.split(".")[0]
                if bound_name == name:
                    return True
    return False


def test_runtime_modules_do_not_import_repo_schema_modules_or_candidates() -> None:
    violations: list[str] = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        relative = path.relative_to(PACKAGE_DIR)
        if relative.parts[0] in {"tests", "agent_conventions"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
        for node in ast.walk(tree):
            imported_module: str | None = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_module = alias.name
                    if imported_module == "models" or imported_module.startswith("models."):
                        violations.append(f"{relative}:{node.lineno}: imports {imported_module}")
                    elif imported_module == "experience_readiness" or imported_module.startswith(
                        "experience_readiness."
                    ):
                        violations.append(f"{relative}:{node.lineno}: imports {imported_module}")
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imported_module = node.module or ""
                if imported_module == "models" or imported_module.startswith("models."):
                    violations.append(f"{relative}:{node.lineno}: imports {imported_module}")
                elif imported_module == "experience_readiness" or imported_module.startswith(
                    "experience_readiness."
                ):
                    violations.append(f"{relative}:{node.lineno}: imports {imported_module}")
        if _defines_name(tree, "_SCHEMA_CANDIDATES"):
            violations.append(f"{relative}: defines _SCHEMA_CANDIDATES")

    assert not violations, "\n".join(violations)


def test_package_modules_do_not_import_top_level_sanitization_check() -> None:
    violations: list[str] = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        relative = path.relative_to(PACKAGE_DIR)
        if relative.parts[0] == "tests":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
        for node in ast.walk(tree):
            imported_modules: list[str] = []
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imported_modules.append(node.module or "")
            for imported_module in imported_modules:
                if imported_module == "sanitization_check" or imported_module.startswith(
                    "sanitization_check."
                ):
                    violations.append(f"{relative}:{node.lineno}: imports {imported_module}")

    assert not violations, "\n".join(violations)


def test_sanitization_check_reexports_package_secret_regexes() -> None:
    import sanitization_check
    from dontpanic_orchestrate import secret_patterns

    assert sanitization_check.SECRET_REGEXES is secret_patterns.SECRET_REGEXES


def test_schema_loader_paths_resolve_inside_installed_package() -> None:
    from dontpanic_orchestrate import environments_loader, plan_loader

    package_dir = Path(dontpanic_orchestrate.__file__).resolve().parent
    for module in (plan_loader, environments_loader):
        schema_dir = Path(module.SCHEMAS_DIR).resolve()
        assert schema_dir.is_relative_to(package_dir), (
            f"{module.__name__}.SCHEMAS_DIR is outside the package: {schema_dir}"
        )
        assert (schema_dir / "plan.schema.json").is_file(), (
            f"{module.__name__}.SCHEMAS_DIR does not contain plan.schema.json"
        )


def test_mcp_server_import_outside_repo_leaves_no_repo_schema_sys_path(tmp_path: Path) -> None:
    child_cwd = tmp_path / "outside-repository"
    child_cwd.mkdir()
    assert not child_cwd.resolve().is_relative_to(REPO_ROOT.resolve())
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SCRIPTS_DIR)
    env.pop("PYTHONHOME", None)
    script = "import json, sys; import dontpanic_orchestrate.mcp_server; print(json.dumps(sys.path))"

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=child_cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    sys_path = json.loads(result.stdout.strip().splitlines()[-1])
    leaked = [
        entry
        for entry in sys_path
        if entry.replace("\\", "/").endswith("schemas/v1.0")
        or entry.replace("\\", "/").endswith("schemas/v1.0/models")
    ]
    assert not leaked, f"repo-relative schema paths leaked into sys.path: {leaked}"
