#!/usr/bin/env python
"""Fail if a number in the write-up disagrees with results/*.csv.

Two kinds of checks:
  * the headline table in README.md is re-derived cell by cell from the CSVs;
  * the load-bearing claims in ARTICLE.md must contain the computed literal.

Run:  python check_numbers.py     (exit code 1 on any mismatch)
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
FIGURES = RESULTS / "figures"

DASHES = str.maketrans({"\u2212": "-", "\u2013": "-", "\u2014": "-", ",": ""})


def normalise(text: str) -> str:
    return text.translate(DASHES)


def plain(cell: str) -> float:
    return float(normalise(cell).replace("*", "").replace("%", "").strip())


@dataclass(frozen=True)
class Claim:
    label: str
    computed: str
    doc: str
    alternatives: tuple[str, ...] = ()

    def ok(self, text: str) -> bool:
        return any(candidate in text for candidate in (self.computed, *self.alternatives))


ROW = re.compile(r"^\|\s*`([a-z0-9_]+)`[^|]*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|")


def load():
    overall = pd.read_csv(RESULTS / "summary_overall.csv").set_index("config")
    per_symbol = pd.read_csv(RESULTS / "per_symbol.csv")
    return overall, per_symbol[~per_symbol["benchmark"]]


def table_rows(text: str) -> dict[str, tuple[float, float, float, str]]:
    rows = {}
    for line in text.splitlines():
        match = ROW.match(line)
        if match:
            config, ret, ruin, cvar, note = match.groups()
            rows[config] = (plain(ret), plain(ruin), plain(cvar), note)
    return rows


def check_table(failures: list[str]) -> int:
    readme = normalise((ROOT / "README.md").read_text(encoding="utf-8"))
    rows = table_rows(readme)
    overall, under = load()
    if len(rows) < 6:
        failures.append(f"README table: expected 6 rows, parsed {len(rows)}")
        return 0

    checked = 0
    for config, (ret, ruin, cvar, raw) in rows.items():
        if config not in overall.index:
            failures.append(f"README table: unknown config {config!r}")
            continue
        row = overall.loc[config]
        expected = {
            "mean return": (ret, float(row["total_return"]) * 100, 0.05),
            "ruin rate": (ruin, float(row["ruin_rate"]) * 100, 0.5),
            "CVaR": (cvar, float(row["cvar_5pct"]) * 100, 0.05),
        }
        for name, (got, want, tol) in expected.items():
            checked += 1
            if abs(got - want) > tol:
                failures.append(f"README table {config} {name}: table says {got}, results say {want:.1f}")

        note = rows[config][3]
        match = re.search(r"(\d+) of 50", note)
        if match:
            checked += 1
            actual = int(under[under["config"] == config]["liquidations"].sum())
            if int(match.group(1)) != actual:
                failures.append(f"README table {config}: note says {match.group(1)} of 50, results say {actual}")
    return checked


def check_prose(failures: list[str]) -> int:
    overall, under = load()
    article = normalise((ROOT / "ARTICLE.md").read_text(encoding="utf-8"))
    dup = under[under["config"] == "dup_nodedupe"]

    def pct(config: str, column: str, digits: int = 1) -> str:
        return f"{float(overall.loc[config, column]) * 100:.{digits}f}".replace(".0", "") + "%"

    def count(config: str) -> str:
        return str(int(under[under["config"] == config]["liquidations"].sum()))

    claims = [
        Claim("control accounts wiped", f"{count('control')} of 50", "ARTICLE.md"),
        Claim("control ruin rate", pct("control", "ruin_rate", 0), "ARTICLE.md"),
        Claim("capped accounts wiped", f"{count('cap_1x')} of 50", "ARTICLE.md"),
        Claim("capped ruin rate", pct("cap_1x", "ruin_rate", 0), "ARTICLE.md"),
        Claim("capped tail", pct("cap_1x", "cvar_5pct"), "ARTICLE.md"),
        Claim("uncapped tail", pct("control", "cvar_5pct"), "ARTICLE.md"),
        Claim("capped return", pct("cap_1x", "total_return"), "ARTICLE.md"),
        Claim("kill-only return", pct("kill_5pct", "total_return"), "ARTICLE.md"),
        Claim("kill-only halts", str(int(overall.loc["kill_5pct", "halts"])), "ARTICLE.md"),
        Claim("duplicate mean peak exposure", f"{dup['max_gross_leverage'].mean():.1f}x", "ARTICLE.md"),
        Claim("duplicate worst peak exposure", f"{dup['max_gross_leverage'].max():.1f}x", "ARTICLE.md"),
        Claim("duplicate accounts above 2x", f"{int((dup['max_gross_leverage'] > 2).sum())} of 50", "ARTICLE.md"),
        Claim("duplicate ruin rate", pct("dup_nodedupe", "ruin_rate", 0), "ARTICLE.md"),
    ]

    checked = 0
    for claim in claims:
        checked += 1
        if not claim.ok(article):
            failures.append(f"ARTICLE.md: {claim.label} should read {claim.computed!r}")
    return checked


def check_zh(failures: list[str]) -> int:
    overall, under = load()
    dup = under[under["config"] == "dup_nodedupe"]
    text = normalise((ROOT / "ARTICLE.zh-CN.md").read_text(encoding="utf-8"))

    def pct(config: str, column: str, digits: int = 1) -> str:
        return f"{float(overall.loc[config, column]) * 100:.{digits}f}".replace(".0", "") + "%"

    claims = [
        Claim("control ruin rate", pct("control", "ruin_rate", 0), "ARTICLE.zh-CN.md"),
        Claim("capped ruin rate", pct("cap_1x", "ruin_rate", 0), "ARTICLE.zh-CN.md"),
        Claim("uncapped tail", pct("control", "cvar_5pct"), "ARTICLE.zh-CN.md"),
        Claim("capped tail", pct("cap_1x", "cvar_5pct"), "ARTICLE.zh-CN.md"),
        Claim("combined tail", pct("all", "cvar_5pct"), "ARTICLE.zh-CN.md"),
        Claim("kill-only return", pct("kill_5pct", "total_return"), "ARTICLE.zh-CN.md"),
        Claim("kill-only halts", str(int(overall.loc["kill_5pct", "halts"])), "ARTICLE.zh-CN.md"),
        Claim("duplicate mean peak exposure", f"{dup['max_gross_leverage'].mean():.1f}x", "ARTICLE.zh-CN.md"),
        Claim("duplicate worst peak exposure", f"{dup['max_gross_leverage'].max():.1f}x", "ARTICLE.zh-CN.md"),
        Claim("duplicate ruin rate", pct("dup_nodedupe", "ruin_rate", 0), "ARTICLE.zh-CN.md"),
    ]

    checked = 0
    for claim in claims:
        checked += 1
        if not claim.ok(text):
            failures.append(f"ARTICLE.zh-CN.md: {claim.label} should read {claim.computed!r}")
    return checked


def check_ranges(failures: list[str]) -> int:
    """The Result 2 claim that every 1x death was a short rests on price ranges."""
    klines = ROOT / "data" / "klines"
    symbols = ["SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "ARBUSDT"]
    files = [klines / f"{symbol}_1h.csv.gz" for symbol in symbols]
    if not all(path.exists() for path in files):
        print("SKIP  price ranges (data/klines not downloaded)")
        return 0

    checked = 0
    for path in files:
        close = pd.read_csv(path)["close"]
        runup = float((close / close.cummin() - 1).max()) * 100
        drawdown = float((close / close.cummax() - 1).min()) * 100
        checked += 2
        if runup < 200:
            failures.append(f"{path.stem}: max run-up {runup:.0f}% breaks the 'at least 200%' claim")
        if drawdown <= -100:
            failures.append(f"{path.stem}: drawdown {drawdown:.0f}% would let a 1x long be wiped")
    return checked


def check_bars(failures: list[str]) -> int:
    """The subtitle's bar count has to match the klines actually shipped."""
    klines = ROOT / "data" / "klines"
    files = sorted(klines.glob("*_1h.csv.gz"))
    if len(files) != 10:
        print("SKIP  bar count (data/klines incomplete)")
        return 0

    bars = sum(len(pd.read_csv(path, usecols=["close"])) for path in files)
    rounded = f"{round(bars, -4):,}"
    checked = 3
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if f"{bars:,}" not in readme:
        failures.append(f"README.md: per-strategy bar count should be {bars:,}")
    if f"{rounded} hourly bars" not in (ROOT / "ARTICLE.md").read_text(encoding="utf-8"):
        failures.append(f"ARTICLE.md: subtitle should state {rounded} hourly bars")
    if "34 万根" not in (ROOT / "ARTICLE.zh-CN.md").read_text(encoding="utf-8"):
        failures.append("ARTICLE.zh-CN.md: intro should state 34 万根")
    return checked


BANNED = {
    "ARTICLE.md": (
        "guaranteed", "risk-free", "risk free", "holy grail", "can't lose",
        "get rich", "sure thing", "100% win", "riskless", "no risk",
    ),
    "ARTICLE.zh-CN.md": (
        "稳赚", "圣杯", "包赚", "必赚", "零风险", "无风险",
        "保证盈利", "躺赚", "财富自由", "稳赢",
    ),
}

HEDGES = {
    "ARTICLE.md": (
        "simplified", "limitation", "cannot", "does not", "assumption",
        "caveat", "not investment advice", "no adl",
    ),
    "ARTICLE.zh-CN.md": (
        "简化", "局限", "不能", "无法", "假设", "不代表", "不是投资建议",
    ),
}


def _prose_paragraphs(text: str) -> list[str]:
    blocks = (block.strip() for block in text.split("\n\n"))
    return [b for b in blocks if b and not b.startswith(("#", "|", "!", "`", ">"))]


def check_prose_hygiene(failures: list[str]) -> int:
    """Selling language and hedging: the parts a number checker cannot see."""
    checked = 0
    for name, words in BANNED.items():
        text = (ROOT / name).read_text(encoding="utf-8")
        lowered = text.lower()
        checked += 1
        for word in words:
            if word in lowered:
                failures.append(f"{name}: banned selling phrase '{word}'")

        checked += 1
        hedges = sum(lowered.count(word) for word in HEDGES[name])
        if hedges < 3:
            failures.append(f"{name}: only {hedges} self-limitation phrases (need >= 3)")

        checked += 1
        paragraphs = _prose_paragraphs(text)
        if paragraphs:
            if name == "ARTICLE.md":
                longest = max(len(re.findall(r"[A-Za-z']+", p)) for p in paragraphs)
                if longest > 220:
                    failures.append(f"{name}: a paragraph runs {longest} words (wall of text)")
            else:
                longest = max(len(p) for p in paragraphs)
                if longest > 450:
                    failures.append(f"{name}: a paragraph runs {longest} characters (wall of text)")
    return checked


def check_artifacts(failures: list[str]) -> int:
    article = (ROOT / "ARTICLE.md").read_text(encoding="utf-8")
    referenced = re.findall(r"results/figures/([A-Za-z0-9_]+\.png)", article)
    checked = 0
    if len(referenced) < 3:
        failures.append(f"ARTICLE.md references {len(referenced)} figures, expected at least 3")

    for name in referenced:
        checked += 1
        if not (FIGURES / name).exists():
            failures.append(f"missing figure asset: {name}")

    meta = RESULTS / "run_meta.json"
    checked += 1
    if not meta.exists():
        failures.append("missing results/run_meta.json")
    else:
        import json

        data = json.loads(meta.read_text(encoding="utf-8"))
        for key in ("seed", "symbols", "configs", "taker_fee", "slippage", "pandas"):
            if key not in data:
                failures.append(f"run_meta.json is missing {key!r}")
        if len(data.get("symbols", [])) != 10:
            failures.append(f"run_meta.json lists {len(data.get('symbols', []))} symbols, expected 10")
    return checked


def main() -> int:
    failures: list[str] = []
    checked = (
        check_table(failures)
        + check_prose(failures)
        + check_zh(failures)
        + check_ranges(failures)
        + check_bars(failures)
        + check_prose_hygiene(failures)
        + check_artifacts(failures)
    )
    for line in failures:
        print(f"FAIL  {line}")
    if failures:
        print(f"\n{len(failures)} problem(s) found")
        return 1
    print(f"OK    {checked} numbers and assets agree with results/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
