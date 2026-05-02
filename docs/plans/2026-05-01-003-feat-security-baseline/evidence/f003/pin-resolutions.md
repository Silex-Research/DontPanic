# F003 pin resolutions

**Plan:** `2026-05-01-003-feat-security-baseline`
**Feature:** F003 (SHA-pin every workflow `uses:` + Dependabot updater policy)
**Captured:** 2026-05-01 (pre-edit; this memo lands BEFORE the workflow patch per F003 acceptance #2)

## Method

For each `uses: <action>@<ref>`:

1. Resolve the ref to a commit SHA via `gh api repos/<action>/git/ref/tags/<tag>` and confirm `object.type == "commit"` (lightweight tag — direct SHA) OR fetch the tag object and deref to `object.sha` (annotated tag).
2. Cross-check by `gh api repos/<action>/commits/<tag> --jq '.sha'` — handles both lightweight and annotated tags.
3. Pin to the **specific patch tag's SHA** with the patch tag in the comment. Floating tags like `v4` and `v5` are mutable (the upstream owner can retag); patch tags like `v4.3.1` are immutable. Dependabot tracks the comment, so naming the patch in the comment is what makes update PRs precise.

## Inventory + resolutions

3 `uses:` occurrences across 2 distinct actions in `.github/workflows/ci.yml` (no other workflow files exist as of this commit).

### 1. `.github/workflows/ci.yml:21` — `actions/checkout@v4`

```
$ gh api repos/actions/checkout/git/ref/tags/v4 --jq '{type: .object.type, sha: .object.sha}'
{"sha":"34e114876b0b11c390a56381ad16ebd13914f8d5","type":"commit"}

$ gh api repos/actions/checkout/git/ref/tags/v4.3.1 --jq '.object.sha'
34e114876b0b11c390a56381ad16ebd13914f8d5
```

`v4` (floating) and `v4.3.1` (immutable patch) currently resolve to the same commit. Pinning to v4.3.1.

**Patch:** `actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5  # v4.3.1`

### 2. `.github/workflows/ci.yml:26` — `actions/setup-python@v5`

```
$ gh api repos/actions/setup-python/git/ref/tags/v5 --jq '{type: .object.type, sha: .object.sha}'
{"sha":"a26af69be951a213d495a4c3e4e4022e16d87065","type":"commit"}

$ gh api repos/actions/setup-python/git/ref/tags/v5.6.0 --jq '.object.sha'
a26af69be951a213d495a4c3e4e4022e16d87065
```

`v5` (floating) and `v5.6.0` (immutable patch) currently resolve to the same commit. Pinning to v5.6.0.

**Patch:** `actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065  # v5.6.0`

### 3. `.github/workflows/ci.yml:71` — `actions/checkout@v4`

Same action + tag as #1. Same SHA, same patch.

**Patch:** `actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5  # v4.3.1`

## Summary table

| File | Line | Original | Pinned form |
|---|---|---|---|
| `.github/workflows/ci.yml` | 21 | `actions/checkout@v4` | `actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5  # v4.3.1` |
| `.github/workflows/ci.yml` | 26 | `actions/setup-python@v5` | `actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065  # v5.6.0` |
| `.github/workflows/ci.yml` | 71 | `actions/checkout@v4` | `actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5  # v4.3.1` |

## Notes for auditor

- Both upstream tags (`v4`, `v5`) are lightweight (`type: commit` returned by git/ref/tags); deref-to-tag-object step is not needed for these specific actions today. The methodology recorded here handles annotated tags too — if a future pin lands an annotated tag, the `git/tag/<tag-object-sha>` step is the canonical second hop.
- The 40-char SHA format requirement (F003 acceptance #1) is satisfied: `34e114876b0b11c390a56381ad16ebd13914f8d5` and `a26af69be951a213d495a4c3e4e4022e16d87065` are both 40 hex characters.
- Tag-to-SHA correctness (F003 acceptance #2) verifiable by replaying any of the `gh api` commands above against today's GitHub state.
- After the workflow patch lands, Dependabot will own ongoing pin rotation for `actions/checkout` and `actions/setup-python` weekly. Manual updates should defer to the bot's PRs.
