"""Per-dispatch process environment isolation for external CLIs.

ExecutionEnvironment owns a temporary namespace for mutable CLI state. It does
not parse plan targets or enforce production gates; those are later F023 steps.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

ISOLATED_ENV_PATHS = {
    "CLOUDSDK_CONFIG": ("gcloud",),
    "XDG_CONFIG_HOME": ("xdg_config",),
    "CONFIGSTORE_DIR": ("configstore",),
    "GH_CONFIG_DIR": ("gh",),
    "DOCKER_CONFIG": ("docker",),
    "GRADLE_USER_HOME": ("gradle",),
    "ANDROID_USER_HOME": ("android", "home"),
    "ANDROID_AVD_HOME": ("android", "avd"),
    "TF_DATA_DIR": ("terraform", "data"),
}

ISOLATED_ENV_FILES = {
    "KUBECONFIG": ("kube", "config"),
    "NPM_CONFIG_USERCONFIG": ("npm", "npmrc"),
}

TARGET_ENV_KEYS = {
    "CLOUDSDK_CORE_PROJECT",
    "FIREBASE_PROJECT",
    "GOOGLE_CLOUD_PROJECT",
    "GCLOUD_PROJECT",
    "JARVIS_TARGET_PROJECT",
}


@dataclass
class ExecutionEnvironment:
    """Context manager that mints isolated CLI config dirs for one dispatch."""

    plan_id: str
    target_env: str | None = None
    target_project: str | None = None
    root: Path | None = None
    cleanup: bool = True
    _created_root: bool = field(default=False, init=False)
    _active: bool = field(default=False, init=False)

    def __enter__(self) -> ExecutionEnvironment:
        if self.root is None:
            safe_plan_id = "".join(c if c.isalnum() or c in "._-" else "-" for c in self.plan_id)
            self.root = Path(tempfile.mkdtemp(prefix=f"jarvis-exec-{safe_plan_id}-"))
            self._created_root = True
        else:
            self.root.mkdir(parents=True, exist_ok=True)

        for parts in ISOLATED_ENV_PATHS.values():
            (self.root.joinpath(*parts)).mkdir(parents=True, exist_ok=True)
        for parts in ISOLATED_ENV_FILES.values():
            path = self.root.joinpath(*parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)

        gcloud_default = self.root / "gcloud" / "configurations" / "config_default"
        gcloud_default.parent.mkdir(parents=True, exist_ok=True)
        if self.target_project and not gcloud_default.exists():
            gcloud_default.write_text(f"[core]\nproject = {self.target_project}\n")

        self._active = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._active = False
        if self.cleanup and self._created_root and self.root is not None:
            shutil.rmtree(self.root, ignore_errors=True)

    def overlay(self) -> dict[str, str]:
        """Return only Jarvis-owned environment keys for this execution."""
        self._require_active()
        assert self.root is not None

        env = {key: str(self.root.joinpath(*parts)) for key, parts in ISOLATED_ENV_PATHS.items()}
        env.update(
            {key: str(self.root.joinpath(*parts)) for key, parts in ISOLATED_ENV_FILES.items()}
        )
        env["JARVIS_EXECUTION_ENV_ROOT"] = str(self.root)
        if self.target_env:
            env["JARVIS_TARGET_ENV"] = self.target_env
        if self.target_project:
            for key in TARGET_ENV_KEYS:
                env[key] = self.target_project
        return env

    def subprocess_env(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        """Return a full environment suitable for subprocess.run(env=...)."""
        merged = dict(os.environ if base is None else base)
        merged.update(self.overlay())
        return merged

    def _require_active(self) -> None:
        if not self._active:
            raise RuntimeError("ExecutionEnvironment must be entered before use")
