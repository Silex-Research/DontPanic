---
name: git-essentials
description: Git conventions for Silex repos (remotes, branching, history rewriting, recovery). Use when running git outside a more specific git skill; git-via-1password-ssh covers auth and signing.
homepage: https://git-scm.com/
metadata: {"clawdbot":{"emoji":"🌳","requires":{"bins":["git"]}}}
---

# Git Essentials

Conventions for git in Silex repos. Standard command syntax is not repeated here; use `git help <command>` when unsure.

## Remotes and auth
- Remotes are SSH (`git@github.com:org/repo.git`), never HTTPS. Auth and commit signing go through the 1Password agent: read the git-via-1password-ssh skill before any network or signing operation.

## Branches
- Work on `feature/<name>`, `fix/<name>`, or `hotfix/<name>` branches, never directly on `main`.
- Rebase feature branches onto their base before merging; sync with `git pull --rebase`.
- Force-push only your own branches, and only with `--force-with-lease`. Never force-push a shared branch.

## History
- Commit small and often; tidy with interactive rebase before pushing, not after.
- Use `git revert` for anything already on a shared branch; `git reset --hard` is for local-only work.
- Recover lost commits with `git reflog`, then `git checkout -b <branch> <hash>`.

## Cleanup
- Preview with `git clean -n` before `git clean -fd`. `-x` also removes ignored files (build output, `.env`), so use it only when that is the intent.
- Keep `.gitignore` current so `git add .` stays safe.

Official docs: https://git-scm.com/doc
