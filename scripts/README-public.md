# DontPanic

This file used to describe an experimental dashboard. The current private-alpha
entry points are:

- [`../README.md`](../README.md) — product overview and quickstart
- [`../docs/GETTING_STARTED.md`](../docs/GETTING_STARTED.md) — human setup path
- [`../docs/AGENT_QUICKSTART.md`](../docs/AGENT_QUICKSTART.md) — AI caller path

Install from the repo root:

```bash
python3 -m pip install -e ".[dev]"
dontpanic --help
dontpanic setup --help
dontpanic doctor --skip-auth
```

The dashboard directory remains in the repo as a local operator surface, but it
is not the primary private-alpha onboarding path.
