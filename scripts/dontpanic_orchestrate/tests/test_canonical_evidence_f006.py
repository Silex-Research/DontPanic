"""Plan 2026-06-17-001 F006 — the C4 canonical-backfill evidence contract.

Covers:
  * a valid evidence file resolves a confirmable observation key to its single
    shape-validated canonical entry (incl. optional hash-shaped origin_key and
    boolean observed_under_temp_prefix);
  * file-fatal defects (invalid JSON, missing/unreadable file, missing top-level
    keys, wrong schema_version, top-level type errors) raise EvidenceFatalError
    with a stable reason — the whole run aborts;
  * row-level defects (absent key, non-list / zero / multiple mappings, unknown
    canonical reference, mismatched path key, unknown fields, missing required
    fields, wrong value types, raw-secret-shaped values, raw origin URL) are
    surfaced as a per-record skip reason, never a fatal abort.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from dontpanic_orchestrate import canonical_evidence as ce  # noqa: E402

# A 16-hex path key, matching invocation_ledger's sha256(...)[:16] shape.
_CANON_KEY = "0123456789abcdef"
_OBS_KEY = "fedcba9876543210"
_ORIGIN_KEY = "00112233445566778899aabbccddeeff"  # 32 hex — hash-shaped


def _valid_canonical(**overrides: object) -> dict:
    obj = {
        "path_key": _CANON_KEY,
        "path_display": "<home>/code/dontpanic",
        "durable_checkout": True,
    }
    obj.update(overrides)
    return obj


def _valid_evidence(**overrides: object) -> dict:
    data = {
        "schema_version": "1.0",
        "canonical_repos": {_CANON_KEY: _valid_canonical()},
        "observation_path_key_to_canonical": {_OBS_KEY: [_CANON_KEY]},
    }
    data.update(overrides)
    return data


# ──────────────────────────────  valid evidence  ──────────────────────────────


def test_valid_evidence_resolves_single_canonical() -> None:
    contract = ce.parse_evidence(_valid_evidence())
    res = contract.resolve(_OBS_KEY)
    assert res.confirmed
    assert res.skip_reason is None
    assert res.canonical.path_key == _CANON_KEY
    assert res.canonical.path_display == "<home>/code/dontpanic"
    assert res.canonical.durable_checkout is True
    assert res.canonical.origin_key is None
    assert res.canonical.observed_under_temp_prefix is None


def test_valid_optional_origin_and_temp_observed_accepted() -> None:
    data = _valid_evidence(
        canonical_repos={
            _CANON_KEY: _valid_canonical(
                origin_key=_ORIGIN_KEY, observed_under_temp_prefix=True
            )
        }
    )
    res = ce.parse_evidence(data).resolve(_OBS_KEY)
    assert res.confirmed
    assert res.canonical.origin_key == _ORIGIN_KEY
    assert res.canonical.observed_under_temp_prefix is True


def test_durable_checkout_false_is_a_valid_shape() -> None:
    # F006 validates durable_checkout only as a boolean shape; its semantic truth
    # is F002's recompute, so False is a perfectly valid shape here.
    data = _valid_evidence(
        canonical_repos={_CANON_KEY: _valid_canonical(durable_checkout=False)}
    )
    res = ce.parse_evidence(data).resolve(_OBS_KEY)
    assert res.confirmed
    assert res.canonical.durable_checkout is False


def test_load_evidence_file_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "canonical-backfill-evidence.json"
    p.write_text(json.dumps(_valid_evidence()), encoding="utf-8")
    contract = ce.load_evidence_file(p)
    assert contract.schema_version == "1.0"
    assert contract.resolve(_OBS_KEY).confirmed


# ──────────────────────────────  file-fatal defects  ──────────────────────────────


def test_invalid_json_is_file_fatal(tmp_path: Path) -> None:
    p = tmp_path / "evidence.json"
    p.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ce.EvidenceFatalError) as exc:
        ce.load_evidence_file(p)
    assert exc.value.reason == ce.FATAL_INVALID_JSON


def test_missing_file_is_file_fatal(tmp_path: Path) -> None:
    with pytest.raises(ce.EvidenceFatalError) as exc:
        ce.load_evidence_file(tmp_path / "nope.json")
    assert exc.value.reason == ce.FATAL_MISSING_FILE


def test_top_level_not_a_mapping_is_file_fatal() -> None:
    with pytest.raises(ce.EvidenceFatalError) as exc:
        ce.parse_evidence([1, 2, 3])
    assert exc.value.reason == ce.FATAL_NOT_A_MAPPING


@pytest.mark.parametrize(
    "missing", ["schema_version", "canonical_repos", "observation_path_key_to_canonical"]
)
def test_missing_required_top_level_key_is_file_fatal(missing: str) -> None:
    data = _valid_evidence()
    del data[missing]
    with pytest.raises(ce.EvidenceFatalError) as exc:
        ce.parse_evidence(data)
    assert exc.value.reason == ce.FATAL_MISSING_TOP_LEVEL_KEY


@pytest.mark.parametrize("version", ["1.1", "2.0", "1", 1.0, "1.0.0"])
def test_wrong_schema_version_is_file_fatal(version: object) -> None:
    with pytest.raises(ce.EvidenceFatalError) as exc:
        ce.parse_evidence(_valid_evidence(schema_version=version))
    assert exc.value.reason == ce.FATAL_WRONG_SCHEMA_VERSION


def test_canonical_repos_not_a_map_is_file_fatal() -> None:
    with pytest.raises(ce.EvidenceFatalError) as exc:
        ce.parse_evidence(_valid_evidence(canonical_repos=["not", "a", "map"]))
    assert exc.value.reason == ce.FATAL_CANONICAL_REPOS_NOT_MAP


def test_observation_map_not_a_map_is_file_fatal() -> None:
    with pytest.raises(ce.EvidenceFatalError) as exc:
        ce.parse_evidence(_valid_evidence(observation_path_key_to_canonical=["x"]))
    assert exc.value.reason == ce.FATAL_OBSERVATION_MAP_NOT_MAP


# ──────────────────────────────  row-level defects  ──────────────────────────────


def test_absent_observation_key_skips() -> None:
    res = ce.parse_evidence(_valid_evidence()).resolve("deadbeefdeadbeef")
    assert not res.confirmed
    assert res.skip_reason == ce.SKIP_ABSENT_OBSERVATION_KEY


def test_non_list_mapping_skips() -> None:
    data = _valid_evidence(observation_path_key_to_canonical={_OBS_KEY: _CANON_KEY})
    res = ce.parse_evidence(data).resolve(_OBS_KEY)
    assert res.skip_reason == ce.SKIP_NON_LIST_MAPPING


def test_zero_mappings_skips() -> None:
    data = _valid_evidence(observation_path_key_to_canonical={_OBS_KEY: []})
    res = ce.parse_evidence(data).resolve(_OBS_KEY)
    assert res.skip_reason == ce.SKIP_ZERO_MAPPINGS


def test_multiple_mappings_skips() -> None:
    data = _valid_evidence(
        observation_path_key_to_canonical={_OBS_KEY: [_CANON_KEY, "1111111111111111"]}
    )
    res = ce.parse_evidence(data).resolve(_OBS_KEY)
    assert res.skip_reason == ce.SKIP_MULTIPLE_MAPPINGS


def test_unknown_canonical_reference_skips() -> None:
    data = _valid_evidence(
        observation_path_key_to_canonical={_OBS_KEY: ["9999999999999999"]}
    )
    res = ce.parse_evidence(data).resolve(_OBS_KEY)
    assert res.skip_reason == ce.SKIP_UNKNOWN_CANONICAL_REFERENCE


def test_mismatched_path_key_skips() -> None:
    # The canonical object's path_key field differs from its map key.
    data = _valid_evidence(
        canonical_repos={_CANON_KEY: _valid_canonical(path_key="2222222222222222")}
    )
    res = ce.parse_evidence(data).resolve(_OBS_KEY)
    assert res.skip_reason == ce.SKIP_PATH_KEY_MISMATCH


def test_unknown_canonical_field_skips() -> None:
    data = _valid_evidence(
        canonical_repos={_CANON_KEY: _valid_canonical(unexpected="x")}
    )
    res = ce.parse_evidence(data).resolve(_OBS_KEY)
    assert res.skip_reason == ce.SKIP_UNKNOWN_CANONICAL_FIELD


@pytest.mark.parametrize("missing", list(ce.REQUIRED_CANONICAL_FIELDS))
def test_missing_required_canonical_field_skips(missing: str) -> None:
    obj = _valid_canonical()
    del obj[missing]
    data = _valid_evidence(canonical_repos={_CANON_KEY: obj})
    res = ce.parse_evidence(data).resolve(_OBS_KEY)
    assert res.skip_reason == ce.SKIP_MISSING_REQUIRED_FIELD


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("path_key", 123),
        ("path_display", 123),
        ("durable_checkout", "true"),  # string, not bool
        ("durable_checkout", 1),  # int 1 is NOT a bool
        ("observed_under_temp_prefix", "yes"),
        ("origin_key", 123),
    ],
)
def test_wrong_value_type_skips(field: str, bad_value: object) -> None:
    obj = _valid_canonical(**{field: bad_value})
    # Keep path_key matching its map key when we're not the field under test.
    if field == "path_key":
        data = _valid_evidence(
            canonical_repos={bad_value: obj}  # type: ignore[dict-item]
            if isinstance(bad_value, str)
            else {_CANON_KEY: obj}
        )
    else:
        data = _valid_evidence(canonical_repos={_CANON_KEY: obj})
    res = ce.parse_evidence(data).resolve(_OBS_KEY)
    assert res.skip_reason == ce.SKIP_WRONG_VALUE_TYPE


def test_raw_origin_url_skips() -> None:
    # A raw origin URL is not hash-shaped and must never be copied.
    for url in ("git@github.com:acme/dontpanic.git", "https://github.com/acme/dontpanic"):
        data = _valid_evidence(
            canonical_repos={_CANON_KEY: _valid_canonical(origin_key=url)}
        )
        res = ce.parse_evidence(data).resolve(_OBS_KEY)
        assert res.skip_reason == ce.SKIP_ORIGIN_NOT_HASH_SHAPED, url


def test_raw_secret_shaped_value_skips() -> None:
    # A GitHub PAT smuggled into path_display must trip the shared no-secret
    # assertion before any field is copied.
    pat = "ghp_" + "a" * 36
    data = _valid_evidence(
        canonical_repos={_CANON_KEY: _valid_canonical(path_display=pat)}
    )
    res = ce.parse_evidence(data).resolve(_OBS_KEY)
    assert res.skip_reason == ce.SKIP_RAW_SECRET_SHAPE


def test_canonical_value_not_a_dict_skips() -> None:
    data = _valid_evidence(canonical_repos={_CANON_KEY: "not-a-dict"})
    res = ce.parse_evidence(data).resolve(_OBS_KEY)
    assert res.skip_reason == ce.SKIP_WRONG_VALUE_TYPE


def test_row_level_defect_never_aborts_other_rows() -> None:
    # One good observation key + one bad one in the same (file-fatal-clean) file:
    # the good one still resolves, the bad one skips. No exception.
    good_obs, bad_obs = _OBS_KEY, "aaaaaaaaaaaaaaaa"
    data = _valid_evidence(
        observation_path_key_to_canonical={good_obs: [_CANON_KEY], bad_obs: []}
    )
    contract = ce.parse_evidence(data)
    assert contract.resolve(good_obs).confirmed
    assert contract.resolve(bad_obs).skip_reason == ce.SKIP_ZERO_MAPPINGS
