---
name: kronos-agent
description: Financial time-series forecasting using the Kronos foundation model (MIT, NeoQuasar). Takes OHLC candles, returns predicted future candles with configurable horizon. Infrastructure skill — called by trader agents or scheduled ingestion, not directly invoked by users or the model.
disable-model-invocation: true
---

# Kronos Agent — Financial Candle Forecasting

Generic inference wrapper around [Kronos](https://github.com/shiyu-coder/Kronos), a
decoder-only foundation model pre-trained on K-line (candlestick) sequences from 45+
global exchanges. Feed it OHLC DataFrames, get forecasted OHLC DataFrames back.

**This skill is infrastructure, not a personality.** It has no identity, no daily
routine, no opinions. Trader agents call it to get predictions; scheduled scripts
call it to pre-compute signals. All personalization (which symbols, what account
size, what risk limits) lives in the caller's config.

## Requirements

- Python 3.10+
- [`uv`](https://docs.astral.sh/uv/) (both scripts use PEP 723 inline dependencies)
- Firebase Application Default Credentials for Firestore writes (only needed for
  non-dry-run use; see "Firebase auth" below)

First model download pulls weights from HuggingFace (`NeoQuasar/Kronos-*`). This
takes 1–3 minutes depending on model size and network. Subsequent runs use the
local HF cache.

## Quickstart

### 1. Verify the submodule is initialized

```bash
cd /path/to/Jarvis
git submodule status claude/skills/kronos-agent/vendor/kronos
# Should print: d5ffd46... claude/skills/kronos-agent/vendor/kronos (heads/master)
```

If the hash is missing or prefixed with `-`, run:
```bash
git submodule update --init claude/skills/kronos-agent/vendor/kronos
```

### 2. Smoke-test the inference wrapper

```bash
cd claude/skills/kronos-agent
./inference.py --smoke-test --size small
```

This loads `Kronos-small` (24.7M params), reads the bundled fixture CSV, predicts
24 future candles, and prints the first/last predictions. If this completes
without error, the environment is working.

For a faster smoke test (4.1M params, 2048 context):
```bash
./inference.py --smoke-test --size mini
```

### 3. Ingest real OHLC and write predictions

```bash
# Copy the template and customize
cp config.example.json config.json
# (edit config.json: set your firebase.project_id, tenant_id, symbols)

# Dry run — fetches OHLC and runs inference, but prints instead of writing
./ingest_ohlc.py --config config.json --dry-run

# Real run — writes predictions to Firestore
./ingest_ohlc.py --config config.json
```

## Library usage (from other Python code)

```python
from pathlib import Path
import sys
sys.path.insert(0, str(Path("/path/to/Jarvis/claude/skills/kronos-agent")))

from inference import predict_ohlc
import pandas as pd

ohlc = pd.DataFrame({
    "open":  [22.11, 22.14, 22.09, ...],
    "high":  [22.18, 22.22, 22.15, ...],
    "low":   [22.08, 22.10, 22.05, ...],
    "close": [22.14, 22.11, 22.13, ...],
    # volume and amount are optional
})
timestamps = pd.Series(pd.to_datetime([...]))

result = predict_ohlc(
    ohlc_df=ohlc,
    x_timestamp=timestamps,
    pred_len=24,
    model_size="small",
)
# result["predictions"] is a list of {"ts", "open", "high", "low", "close", "volume"}
```

## Model Sizes

| Size    | Params | Context | Use Case                           |
|---------|-------:|--------:|------------------------------------|
| `mini`  |   4.1M |    2048 | CPU-only, fast iteration, long context |
| `small` |  24.7M |     512 | Default. Good quality, runs on CPU in ~30s/symbol |
| `base`  | 102.3M |     512 | Best quality; recommend GPU or patience |

`large` (499.2M) is not open-source and not supported by this wrapper.

## Config Schema

```json
{
  "firebase": {
    "project_id": "your-firebase-project-id"
  },
  "tenant_id": "default",
  "firestore_path": "tenants/{tenant_id}/kronos_predictions/{symbol}",
  "symbols": ["SLV", "F", "T"],
  "yfinance": {
    "period":   "60d",
    "interval": "1d"
  },
  "kronos": {
    "model_size":   "small",
    "pred_len":     24,
    "temperature":  1.0,
    "top_p":        0.9,
    "sample_count": 1
  }
}
```

`period` and `interval` pass through to yfinance. Common combos:
- Daily bars: `period="1y"`, `interval="1d"`
- Hourly bars: `period="60d"`, `interval="1h"` (yfinance caps hourly history at 60d)
- 5-minute bars: `period="60d"`, `interval="5m"` (Kronos's native training resolution)

## Firestore Output Contract

Each run writes one document per symbol at the configured path. Default path:
```
tenants/{tenant_id}/kronos_predictions/{symbol}
```

Document shape:
```json
{
  "symbol": "SLV",
  "run_at": "2026-04-11T14:30:00+00:00",
  "model": "Kronos-small",
  "model_size": "small",
  "context_used": 60,
  "pred_len": 24,
  "predictions": [
    {
      "ts": "2026-04-12T00:00:00",
      "open":  22.14,
      "high":  22.18,
      "low":   22.09,
      "close": 22.15,
      "volume": 12345678.0
    }
  ],
  "sampling": {
    "temperature": 1.0,
    "top_p": 0.9,
    "sample_count": 1
  }
}
```

Overwrite semantics: each run replaces the symbol's document. If you need
historical tracking of predictions, add a subcollection keyed by `run_at` in
your caller — this skill intentionally keeps the contract simple.

## Firebase auth

The script uses Firebase Application Default Credentials (ADC). Any of these
will work:

1. **gcloud** (most common for local dev):
   ```bash
   gcloud auth application-default login
   ```
2. **Service account key**:
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
   ```
3. **Workload identity** (when running on GCP infrastructure) — automatic.

If you don't want to touch Firestore at all, always pass `--dry-run`. The script
never initializes Firebase in dry-run mode.

## Integration with trader agents

The intended handoff is:

```
1. Scheduled cron runs `ingest_ohlc.py` every N minutes / hours
2. Predictions land in Firestore at tenants/{tenant_id}/kronos_predictions/{symbol}
3. Trader agent reads predictions on each decision cycle
4. Trader agent uses Kronos as one signal among many (RSI, SMA, VIX, etc.)
5. Trader agent applies its own risk management — Kronos is advisory, not authoritative
```

This decoupling means:
- Inference is slow but offline-acceptable (trader doesn't wait on GPU work)
- Execution is fast and never blocked by a model download or crash
- The trader can degrade gracefully when predictions are stale or missing
- You can A/B test trader decisions with and without Kronos signals

## Kronos source & license

- **Upstream**: https://github.com/shiyu-coder/Kronos
- **License**: MIT (see `vendor/kronos/LICENSE`)
- **Pinned commit**: `d5ffd46ab061af1146ea415e4ce86d24b5231b01`
- **Models on HF**: `NeoQuasar/Kronos-{mini,small,base}` + `NeoQuasar/Kronos-Tokenizer-{base,2k}`

To update the pin:
```bash
cd claude/skills/kronos-agent/vendor/kronos
git fetch origin
git checkout <new-commit-sha>
cd ../../../../..
git add claude/skills/kronos-agent/vendor/kronos
git commit -m "bump: kronos submodule to <sha>"
```

## Design principles

- **Generic**: Zero hardcoded symbols, account sizes, or broker assumptions.
- **Config-driven**: Everything user-specific lives in `config.json`, never in code.
- **PEP 723 inline deps**: Heavy deps (torch, transformers) are isolated in uv's
  cache — no venv pollution in the caller's environment.
- **Fail loudly**: Bad config, missing columns, or network errors raise clearly
  rather than silently producing garbage.
- **JSON-serializable output**: `predict_ohlc()` returns plain dicts/lists only,
  so the result can be piped directly to Firestore, Redis, or a file.

## What this skill does NOT do

- **No execution.** This is inference only. It never places trades.
- **No risk management.** That belongs in the trader agent, not here.
- **No portfolio logic.** No position sizing, no PnL tracking.
- **No data storage beyond the latest prediction.** Historical tracking is the
  caller's responsibility.
- **No model fine-tuning.** Use Kronos's upstream `finetune/` directory directly
  if you need that.

## Troubleshooting

**`ModuleNotFoundError: No module named 'model'`** — the submodule isn't
initialized. Run `git submodule update --init` from the Jarvis repo root.

**First run hangs on "downloading/loading model"** — HuggingFace is pulling
weights. `Kronos-small` is ~100 MB, `Kronos-base` is ~400 MB. Be patient or
pre-download with `huggingface-cli download NeoQuasar/Kronos-small`.

**`DefaultCredentialsError`** — you're not in dry-run mode and haven't configured
ADC. Either run `gcloud auth application-default login` or add `--dry-run`.

**yfinance returns empty DataFrame** — the symbol may be delisted, or the
period/interval combo is unsupported (yfinance caps `interval="1h"` at 60 days
of history, for example). Check the symbol in a browser first.

**Predictions look unreasonable** — Kronos is a foundation model trained on
diverse market data. Low-volume tickers or highly illiquid instruments may
produce noisy forecasts. Try `sample_count=5` to average across samples, or use
a larger model size.
