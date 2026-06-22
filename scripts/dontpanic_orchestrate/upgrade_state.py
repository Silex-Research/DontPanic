"""Plan 2026-06-21-001 F004 — per-instance upgrade-state marker + releases-since
diff + first-run policy.

This is the **core/persistence** layer of the upgrade-readiness feature. It owns
the on-disk marker ``upgrade-state.json`` (HOME-resolved under ``~/.dontpanic``),
the pure ``releases_since`` diff, the first-run advisory policy, and the pure
``advance_marker`` / ``dismiss_advisory`` transforms.

CONSENT INVARIANT — NO SILENT WRITE (D015): :func:`write_upgrade_state` is the ONLY
writer, and it is invoked ONLY by the F007 acknowledge/dismiss path. A *read*
(:func:`read_upgrade_state`) NEVER persists anything: when the marker file is
absent it returns an IN-MEMORY effective marker (anchored to the latest release)
without touching disk, so a plain ``doctor`` / ``--upgrade`` read can never
silently suppress advisories by writing a fresh "I've seen latest" marker.

THREE MARKER CASES (D040/D042/D044), surfaced via :class:`MarkerState`:

* **absent** — no file ever (fresh install). The in-memory effective marker
  anchors to the LATEST release so the advisory history is NOT replayed; only
  ``show_on_first_run`` advisories are shown (D012). The DISPLAYED acknowledgement
  (``last_seen_release`` / ``last_seen_commit``) is NULL / "never acknowledged" —
  the latest anchor is an internal diff device, never a displayed acknowledgement
  (D042), so it can never imply the operator acknowledged the latest release.

* **predates** — an EXISTING marker whose ``last_seen_release`` is absent from the
  manifest OR is the baseline (orders before the earliest manifest release). This
  is a real UPGRADE from an old version: every manifest release is new and ALL
  their advisories are shown — the ``show_on_first_run`` filter does NOT apply
  here (D040/D044). The displayed acknowledgement reflects the real marker value.

* **known** — an EXISTING in-manifest marker: :func:`releases_since` returns the
  releases strictly newer than ``last_seen_release`` (manifest order) and their
  advisories are shown.

REQUIRED ACTIONS BYPASS THE MARKER (D004/D012): nothing in this module satisfies a
required action — required-action satisfaction is owned solely by the F003
``status_probe`` layer. :func:`advance_marker` / :func:`dismiss_advisory` change
ONLY advisory visibility / acknowledgement; they can never clear a probe-failing
required action.

:func:`releases_since` and :func:`first_run_advisories` are PURE and NEVER raise —
in particular ``releases_since`` never raises on an unknown / stale / baseline
``last_seen_release`` (D035).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dontpanic_orchestrate import global_config as gc
from dontpanic_orchestrate.upgrade_releases_model import (
    Kind,
    UpgradeAction,
    UpgradeManifest,
    UpgradeRelease,
)

_LOG = logging.getLogger(__name__)

#: Marker filename under ``$DONTPANIC_HOME`` (HOME-resolved, never committed).
MARKER_FILENAME = "upgrade-state.json"


class MarkerState(str, Enum):
    """Which of the three marker cases (D040/D042) a read resolved to.

    * ``absent`` — no marker file (fresh install); first-run advisory policy.
    * ``predates`` — existing marker before all manifest releases (a real upgrade);
      ALL advisories shown.
    * ``known`` — existing in-manifest marker; ``releases_since`` advisories shown.
    """

    absent = "absent"
    predates = "predates"
    known = "known"


class UpgradeStateMarker(BaseModel):
    """The on-disk per-instance marker value.

    Carries NO secret-shaped data by construction — only release ids, a commit
    sha, dismissed-advisory keys, and an init timestamp. ``extra='forbid'`` so a
    stray/injected field is rejected rather than silently round-tripped.
    """

    model_config = ConfigDict(extra="forbid")

    last_seen_release: str | None = Field(
        None, description="Last acknowledged release id (None = never acknowledged)."
    )
    last_seen_commit: str | None = Field(
        None, description="Installed commit sha at last acknowledgement (optional)."
    )
    dismissed_advisories: list[str] = Field(
        default_factory=list,
        description="Stable advisory keys (upgrade:<release>:<action>) explicitly dismissed.",
    )
    first_initialized_at: str | None = Field(
        None, description="ISO-8601 instant the marker was first written (F007 stamps it)."
    )


@dataclass(frozen=True)
class EffectiveMarker:
    """The result of :func:`read_upgrade_state`.

    ``marker`` is the marker value used for the diff — for an ABSENT file this is
    the in-memory effective marker anchored to the latest release (NOT persisted).
    ``displayed_last_seen_release`` / ``displayed_last_seen_commit`` are what a
    surface should SHOW as the acknowledgement — NULL for an absent marker (D042),
    so the internal latest-anchor never leaks as a displayed acknowledgement.
    """

    marker: UpgradeStateMarker
    marker_state: MarkerState
    file_present: bool
    displayed_last_seen_release: str | None
    displayed_last_seen_commit: str | None


@dataclass(frozen=True)
class VisibleAdvisory:
    """An advisory action that is visible to this instance, with its release id."""

    release_id: str
    action: UpgradeAction

    @property
    def key(self) -> str:
        """The stable advisory key ``upgrade:<release>:<action>`` (dismissal id)."""
        return advisory_key(self.release_id, self.action.id)


def advisory_key(release_id: str, action_id: str) -> str:
    """The stable advisory id ``upgrade:<release>:<action>`` used for dismissal."""
    return f"upgrade:{release_id}:{action_id}"


# ──────────────────────────────  paths + persistence  ──────────────────────────────


def marker_path(path: Path | str | None = None) -> Path:
    """Resolve the marker path. ``None`` -> ``$DONTPANIC_HOME``/``upgrade-state.json``.

    Tests pass an explicit ``path`` to drive a tmp HOME without touching real state.
    """
    if path is not None:
        return Path(path)
    return gc.dontpanic_home() / MARKER_FILENAME


def write_upgrade_state(marker: UpgradeStateMarker, *, path: Path | str | None = None) -> Path:
    """Persist the marker (D015: ONLY the F007 acknowledge/dismiss path calls this).

    Creates the parent directory if needed. This is the SOLE writer of the marker;
    reads never persist. Returns the written path.
    """
    target = marker_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(marker.model_dump(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def _load_marker(target: Path) -> UpgradeStateMarker:
    """Load a PRESENT marker file, fail-SAFE toward showing advisories.

    A malformed / unreadable / schema-violating present file degrades to an EMPTY
    marker (``last_seen_release=None``) — which classifies as ``predates`` and thus
    shows ALL advisories — rather than masquerading as a fresh ``absent`` install
    that would apply the first-run suppression filter. The safe direction is to
    over-show, never to silently suppress (mirrors the F003 fail-open spirit)."""
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning("upgrade-state marker at %s unreadable/invalid (%s); showing all advisories", target, exc)
        return UpgradeStateMarker()
    try:
        return UpgradeStateMarker.model_validate(raw)
    except ValidationError as exc:
        _LOG.warning("upgrade-state marker at %s failed validation (%s); showing all advisories", target, exc)
        return UpgradeStateMarker()


def read_upgrade_state(
    manifest: UpgradeManifest, *, path: Path | str | None = None
) -> EffectiveMarker:
    """Read the marker WITHOUT ever writing (D015).

    * ABSENT file -> in-memory effective marker anchored to the latest release;
      ``marker_state=absent``; displayed acknowledgement is NULL (D042). NO file is
      created (dedicated test asserts the file stays absent after a read).
    * PRESENT file -> the parsed marker; ``marker_state`` is ``known`` when
      ``last_seen_release`` is in the manifest, else ``predates`` (absent-from-manifest
      or baseline -> before all releases, D040). Displayed acknowledgement reflects
      the real marker value.
    """
    target = marker_path(path)
    if not target.is_file():
        latest = manifest.releases[-1].id if manifest.releases else None
        # Anchor to latest so releases_since(effective) == [] -> history NOT replayed.
        effective = UpgradeStateMarker(last_seen_release=latest)
        return EffectiveMarker(
            marker=effective,
            marker_state=MarkerState.absent,
            file_present=False,
            displayed_last_seen_release=None,
            displayed_last_seen_commit=None,
        )

    marker = _load_marker(target)
    state = _classify_marker(marker, manifest)
    return EffectiveMarker(
        marker=marker,
        marker_state=state,
        file_present=True,
        displayed_last_seen_release=marker.last_seen_release,
        displayed_last_seen_commit=marker.last_seen_commit,
    )


# ──────────────────────────────  pure diff + advisory policy  ──────────────────────────────


def _release_index(manifest: UpgradeManifest, release_id: str | None) -> int | None:
    if release_id is None:
        return None
    for idx, release in enumerate(manifest.releases):
        if release.id == release_id:
            return idx
    return None


def _classify_marker(marker: UpgradeStateMarker, manifest: UpgradeManifest) -> MarkerState:
    """Classify a PRESENT marker as ``known`` (in-manifest) or ``predates`` (before-all)."""
    if _release_index(manifest, marker.last_seen_release) is not None:
        return MarkerState.known
    return MarkerState.predates


def releases_since(marker: UpgradeStateMarker, manifest: UpgradeManifest) -> list[UpgradeRelease]:
    """Releases strictly newer than ``marker.last_seen_release`` in manifest order (PURE).

    * ``last_seen_release`` in the manifest -> the releases AFTER it.
    * ``last_seen_release`` None, baseline, or absent-from-manifest -> ALL releases
      (treated as positioned before all manifest releases, D035/D040).

    NEVER raises on an unknown / stale / baseline ``last_seen_release`` (D035).
    """
    idx = _release_index(manifest, marker.last_seen_release)
    if idx is None:
        # before-all: None, baseline, or absent-from-manifest -> every release is new.
        return list(manifest.releases)
    return list(manifest.releases[idx + 1 :])


def _advisories_in(releases: list[UpgradeRelease]) -> list[VisibleAdvisory]:
    advisories: list[VisibleAdvisory] = []
    for release in releases:
        for action in release.actions:
            if action.kind is Kind.advisory:
                advisories.append(VisibleAdvisory(release_id=release.id, action=action))
    return advisories


def first_run_advisories(manifest: UpgradeManifest) -> list[VisibleAdvisory]:
    """Advisories shown on a fresh (ABSENT) marker — only ``show_on_first_run`` releases (PURE, D012).

    The full advisory history is NOT replayed on first run; only releases flagged
    ``show_on_first_run=true`` contribute advisories. NEVER raises.
    """
    return _advisories_in([r for r in manifest.releases if r.show_on_first_run])


def visible_advisories(effective: EffectiveMarker, manifest: UpgradeManifest) -> list[VisibleAdvisory]:
    """Advisories visible to this instance, governed by ``marker_state`` then dismissals.

    * ``absent`` -> :func:`first_run_advisories` (``show_on_first_run`` only, D012/D044).
    * ``predates`` -> ALL manifest advisories (no first-run filter — a real upgrade, D040).
    * ``known`` -> advisories of :func:`releases_since`.

    Dismissed advisory keys (from the marker) are then filtered out. PURE; never raises.
    """
    if effective.marker_state is MarkerState.absent:
        advisories = first_run_advisories(manifest)
    elif effective.marker_state is MarkerState.predates:
        advisories = _advisories_in(list(manifest.releases))
    else:  # known
        advisories = _advisories_in(releases_since(effective.marker, manifest))

    dismissed = set(effective.marker.dismissed_advisories)
    return [adv for adv in advisories if adv.key not in dismissed]


# ──────────────────────────────  pure marker transforms  ──────────────────────────────


def advance_marker(
    marker: UpgradeStateMarker, *, release_id: str, commit: str | None = None
) -> UpgradeStateMarker:
    """Return a NEW marker advanced to ``release_id`` (and optional ``commit``) — PURE.

    Preserves ``dismissed_advisories`` and ``first_initialized_at``; the input
    marker is never mutated. This changes acknowledgement / advisory visibility
    ONLY — it can never satisfy a required action (those are probe-driven, D004).
    """
    return marker.model_copy(
        update={"last_seen_release": release_id, "last_seen_commit": commit}
    )


def dismiss_advisory(marker: UpgradeStateMarker, key: str) -> UpgradeStateMarker:
    """Return a NEW marker with advisory ``key`` dismissed (idempotent) — PURE.

    The input marker is never mutated. Dismissing suppresses one advisory only; it
    never touches required-action state.
    """
    if key in marker.dismissed_advisories:
        return marker.model_copy()
    return marker.model_copy(
        update={"dismissed_advisories": [*marker.dismissed_advisories, key]}
    )


__all__ = [
    "MARKER_FILENAME",
    "EffectiveMarker",
    "MarkerState",
    "UpgradeStateMarker",
    "VisibleAdvisory",
    "advance_marker",
    "advisory_key",
    "dismiss_advisory",
    "first_run_advisories",
    "marker_path",
    "read_upgrade_state",
    "releases_since",
    "visible_advisories",
    "write_upgrade_state",
]
