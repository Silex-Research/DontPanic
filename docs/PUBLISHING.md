# Publishing DontPanic

This is a manual maintainer runbook. It covers the PyPI distribution
`dontpanic-orchestrate` and the MCP Registry entry
`io.github.silex-research/dontpanic`, described by [`server.json`](../server.json).
Every step below requires explicit maintainer approval before it is run. No
release or publishing workflow is automated by this document.

## Versioning

[`scripts/dontpanic_orchestrate/__init__.py`](../scripts/dontpanic_orchestrate/__init__.py)
contains `__version__`, the single source of truth. After changing it, run:

```bash
python3 scripts/sync_version.py
python3 scripts/sync_version.py --check
python3 scripts/sync_agent_conventions.py
python3 scripts/sync_agent_conventions.py --check
```

The test suite fails when the pinned listing surfaces drift from that version.
The agent-conventions command refreshes the packaged schema/model mirror from
`claude/shared` and checks it for drift.

## Release tags

Future DontPanic release tags use the `dontpanic-v` prefix, for example
`dontpanic-v<version>`. The prefix avoids collisions with the vendored
agent-conventions tags `v1.0.0` through `v1.7.0` present in the repository
history. Do not reuse bare `v*` tags.

## Planned TestPyPI release-candidate dry run

This dry run requires maintainer approval and has not yet been run.

1. With maintainer approval, set an RC version such as `<version>rc1` in
   `__version__`, then synchronize the pinned surfaces:

   ```bash
   python3 scripts/sync_version.py
   python3 scripts/sync_version.py --check
   ```

2. With maintainer approval, build the distributions:

   ```bash
   uv build
   ```

3. With maintainer approval, upload the build to TestPyPI using a configured
   TestPyPI trusted publisher.

4. With maintainer approval, verify the install and MCP surface:

   ```bash
   uvx --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ dontpanic-orchestrate==<version>rc1
   ```

   `dontpanic-orchestrate` is the MCP server entrypoint, equivalent to
   `dontpanic mcp serve`; the full CLI is `dontpanic`. Send an MCP
   `initialize` request followed by `tools/list`. Confirm the
   response contains all nine tools and that each tool includes its read-only
   and destructive annotations.

## PyPI trusted publishing

With maintainer approval, configure a PyPI trusted publisher for the GitHub
repository. Build the distributions with `uv build`, then publish from a
maintainer-approved trusted-publisher run. After publishing, confirm that
PyPI displays the project README containing the `mcp-name:` marker; the MCP
Registry uses that marker for the repository ownership check.

## MCP Registry

After the matching PyPI version is live, and with maintainer approval, install
`mcp-publisher`, authenticate with GitHub, and publish from the repository root:

```bash
mcp-publisher login github
mcp-publisher publish
```

With maintainer approval, verify the published entry by searching the MCP
Registry API for `io.github.silex-research/dontpanic` and checking its package
version and stdio launch configuration.

## Local install pins

Use the versioned MCP launch command or install the CLI. `dontpanic-orchestrate`
is the MCP server entrypoint, equivalent to `dontpanic mcp serve`; the full
CLI is `dontpanic`:

```bash
uvx dontpanic-orchestrate==0.2.0
pipx install dontpanic-orchestrate
```
