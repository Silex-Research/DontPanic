"""Plan 2026-06-06-007 F001 — architecture clusters/levels + .mmd export.

The Architecture surface is an interactive component map. Its render
source of truth is the view-state graph model
(``nodes``/``edges``/``levels``/``clusters``/``freshness``) built by
:mod:`architecture_view_state`. This module owns the *clustering*:

  * :func:`cluster_key` — derive a node's cluster (its source directory).
  * :func:`build_clusters_and_levels` — fold the node list into a
    directory tree (root = "System") plus the per-depth level index.

It also provides an OPTIONAL, cache-only diffable export
(:func:`write_levels`) that renders per-level Mermaid ``.mmd`` slices for
docs/git review. The ``.mmd`` files are NEVER the page's render source —
the dashboard reads the view-state directly. Writing is best-effort and
confined to the build's own output directory, so a foreign project's
tree is never mutated.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT_KEY = ""
ROOT_TITLE = "System"
LEVELS_DIRNAME = "architecture-levels"


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


# ── Optional diffable .mmd export (cache-only) ──────────────────────────


def render_level_mermaid(view_state: dict[str, Any], level: int) -> str:
    """Render a Mermaid flowchart slice for one level's clusters.

    Each cluster at ``level`` becomes a ``subgraph`` listing its direct
    nodes; edges whose endpoints both fall inside this level's clusters
    are drawn. Output is deterministic (sorted) so a regenerated slice
    diffs cleanly against the committed one.
    """

    clusters = [c for c in view_state.get("clusters", []) if c.get("level") == level]
    node_titles = {
        n["id"]: n.get("title") or n["id"]
        for n in view_state.get("nodes", [])
        if isinstance(n, dict) and isinstance(n.get("id"), str)
    }
    member_ids: set[str] = set()
    lines = ["flowchart LR"]
    for cluster in sorted(clusters, key=lambda c: c["id"]):
        node_ids = sorted(cluster.get("node_ids", []))
        if not node_ids:
            continue
        lines.append(f'  subgraph {_mmd_id(cluster["id"])}["{_mmd_label(cluster["title"])}"]')
        for nid in node_ids:
            member_ids.add(nid)
            lines.append(f'    {_mmd_id(nid)}["{_mmd_label(node_titles.get(nid, nid))}"]')
        lines.append("  end")

    edges = sorted(
        (
            (e.get("from"), e.get("to"))
            for e in view_state.get("edges", [])
            if isinstance(e, dict)
            and e.get("from") in member_ids
            and e.get("to") in member_ids
        ),
    )
    for src, dst in edges:
        lines.append(f"  {_mmd_id(src)} --> {_mmd_id(dst)}")

    return "\n".join(lines) + "\n"


def write_levels(
    view_state: dict[str, Any],
    *,
    out_dir: Path,
    repo_root: Path | None = None,
) -> list[Path]:
    """Write per-level ``.mmd`` slices under ``out_dir/architecture-levels``.

    Cache-only: the slices land inside the build's own output directory,
    never in the target repo's ``docs/`` tree, so running a build against
    a foreign project never mutates it. Best-effort — returns the list of
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
        content = render_level_mermaid(view_state, level)
        path = target_dir / f"L{level}.mmd"
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def _mmd_id(raw: str) -> str:
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
    "render_level_mermaid",
    "write_levels",
]
