"""Navigable architecture — per-level Mermaid slices (plan 2026-06-06-004 F008, spec §9).

The flat 149-node force-directed graph is replaced by a C4-style hierarchy: never draw the
whole thing, draw one small legible level at a time, generated deterministically from
``architecture.json`` and written to ``docs/architecture/levels/*.mmd`` (diff-able text, not an
opaque canvas — reviewable in a PR, readable by a human or an agent, regenerated on the hook).

Render-truth per node (§9.3): each node carries individual freshness from
``source_fingerprint.file_hashes`` — solid green when its file hash matches the snapshot, dashed
red when the file changed since generation (drift). The operator sees *where* the map can't be
trusted instead of a uniformly confident-looking diagram.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

LANES = ("Plans", "Features", "Modules", "Schemas", "Evidence")
_CLUSTER_DEPTH = 2  # group modules by their first N path segments → ~a dozen legible clusters
_MAX_NODES = 25  # §9 — every slice stays legible; a denser package paginates into ≤25-node pages
_DENSE_THRESHOLD = 30  # past this (within a page), request the ELK layout for orthogonal routing (§9.2)

_CLASSDEFS = (
    "classDef fresh stroke:#16A34A,stroke-width:2px;\n"
    "classDef drift stroke:#DC2626,stroke-width:2px,stroke-dasharray:4 3;"
)


def _nid(s: str) -> str:
    """A Mermaid-safe node id."""
    return re.sub(r"[^0-9a-zA-Z_]", "_", str(s)) or "n"


def cluster_key(path: str, depth: int = _CLUSTER_DEPTH) -> str:
    """Group a module into its package = the file's directory. Directory clustering keeps each
    package legible (a fixed prefix length collapses a deep tree into one mega-cluster); a
    package that is still dense past ~30 nodes is rendered with ELK at L3 (§9.2)."""
    parts = [p for p in str(path).split("/") if p]
    if len(parts) <= 1:
        return "(root)"  # a top-level file has no package
    return "/".join(parts[:-1])


def _modules(snapshot: Mapping[str, object]) -> list[Mapping[str, object]]:
    mods = snapshot.get("modules")
    return [m for m in mods if isinstance(m, Mapping)] if isinstance(mods, Sequence) else []


def _cls(path: str, drifted: Iterable[str]) -> str:
    return "drift" if path in set(drifted) else "fresh"


def _clusters(snapshot: Mapping[str, object]) -> dict[str, list[Mapping[str, object]]]:
    groups: dict[str, list[Mapping[str, object]]] = {}
    for m in _modules(snapshot):
        groups.setdefault(cluster_key(str(m.get("path", ""))), []).append(m)
    return dict(sorted(groups.items()))


def _cluster_drifted(mods: Iterable[Mapping[str, object]], drifted: set[str]) -> bool:
    return any(str(m.get("path", "")) in drifted for m in mods)


def level_context(snapshot: Mapping[str, object]) -> str:
    """L0 — the project as one node + its plans/schemas/modules counts."""
    plans = snapshot.get("plans") or []
    schemas = snapshot.get("schemas") or []
    lines = ["%% L0 — context (generated from architecture.json)", "graph LR", f"  {_CLASSDEFS}"]
    lines.append(f'  project["⬢ project · {len(_modules(snapshot))} mods"]:::fresh')
    lines.append(f'  plans["▤ plans · {len(plans)}"]:::fresh')
    lines.append(f'  schemas[("◳ schemas · {len(schemas)}")]:::fresh')
    lines.append("  project --> plans")
    lines.append("  project --> schemas")
    return "\n".join(lines)


def level_lanes() -> str:
    """L1 — the five doc lanes (the default landing), a fixed legible chain."""
    lines = ["%% L1 — lanes", "graph LR"]
    ids = [_nid(l) for l in LANES]
    for lane, i in zip(LANES, ids):
        lines.append(f'  {i}["{lane}"]')
    for a, b in zip(ids, ids[1:]):
        lines.append(f"  {a} --> {b}")
    return "\n".join(lines)


def level_clusters(snapshot: Mapping[str, object], drifted: Iterable[str] = ()) -> str:
    """L2 — ~a dozen path-derived clusters; edges = aggregated cross-cluster imports."""
    drift = set(drifted)
    clusters = _clusters(snapshot)
    name_to_cluster = _name_index(snapshot)
    lines = ["%% L2 — clusters", "graph LR", f"  {_CLASSDEFS}"]
    for key, mods in clusters.items():
        cls = "drift" if _cluster_drifted(mods, drift) else "fresh"
        mark = "○ drift" if cls == "drift" else "●"
        lines.append(f'  {_nid(key)}["⬣ {key} · {len(mods)} mods · {mark}"]:::{cls}')
    for src, dst in sorted(_cluster_edges(snapshot, name_to_cluster)):
        if src != dst:
            lines.append(f"  {_nid(src)} --> {_nid(dst)}")
    return "\n".join(lines)


def level_subgraph(
    snapshot: Mapping[str, object],
    cluster: str,
    drifted: Iterable[str] = (),
    mods: Sequence[Mapping[str, object]] | None = None,
) -> str:
    """L3 — the modules inside one cluster (or one bounded page of it) + their import edges."""
    drift = set(drifted)
    if mods is None:
        mods = _clusters(snapshot).get(cluster, [])
    paths = {str(m.get("path", "")) for m in mods}
    name_to_path = {str(m.get("name") or Path(str(m.get("path", ""))).stem): str(m.get("path", "")) for m in mods}
    renderer = '%%{init: {"flowchart":{"defaultRenderer":"elk"}}}%%\n' if len(mods) > _DENSE_THRESHOLD else ""
    lines = [f"{renderer}%% L3 — {cluster}", "graph LR", f"  {_CLASSDEFS}"]
    for m in mods:
        p = str(m.get("path", ""))
        lines.append(f'  {_nid(p)}["{Path(p).name}"]:::{_cls(p, drift)}')
    for m in mods:
        sp = str(m.get("path", ""))
        for imp in m.get("imports") or []:
            tp = _resolve_import(str(imp), name_to_path)
            if tp and tp in paths and tp != sp:
                lines.append(f"  {_nid(sp)} --> {_nid(tp)}")
    return "\n".join(lines)


def _name_index(snapshot: Mapping[str, object]) -> dict[str, str]:
    """name / last-path-segment → cluster, for resolving imports to clusters."""
    idx: dict[str, str] = {}
    for m in _modules(snapshot):
        path = str(m.get("path", ""))
        key = cluster_key(path)
        for token in {str(m.get("name") or ""), Path(path).stem}:
            if token:
                idx[token] = key
    return idx


def _resolve_import(imp: str, name_to_path: Mapping[str, str]) -> str | None:
    for name, path in name_to_path.items():
        if name and (imp == name or imp.endswith(f".{name}") or imp.endswith(f"/{name}")):
            return path
    return None


def _cluster_edges(snapshot: Mapping[str, object], name_to_cluster: Mapping[str, str]) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for m in _modules(snapshot):
        src = cluster_key(str(m.get("path", "")))
        for imp in m.get("imports") or []:
            for name, clstr in name_to_cluster.items():
                if name and (str(imp) == name or str(imp).endswith(f".{name}") or str(imp).endswith(f"/{name}")):
                    edges.add((src, clstr))
                    break
    return edges


def build_levels(snapshot: Mapping[str, object], drifted: Iterable[str] = ()) -> dict[str, str]:
    """All level slices, keyed by level id (L0, L1, L2, and L3-<cluster> per cluster)."""
    out = {
        "L0": level_context(snapshot),
        "L1": level_lanes(),
        "L2": level_clusters(snapshot, drifted),
    }
    for cluster, mods in _clusters(snapshot).items():
        # Keep every L3 slice legible (§9): a package denser than _MAX_NODES paginates into
        # bounded pages rather than one illegible mega-graph (ELK only fixes layout, not size).
        if len(mods) <= _MAX_NODES:
            out[f"L3-{cluster}"] = level_subgraph(snapshot, cluster, drifted, mods)
        else:
            pages = [mods[i : i + _MAX_NODES] for i in range(0, len(mods), _MAX_NODES)]
            for n, page in enumerate(pages, 1):
                out[f"L3-{cluster}#{n}"] = level_subgraph(snapshot, cluster, drifted, page)
    return out


def compute_drift(snapshot: Mapping[str, object], repo_root: str | Path) -> set[str]:
    """Paths whose CURRENT file hash differs from the snapshot — render-truth per node (§9.3).
    A missing file counts as drift; an unreadable one is left out (best-effort, never raises)."""
    root = Path(repo_root)
    fh = ((snapshot.get("source_fingerprint") or {}).get("file_hashes")) or {}
    algo = ((snapshot.get("source_fingerprint") or {}).get("algo")) or "sha256"
    drifted: set[str] = set()
    for path, recorded in fh.items() if isinstance(fh, Mapping) else []:
        f = root / path
        try:
            cur = hashlib.new(algo, f.read_bytes()).hexdigest() if f.is_file() else None
        except (OSError, ValueError):
            continue
        if cur != recorded:
            drifted.add(str(path))
    return drifted


def write_levels(
    snapshot: Mapping[str, object],
    out_dir: str | Path,
    drifted: Iterable[str] | None = None,
    repo_root: str | Path | None = None,
) -> list[Path]:
    """Write each level to ``<out_dir>/<level>.mmd`` (deterministic, diff-able). Returns paths.

    Render-truth by default (§9.3): when ``drifted`` isn't supplied, drift is computed from the
    snapshot's ``source_fingerprint`` against ``repo_root`` so the writer never silently emits
    every node as fresh. Pass ``drifted=()`` to opt out explicitly."""
    if drifted is None:
        drifted = compute_drift(snapshot, repo_root) if repo_root is not None else ()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for level, mermaid in build_levels(snapshot, drifted).items():
        p = out / f"{_nid(level)}.mmd"
        p.write_text(mermaid + "\n", encoding="utf-8")
        written.append(p)
    return sorted(written)
