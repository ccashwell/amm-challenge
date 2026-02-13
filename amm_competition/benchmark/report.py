"""Text-based benchmark report formatting.

Produces clean terminal output with scenario cards and a cross-scenario
comparison table.
"""

from __future__ import annotations

import io
from typing import Sequence

from amm_competition.benchmark.metrics import ScenarioResult


_WIDTH = 72
_SEP = "=" * _WIDTH
_THIN = "-" * _WIDTH


def _center(text: str, width: int = _WIDTH) -> str:
    return text.center(width)


def _row(label: str, hook_val: str, base_val: str, delta: str = "") -> str:
    return f"  {label:<22s} {hook_val:>12s}  {base_val:>12s}  {delta:>12s}"


def format_scenario_card(r: ScenarioResult) -> str:
    """Format a single scenario result as a text card."""
    buf = io.StringIO()
    w = buf.write

    w(f"\n{_THIN}\n")
    w(f"  SCENARIO: {r.scenario_name}\n")
    w(f"  {r.scenario_description}\n")
    w(f"  ({r.n_simulations} simulations)\n")
    w(f"{_THIN}\n")

    # Header
    w(_row("", r.hook.name, r.baseline.name, "delta") + "\n")
    w(f"  {'':22s} {'':>12s}  {'':>12s}  {'':>12s}\n")

    # Edge
    w(_row(
        "Edge (mean)",
        f"{r.hook.edge_mean:+.2f}",
        f"{r.baseline.edge_mean:+.2f}",
        f"{r.edge_advantage:+.2f}",
    ) + "\n")
    w(_row(
        "Edge (median)",
        f"{r.hook.edge_median:+.2f}",
        f"{r.baseline.edge_median:+.2f}",
        "",
    ) + "\n")
    w(_row(
        "Edge (std)",
        f"{r.hook.edge_std:.2f}",
        f"{r.baseline.edge_std:.2f}",
        "",
    ) + "\n")

    # PnL
    w(_row(
        "PnL (mean)",
        f"{r.hook.pnl_mean:+.2f}",
        f"{r.baseline.pnl_mean:+.2f}",
        f"{r.hook.pnl_mean - r.baseline.pnl_mean:+.2f}",
    ) + "\n")
    w(_row(
        "PnL (std)",
        f"{r.hook.pnl_std:.2f}",
        f"{r.baseline.pnl_std:.2f}",
        "",
    ) + "\n")

    # Win rate
    w(f"\n  {'Win rate':<22s} {r.win_rate * 100:>11.1f}%\n")

    # Volume
    w(f"\n  {'Retail Vol (Y)':<22s} {r.hook.retail_volume_y_mean:>12,.0f}"
      f"  {r.baseline.retail_volume_y_mean:>12,.0f}"
      f"  {r.volume_share * 100:>10.1f}% share\n")
    w(f"  {'Arb Vol (Y)':<22s} {r.hook.arb_volume_y_mean:>12,.0f}"
      f"  {r.baseline.arb_volume_y_mean:>12,.0f}\n")

    # Fees
    w(f"\n  {'Avg Bid Fee':<22s} {r.hook.avg_bid_fee_bps:>10.1f} bps"
      f"  {r.baseline.avg_bid_fee_bps:>10.1f} bps\n")
    w(f"  {'Avg Ask Fee':<22s} {r.hook.avg_ask_fee_bps:>10.1f} bps"
      f"  {r.baseline.avg_ask_fee_bps:>10.1f} bps\n")

    # Edge percentiles
    w(f"\n  Hook edge percentiles:"
      f"  p5={r.hook.edge_p5:+.1f}"
      f"  p25={r.hook.edge_p25:+.1f}"
      f"  p50={r.hook.edge_median:+.1f}"
      f"  p75={r.hook.edge_p75:+.1f}"
      f"  p95={r.hook.edge_p95:+.1f}\n")

    return buf.getvalue()


def format_summary_table(results: Sequence[ScenarioResult]) -> str:
    """Format cross-scenario comparison as a summary table."""
    buf = io.StringIO()
    w = buf.write

    w(f"\n{_SEP}\n")
    w(_center("Cross-Scenario Summary") + "\n")
    w(f"{_SEP}\n\n")

    header = (
        f"  {'Scenario':<18s}"
        f"{'Win Rate':>10s}"
        f"{'Edge D':>10s}"
        f"{'Vol Share':>10s}"
        f"{'PnL D':>10s}"
        f"  {'Verdict':>8s}"
    )
    w(header + "\n")
    w(f"  {'-' * 66}\n")

    for r in results:
        verdict = "+" if r.win_rate > 0.5 else ("-" if r.win_rate < 0.5 else "~")
        w(
            f"  {r.scenario_name:<18s}"
            f"{r.win_rate * 100:>9.1f}%"
            f"{r.edge_advantage:>+10.2f}"
            f"{r.volume_share * 100:>9.1f}%"
            f"{r.hook.pnl_mean - r.baseline.pnl_mean:>+10.2f}"
            f"  {verdict:>8s}"
            "\n"
        )

    return buf.getvalue()


def format_report(
    hook_name: str,
    baseline_name: str,
    results: Sequence[ScenarioResult],
) -> str:
    """Format the complete benchmark report."""
    buf = io.StringIO()
    w = buf.write

    w(f"\n{_SEP}\n")
    w(_center(f"Hook Benchmark Report") + "\n")
    w(_center(f"{hook_name}  vs  {baseline_name}") + "\n")
    w(f"{_SEP}\n")

    for r in results:
        w(format_scenario_card(r))

    if len(results) > 1:
        w(format_summary_table(results))

    w(f"\n{_SEP}\n")
    return buf.getvalue()
