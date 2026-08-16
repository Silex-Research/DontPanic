"""Run artifact: reliability (pass@k / pass^k) and cost (plan 2026-08-09-003 F005)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dontpanic_orchestrate.state_projection import scrub_secrets


def pass_at_k(n: int, c: int, k: int) -> float:
    """Chen et al. unbiased estimator of P(at least one of k succeeds)."""
    if n <= 0 or k <= 0:
        return 0.0
    if k > n:
        k = n
    if n - c < k:
        return 1.0
    product = 1.0
    for i in range(k):
        product *= (n - c - i) / (n - i)
    return 1.0 - product


def pass_hat_k(n: int, c: int, k: int) -> float:
    """P(all k succeed) under i.i.d. Bernoulli(c/n)."""
    if n <= 0 or k < 0:
        return 0.0
    return (c / n) ** k


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return scrub_secrets(value)
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, dict):
        return {_scrub(k) if isinstance(k, str) else k: _scrub(v) for k, v in value.items()}
    return value


def write_run_artifact(result: Any, path: Path) -> Path:
    """Write one machine-readable artifact, secret-scrubbed."""
    trials = list(result.trials)
    n = len(trials)
    c = sum(1 for t in trials if t.reached_expected)
    tokens_in = sum(int(t.tokens_in) for t in trials)
    tokens_out = sum(int(t.tokens_out) for t in trials)
    duration = sum(float(t.duration_s) for t in trials)
    k = n if n > 0 else 1
    payload = {
        "schema_version": "1.0",
        "scenario_id": getattr(result, "scenario_id", ""),
        "trials": [t.to_dict() if hasattr(t, "to_dict") else dict(t) for t in trials],
        "aggregate": {
            "trials_run": n,
            "trials_reached_expected": c,
            "success_fraction": (c / n) if n else 0.0,
            "k": k,
            "pass_at_k": pass_at_k(n, c, k),
            "pass_hat_k": pass_hat_k(n, c, k),
            "tokens_in_total": tokens_in,
            "tokens_out_total": tokens_out,
            "duration_s_total": duration,
        },
    }
    if n > 0 and c == n:
        # Keep the exact integer 1 the acceptance names, not 0.999...
        payload["aggregate"]["success_fraction"] = 1
        payload["aggregate"]["pass_hat_k"] = 1
        payload["aggregate"]["pass_at_k"] = 1
    scrubbed = _scrub(payload)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scrubbed, indent=2) + "\n")
    return path
