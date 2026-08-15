"""Close-out artifacts are named for the FEATURE they record, not the plan.

`close --operator-resolved` wrote three artifacts whose names varied only by
plan:

    evidence/closeout-memo.md
    audit/operator-resolution-<plan_id>.json
    audit/signoff-<plan_id>.json

The operation is per-feature. So the second operator-resolved close on a plan
silently overwrote the first — no warning, no merge, exit code zero — and the
earlier feature's `evidence_refs` were left pointing at a document describing a
*different* feature.

Measured across the fleet on 2026-08-14: 13 plans, 51 memos destroyed, worst
case a single silex-crucible plan whose memo had held 16 different feature ids.
Root cause and recovery recipe in
`docs/solutions/2026-08-14-closeout-memo-clobber.md`.

These tests pin two properties:

  1. two closes on one plan leave TWO memos, each naming its own feature;
  2. a write that WOULD clobber a different feature's artifact refuses loudly
     rather than proceeding.

The second matters more than the first. Per-feature names alone would leave any
existing shared-path memo silently replaceable; the guard is what turns a silent
overwrite into a visible refusal.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dontpanic_orchestrate import closeout


def _memo_feature_id(path: Path) -> str | None:
    for line in path.read_text().splitlines()[:12]:
        if line.startswith("feature_id:"):
            return line.split(":", 1)[1].strip()
    return None


class TestPerFeatureNaming:
    def test_memo_relpath_varies_by_feature(self):
        a = closeout.closeout_memo_relpath("F002")
        b = closeout.closeout_memo_relpath("F004")
        assert a != b, "two features must not share one memo path"
        assert "F002" in str(a) and "F004" in str(b)
        assert a.parent == Path("evidence") and b.parent == Path("evidence")

    def test_resolution_path_varies_by_feature(self, tmp_path):
        a = closeout.operator_resolution_path(tmp_path, "plan-x", "F002")
        b = closeout.operator_resolution_path(tmp_path, "plan-x", "F004")
        assert a != b, "two features must not share one resolution sidecar"
        assert "F002" in a.name and "F004" in b.name

    def test_memo_path_is_stable_for_the_same_feature(self):
        assert closeout.closeout_memo_relpath("F002") == closeout.closeout_memo_relpath("F002")


class TestRefusesToClobberAnotherFeature:
    """The guard: a differing feature_id is a refusal, not an overwrite."""

    def _memo(self, tmp_path: Path, feature_id: str) -> Path:
        p = tmp_path / "evidence" / "closeout-memo.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"---\nfeature_id: {feature_id}\n---\n\nrationale for {feature_id}\n")
        return p

    def test_refuses_when_existing_artifact_names_a_different_feature(self, tmp_path):
        path = self._memo(tmp_path, "F002")
        with pytest.raises(closeout.CloseoutArtifactConflict) as exc:
            closeout.assert_artifact_not_another_features(path, feature_id="F004")
        msg = str(exc.value)
        assert "F002" in msg and "F004" in msg, "the refusal must name both features"

    def test_allows_rewriting_the_same_features_artifact(self, tmp_path):
        """Re-running a close for the SAME feature is a legitimate refresh."""
        path = self._memo(tmp_path, "F002")
        closeout.assert_artifact_not_another_features(path, feature_id="F002")

    def test_allows_writing_where_nothing_exists(self, tmp_path):
        closeout.assert_artifact_not_another_features(
            tmp_path / "evidence" / "closeout-memo-F002.md", feature_id="F002"
        )

    def test_unreadable_or_unlabelled_artifact_does_not_block(self, tmp_path):
        """An artifact with no feature_id cannot be proven to belong elsewhere.

        Refusing here would strand operators behind a file we cannot attribute.
        We only refuse on a POSITIVE mismatch.
        """
        p = tmp_path / "evidence" / "closeout-memo.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("no frontmatter here\n")
        closeout.assert_artifact_not_another_features(p, feature_id="F004")


class TestTwoClosesLeaveTwoMemos:
    """The end-to-end property the fleet scan measured the absence of."""

    def test_second_close_does_not_destroy_the_first(self, tmp_path):
        evidence = tmp_path / "evidence"
        evidence.mkdir(parents=True)
        for fid in ("F002", "F004"):
            path = tmp_path / closeout.closeout_memo_relpath(fid)
            closeout.assert_artifact_not_another_features(path, feature_id=fid)
            path.write_text(f"---\nfeature_id: {fid}\n---\n\nrationale for {fid}\n")

        memos = sorted(p.name for p in evidence.glob("closeout-memo*.md"))
        assert len(memos) == 2, f"expected one memo per feature, got {memos}"
        ids = sorted(_memo_feature_id(evidence / m) for m in memos)
        assert ids == ["F002", "F004"], (
            "each memo must still name its own feature — this is the exact "
            "property whose absence destroyed 51 records across 13 plans"
        )
