---
name: changelog
description: Render a markdown changelog for a git revision range, grouped by Conventional Commits prefix
trigger_keywords: [changelog, release notes, commit summary, what changed]
file_patterns: []
applicable_agents: [all]
phase: on-demand
---

# changelog

## Purpose

Render a deterministic, operator-facing markdown changelog for a git revision range. Reads `git log` output (or a recorded fixture), groups commits by Conventional Commits prefix (`feat`, `fix`, `refactor`, `docs`, `test`, `chore`, etc.), and emits a markdown report with a per-group file-change summary and a per-commit blurb. No LLM calls — pure parsing + template rendering, so output is byte-stable given identical inputs. Use when assembling release notes, summarizing what landed since the last tag, or producing a deterministic artifact for review.

This skill is intentionally narrow: it does not invoke an LLM, talk to GitHub, or rewrite commit prose. If operators want polished narrative, that is a follow-up step layered on top of this output.

## Arguments

| Argument | Required | Description |
|---|---|---|
| `--from` | no | Start revision (exclusive). Default: most recent tag reachable from `--to`. |
| `--to` | no | End revision (inclusive). Default: `HEAD`. |
| `--format` | no | `markdown` (default) or `json`. |
| `--fixtures` | no | Directory containing a recorded `git_log.txt` — when set, the skill reads that file instead of running `git`. Optional `meta.json` carries `{from, to}` labels for headers. |
| `--out` | no | Path to write the rendered output. Default: stdout. |

If no arguments: defaults to `--from <last-tag> --to HEAD --format markdown` and writes to stdout.

## Prerequisites

- A git working tree (only when `--fixtures` is not used). Fixture mode runs in a fresh clone with no history.
- For convention parsing rules, see `claude/shared/conventions/` (no inlined rules in this skill).

## Steps

1. **Resolve range** — if `--fixtures` is supplied, read `git_log.txt` from that directory and use the labels in `meta.json` for header text. Otherwise run `git log --no-color --reverse --name-status --pretty=format:<stable-format> <from>..<to>`.
2. **Parse** — split the output on the `--COMMIT--` record marker; extract hash, short hash, ISO date, author, parents, subject + body, and file-status pairs (M/A/D/R/C).
3. **Classify** — for each commit, match the subject against `^<type>(\(scope\))?!?:` against the canonical Conventional Commits types. Unmatched commits land in the `other` group. Merge commits (parents > 1) are tagged but not dropped.
4. **Render** — emit a markdown report with a header (range + commit count), one section per non-empty group in the canonical order (`feat → fix → perf → refactor → docs → test → build → ci → chore → style → revert → other`), each with a one-line file-change summary and a bulleted list of `- short subject` blurbs. JSON format mirrors the same structure.
5. **Write** — print to stdout or to `--out`.

## Output

A markdown changelog (or JSON) describing the range. Empty ranges produce a valid header + `_No commits in range._` body and exit 0. Output is deterministic given the same input bytes — fixture-based golden tests compare byte-for-byte.

Exit codes: 0 on success (including empty range), 2 on malformed CLI flags or fixture-mode missing `git_log.txt`.

## Examples

```
python -m claude.skills.changelog.changelog \
  --fixtures claude/skills/changelog/tests/fixtures/nominal/
```

Expected: prints the nominal-fixture changelog to stdout. Re-running yields identical bytes.

```
python -m claude.skills.changelog.changelog --from v1.0.0 --to HEAD --format json --out CHANGELOG.json
```

Expected: writes a JSON document with `range`, `commit_count`, and a `groups` map keyed by Conventional Commits type to `claude/skills/changelog/CHANGELOG.json`.
