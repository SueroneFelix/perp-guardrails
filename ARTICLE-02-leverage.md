# Study 2: I expected the leverage cap to be a dial. Between 5x and 2x it did nothing but relabel the loss.

*The same 50 strategy × market combinations as study 1, re-run at four cap levels on 10 Binance perps — 17 million bar evaluations per level, reproducible from public data.*

**TL;DR**

- **Ruin falls at every step: 41 → 28 → 21 → 9 of 50** as the cap tightens 5x → 3x → 2x → 1x. That looks like a dial.
- **It isn't one, economically.** At 3x and 2x, **not a single account kept half its capital**. Median final equity was $0 and $1. Only at 1x did anything survive with money: **7 of 50 kept at least half, 3 ended above break-even**.
- **Mean return barely moves between 5x and 2x** (−100.0% → −99.0%). The cap changed the label on the loss, not the loss.
- **The cap never rejected an order.** It resizes positions; the kill switch is the rule that deletes trades. That distinction matters more than it sounds.

---

Study 1 ended with an uncomfortable sentence: the 1x exposure cap did most of the work. The obvious follow-up is the one every commenter asked:

*Why only 1x? What about 2x or 3x?*

Fair. A single cap level cannot tell you whether the result is a cliff or a slope. So I ran the same 50 accounts again at 3x and 2x, kept 5x as the control, and reused the 1x arm unchanged.

Two arms — `control` and `cap_1x` — are literally the study 1 configurations, and they reproduce it to the decimal: 41/50 and 9/50 ruined, CVaR −60.9% and −9.9%. That is the reproducibility check baked into the design. If those two numbers had moved, I would have had a bug, not a finding.

## What the sweep shows

| Cap | Ruined | Median final equity | Kept ≥50% of capital | Ended above break-even | Orders sent |
|---|---|---|---|---|---|
| 5x (no cap) | **41/50 (82%)** | $0 | 0 | 0 | 17,844 |
| 3x | **28/50 (56%)** | $0 | 0 | 0 | 44,868 |
| 2x | **21/50 (42%)** | $1 | 0 | 0 | 57,985 |
| 1x | **9/50 (18%)** | $473 | **7 (14%)** | 3 (6%) | 65,319 |

![Leverage cap sweep](results/figures/fig4_leverage.png)

Read the second column and you see a dial. Read the third and fourth and you see why it isn't one.

At 3x, 22 of 50 accounts never hit zero — a real improvement over the 9 that survived at 5x. But every one of those 22 ended effectively broke. **The extra survivors did not keep money; they just took longer to lose it.** Median final equity at 3x: zero dollars. At 2x: one dollar.

At 1x the picture changes character. Seven accounts kept at least half their capital, three ended above where they started, and the best one made **+126%** over four years. Not because 1x is magic, but because at 1x an account can absorb a 100% adverse move — and in crypto, over four years, some accounts eventually had to.

## The part I did not expect: dead accounts stop trading

Look at the order counts: 17,844 at 5x, 65,319 at 1x. Lower leverage produced **3.7× as many orders**, which is not a leverage effect at all.

It is a survivorship effect visible in the fill log. At 5x, an account is liquidated early and then it is simply gone — it sends no more orders for the remaining three years. At 1x it stays alive and keeps paying fees for the whole sample. The strategy did not become more active; the account stopped being dead.

That has a practical consequence for anyone judging a live system by order flow: **a sudden drop in order count can be the first symptom of a blown account**, before any alert fires. It is also why "my bot traded less this month" deserves a look at equity, not just at the signal.

## The cap does not block orders

The `cap_blocked` counter is zero in every arm, at every level. The cap is implemented as position sizing — `min(leverage, cap)` — so nothing gets rejected; positions are simply opened smaller.

This is worth stating plainly because "exposure cap" sounds like a gate that refuses trades, and people evaluate it as if it had a cost in missed opportunities. In this study it has none of that cost. It cannot miss a trade. It only changes how much of the account each trade is allowed to risk.

The rule that *does* delete trades is the daily kill switch — it flattens and freezes the account. Different instrument, different trade-off, and study 1 showed it can be actively harmful when the threshold is mismatched to the leverage.

## Where the cap helps depends on the strategy

Ruin counts by strategy, 5x → 3x → 2x → 1x:

| Strategy | 5x | 3x | 2x | 1x |
|---|---|---|---|---|
| `donchian` | 4 | 0 | 0 | 0 |
| `ma_trend` | 7 | 2 | 0 | 0 |
| `bollinger_mr` | 10 | 8 | 7 | 1 |
| `random_entry` | 10 | 9 | 5 | 1 |
| `funding_carry` | 10 | 9 | 9 | 7 |

Trend-following is rescued almost immediately: `donchian` is fully alive at 3x, `ma_trend` at 2x.

`funding_carry` is not rescued at any level below 5x. Nine of ten die at 3x, still seven of ten at 1x. That is consistent with study 1's finding that everything dying at 1x was short: a strategy that flips with the funding sign spends long stretches short into a market that went up 2–33× off local lows. Lowering leverage delays that outcome; it does not change the direction of the bet.

So "cap at 1x" is not a universal fix. It buys survival for strategies whose failure mode is *sizing*, and only delay for strategies whose failure mode is *direction*.

## What this study does not settle

- **Three cap levels is not a curve.** I tested 5x, 3x, 2x, 1x. Whether 1.5x keeps more capital than 1x, or whether 2.5x behaves like 3x, is untested. I am not going to interpolate between points I did not run.
- **Same four years, same ten symbols, same five strategies.** A single regime sample. The ordering may hold; the magnitudes will not.
- **Simplified liquidation**, as in study 1: intrabar adverse extreme to zero, no partial liquidation, no ADL, no exchange-specific maintenance margin. Real outcomes are usually worse.
- **One definition of "kept the capital".** Half of starting equity, and break-even, are arbitrary thresholds. They are reported because "survived" alone was hiding the interesting part, not because $5,000 is a meaningful number.

## Reproduce it

```bash
python run.py download
python run.py validate
python run.py run --configs control,cap_1x,cap_2x,cap_3x --tag leverage
python figures.py
python -X utf8 check_numbers.py
```

The leverage arm writes into `results/leverage/` and leaves study 1's tables untouched — `--configs` refuses to run without `--tag`, so a partial matrix cannot silently overwrite published results. `check_numbers.py` recomputes every figure in this article from those CSVs, including the ruin counts, the capital-retention shares and the fact that `control` and `cap_1x` still match study 1.

Code: MIT. Data: Binance public API. Nothing here is investment advice, and a four-year simulation is not a forecast.

**Repo:** https://github.com/SueroneFelix/perp-guardrails
