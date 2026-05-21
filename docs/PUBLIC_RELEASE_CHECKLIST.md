# Public Release Checklist

This checklist is mandatory before changing `Silex-Research/DontPanic` from
private to public. Treat the visibility flip as irreversible: once public,
assume clones, search indexes, archives, and automated crawlers have permanent
copies of the repository history and public GitHub surfaces.

## 1. Content Fit

- Decide whether `docs/plans/**`, `audit/**`, `evidence/**`, and
  `decisions.jsonl` are intended public artifacts.
- Review plan and audit content for internal strategy, vendor commentary,
  budget details, references to private repos, or candid personnel/process
  notes.
- Redact or split the public branch before the first public push. Do not rely on
  making the repo private again after exposure.

## 2. Secret and History Scans

- Run the committed-tree sanitizer:

  ```bash
  python3 scripts/sanitization_check.py
  ```

- Run a full git-history scanner from a complete clone:

  ```bash
  gitleaks detect --source . --log-opts="--all" --redact=100
  ```

- Any real finding blocks public release until the credential is rotated and
  history is rewritten or the release branch is rebuilt without the finding.
- False positives must be documented with commit, file, rule, and rationale.

## 3. Non-tree GitHub Surfaces

- Audit or delete GitHub Actions run logs.
- Audit issues, pull requests, releases, discussions, and project boards.
- Delete stale WIP branches that should not become public.
- Review `.github/workflows/**`, `.gitmodules`, lockfiles, and submodule URLs.

## 4. Governance Files

- `LICENSE`
- `SECURITY.md`
- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- `.github/CODEOWNERS`
- required CI workflow documented by name

## 5. Recovery Point

- Create a backup bundle:

  ```bash
  git bundle create /private/tmp/DontPanic-prepublic-$(date +%F).bundle --all
  ```

- Tag the pre-public state:

  ```bash
  git tag pre-public-$(date +%F)
  git push origin pre-public-$(date +%F)
  ```

## 6. Visibility Flip

Only after the previous sections are clean:

```bash
gh repo edit Silex-Research/DontPanic \
  --visibility public \
  --accept-visibility-change-consequences
```

## 7. Immediate Public Hardening

- Enable secret scanning and push protection.
- Enable Dependabot alerts and security updates.
- Disable Wiki unless there is a public docs plan for it.
- Use squash-only merges unless a maintainer explicitly changes the policy.
- Enable delete-branch-on-merge.
- Add a branch ruleset for `main`:
  - require pull requests;
  - require the CI workflow;
  - require CODEOWNERS review;
  - block force pushes;
  - block branch deletion;
  - require signed commits if the org policy supports it.
