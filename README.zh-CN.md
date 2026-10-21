# Guardrail Ablation Study

> 给加密永续策略装上执行风控，尾部风险到底改变了多少？
> 一个完全公开数据、公开代码、可逐行复现的实证研究。

**语言**：[English](README.md) · 中文

本仓库是 **QuantEngine Guard** 的信任起点：在对任何客户说"风控有用"之前，先把这句话变成一个别人能自己跑出来的数字。

---

## 结论（W1 预跑，W2 定稿）

对外长文见 `ARTICLE.md`（英文，约 2,000 词，配 3 张图）。本节是它的数据底稿。

10 币对 × 5 策略 = 50 个 (策略, 币对) 组合，2022-01-01 – 2025-12-31，含手续费、滑点与资金费率：

| 配置 | 总收益 | 爆仓率 | 日 CVaR(5%) | 说明 |
|---|---|---|---|---|
| `control` 5x，无风控 | −100% | **82%** | −60.9% | 五分之四的组合归零 |
| `cap_1x` 仓位上限 1x | −78.2% | 18% | −9.9% | 剩余爆仓全部来自 1x 做空被逼空 |
| `kill_5pct` 仅日亏熔断 | −99.6% | 14% | −18.2% | 熔断 33,178 次，把爆仓换成慢性失血 |
| `all` 上限 + 熔断 | −72.3% | **0%** | −6.7% | 50 个组合无一归零 |
| `dup_nodedupe` 重复订单不拦截 | −85.1% | 34% | −12.3% | 峰值敞口被打到 3.9x |
| `dup_dedupe` 重复订单幂等 | −78.2% | 18% | −9.9% | 拦截重复订单后回到 1x 基线 |

三条可对外讲的结论：

1. **仓位上限是唯一真正救命的规则**：爆仓率 82% → 18%，CVaR 从 −61% 收到 −10%。
2. **只有上限不够，做空方向仍会归零**：1x 做空遇到 10 倍拉升同样爆仓；上限 + 熔断才把爆仓率压到 0%。
3. **幂等去重不是"锦上添花"**：10% 的订单被重发，就能把峰值敞口推到 3.9x、爆仓率从 18% 抬到 34%、收益多亏 7 个百分点。

**关于绝对收益**：这五个策略是故意选得"笨"的对照基线，不是要证明能赚钱。把费用/资金费率归零后（`run.py run --gross`），`cap_1x` 仍是 −45%，`control` −100% —— 说明**策略本身没有 alpha，成本是第一位，风控只决定你怎么死，不决定你赚不赚**。这正是产品要卖的东西：不承诺收益，只保证不出事。

---

## 研究设计

| 项 | 设定 |
|---|---|
| 交易所 / 品种 | Binance USDⓈ-M 永续 |
| 周期 | 1h，2022-01-01 – 2025-12-31（UTC） |
| 币对 | BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, LINK, ARB（USDT 计价） |
| 初始权益 | $10,000 / 每个 (币对 × 策略) |
| 成本 | taker 5 bps + 滑点 2 bps（每边） |
| 资金费率 | 按结算时点计入持仓 |
| 执行 | 信号在 K 线收盘生成，**下一根开盘成交**（无未来函数） |
| 仓位 | 入场时定仓，不逐 bar 再平衡 |

### 五个公开策略基线

1. `ma_trend` — 双均线趋势（20/60）
2. `bollinger_mr` — 布林带均值回归（20, 2σ，z<0.5 离场）
3. `donchian` — 唐奇安通道突破（20 进 / 10 出）
4. `funding_carry` — 资金费率收割（按 24h 累计费率方向持仓）
5. `random_entry` — 随机入场（对照组，排除"策略运气"）

### 风控消融矩阵（这是本文的核心）

**实验一：杠杆上限与日亏熔断**（不注入重复订单）

| 配置 | 杠杆 | 敞口上限 | 日亏熔断 | 说明 |
|---|---|---|---|---|
| `control` | 5x | — | — | 典型散户基线 |
| `cap_1x` | 5x | 1x | — | 只加仓位上限 |
| `kill_5pct` | 5x | — | 5% | 只加日亏熔断 |
| `all` | 5x | 1x | 5% | 两层全开 |

**实验二：订单幂等**（两臂都在 1x，隔离"去重"本身）

| 配置 | 重复订单比例 | 去重 | 说明 |
|---|---|---|---|
| `dup_nodedupe` | 10% | 关闭 | 重发订单会再次成交 |
| `dup_dedupe` | 10% | 30s 窗口 | 重发订单被拦截 |

**重复订单来源**：10% 的订单在 30 秒内被"重发"（模拟 webhook 重试、策略重复触发）。去重关闭时，重发订单会按原方向再次成交——这既可能让仓位翻倍，也可能让一次平仓变成反向开仓。若同时存在敞口上限，超限的重发订单会先被上限拦下（计入 `cap_blocked`）。

### 基准

`buy_hold`（始终 1x 做多）不进消融均值，只作引擎正确性与市场环境的参照。net 口径下 10 币对均值 −26.4%，说明资金费率对长期多头是实打实的成本。

### 指标

总收益、CAGR、最大回撤、Calmar、Sharpe、日收益 CVaR(5%)、最差单日、爆仓率（ruin rate）、拦截/放行的重复订单数、熔断次数。

---

## 复现

```bash
# 1. 环境（Python 3.13）
uv venv .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt   # Windows
# uv pip install --python .venv/bin/python -r requirements.txt         # macOS / Linux

# 2. 下载公开数据（约 2–3 分钟，无需 API Key）
python run.py download

# 3. 校验数据连续性（必须无缺口）
python run.py validate

# 4. 跑完整矩阵（10 币对 × 5 策略 × 6 配置）
python run.py run

# 5. 费用/资金费率归零的对照（同一批信号，隔离成本）
python run.py run --gross

# 6. 引擎行为测试（仓位上限 / 幂等 / 熔断 / 无未来函数）
python -m unittest discover -s tests -v

# 7. 可选：重绘文章配图（需要 requirements-figures.txt）
uv pip install --python .venv/bin/python -r requirements-figures.txt
python figures.py

# 快速冒烟（单个币对，2024 年起）；子集结果写到 *_subset.csv，不覆盖正式结果
python run.py run --symbols BTCUSDT --start 2024-01-01T00:00:00Z
```

输出：

```
results/
├── per_symbol.csv            # 每个 (symbol, strategy, config) 一行
├── summary_by_strategy.csv   # 策略 × 配置 聚合
├── summary_overall.csv       # 配置 聚合（正文表格）
├── summary_benchmark.csv     # buy & hold 参照
├── equity_curves_sample.csv  # 首个币对/策略的净值曲线（不入库）
├── figures/                  # 文章配图（PNG + SVG，由 figures.py 生成）
├── run_meta.json             # 版本、参数、种子、依赖版本
└── *_gross.csv               # 费用/资金费率归零的同一批结果
```

**复现要求**：`run_meta.json` 中的 `seed`、成本参数与 `git rev-parse HEAD` 一致，结果应逐位相同。

---

## 模型假设与局限（必须与结论一起发布）

1. 清算被简化为"盘中不利极值击穿权益"，未建模部分强平、保险基金与 ADL。
2. 不建模盘口深度与冲击成本，只用一个固定滑点；小币种的真实滑点更高，意味着**尾部更差**。
3. 仓位在入场时固定，不随权益再平衡；真实系统通常有偏差阈值。
4. 未建模交易所限频、下单失败、断线重连——这些恰恰是风控层存在的原因，属于讨论而非测量对象。
5. 资金费率使用历史实际值，不预测。
6. 样本区间包含 2022 熊市与 2023–2025 牛市，结论不应外推到其他市场结构。

## 目录

```
src/qe_study/
├── config.py      # 冻结参数（改动即需要新版本号）
├── data.py        # 公开数据下载 + 校验和清单
├── strategies.py  # 五个基线策略
├── rules.py       # 风控配置矩阵
├── engine.py      # 逐 bar 撮合与风控执行
├── metrics.py     # 风险收益指标
└── cli.py         # download / validate / run
rules.schema.json  # 风控规则的声明式 schema（后续产品直接复用）
```

## 许可

代码 MIT；数据来自 Binance 公开 API，遵循其使用条款。本研究不构成投资建议。
