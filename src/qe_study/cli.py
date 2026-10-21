"""Command line entry point: download | validate | run."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C
from . import data, metrics, strategies
from .engine import simulate
from .rules import CONFIG_BY_NAME, CONFIGS

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"


def _parse_list(value: str | None) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()] if value else []


def cmd_download(args: argparse.Namespace) -> None:
    symbols = _parse_list(args.symbols) or C.SYMBOLS
    data.download(symbols, force=args.force)


def cmd_validate(args: argparse.Namespace) -> None:
    symbols = _parse_list(args.symbols) or C.SYMBOLS
    report = data.validate(symbols)
    frame = pd.DataFrame(report)
    print(frame.to_string(index=False))
    if not all(item["ok"] for item in report):
        print("\n[validate] gaps or missing files detected — run `download --force`", file=sys.stderr)


def cmd_run(args: argparse.Namespace) -> None:
    symbols = _parse_list(args.symbols) or C.SYMBOLS
    strategy_names = _parse_list(args.strategies) or list(strategies.STRATEGIES + strategies.BENCHMARKS)
    config_names = _parse_list(args.configs) or [cfg.name for cfg in CONFIGS]
    configs = [CONFIG_BY_NAME[name] for name in config_names]

    start_ms = data.ms(args.start) if args.start else data.START_MS
    if args.symbols or args.start:
        # subset runs must not overwrite the published full-matrix tables
        suffix = ("_gross" if args.gross else "") + "_subset"
        print("[run] subset run -> results/*_subset.csv (full matrix untouched)", file=sys.stderr)
    else:
        suffix = "_gross" if args.gross else ""
    if args.gross:
        # sanity check: same signals, zero fees/slippage/funding
        C.TAKER_FEE = 0.0
        C.SLIPPAGE = 0.0

    rows: list[dict] = []
    curves: dict[str, pd.Series] = {}

    for symbol in symbols:
        df_full, funding_full = data.load(symbol)
        mask = df_full["open_time"].to_numpy(dtype="int64") >= start_ms
        df = df_full.loc[mask].reset_index(drop=True)
        funding = funding_full[mask]
        funding_cost = np.zeros_like(funding) if args.gross else funding
        if df.empty:
            print(f"[run] {symbol}: no data — skipped", file=sys.stderr)
            continue

        open_ = df["open"].to_numpy(dtype="float64")
        high = df["high"].to_numpy(dtype="float64")
        low = df["low"].to_numpy(dtype="float64")
        close = df["close"].to_numpy(dtype="float64")
        ts = df["open_time"].to_numpy(dtype="int64")

        for strategy_name in strategy_names:
            states = strategies.build(strategy_name, df, funding, seed=C.SEED)
            for cfg in configs:
                result = simulate(
                    open_, high, low, close, ts, funding_cost, states, cfg, seed=C.SEED
                )
                row = {
                    "symbol": symbol,
                    "strategy": strategy_name,
                    "benchmark": strategy_name in strategies.BENCHMARKS,
                    "group": cfg.group,
                    "config": cfg.name,
                    "orders": result.orders,
                    "dups_blocked": result.duplicates_blocked,
                    "dups_executed": result.duplicates_executed,
                    "cap_blocked": result.cap_blocked,
                    "halts": result.halts,
                    "liquidations": result.liquidations,
                    "ruined": result.ruined,
                    "max_gross_leverage": result.max_gross_leverage,
                }
                row.update(metrics.summarize(result.equity, ts))
                rows.append(row)

                if symbol == symbols[0] and strategy_name == strategy_names[0]:
                    curves[f"{cfg.name}"] = pd.Series(
                        result.equity, index=pd.to_datetime(ts, unit="ms", utc=True)
                    )

    if not rows:
        raise SystemExit("no results — check data availability")

    per_symbol = pd.DataFrame(rows)
    RESULTS.mkdir(parents=True, exist_ok=True)
    per_symbol.to_csv(RESULTS / f"per_symbol{suffix}.csv", index=False)

    under_test = per_symbol[~per_symbol["benchmark"]]
    benchmarks = per_symbol[per_symbol["benchmark"]]

    by_strategy = _aggregate(under_test, ["strategy", "config"])
    by_strategy.to_csv(RESULTS / f"summary_by_strategy{suffix}.csv", index=False)
    overall = _aggregate(under_test, ["group", "config"])
    overall.to_csv(RESULTS / f"summary_overall{suffix}.csv", index=False)
    bench_summary = _aggregate(benchmarks, ["config"]) if len(benchmarks) else pd.DataFrame()
    if len(bench_summary):
        bench_summary.to_csv(RESULTS / f"summary_benchmark{suffix}.csv", index=False)

    if curves:
        pd.DataFrame(curves).to_csv(RESULTS / f"equity_curves_sample{suffix}.csv")

    meta = {
        "study_version": C.STUDY_VERSION,
        "gross": bool(args.gross),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbols": symbols,
        "strategies": strategy_names,
        "configs": [cfg.to_dict() for cfg in configs],
        "start": args.start or C.START,
        "taker_fee": C.TAKER_FEE,
        "slippage": C.SLIPPAGE,
        "seed": C.SEED,
        "pandas": pd.__version__,
        "numpy": np.__version__,
    }
    (RESULTS / f"run_meta{suffix}.json").write_text(json.dumps(meta, indent=2))

    _print_table(overall, "UNDER TEST (mean across strategy x symbol)", group="group")
    _print_table(by_strategy, "BY STRATEGY (mean across symbols)", group="strategy")
    if len(bench_summary):
        _print_table(bench_summary, "BENCHMARK — buy & hold (mean across symbols)")


def _aggregate(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    numeric = [
        "total_return", "cagr", "max_drawdown", "calmar", "sharpe",
        "cvar_5pct", "worst_day", "final_equity", "max_gross_leverage",
    ]
    grouped = frame.groupby(keys, dropna=False)
    out = grouped[numeric].mean()
    out["n"] = grouped.size()
    out["ruin_rate"] = grouped["ruined"].mean()
    out["orders"] = grouped["orders"].mean()
    out["dups_blocked"] = grouped["dups_blocked"].sum()
    out["dups_executed"] = grouped["dups_executed"].sum()
    out["cap_blocked"] = grouped["cap_blocked"].sum()
    out["halts"] = grouped["halts"].sum()
    return out.reset_index()


def _print_table(frame: pd.DataFrame, title: str, group: str | None = None) -> None:
    print(f"\n=== {title} ===")
    show = frame.copy()
    for col in ("total_return", "cagr", "max_drawdown", "calmar", "sharpe", "cvar_5pct", "worst_day", "ruin_rate"):
        if col in show:
            show[col] = show[col].map(lambda v: f"{v:+.1%}" if pd.notna(v) and col != "calmar" and col != "sharpe" else (f"{v:.2f}" if pd.notna(v) else "nan"))
    keep = [col for col in ["group", "strategy", "config", "n", "total_return", "cagr", "max_drawdown", "calmar", "cvar_5pct", "ruin_rate", "dups_blocked", "cap_blocked", "halts"] if col in show]
    print(show[keep].to_string(index=False))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="qe-study", description="Guardrail ablation study")
    parser.add_argument("--version", action="version", version=C.STUDY_VERSION)
    sub = parser.add_subparsers(dest="command", required=True)

    p_dl = sub.add_parser("download", help="fetch public klines + funding rates")
    p_dl.add_argument("--symbols")
    p_dl.add_argument("--force", action="store_true")
    p_dl.set_defaults(func=cmd_download)

    p_val = sub.add_parser("validate", help="check continuity of cached data")
    p_val.add_argument("--symbols")
    p_val.set_defaults(func=cmd_validate)

    p_run = sub.add_parser("run", help="run the ablation matrix")
    p_run.add_argument("--symbols")
    p_run.add_argument("--strategies")
    p_run.add_argument("--configs")
    p_run.add_argument("--start", help="ISO date, e.g. 2024-01-01T00:00:00Z")
    p_run.add_argument("--gross", action="store_true", help="zero fees, slippage and funding")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
