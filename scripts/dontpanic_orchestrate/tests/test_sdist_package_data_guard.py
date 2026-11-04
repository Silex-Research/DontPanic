"""REGRESSION GUARD: every [tool.setuptools.package-data] file ships in the sdist.

This is a regression guard, not a test-first fix. It already passes at the
commit it was added on top of: setuptools puts package-data files in the sdist
on its own. It exists so that a future change to MANIFEST.in, the package-data
globs, or the build backend cannot silently drop runtime data (releases.json,
the vendored v1_0 schemas, capability manifests, prompts) from a source install.

The expected file list is derived from pyproject.toml's package-data globs
matched against the source tree, so no file names are hardcoded. The build is
offline: the PEP 517 setuptools backend runs in a subprocess with no build
isolation (``python -m build --sdist --no-isolation`` when ``build`` is
installed, otherwise ``setuptools.build_meta.build_sdist`` directly). The sdist-
building test is skipped when setuptools is not importable; the glob-vs-tree
check still runs.

Run: PYTHONPATH=scripts pytest scripts/dontpanic_orchestrate/tests/test_sdist_package_data_guard.py
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"

needs_setuptools = pytest.mark.skipif(
    importlib.util.find_spec("setuptools") is None,
    reason="setuptools not importable; cannot build an sdist offline",
)

# Floor per glob as of this guard's introduction (26 files total). Adding files
# is fine; dropping below the floor means runtime data went missing from the
# source tree itself, which is worth a look before relaxing the number.
MIN_FILES_PER_GLOB = {
    "data/*.json": 2,
    "agent_conventions/VERSION": 1,
    "agent_conventions/schemas/v1_0/*.json": 13,
    "capability_manifests/*.json": 8,
    "prompts/*.md": 2,
}


def _load_pyproject() -> dict:
    try:
        import tomllib  # noqa: PLC0415  # py3.11+
    except ModuleNotFoundError:  # pragma: no cover - py3.10
        tomllib = pytest.importorskip("tomli")
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _package_data_globs() -> dict[str, list[str]]:
    cfg = _load_pyproject()
    package_data = cfg.get("tool", {}).get("setuptools", {}).get("package-data", {})
    assert package_data, "pyproject.toml has no [tool.setuptools.package-data]"
    return package_data


def _expected_files() -> dict[str, list[str]]:
    """Map each package-data glob to repo-relative paths it matches today."""
    expected: dict[str, list[str]] = {}
    for package, globs in _package_data_globs().items():
        pkg_dir = SCRIPTS_DIR.joinpath(*package.split("."))
        for pattern in globs:
            matches = sorted(
                p.relative_to(REPO_ROOT).as_posix() for p in pkg_dir.glob(pattern) if p.is_file()
            )
            expected[pattern] = matches
    return expected


@pytest.fixture(scope="module")
def sdist_members(tmp_path_factory: pytest.TempPathFactory) -> set[str]:
    out_dir = tmp_path_factory.mktemp("sdist-guard")
    env = dict(os.environ, PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    # Probe for pypa/build from the temp dir, not the repo root: an ignored
    # build/ directory left in the checkout by wheel builds would otherwise
    # shadow it as a namespace package.
    probe = subprocess.run(
        [sys.executable, "-c", "import build.__main__"],
        cwd=str(out_dir),
        capture_output=True,
        timeout=60,
        check=False,
        env=env,
    )
    if probe.returncode == 0:
        cwd = out_dir
        cmd = [
            sys.executable,
            "-m",
            "build",
            "--sdist",
            "--no-isolation",
            "--skip-dependency-check",
            "--outdir",
            str(out_dir),
            str(REPO_ROOT),
        ]
    else:
        cwd = REPO_ROOT
        cmd = [
            sys.executable,
            "-c",
            "import sys\n"
            "from setuptools import build_meta as bm\n"
            "print(bm.build_sdist(sys.argv[1]))\n",
            str(out_dir),
        ]
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        env=env,
    )
    assert result.returncode == 0, (
        f"offline sdist build failed (exit {result.returncode})\n"
        f"stdout:\n{result.stdout[-2000:]}\nstderr:\n{result.stderr[-2000:]}"
    )
    sdists = sorted(out_dir.glob("*.tar.gz"))
    assert len(sdists) == 1, f"expected exactly one sdist, found {sdists}"
    with tarfile.open(sdists[0]) as tf:
        names = tf.getnames()
    # Members are namespaced under <name>-<version>/; strip that prefix.
    return {n.split("/", 1)[1] for n in names if "/" in n}


def test_package_data_globs_match_source_tree() -> None:
    expected = _expected_files()
    for pattern, floor in MIN_FILES_PER_GLOB.items():
        assert pattern in expected, f"package-data glob {pattern!r} no longer declared"
        assert len(expected[pattern]) >= floor, (
            f"{pattern!r} matches {len(expected[pattern])} files, expected >= {floor}: "
            f"{expected[pattern]}"
        )
    for pattern, files in expected.items():
        assert files, f"package-data glob {pattern!r} matches no files"


@needs_setuptools
def test_sdist_ships_every_package_data_file(sdist_members: set[str]) -> None:
    expected = _expected_files()
    missing = {
        pattern: [f for f in files if f not in sdist_members] for pattern, files in expected.items()
    }
    missing = {k: v for k, v in missing.items() if v}
    assert not missing, f"package-data files missing from the sdist: {missing}"
    total = sum(len(v) for v in expected.values())
    assert total >= sum(MIN_FILES_PER_GLOB.values())
