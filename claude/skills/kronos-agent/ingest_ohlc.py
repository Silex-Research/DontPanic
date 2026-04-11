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
#   "yfinance>=0.2.40",
#   "firebase-admin>=6.5.0",
# ]
# ///
"""
Kronos OHLC ingestion — fetches candles, runs inference, writes predictions.

Reads a config file listing symbols + parameters, pulls historical OHLC from
Yahoo Finance, calls the Kronos inference wrapper, and writes the results to
Firestore at a configurable path. Supports dry-run mode for testing.

This script is a generic ingestion pipeline. All personalization (which symbols,
which tenant, which Firebase project) lives in the config file — not in code.

Usage:
    ./ingest_ohlc.py --config ./config.example.json --dry-run
    ./ingest_ohlc.py --config /path/to/my.config.json
    ./ingest_ohlc.py --config ./config.json --symbols SLV F T  # override symbols

Config schema (see config.example.json):
    {
      "firebase": { "project_id": "my-project" },     # optional; uses ADC
      "tenant_id": "default",                          # Firestore tenant scope
      "firestore_path": "tenants/{tenant_id}/kronos_predictions/{symbol}",
      "symbols": ["SLV", "F", "T"],
      "yfinance": {
        "period": "60d",         # 60 days of daily bars
        "interval": "1d"
      },
      "kronos": {
        "model_size": "small",   # mini | small | base
        "pred_len": 24,          # number of future candles
        "temperature": 1.0,
        "top_p": 0.9,
        "sample_count": 1
      }
    }
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parent

# Import the inference wrapper from the same directory.
sys.path.insert(0, str(SKILL_DIR))
from inference import predict_ohlc  # noqa: E402


# ── Config loading ────────────────────────────────────────────────────

DEFAULT_CONFIG: dict[str, Any] = {
    "firebase": {},
    "tenant_id": "default",
    "firestore_path": "tenants/{tenant_id}/kronos_predictions/{symbol}",
    "symbols": [],
    "yfinance": {"period": "60d", "interval": "1d"},
    "kronos": {
        "model_size": "small",
        "pred_len": 24,
        "temperature": 1.0,
        "top_p": 0.9,
        "sample_count": 1,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. override wins on conflicts."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Config file not found: {path}")
    with path.open("r") as f:
        user_config = json.load(f)
    return _deep_merge(DEFAULT_CONFIG, user_config)


# ── Yahoo Finance fetch ───────────────────────────────────────────────

def fetch_ohlc(symbol: str, period: str, interval: str):
    """Fetch OHLC bars for a symbol. Returns (df, x_timestamp) or raises."""
    import pandas as pd
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    hist = ticker.history(period=period, interval=interval, auto_adjust=False)
    if hist is None or hist.empty:
        raise RuntimeError(f"No OHLC data returned for {symbol} (period={period}, interval={interval})")

    # yfinance returns title-case columns; Kronos expects lowercase.
    df = pd.DataFrame({
        "open": hist["Open"].values,
        "high": hist["High"].values,
        "low": hist["Low"].values,
        "close": hist["Close"].values,
        "volume": hist["Volume"].values.astype(float),
    })
    # Kronos examples include an "amount" column (close * volume approximation).
    df["amount"] = df["close"] * df["volume"]

    x_timestamp = pd.Series(pd.to_datetime(hist.index).tz_localize(None))
    return df, x_timestamp


# ── Firestore write ───────────────────────────────────────────────────

_db = None


def get_db(firebase_cfg: dict[str, Any]):
    global _db
    if _db is None:
        import firebase_admin
        from firebase_admin import credentials, firestore

        if not firebase_admin._apps:
            cred = credentials.ApplicationDefault()
            init_args = {}
            if firebase_cfg.get("project_id"):
                init_args["projectId"] = firebase_cfg["project_id"]
            firebase_admin.initialize_app(cred, init_args or None)
        _db = firestore.client()
    return _db


def write_prediction(
    result: dict[str, Any],
    symbol: str,
    tenant_id: str,
    firestore_path_template: str,
    firebase_cfg: dict[str, Any],
    dry_run: bool,
) -> None:
    path = firestore_path_template.format(tenant_id=tenant_id, symbol=symbol)

    doc = {
        "symbol": symbol,
        "run_at": result["run_at"],
        "model": result["model"],
        "model_size": result["model_size"],
        "context_used": result["context_used"],
        "pred_len": result["pred_len"],
        "predictions": result["predictions"],
        "sampling": result["sampling"],
    }

    if dry_run:
        print(f"  [DRY RUN] Would write to: {path}")
        print(f"  [DRY RUN] First predicted candle: {json.dumps(result['predictions'][0])}")
        return

    db = get_db(firebase_cfg)
    # Convert "tenants/foo/kronos_predictions/SLV" -> nested collection refs.
    parts = path.split("/")
    if len(parts) % 2 != 0:
        raise ValueError(
            f"Firestore document path must have even number of segments: {path}"
        )
    ref: Any = db
    for i in range(0, len(parts), 2):
        ref = ref.collection(parts[i]).document(parts[i + 1])
    ref.set(doc)
    print(f"  Written to {path}")


# ── Main ──────────────────────────────────────────────────────────────

def process_symbol(symbol: str, config: dict[str, Any], dry_run: bool) -> bool:
    """Fetch, predict, write for a single symbol. Returns True on success."""
    print(f"[{symbol}]")
    try:
        yf_cfg = config["yfinance"]
        kronos_cfg = config["kronos"]

        print(f"  Fetching OHLC ({yf_cfg['period']}, {yf_cfg['interval']})...")
        ohlc_df, x_ts = fetch_ohlc(symbol, yf_cfg["period"], yf_cfg["interval"])
        print(f"  Got {len(ohlc_df)} candles, last={x_ts.iloc[-1]}")

        print(f"  Running Kronos-{kronos_cfg['model_size']} inference (pred_len={kronos_cfg['pred_len']})...")
        result = predict_ohlc(
            ohlc_df=ohlc_df,
            x_timestamp=x_ts,
            pred_len=kronos_cfg["pred_len"],
            model_size=kronos_cfg["model_size"],
            temperature=kronos_cfg.get("temperature", 1.0),
            top_p=kronos_cfg.get("top_p", 0.9),
            sample_count=kronos_cfg.get("sample_count", 1),
        )

        write_prediction(
            result=result,
            symbol=symbol,
            tenant_id=config["tenant_id"],
            firestore_path_template=config["firestore_path"],
            firebase_cfg=config.get("firebase", {}),
            dry_run=dry_run,
        )
        return True
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch OHLC, run Kronos inference, write predictions to Firestore"
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to config.json (see config.example.json for schema)",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="Override symbols from config (space-separated list)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written to Firestore without writing",
    )
    args = parser.parse_args()

    print("Kronos OHLC Ingestion")
    print("=" * 50)
    config = load_config(args.config)

    symbols = args.symbols if args.symbols else config["symbols"]
    if not symbols:
        print("No symbols specified (config.symbols is empty and --symbols not passed)")
        return 2

    print(f"Config:     {args.config}")
    print(f"Tenant:     {config['tenant_id']}")
    print(f"Symbols:    {symbols}")
    print(f"Model:      Kronos-{config['kronos']['model_size']}")
    print(f"Pred len:   {config['kronos']['pred_len']}")
    print(f"Dry run:    {args.dry_run}")
    print(f"Started:    {datetime.now(timezone.utc).isoformat()}")
    print()

    success = 0
    failed = 0
    for sym in symbols:
        if process_symbol(sym.upper(), config, args.dry_run):
            success += 1
        else:
            failed += 1
        print()

    print("=" * 50)
    print(f"Done. {success} succeeded, {failed} failed.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
