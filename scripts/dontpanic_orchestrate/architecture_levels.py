"""Architecture clusters/levels (the model) + an optional Mermaid export.

THE SINGLE SOURCE OF TRUTH for architecture clustering. The live interactive
component map (Architecture page) reads ``clusters``/``levels`` straight from
the view-state built by :mod:`architecture_view_state`, which derives them via
:func:`build_clusters_and_levels` here. There must be exactly ONE clustering
definition (:func:`cluster_key` + :func:`build_clusters_and_levels`); the map
is never driven by a second, independently-walked architecture source.

This module ALSO provides an OPTIONAL, docs/cache-only diffable Mermaid export
(:func:`export_mermaid_levels`) that renders per-level ``.mmd`` slices *from
that same model* — never the UI's render source. It folds in the render-truth
mechanics of the earlier (plan 2026-06-06-004 F008) Mermaid writer:

  * per-node drift coloring (§9.3) — :func:`compute_drift` hashes files against
    ``source_fingerprint.file_hashes`` so a changed file shows dashed-red, not a
    uniformly confident-looking diagram;
  * legibility (§9) — a cluster denser than ``_MAX_NODES`` paginates into bounded
    pages; a busy level requests the ELK layout for orthogonal routing.

Reconciliation note (007↔004): this file supersedes the older
``architecture_levels.py`` on the unmerged ``chore/plan-ledger-reconciliation-
2026-06-04`` branch, which kept its OWN clustering (``_clusters`` /
``_cluster_edges`` / a separate ``cluster_key``) and a C4 lane/context taxonomy.
Those were a second architecture source; the curated structure is replaced by
the directory-depth cluster/level model the view-state already carries, with the
old writer's drift/legibility behaviour folded in here. On merge, take this
version wholesale; the old ``test_architecture_levels_f008.py`` is superseded by
``test_architecture_levels_f007.py`` (the old generator had no production call
site — only its own test).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

ROOT_KEY = ""
ROOT_TITLE = "System"
LEVELS_DIRNAME = "architecture-levels"

# §9 legibility knobs (folded from the F008 writer).
_MAX_NODES = 25  # a cluster denser than this paginates into ≤25-node pages
_DENSE_THRESHOLD = 30  # a level busier than this requests ELK orthogonal routing

_CLASSDEFS = (
    "  classDef fresh stroke:#16A34A,stroke-width:2px;\n"
    "  classDef drift stroke:#DC2626,stroke-width:2px,stroke-dasharray:4 3;"
)
_ELK_DIRECTIVE = '%%{init: {"flowchart":{"defaultRenderer":"elk"}}}%%\n'


# ── Clustering model (the single source of truth) ───────────────────────


def cluster_key(source_path: str | None) -> str | None:
    """Directory a node belongs to, derived from its ``source_path``.

    * ``"a/b/c.py"`` → ``"a/b"``
    * ``"README.md"`` (root-level file) → ``""`` (the System root)
    * ``None`` / ``""`` (no source path) → ``None`` (caller attaches the
      node to the System root).
    """

    if not isinstance(source_path, str) or not source_path:
        return None
    norm = source_path.replace("\\", "/")
    if "/" in norm:
        return norm.rsplit("/", 1)[0]
    return ROOT_KEY


def cluster_node_id(key: str) -> str:
    return f"cluster:{key}"


def cluster_title(key: str) -> str:
    if key == ROOT_KEY:
        return ROOT_TITLE
    return key.rsplit("/", 1)[-1]


def _parent_key(key: str) -> str | None:
    if key == ROOT_KEY:
        return None
    if "/" in key:
        return key.rsplit("/", 1)[0]
    return ROOT_KEY


def build_clusters_and_levels(
    nodes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fold ``nodes`` into a directory cluster tree + a per-depth index.

    Returns ``(clusters, levels)``. Both are deterministically ordered so
    the same node list always yields byte-identical output.

    Each cluster: ``{id, key, title, level, parent_id, node_ids,
    child_cluster_ids}``. ``node_ids`` holds the nodes *directly* in the
    cluster (sorted); ancestor directories are materialized even when they
    hold no direct nodes so the breadcrumb path stays unbroken.

    Each level: ``{id, level, title, cluster_ids}`` listing every cluster
    id at that depth (sorted).
    """

    direct: dict[str, list[str]] = {}
    all_keys: set[str] = {ROOT_KEY}

    for node in nodes:
        if not isinstance(node, dict):
            continue
        nid = node.get("id")
        if not isinstance(nid, str) or not nid:
            continue
        key = cluster_key(node.get("source_path"))
        if key is None:
            key = ROOT_KEY
        direct.setdefault(key, []).append(nid)
        # Register every ancestor directory so the tree is connected.
        parts = key.split("/") if key else []
        for depth in range(len(parts) + 1):
            all_keys.add("/".join(parts[:depth]))

    children: dict[str, list[str]] = {}
    for key in all_keys:
        parent = _parent_key(key)
        if parent is not None:
            children.setdefault(parent, []).append(cluster_node_id(key))

    clusters: list[dict[str, Any]] = []
    for key in sorted(all_keys):
        parent = _parent_key(key)
        clusters.append(
            {
                "id": cluster_node_id(key),
                "key": key,
                "title": cluster_title(key),
                "level": 0 if key == ROOT_KEY else key.count("/") + 1,
                "parent_id": cluster_node_id(parent) if parent is not None else None,
                "node_ids": sorted(direct.get(key, [])),
                "child_cluster_ids": sorted(children.get(key, [])),
            }
        )

    levels_by_depth: dict[int, list[str]] = {}
    for cluster in clusters:
        levels_by_depth.setdefault(cluster["level"], []).append(cluster["id"])

    levels: list[dict[str, Any]] = []
    for level in sorted(levels_by_depth):
        levels.append(
            {
                "id": f"level:{level}",
                "level": level,
                "title": f"L{level}",
                "cluster_ids": sorted(levels_by_depth[level]),
            }
        )

    return clusters, levels


# ── Render-truth drift (folded from F008 §9.3) ──────────────────────────


def compute_drift(
    snapshot: Mapping[str, Any],
    repo_root: str | Path,
) -> set[str]:
    """Source paths whose CURRENT file hash differs from the snapshot.

    Render-truth per node (§9.3): hashes each file recorded in
    ``source_fingerprint.file_hashes`` against the working tree so the
    export can mark drifted nodes dashed-red instead of uniformly fresh. A
    missing file counts as drift; an unreadable one is skipped. Best-effort
    — never raises. The result feeds :func:`export_mermaid_levels` as an
    optional overlay (the cluster/level STRUCTURE still comes only from the
    view-state model, so there is no second architecture source).
    """

    root = Path(repo_root)
    fp = snapshot.get("source_fingerprint") if isinstance(snapshot, Mapping) else None
    fp = fp if isinstance(fp, Mapping) else {}
    file_hashes = fp.get("file_hashes")
    algo = fp.get("algo") or "sha256"
    drifted: set[str] = set()
    if not isinstance(file_hashes, Mapping):
        return drifted
    for path, recorded in file_hashes.items():
        f = root / str(path)
        try:
            current = hashlib.new(algo, f.read_bytes()).hexdigest() if f.is_file() else None
        except (OSError, ValueError):
            continue
        if current != recorded:
            drifted.add(str(path))
    return drifted


# ── Optional Mermaid export (docs/cache-only, never the UI source) ──────


def render_level_mermaid(
    view_state: Mapping[str, Any],
    level: int,
    *,
    drift: Iterable[str] = (),
) -> str:
    """Render a Mermaid flowchart slice for one level's clusters.

    Structure comes entirely from the view-state model (``clusters`` +
    ``nodes`` + ``edges``). ``drift`` is an optional set of source paths
    (from :func:`compute_drift`); nodes whose ``source_path`` is in it are
    marked ``:::drift``, everything else ``:::fresh``. A cluster denser than
    ``_MAX_NODES`` paginates into bounded subgraph pages; a level busier than
    ``_DENSE_THRESHOLD`` requests the ELK layout. Deterministic (sorted).
    """

    drift_set = {str(p) for p in (drift or ())}
    clusters = [
        c for c in view_state.get("clusters", []) if c.get("level") == level
    ]
    nodes_by_id = {
        n["id"]: n
        for n in view_state.get("nodes", [])
        if isinstance(n, dict) and isinstance(n.get("id"), str)
    }

    member_ids: set[str] = set()
    pages: list[tuple[str, str, list[str]]] = []  # (subgraph id, title, node ids)
    for cluster in sorted(clusters, key=lambda c: c["id"]):
        node_ids = sorted(cluster.get("node_ids", []))
        if not node_ids:
            continue
        title = cluster.get("title") or cluster["id"]
        if len(node_ids) <= _MAX_NODES:
            pages.append((cluster["id"], title, node_ids))
        else:
            for page_no, start in enumerate(range(0, len(node_ids), _MAX_NODES), 1):
                page_ids = node_ids[start : start + _MAX_NODES]
                pages.append((f'{cluster["id"]}#{page_no}', f"{title} (page {page_no})", page_ids))
        member_ids.update(node_ids)

    header = _ELK_DIRECTIVE if len(member_ids) > _DENSE_THRESHOLD else ""
    lines = [f"{header}flowchart LR"]
    if member_ids:
        lines.append(_CLASSDEFS)
    for subgraph_id, title, node_ids in pages:
        lines.append(f'  subgraph {_nid(subgraph_id)}["{_mmd_label(title)}"]')
        for nid in node_ids:
            node = nodes_by_id.get(nid, {})
            klass = "drift" if node.get("source_path") in drift_set else "fresh"
            label = node.get("title") or nid
            lines.append(f'    {_nid(nid)}["{_mmd_label(label)}"]:::{klass}')
        lines.append("  end")

    edges = sorted(
        (e.get("from"), e.get("to"))
        for e in view_state.get("edges", [])
        if isinstance(e, dict)
        and e.get("from") in member_ids
        and e.get("to") in member_ids
    )
    for src, dst in edges:
        lines.append(f"  {_nid(src)} --> {_nid(dst)}")

    return "\n".join(lines) + "\n"


def export_mermaid_levels(
    view_state: Mapping[str, Any],
    *,
    out_dir: str | Path,
    drift: Iterable[str] = (),
) -> list[Path]:
    """Write per-level ``LN.mmd`` slices under ``<out_dir>/architecture-levels``.

    Docs/cache-only: the slices are an OPTIONAL diffable export, NEVER the
    Architecture page's render source (the page reads clusters/levels from
    the view-state directly). Confine writes to the caller's own ``out_dir``
    so a build against a foreign project never mutates its tree. Pass
    ``drift`` (e.g. ``compute_drift(snapshot, repo_root)``) to color drifted
    nodes; omit it for structure-only slices. Best-effort — returns the
    written paths (empty when the view-state carries no clusters).
    """

    levels = view_state.get("levels") or []
    if not view_state.get("clusters"):
        return []

    target_dir = Path(out_dir) / LEVELS_DIRNAME
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for level_entry in sorted(levels, key=lambda lv: lv.get("level", 0)):
        level = level_entry.get("level", 0)
        content = render_level_mermaid(view_state, level, drift=drift)
        path = target_dir / f"L{level}.mmd"
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


# Deprecated alias — kept so existing callers (dashboard.build) and the
# 007 tests keep working under the canonical name. Prefer
# ``export_mermaid_levels``.
def write_levels(
    view_state: Mapping[str, Any],
    *,
    out_dir: str | Path,
    drift: Iterable[str] = (),
) -> list[Path]:
    return export_mermaid_levels(view_state, out_dir=out_dir, drift=drift)


def _nid(raw: str) -> str:
    """Sanitize a node/cluster id into a Mermaid-safe identifier."""

    safe = "".join(ch if ch.isalnum() else "_" for ch in str(raw))
    return safe or "_"


def _mmd_label(raw: str) -> str:
    return str(raw).replace('"', "'").replace("\n", " ")


__all__ = [
    "ROOT_KEY",
    "ROOT_TITLE",
    "LEVELS_DIRNAME",
    "cluster_key",
    "cluster_node_id",
    "cluster_title",
    "build_clusters_and_levels",
    "compute_drift",
    "render_level_mermaid",
    "export_mermaid_levels",
    "write_levels",
]
