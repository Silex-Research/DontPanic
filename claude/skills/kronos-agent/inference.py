#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "torch>=2.0.0",
#   "numpy",
#   "pandas==2.2.2",
#   "einops==0.8.1",
#   "huggingface_hub==0.33.1",
#   "tqdm==4.67.1",
#   "safetensors==0.6.2",
# ]
# ///
"""
Kronos inference wrapper — generic, config-driven OHLC forecasting.

Loads a Kronos model (mini/small/base from NeoQuasar HuggingFace org), takes an
OHLC pandas DataFrame, returns predicted candles as a structured dict.

Usage (as a library):
    from inference import predict_ohlc
    result = predict_ohlc(
        ohlc_df=my_df,
        x_timestamp=my_timestamps,
        pred_len=24,
        model_size="small",
    )

Usage (as a CLI, smoke test):
    ./inference.py --smoke-test         # uses Kronos's bundled fixture data
    ./inference.py --smoke-test --size mini   # use the smallest model

PEP 723 inline deps: run with `uv run inference.py` — torch/einops/etc. are
installed in an isolated cache, not the global environment.

Kronos source: vendored as git submodule at ./vendor/kronos (MIT, pinned to d5ffd46).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parent
VENDOR_KRONOS = SKILL_DIR / "vendor" / "kronos"

# Kronos uses relative imports from its own root; insert vendor path so
# `from model import ...` resolves to the vendored copy.
if str(VENDOR_KRONOS) not in sys.path:
    sys.path.insert(0, str(VENDOR_KRONOS))

# ── Model registry ────────────────────────────────────────────────────

# Open-source Kronos models published by NeoQuasar on HuggingFace.
# context_len is the hard limit of the tokenizer/model; callers must not
# pass more history than this.
KRONOS_MODELS = {
    "mini": {
        "model_id": "NeoQuasar/Kronos-mini",
        "tokenizer_id": "NeoQuasar/Kronos-Tokenizer-2k",
        "context_len": 2048,
        "params_m": 4.1,
    },
    "small": {
        "model_id": "NeoQuasar/Kronos-small",
        "tokenizer_id": "NeoQuasar/Kronos-Tokenizer-base",
        "context_len": 512,
        "params_m": 24.7,
    },
    "base": {
        "model_id": "NeoQuasar/Kronos-base",
        "tokenizer_id": "NeoQuasar/Kronos-Tokenizer-base",
        "context_len": 512,
        "params_m": 102.3,
    },
}


# ── Core inference ────────────────────────────────────────────────────

def _load_predictor(model_size: str):
    """Import Kronos lazily so PEP 723 deps are resolved before import."""
    from model import Kronos, KronosPredictor, KronosTokenizer  # type: ignore

    if model_size not in KRONOS_MODELS:
        raise ValueError(
            f"Unknown Kronos model size '{model_size}'. "
            f"Choose one of: {list(KRONOS_MODELS.keys())}"
        )

    spec = KRONOS_MODELS[model_size]
    tokenizer = KronosTokenizer.from_pretrained(spec["tokenizer_id"])
    model = Kronos.from_pretrained(spec["model_id"])
    predictor = KronosPredictor(model, tokenizer, max_context=spec["context_len"])
    return predictor, spec


def predict_ohlc(
    ohlc_df,
    x_timestamp,
    *,
    pred_len: int = 24,
    model_size: str = "small",
    y_timestamp=None,
    temperature: float = 1.0,
    top_p: float = 0.9,
    sample_count: int = 1,
    verbose: bool = False,
) -> dict[str, Any]:
    """Run Kronos forecasting on an OHLC DataFrame.

    Args:
        ohlc_df: pandas.DataFrame with columns ['open','high','low','close'] and
                 optionally 'volume' and 'amount'. Must be time-ordered ascending.
        x_timestamp: pandas.Series of historical timestamps, aligned with ohlc_df.
        pred_len: Number of future candles to predict.
        model_size: One of 'mini', 'small', 'base'.
        y_timestamp: Optional pandas.Series of future timestamps. If None, extrapolated
                     from x_timestamp by computing the median delta and extending.
        temperature: Sampling temperature for the predictor (default 1.0).
        top_p: Nucleus sampling top-p (default 0.9).
        sample_count: Number of samples to draw and average (default 1).
        verbose: Pass verbose=True through to the predictor.

    Returns:
        A dict shaped like:
        {
          "model": "Kronos-small",
          "model_size": "small",
          "context_used": <int>,
          "pred_len": <int>,
          "run_at": "<iso8601>",
          "predictions": [
             {"ts": "...", "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...},
             ...
          ],
          "sampling": {"temperature": 1.0, "top_p": 0.9, "sample_count": 1},
        }

    Raises:
        ValueError: If ohlc_df is missing required columns, context exceeds model
                    limit, or sample_count < 1.
        ImportError: If torch/numpy/pandas aren't available in the current env.
    """
    import numpy as np
    import pandas as pd

    required_cols = {"open", "high", "low", "close"}
    missing = required_cols - set(ohlc_df.columns)
    if missing:
        raise ValueError(
            f"ohlc_df is missing required columns: {sorted(missing)}. "
            f"Got: {list(ohlc_df.columns)}"
        )
    if sample_count < 1:
        raise ValueError(f"sample_count must be >= 1, got {sample_count}")
    if pred_len < 1:
        raise ValueError(f"pred_len must be >= 1, got {pred_len}")

    predictor, spec = _load_predictor(model_size)

    context_len = spec["context_len"]
    if len(ohlc_df) > context_len:
        # Truncate to the most recent context_len candles (leave the oldest)
        ohlc_df = ohlc_df.iloc[-context_len:].reset_index(drop=True)
        x_timestamp = x_timestamp.iloc[-context_len:].reset_index(drop=True)

    # Extrapolate y_timestamp from x_timestamp if caller didn't provide it.
    if y_timestamp is None:
        ts = pd.to_datetime(x_timestamp)
        if len(ts) < 2:
            raise ValueError(
                "Cannot extrapolate y_timestamp from fewer than 2 historical points; "
                "pass y_timestamp explicitly."
            )
        deltas = ts.diff().dropna()
        median_delta = deltas.median()
        last = ts.iloc[-1]
        y_timestamp = pd.Series([last + (i + 1) * median_delta for i in range(pred_len)])

    pred_df = predictor.predict(
        df=ohlc_df,
        x_timestamp=x_timestamp,
        y_timestamp=y_timestamp,
        pred_len=pred_len,
        T=temperature,
        top_p=top_p,
        sample_count=sample_count,
        verbose=verbose,
    )

    # Normalize to plain Python dict for JSON/Firestore compatibility.
    # pred_df may be indexed by the future timestamps (Kronos does this), so
    # iterate positionally with enumerate rather than assuming integer index.
    predictions: list[dict[str, Any]] = []
    ts_list = pd.to_datetime(y_timestamp).tolist()
    for pos, (_, row) in enumerate(pred_df.iterrows()):
        ts_value = ts_list[pos] if pos < len(ts_list) else None
        candle = {
            "ts": ts_value.isoformat() if ts_value is not None else None,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        }
        if "volume" in row:
            v = row["volume"]
            candle["volume"] = float(v) if not (isinstance(v, float) and np.isnan(v)) else None
        predictions.append(candle)

    return {
        "model": f"Kronos-{model_size}",
        "model_size": model_size,
        "context_used": len(ohlc_df),
        "pred_len": pred_len,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "predictions": predictions,
        "sampling": {
            "temperature": temperature,
            "top_p": top_p,
            "sample_count": sample_count,
        },
    }


# ── CLI / smoke test ──────────────────────────────────────────────────

def _smoke_test(model_size: str, pred_len: int) -> None:
    """Run inference against the bundled Kronos fixture data.

    Uses vendor/kronos/examples/data/XSHG_5min_600977.csv to verify that the
    model downloads from HF, loads, and produces output. Keeps first `lookback`
    rows as history, predicts the next `pred_len`.
    """
    import pandas as pd

    fixture = VENDOR_KRONOS / "examples" / "data" / "XSHG_5min_600977.csv"
    if not fixture.exists():
        raise SystemExit(
            f"Fixture not found: {fixture}\n"
            "The Kronos submodule may not be initialized. Run:\n"
            "  git submodule update --init claude/skills/kronos-agent/vendor/kronos"
        )

    print(f"[smoke] loading fixture: {fixture.name}")
    df = pd.read_csv(fixture)
    df["timestamps"] = pd.to_datetime(df["timestamps"])

    lookback = 400
    x_df = df.loc[: lookback - 1, ["open", "high", "low", "close", "volume", "amount"]]
    x_ts = df.loc[: lookback - 1, "timestamps"]
    y_ts = df.loc[lookback : lookback + pred_len - 1, "timestamps"]

    print(f"[smoke] model={model_size}, lookback={lookback}, pred_len={pred_len}")
    print(f"[smoke] downloading/loading model (first run may take ~1-2 min)...")

    result = predict_ohlc(
        ohlc_df=x_df,
        x_timestamp=x_ts,
        pred_len=pred_len,
        model_size=model_size,
        y_timestamp=y_ts,
        verbose=True,
    )

    print(f"\n[smoke] OK — predicted {len(result['predictions'])} candles")
    print(f"[smoke] first prediction: {json.dumps(result['predictions'][0], indent=2)}")
    print(f"[smoke] last  prediction: {json.dumps(result['predictions'][-1], indent=2)}")
    print(f"[smoke] run_at: {result['run_at']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Kronos inference wrapper")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run against bundled fixture data to verify model loads + predicts",
    )
    parser.add_argument(
        "--size",
        choices=list(KRONOS_MODELS.keys()),
        default="small",
        help="Kronos model size (default: small)",
    )
    parser.add_argument(
        "--pred-len",
        type=int,
        default=24,
        help="Number of future candles to predict (default: 24)",
    )
    args = parser.parse_args()

    if args.smoke_test:
        _smoke_test(args.size, args.pred_len)
        return 0

    parser.print_help()
    print("\nThis script is primarily a library. Use --smoke-test to verify setup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
