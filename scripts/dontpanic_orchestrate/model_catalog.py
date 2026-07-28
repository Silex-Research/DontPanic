"""Plan 2026-07-27-001 F015 — model catalog discovery + aliases (Track D4).

The model catalog is DATA, never ``AGENT_REGISTRY`` keys (D010): a new
model version (Grok 4.5, next Claude, an OpenRouter OSS drop) never
requires a new Python registry key or any code change. This module owns
three surfaces:

  1. Discovery — ``get_catalog(harness)``. Registered harnesses are asked
     via the optional :meth:`BaseExecutor.list_models` interface; a
     ``None`` return is the documented pass-through (claude/codex today:
     any freeform model string is forwarded to the vendor CLI unverified).
     Known-but-unregistered discovery surfaces (``ollama`` via the local
     CLI, ``openrouter`` via the models API with an offline-safe cache)
     live in the ``_DISCOVERY`` table so the catalog exists before a
     harness adapter earns dispatchability (D3 comes later than D4).
  2. Aliases — ``model_aliases`` in the global and per-project config
     (project wins per key). Resolution is single-hop: an alias maps to a
     vendor model id, never to another alias.
  3. Probe — ``probe_model(harness, model)`` classifies a configured model
     for the doctor: ``ok`` (in catalog) / ``unknown`` (catalog exists but
     does not list it — freeform is allowed, so this is advisory) /
     ``rejected`` (an authoritative harness probe refused it — the only
     hard failure) / ``pass_through`` / ``unverifiable`` (no catalog
     reachable — e.g. ollama not installed, or offline with no cache).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_CACHE_TTL_SECONDS = 24 * 3600
_SUBPROCESS_TIMEOUT = 15


class UnknownHarnessError(ValueError):
    """The harness id is neither registered nor a known discovery surface.
    Model ids are never harnesses (D010)."""


class CatalogUnavailableError(RuntimeError):
    """Discovery exists for this harness but could not produce a catalog
    right now (binary missing, network down with no cache, …)."""


@dataclass(frozen=True)
class ModelCatalog:
    harness: str
    source: str  # "pass_through" | "ollama_cli" | "openrouter_api" | "openrouter_cache" | "<harness>_executor"
    models: tuple[str, ...] | None  # None = pass-through (no catalog)
    detail: str = ""
    stale: bool = False  # served from cache after a failed/skipped refresh


@dataclass(frozen=True)
class ModelProbe:
    status: str  # "ok" | "unknown" | "rejected" | "pass_through" | "unverifiable"
    detail: str = ""


# ── Discovery ──────────────────────────────────────────────────────────────


def _discover_ollama(*, refresh: bool, allow_network: bool) -> ModelCatalog:
    """``ollama list`` — local daemon, offline-safe by construction; the
    refresh/network knobs are irrelevant here."""
    del refresh, allow_network
    ollama = shutil.which("ollama")
    if ollama is None:
        raise CatalogUnavailableError(
            "ollama CLI not on PATH — install ollama (https://ollama.com) to discover local models"
        )
    try:
        proc = subprocess.run(  # noqa: S603 — absolute vendor CLI path, fixed argv
            [ollama, "list"],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CatalogUnavailableError(f"`ollama list` failed to run: {exc}") from exc
    if proc.returncode != 0:
        raise CatalogUnavailableError(
            f"`ollama list` exited {proc.returncode}: {(proc.stderr or '').strip()[:200]}"
        )
    models: list[str] = []
    for line in proc.stdout.splitlines():
        name = line.split()[0] if line.split() else ""
        if not name or name.upper() == "NAME":
            continue
        models.append(name)
    return ModelCatalog(harness="ollama", source="ollama_cli", models=tuple(models))


def _openrouter_cache_path() -> Path:
    from dontpanic_orchestrate import global_config as gc

    return gc.dontpanic_home() / "cache" / "models" / "openrouter.json"


def _read_openrouter_cache() -> tuple[str, ...] | None:
    path = _openrouter_cache_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        models = data["models"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
        return None
    if not isinstance(models, list) or not all(isinstance(m, str) for m in models):
        return None
    return tuple(models)


def _openrouter_cache_expired() -> bool:
    path = _openrouter_cache_path()
    try:
        return (time.time() - path.stat().st_mtime) > OPENROUTER_CACHE_TTL_SECONDS
    except OSError:
        return True


def _fetch_openrouter_ids() -> list[str]:
    """GET the OpenRouter models API and return the model id list. Split
    out as a seam so tests never touch the network."""
    req = urllib.request.Request(  # noqa: S310 — fixed https URL constant
        OPENROUTER_MODELS_URL, headers={"User-Agent": "dontpanic-model-catalog"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        payload = json.loads(resp.read().decode("utf-8"))
    return [
        entry["id"]
        for entry in payload.get("data", [])
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    ]


def _write_openrouter_cache(models: list[str]) -> None:
    path = _openrouter_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"models": models}, indent=2, ensure_ascii=False) + "\n")


def _discover_openrouter(*, refresh: bool, allow_network: bool) -> ModelCatalog:
    """OpenRouter models API with an offline-safe cache under
    ``~/.dontpanic/cache/models/openrouter.json``. Fresh cache serves
    without network; a failed refresh falls back to the cache (stale);
    ``allow_network=False`` (the doctor path) is cache-only."""
    cached = _read_openrouter_cache()
    expired = _openrouter_cache_expired()
    if cached is not None and not refresh and (not expired or not allow_network):
        return ModelCatalog(
            harness="openrouter", source="openrouter_cache", models=cached, stale=expired
        )
    if not allow_network:
        if cached is not None:
            return ModelCatalog(
                harness="openrouter", source="openrouter_cache", models=cached, stale=expired
            )
        raise CatalogUnavailableError(
            "openrouter catalog: no usable cache and network disabled — run "
            "`dontpanic models list --harness openrouter` online once to seed it"
        )
    try:
        ids = _fetch_openrouter_ids()
    except Exception as exc:  # noqa: BLE001 — any fetch failure degrades to cache
        if cached is not None:
            return ModelCatalog(
                harness="openrouter",
                source="openrouter_cache",
                models=cached,
                detail=f"refresh failed ({exc}); serving cached catalog",
                stale=True,
            )
        raise CatalogUnavailableError(
            f"openrouter models API unreachable and no cache exists: {exc}"
        ) from exc
    _write_openrouter_cache(ids)
    return ModelCatalog(harness="openrouter", source="openrouter_api", models=tuple(ids))


_DISCOVERY = {
    "ollama": _discover_ollama,
    "openrouter": _discover_openrouter,
}
"""Discovery surfaces for harnesses that have no executor yet (D3 adapters
land separately). Keyed by canonical harness id; these are catalog sources,
NOT dispatch registrations."""


def known_catalog_harnesses() -> list[str]:
    """Every harness id ``models list`` accepts: registered executors plus
    the standalone discovery surfaces."""
    from dontpanic_orchestrate.executors import AGENT_REGISTRY

    return sorted(set(AGENT_REGISTRY) | set(_DISCOVERY))


def get_catalog(harness: str, *, refresh: bool = False, allow_network: bool = True) -> ModelCatalog:
    """Model catalog for ``harness`` (D015 aliases accepted).

    Harnesses with a dedicated discovery surface (``_DISCOVERY``: ollama's
    local CLI, openrouter's models API + cache) answer through it whether or
    not an executor is registered — F014 registered both as dispatchable
    harnesses, and registration must not regress their catalogs to
    pass-through. Other registered harnesses answer through the optional
    :meth:`BaseExecutor.list_models` interface — ``None`` is the documented
    pass-through. Anything else raises :class:`UnknownHarnessError`.
    """
    from dontpanic_orchestrate.config.worker_profiles import normalize_harness
    from dontpanic_orchestrate.executors import AGENT_REGISTRY, get_executor

    normalized = normalize_harness(harness)
    discover = _DISCOVERY.get(normalized)
    if discover is not None:
        return discover(refresh=refresh, allow_network=allow_network)
    if normalized in AGENT_REGISTRY:
        models = get_executor(normalized).list_models()
        if models is None:
            return ModelCatalog(
                harness=normalized,
                source="pass_through",
                models=None,
                detail=(
                    f"{normalized} has no model-discovery surface; any freeform "
                    "model string is forwarded to the harness CLI unchanged"
                ),
            )
        return ModelCatalog(
            harness=normalized, source=f"{normalized}_executor", models=tuple(models)
        )
    raise UnknownHarnessError(
        f"unknown harness {harness!r}; known: {', '.join(known_catalog_harnesses())}. "
        "Model ids are never harnesses (D010)."
    )


# ── Aliases ────────────────────────────────────────────────────────────────


def load_model_aliases(plan_dir_or_project: Path | None) -> dict[str, str]:
    """Merged ``model_aliases`` table: global config overlaid by the
    per-project config (project wins per key). Missing blocks are the
    valid zero state — returns {}."""
    from dontpanic_orchestrate import global_config as gc
    from dontpanic_orchestrate import project_config as pc
    from dontpanic_orchestrate.worker_profiles import project_root_for

    merged: dict[str, str] = dict(gc.load_config().model_aliases or {})
    root = project_root_for(plan_dir_or_project)
    if root is not None:
        project_cfg = pc.load_project_config(root)
        if project_cfg is not None and project_cfg.model_aliases:
            merged.update(project_cfg.model_aliases)
    return merged


def resolve_alias(model: str | None, plan_dir_or_project: Path | None) -> str | None:
    """Single-hop alias resolution: an alias maps to a vendor model id,
    never to another alias (no chaining, so no cycles). A model string
    with no alias entry passes through unchanged — freeform models never
    require a config or code change."""
    if not model:
        return model
    return load_model_aliases(plan_dir_or_project).get(model, model)


# ── Probe (doctor) ─────────────────────────────────────────────────────────


def _ollama_probe_rejects(model: str) -> str | None:
    """Authoritative local probe: ``ollama show <model>``. Returns the
    rejection detail when the harness refuses the model, None when it
    accepts (or when the probe itself cannot run)."""
    ollama = shutil.which("ollama")
    if ollama is None:
        return None
    try:
        proc = subprocess.run(  # noqa: S603 — absolute vendor CLI path, fixed argv
            [ollama, "show", model],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "").strip()[:200] or f"exit {proc.returncode}"
    return ""


def probe_model(harness: str, model: str, *, allow_network: bool = True) -> ModelProbe:
    """Classify ``model`` against ``harness``'s catalog for the doctor.

    Freeform strings are allowed by design: absence from a catalog is
    ``unknown`` (advisory), never a failure. Only an authoritative harness
    probe refusal (ollama's ``show``) yields ``rejected``.
    """
    try:
        catalog = get_catalog(harness, allow_network=allow_network)
    except UnknownHarnessError:
        raise
    except CatalogUnavailableError as exc:
        return ModelProbe(status="unverifiable", detail=str(exc))
    if catalog.models is None:
        return ModelProbe(status="pass_through", detail=catalog.detail)
    if model in catalog.models:
        return ModelProbe(status="ok", detail=f"listed by {catalog.source}")
    if catalog.harness == "ollama":
        rejection = _ollama_probe_rejects(model)
        if rejection:
            return ModelProbe(status="rejected", detail=rejection)
        if rejection == "":
            return ModelProbe(status="ok", detail="accepted by `ollama show`")
    return ModelProbe(
        status="unknown",
        detail=f"not listed by {catalog.source} ({len(catalog.models)} models)"
        + (" — catalog may be stale" if catalog.stale else ""),
    )


__all__ = [
    "CatalogUnavailableError",
    "ModelCatalog",
    "ModelProbe",
    "OPENROUTER_CACHE_TTL_SECONDS",
    "OPENROUTER_MODELS_URL",
    "UnknownHarnessError",
    "get_catalog",
    "known_catalog_harnesses",
    "load_model_aliases",
    "probe_model",
    "resolve_alias",
]
