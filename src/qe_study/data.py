"""Public OHLCV + funding-rate downloader with on-disk cache and checksums.

Only public Binance USDⓈ-M endpoints are used; no API keys, no paid data.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
KLINE_DIR = DATA_DIR / "klines"
FUNDING_DIR = DATA_DIR / "funding"
MANIFEST = DATA_DIR / "manifest.json"

BASE = "https://fapi.binance.com"
MINUTE_MS = 60_000
DAY_MS = 86_400_000


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


ms = _ms


START_MS = _ms(C.START)
END_MS = _ms(C.END)


def _get(url: str, retries: int = 4) -> list:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "qe-study/0.1"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"request failed after {retries} attempts: {url} ({last})")


def fetch_klines(symbol: str) -> pd.DataFrame:
    rows: list[list] = []
    cursor = START_MS
    while cursor < END_MS:
        url = (
            f"{BASE}/fapi/v1/klines?symbol={symbol}&interval={C.INTERVAL}"
            f"&startTime={cursor}&endTime={END_MS - 1}&limit=1500"
        )
        batch = _get(url)
        if not batch:
            break
        rows.extend(batch)
        next_cursor = int(batch[-1][0]) + C.BAR_MS
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        time.sleep(0.12)

    df = pd.DataFrame(rows, columns=[
        "open_time", "open", "high", "low", "close", "volume", "close_time",
        "quote_volume", "trades", "taker_base", "taker_quote", "ignore",
    ])
    if df.empty:
        return df
    df = df[["open_time", "open", "high", "low", "close", "volume", "quote_volume"]].copy()
    df["open_time"] = df["open_time"].astype("int64")
    for col in ("open", "high", "low", "close", "volume", "quote_volume"):
        df[col] = df[col].astype(float)
    df = df.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
    return df


def fetch_funding(symbol: str) -> pd.DataFrame:
    rows: list[dict] = []
    cursor = START_MS
    while cursor < END_MS:
        url = (
            f"{BASE}/fapi/v1/fundingRate?symbol={symbol}"
            f"&startTime={cursor}&endTime={END_MS - 1}&limit=1000"
        )
        batch = _get(url)
        if not batch:
            break
        rows.extend(batch)
        next_cursor = int(batch[-1]["fundingTime"]) + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        time.sleep(0.12)

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["funding_time", "funding_rate"])
    df = df[["fundingTime", "fundingRate"]].rename(
        columns={"fundingTime": "funding_time", "fundingRate": "funding_rate"}
    )
    df["funding_time"] = df["funding_time"].astype("int64")
    df["funding_rate"] = df["funding_rate"].astype(float)
    return df.drop_duplicates("funding_time").sort_values("funding_time").reset_index(drop=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_csv_gz(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        df.to_csv(fh, index=False)


def _read_csv_gz(path: Path) -> pd.DataFrame:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return pd.read_csv(fh)


def kline_path(symbol: str) -> Path:
    return KLINE_DIR / f"{symbol}_{C.INTERVAL}.csv.gz"


def funding_path(symbol: str) -> Path:
    return FUNDING_DIR / f"{symbol}_funding.csv.gz"


def download(symbols: list[str] | None = None, force: bool = False) -> dict:
    symbols = symbols or C.SYMBOLS
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    for symbol in symbols:
        kp, fp = kline_path(symbol), funding_path(symbol)
        if force or not kp.exists():
            df = fetch_klines(symbol)
            _write_csv_gz(df, kp)
            print(f"[data] {symbol} klines {len(df):,} rows")
        if force or not fp.exists():
            fd = fetch_funding(symbol)
            _write_csv_gz(fd, fp)
            print(f"[data] {symbol} funding {len(fd):,} rows")
        manifest[symbol] = {
            "interval": C.INTERVAL,
            "start": C.START,
            "end": C.END,
            "klines_sha256": _sha256(kp),
            "funding_sha256": _sha256(fp),
            "klines_rows": int(len(_read_csv_gz(kp))),
            "funding_rows": int(len(_read_csv_gz(fp))),
        }
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def validate(symbols: list[str] | None = None) -> list[dict]:
    """Check bar continuity and manifest hashes; returns per-symbol report."""
    symbols = symbols or C.SYMBOLS
    report = []
    for symbol in symbols:
        kp = kline_path(symbol)
        if not kp.exists():
            report.append({"symbol": symbol, "ok": False, "reason": "missing data"})
            continue
        df = _read_csv_gz(kp)
        ts = df["open_time"].to_numpy(dtype="int64")
        diffs = np.diff(ts)
        gaps = int((diffs != C.BAR_MS).sum())
        # late-listed symbols (e.g. ARB) legitimately start after START_MS
        expected = int((END_MS - int(ts[0])) // C.BAR_MS)
        report.append({
            "symbol": symbol,
            "ok": gaps == 0 and len(df) == expected,
            "rows": len(df),
            "expected_rows": expected,
            "gaps": gaps,
            "late_listing_days": int((int(ts[0]) - START_MS) // DAY_MS),
            "first": datetime.fromtimestamp(ts[0] / 1000, tz=timezone.utc).isoformat(),
            "last": datetime.fromtimestamp(ts[-1] / 1000, tz=timezone.utc).isoformat(),
        })
    return report


def load(symbol: str) -> tuple[pd.DataFrame, np.ndarray]:
    """Return (ohlcv frame, funding rate per bar as float array)."""
    df = _read_csv_gz(kline_path(symbol))
    funding = _read_csv_gz(funding_path(symbol))
    if funding.empty:
        per_bar = np.zeros(len(df), dtype="float64")
        return df, per_bar

    # Funding settles at 00:00/08:00/16:00 UTC; map onto the bar that starts then.
    fund = funding.copy()
    fund["open_time"] = (fund["funding_time"] // C.BAR_MS) * C.BAR_MS
    fund = fund.groupby("open_time", as_index=False)["funding_rate"].sum()
    merged = df[["open_time"]].merge(fund, on="open_time", how="left")
    per_bar = merged["funding_rate"].fillna(0.0).to_numpy(dtype="float64")
    return df, per_bar
