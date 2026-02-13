"""Compute rich benchmark metrics from raw Rust simulation results.

Works directly with the ``amm_sim_rs.BatchSimulationResult`` that comes back
from ``run_batch()``, extracting per-simulation scalars and aggregating them
into distribution statistics and comparison metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

# Keys used by the Rust engine for the two strategies
_SUBMISSION = "submission"
_NORMALIZER = "normalizer"


@dataclass
class StrategyStats:
    """Aggregate statistics for one strategy across all simulations."""

    name: str

    # Edge distribution
    edge_mean: float = 0.0
    edge_std: float = 0.0
    edge_median: float = 0.0
    edge_p5: float = 0.0
    edge_p25: float = 0.0
    edge_p75: float = 0.0
    edge_p95: float = 0.0

    # PnL distribution
    pnl_mean: float = 0.0
    pnl_std: float = 0.0
    pnl_median: float = 0.0

    # Volume (averages across sims)
    retail_volume_y_mean: float = 0.0
    arb_volume_y_mean: float = 0.0

    # Fee statistics (averaged across sims)
    avg_bid_fee_bps: float = 0.0
    avg_ask_fee_bps: float = 0.0


@dataclass
class ScenarioResult:
    """Complete benchmark result for one scenario."""

    scenario_name: str
    scenario_description: str
    n_simulations: int

    hook: StrategyStats = field(default_factory=lambda: StrategyStats(""))
    baseline: StrategyStats = field(default_factory=lambda: StrategyStats(""))

    # Head-to-head
    wins_hook: int = 0
    wins_baseline: int = 0
    draws: int = 0

    # Derived comparison metrics
    win_rate: float = 0.0
    edge_advantage: float = 0.0
    volume_share: float = 0.0  # hook retail volume / total retail volume
    volume_ratio: float = 0.0  # hook retail volume / baseline retail volume


def compute_scenario_metrics(
    scenario_name: str,
    scenario_description: str,
    batch_result,
    hook_name: str = "hook",
    baseline_name: str = "baseline",
) -> ScenarioResult:
    """Compute all metrics for a single scenario from a BatchSimulationResult."""
    results = batch_result.results
    n = len(results)
    if n == 0:
        return ScenarioResult(
            scenario_name=scenario_name,
            scenario_description=scenario_description,
            n_simulations=0,
        )

    # Collect per-simulation arrays
    hook_edges = np.empty(n)
    hook_pnls = np.empty(n)
    hook_retail_vol = np.empty(n)
    hook_arb_vol = np.empty(n)
    hook_bid_fees = np.empty(n)
    hook_ask_fees = np.empty(n)

    base_edges = np.empty(n)
    base_pnls = np.empty(n)
    base_retail_vol = np.empty(n)
    base_arb_vol = np.empty(n)
    base_bid_fees = np.empty(n)
    base_ask_fees = np.empty(n)

    wins_h, wins_b, draws = 0, 0, 0

    for i, sim in enumerate(results):
        he = sim.edges.get(_SUBMISSION, 0.0)
        be = sim.edges.get(_NORMALIZER, 0.0)
        hook_edges[i] = he
        base_edges[i] = be

        if he > be:
            wins_h += 1
        elif be > he:
            wins_b += 1
        else:
            draws += 1

        hook_pnls[i] = sim.pnl.get(_SUBMISSION, 0.0)
        base_pnls[i] = sim.pnl.get(_NORMALIZER, 0.0)

        hook_retail_vol[i] = sim.retail_volume_y.get(_SUBMISSION, 0.0)
        base_retail_vol[i] = sim.retail_volume_y.get(_NORMALIZER, 0.0)

        hook_arb_vol[i] = sim.arb_volume_y.get(_SUBMISSION, 0.0)
        base_arb_vol[i] = sim.arb_volume_y.get(_NORMALIZER, 0.0)

        h_avg = sim.average_fees.get(_SUBMISSION, (0.0, 0.0))
        b_avg = sim.average_fees.get(_NORMALIZER, (0.0, 0.0))
        hook_bid_fees[i] = h_avg[0]
        hook_ask_fees[i] = h_avg[1]
        base_bid_fees[i] = b_avg[0]
        base_ask_fees[i] = b_avg[1]

    # Build StrategyStats for hook
    hook_stats = StrategyStats(
        name=hook_name,
        edge_mean=float(np.mean(hook_edges)),
        edge_std=float(np.std(hook_edges)),
        edge_median=float(np.median(hook_edges)),
        edge_p5=float(np.percentile(hook_edges, 5)),
        edge_p25=float(np.percentile(hook_edges, 25)),
        edge_p75=float(np.percentile(hook_edges, 75)),
        edge_p95=float(np.percentile(hook_edges, 95)),
        pnl_mean=float(np.mean(hook_pnls)),
        pnl_std=float(np.std(hook_pnls)),
        pnl_median=float(np.median(hook_pnls)),
        retail_volume_y_mean=float(np.mean(hook_retail_vol)),
        arb_volume_y_mean=float(np.mean(hook_arb_vol)),
        avg_bid_fee_bps=float(np.mean(hook_bid_fees)) * 10_000,
        avg_ask_fee_bps=float(np.mean(hook_ask_fees)) * 10_000,
    )

    # Build StrategyStats for baseline
    base_stats = StrategyStats(
        name=baseline_name,
        edge_mean=float(np.mean(base_edges)),
        edge_std=float(np.std(base_edges)),
        edge_median=float(np.median(base_edges)),
        edge_p5=float(np.percentile(base_edges, 5)),
        edge_p25=float(np.percentile(base_edges, 25)),
        edge_p75=float(np.percentile(base_edges, 75)),
        edge_p95=float(np.percentile(base_edges, 95)),
        pnl_mean=float(np.mean(base_pnls)),
        pnl_std=float(np.std(base_pnls)),
        pnl_median=float(np.median(base_pnls)),
        retail_volume_y_mean=float(np.mean(base_retail_vol)),
        arb_volume_y_mean=float(np.mean(base_arb_vol)),
        avg_bid_fee_bps=float(np.mean(base_bid_fees)) * 10_000,
        avg_ask_fee_bps=float(np.mean(base_ask_fees)) * 10_000,
    )

    # Comparison
    total_retail = hook_stats.retail_volume_y_mean + base_stats.retail_volume_y_mean
    vol_share = hook_stats.retail_volume_y_mean / total_retail if total_retail > 0 else 0.5
    vol_ratio = (
        hook_stats.retail_volume_y_mean / base_stats.retail_volume_y_mean
        if base_stats.retail_volume_y_mean > 0
        else float("inf")
    )

    return ScenarioResult(
        scenario_name=scenario_name,
        scenario_description=scenario_description,
        n_simulations=n,
        hook=hook_stats,
        baseline=base_stats,
        wins_hook=wins_h,
        wins_baseline=wins_b,
        draws=draws,
        win_rate=wins_h / n if n > 0 else 0.0,
        edge_advantage=hook_stats.edge_mean - base_stats.edge_mean,
        volume_share=vol_share,
        volume_ratio=vol_ratio,
    )
