# Publishing DontPanic

This is a manual maintainer runbook. It covers the PyPI distribution
`dontpanic-orchestrate` and the MCP Registry entry
`io.github.Silex-Research/dontpanic`, described by [`server.json`](../server.json).
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
The agent-conventions command refreshes the packaged schema/model copies from
`claude/shared` and checks them for drift. Schemas are byte-identical;
generated models carry a generated header and a relative-import rewrite.

## Release tags

Future DontPanic release tags use the `dontpanic-v` prefix, for example
`dontpanic-v<version>`. The prefix avoids collisions with the vendored
agent-conventions tags `v1.0.0` through `v1.7.0` present in the repository
history. Do not reuse bare `v*` tags.

## Planned TestPyPI release-candidate dry run

This dry run requires maintainer approval and has not yet been run.

1. Before any PyPI upload, run the MCP namespace pin test and confirm it
   passes:

   ```bash
   PYTHONPATH=scripts .venv/bin/python -m pytest -q scripts/dontpanic_orchestrate/tests/test_mcp_plugin_listing.py
   ```

   With maintainer approval, set an RC version such as `<version>rc1` in
   `__version__`, then synchronize the pinned surfaces:

   ```bash
   python3 scripts/sync_version.py
   python3 scripts/sync_version.py --check
   ```

2. With maintainer approval, build the distributions:

   ```bash
   uv build
   ```

3. With maintainer approval, upload the `<version>rc1` build from step 2 to
   TestPyPI. Use a maintainer-held TestPyPI API token supplied through the
   environment; never commit the token. This repository has no OIDC publish
   job, so trusted publishing is not available from it. Step 4 verifies the
   exact `<version>rc1` uploaded here:

   ```bash
   UV_PUBLISH_TOKEN=<TestPyPI API token> uv publish --publish-url https://test.pypi.org/legacy/ dist/*
   ```

4. With maintainer approval, download only the RC artifact and verify its
   install and MCP surface. The local wheel launch resolves its dependencies
   from PyPI:

   ```bash
   pip download --no-deps --index-url https://test.pypi.org/simple/ dontpanic-orchestrate==<version>rc1 -d <dir>
   uvx --from <dir>/<wheel-file.whl> dontpanic-orchestrate
   ```

   `dontpanic-orchestrate` is the MCP server entrypoint, equivalent to
   `dontpanic mcp serve`; the full CLI is `dontpanic`. Send an MCP
   `initialize` request followed by `tools/list`. Confirm the
   response contains all nine tools and that each tool includes its read-only
   and destructive annotations.

## PyPI trusted publishing

PyPI trusted publishing is future work.
This repository ships no publish workflow. Any future publisher configuration
and upload path requires maintainer approval. The MCP Registry ownership check
uses the README's `mcp-name:` marker.

## MCP Registry

After the matching PyPI version is live, and with maintainer approval, install
`mcp-publisher` and publish from the repository root. The interactive
`mcp-publisher login github` flow cannot publish an organization namespace
(modelcontextprotocol/registry issue #1468). Use either an OIDC login from a
GitHub Actions job with `permissions: id-token: write`, or an org-scoped token:

```bash
mcp-publisher login github-oidc
mcp-publisher publish
```

For token authentication, the publishing account must be an organization
Owner. A classic PAT needs `read:org`; a fine-grained PAT needs Organization
Members read-only permission:

```bash
mcp-publisher login github --token <PAT>
mcp-publisher publish
```

With maintainer approval, verify the published entry by searching the MCP
Registry API for `io.github.Silex-Research/dontpanic` and checking its package
version and stdio launch configuration.

## Local install pins

Use the versioned MCP launch command or install the CLI. `dontpanic-orchestrate`
is the MCP server entrypoint, equivalent to `dontpanic mcp serve`; the full
CLI is `dontpanic`:

```bash
uvx dontpanic-orchestrate==0.2.1
pipx install dontpanic-orchestrate
```
