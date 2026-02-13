"""Pre-defined market scenarios for hook benchmarking.

Each scenario represents a distinct market regime — volatility level, order-flow
direction, price trend, or retail activity — so that hooks can be stress-tested
across realistic conditions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import amm_sim_rs


@dataclass(frozen=True)
class Scenario:
    """A named market regime with fixed simulation parameters."""

    name: str
    description: str

    # Simulation size
    n_simulations: int = 200
    n_steps: int = 10_000

    # Pool initial state
    initial_price: float = 100.0
    initial_x: float = 100.0
    initial_y: float = 10_000.0

    # Price process (GBM)
    gbm_mu: float = 0.0
    gbm_sigma: float = 0.000_945  # ~30% annualised at dt=1
    gbm_dt: float = 1.0

    # Retail flow
    retail_arrival_rate: float = 0.8
    retail_mean_size: float = 20.0
    retail_buy_prob: float = 0.5
    retail_size_sigma: float = 1.2

    def build_configs(self) -> list[amm_sim_rs.SimulationConfig]:
        """Build one SimulationConfig per simulation, seeded deterministically."""
        return [
            amm_sim_rs.SimulationConfig(
                seed=i,
                n_steps=self.n_steps,
                initial_price=self.initial_price,
                initial_x=self.initial_x,
                initial_y=self.initial_y,
                gbm_mu=self.gbm_mu,
                gbm_sigma=self.gbm_sigma,
                gbm_dt=self.gbm_dt,
                retail_arrival_rate=self.retail_arrival_rate,
                retail_mean_size=self.retail_mean_size,
                retail_buy_prob=self.retail_buy_prob,
                retail_size_sigma=self.retail_size_sigma,
            )
            for i in range(self.n_simulations)
        ]


# ---------------------------------------------------------------------------
# Pre-defined scenarios
# ---------------------------------------------------------------------------

BASELINE = Scenario(
    name="baseline",
    description="Moderate volatility, balanced flow, no trend",
)

LOW_VOL = Scenario(
    name="low_volatility",
    description="Calm market (~15% annualised vol)",
    gbm_sigma=0.000_47,
)

HIGH_VOL = Scenario(
    name="high_volatility",
    description="Stressed market (~60% annualised vol)",
    gbm_sigma=0.001_89,
)

TRENDING_UP = Scenario(
    name="trending_up",
    description="Persistent upward drift (positive mu)",
    gbm_mu=0.000_05,
)

TRENDING_DOWN = Scenario(
    name="trending_down",
    description="Persistent downward drift (negative mu)",
    gbm_mu=-0.000_05,
)

BUY_HEAVY = Scenario(
    name="buy_heavy",
    description="70% of retail flow is buys",
    retail_buy_prob=0.7,
)

SELL_HEAVY = Scenario(
    name="sell_heavy",
    description="70% of retail flow is sells",
    retail_buy_prob=0.3,
)

HIGH_RETAIL = Scenario(
    name="high_retail",
    description="Double the retail arrival rate",
    retail_arrival_rate=1.6,
)

LOW_RETAIL = Scenario(
    name="low_retail",
    description="Sparse retail flow",
    retail_arrival_rate=0.3,
)

WHALE_ORDERS = Scenario(
    name="whale_orders",
    description="Large average retail order size",
    retail_mean_size=60.0,
)

# Curated suites
QUICK_SUITE: Sequence[Scenario] = (BASELINE, HIGH_VOL, BUY_HEAVY)

DEFAULT_SUITE: Sequence[Scenario] = (
    BASELINE,
    LOW_VOL,
    HIGH_VOL,
    TRENDING_UP,
    TRENDING_DOWN,
    BUY_HEAVY,
    SELL_HEAVY,
)

FULL_SUITE: Sequence[Scenario] = (
    BASELINE,
    LOW_VOL,
    HIGH_VOL,
    TRENDING_UP,
    TRENDING_DOWN,
    BUY_HEAVY,
    SELL_HEAVY,
    HIGH_RETAIL,
    LOW_RETAIL,
    WHALE_ORDERS,
)
