"""Guardrail configurations under test (two isolated experiments)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from . import config as C


@dataclass(frozen=True)
class GuardConfig:
    """A guardrail policy. `None` means the rule is disabled."""

    name: str
    group: str = "main"
    leverage: float = C.CONTROL_LEVERAGE
    exposure_cap: float | None = None      # max gross notional / equity
    daily_loss_limit: float | None = None  # fraction of day-start equity
    dedupe: bool = False
    dedupe_window_s: int = C.DUPLICATE_WINDOW_S
    duplicate_prob: float = 0.0            # off in the main matrix

    @property
    def max_leverage(self) -> float:
        return min(self.leverage, self.exposure_cap) if self.exposure_cap else self.leverage

    def to_dict(self) -> dict:
        return asdict(self)


# Experiment 1 — leverage cap and daily kill switch, no duplicate traffic.
MAIN_CONFIGS: tuple[GuardConfig, ...] = (
    GuardConfig(name="control"),
    GuardConfig(name="cap_1x", exposure_cap=C.EXPOSURE_CAP),
    GuardConfig(name="kill_5pct", daily_loss_limit=C.DAILY_LOSS_LIMIT),
    GuardConfig(
        name="all",
        exposure_cap=C.EXPOSURE_CAP,
        daily_loss_limit=C.DAILY_LOSS_LIMIT,
    ),
)

# Experiment 2 — 10% of orders are re-sent; does idempotency matter?
# Both arms run at 1x so a duplicated entry (2x) stays survivable and the
# difference isolates deduplication rather than leverage.
DUP_CONFIGS: tuple[GuardConfig, ...] = (
    GuardConfig(name="dup_nodedupe", group="dup", leverage=1.0, duplicate_prob=C.DUPLICATE_PROB),
    GuardConfig(
        name="dup_dedupe",
        group="dup",
        leverage=1.0,
        duplicate_prob=C.DUPLICATE_PROB,
        dedupe=True,
    ),
)

# Study 2 (v0.2) — how far down does the cap have to go?
# Runs alongside control (5x) and cap_1x from the main matrix; reusing those
# two arms makes their numbers a cross-check against study 1.
LEVERAGE_CONFIGS: tuple[GuardConfig, ...] = (
    GuardConfig(name="cap_2x", group="leverage", exposure_cap=2.0),
    GuardConfig(name="cap_3x", group="leverage", exposure_cap=3.0),
)

# Study 3 (v0.3) — does the duplicate *rate* matter, or only the fact of duplication?
# All arms sit at 1x with dedupe off, so the only moving part is how often an
# order is re-sent. dup_nodedupe (10%) and dup_dedupe come along as cross-checks
# against study 1, and dup_0pct should land on cap_1x: same 1x exposure, no
# duplicate traffic.
DUP_RATE_CONFIGS: tuple[GuardConfig, ...] = (
    GuardConfig(name="dup_0pct", group="dup_rate", leverage=1.0, duplicate_prob=0.0),
    GuardConfig(name="dup_1pct", group="dup_rate", leverage=1.0, duplicate_prob=0.01),
    GuardConfig(name="dup_5pct", group="dup_rate", leverage=1.0, duplicate_prob=0.05),
    GuardConfig(name="dup_20pct", group="dup_rate", leverage=1.0, duplicate_prob=0.20),
)

CONFIGS: tuple[GuardConfig, ...] = MAIN_CONFIGS + DUP_CONFIGS
CONFIG_BY_NAME = {cfg.name: cfg for cfg in CONFIGS + LEVERAGE_CONFIGS + DUP_RATE_CONFIGS}

