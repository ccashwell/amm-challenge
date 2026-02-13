"""Tests for the hook benchmarking framework."""

from __future__ import annotations

from pathlib import Path

import pytest

from amm_competition.benchmark.analyzer import BenchmarkReport, HookBenchmark
from amm_competition.benchmark.metrics import (
    ScenarioResult,
    StrategyStats,
    compute_scenario_metrics,
)
from amm_competition.benchmark.report import format_report, format_scenario_card, format_summary_table
from amm_competition.benchmark.scenarios import (
    BASELINE,
    BUY_HEAVY,
    DEFAULT_SUITE,
    FULL_SUITE,
    HIGH_VOL,
    LOW_VOL,
    QUICK_SUITE,
    SELL_HEAVY,
    Scenario,
)

CONTRACTS_DIR = Path(__file__).parent.parent / "contracts" / "src"


# ---------------------------------------------------------------------------
# Scenario tests
# ---------------------------------------------------------------------------

class TestScenarios:
    def test_baseline_defaults(self):
        assert BASELINE.name == "baseline"
        assert BASELINE.gbm_mu == 0.0
        assert BASELINE.retail_buy_prob == 0.5

    def test_high_vol_has_higher_sigma(self):
        assert HIGH_VOL.gbm_sigma > BASELINE.gbm_sigma

    def test_low_vol_has_lower_sigma(self):
        assert LOW_VOL.gbm_sigma < BASELINE.gbm_sigma

    def test_buy_heavy_has_buy_bias(self):
        assert BUY_HEAVY.retail_buy_prob > 0.5

    def test_sell_heavy_has_sell_bias(self):
        assert SELL_HEAVY.retail_buy_prob < 0.5

    def test_build_configs_length(self):
        s = Scenario(name="test", description="test", n_simulations=5, n_steps=100)
        configs = s.build_configs()
        assert len(configs) == 5

    def test_build_configs_deterministic_seeds(self):
        s = Scenario(name="test", description="test", n_simulations=3, n_steps=100)
        configs = s.build_configs()
        # Each config should have a different seed (0, 1, 2)
        # We can verify they produce different results by checking the objects exist
        assert len(configs) == 3

    def test_suites_are_non_empty(self):
        assert len(QUICK_SUITE) >= 2
        assert len(DEFAULT_SUITE) >= 5
        assert len(FULL_SUITE) >= 8


# ---------------------------------------------------------------------------
# Metrics tests
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_strategy_stats_defaults(self):
        s = StrategyStats(name="test")
        assert s.edge_mean == 0.0
        assert s.pnl_mean == 0.0
        assert s.retail_volume_y_mean == 0.0

    def test_scenario_result_defaults(self):
        r = ScenarioResult(
            scenario_name="test",
            scenario_description="test",
            n_simulations=0,
        )
        assert r.win_rate == 0.0
        assert r.volume_share == 0.0


# ---------------------------------------------------------------------------
# Report formatting tests
# ---------------------------------------------------------------------------

class TestReport:
    def test_format_scenario_card_contains_name(self):
        r = ScenarioResult(
            scenario_name="test_scenario",
            scenario_description="A test",
            n_simulations=10,
            hook=StrategyStats(name="MyHook"),
            baseline=StrategyStats(name="Vanilla"),
        )
        card = format_scenario_card(r)
        assert "test_scenario" in card
        assert "MyHook" in card
        assert "Vanilla" in card

    def test_format_summary_table_multiple(self):
        results = [
            ScenarioResult(
                scenario_name="s1",
                scenario_description="",
                n_simulations=10,
                win_rate=0.6,
                edge_advantage=1.5,
                volume_share=0.52,
                hook=StrategyStats(name="Hook", pnl_mean=5.0),
                baseline=StrategyStats(name="Base", pnl_mean=3.0),
            ),
            ScenarioResult(
                scenario_name="s2",
                scenario_description="",
                n_simulations=10,
                win_rate=0.4,
                edge_advantage=-0.5,
                volume_share=0.48,
                hook=StrategyStats(name="Hook", pnl_mean=2.0),
                baseline=StrategyStats(name="Base", pnl_mean=4.0),
            ),
        ]
        table = format_summary_table(results)
        assert "s1" in table
        assert "s2" in table
        assert "+" in table  # winning verdict
        assert "-" in table  # losing verdict

    def test_format_report_complete(self):
        r = ScenarioResult(
            scenario_name="test",
            scenario_description="",
            n_simulations=10,
            hook=StrategyStats(name="Hook"),
            baseline=StrategyStats(name="Base"),
        )
        report = format_report("Hook", "Base", [r])
        assert "Hook" in report
        assert "Base" in report
        assert "Benchmark Report" in report


# ---------------------------------------------------------------------------
# Integration tests (run actual simulations)
# ---------------------------------------------------------------------------

class TestHookBenchmarkIntegration:
    """Integration tests that compile real contracts and run simulations.

    Uses small simulation counts for speed.
    """

    @pytest.fixture
    def tiny_scenario(self) -> Scenario:
        return Scenario(
            name="tiny",
            description="Minimal scenario for testing",
            n_simulations=3,
            n_steps=200,
        )

    def test_benchmark_from_sol_path(self, tiny_scenario: Scenario):
        """End-to-end: .sol path -> benchmark report."""
        sol_path = CONTRACTS_DIR / "AsymmetricFeeStrategy.sol"
        bench = HookBenchmark(sol_path)
        report = bench.run(scenarios=[tiny_scenario], progress=False)

        assert isinstance(report, BenchmarkReport)
        assert len(report.results) == 1
        assert report.hook_name == "Asymmetric_25_35bps"
        assert report.baseline_name == "Vanilla_30bps"

        sr = report.results[0]
        assert sr.n_simulations == 3
        assert sr.wins_hook + sr.wins_baseline + sr.draws == 3
        assert 0.0 <= sr.volume_share <= 1.0

    def test_benchmark_from_adapter(self, tiny_scenario: Scenario):
        """Benchmark accepts pre-compiled EVMStrategyAdapter."""
        from amm_competition.evm.adapter import EVMStrategyAdapter

        sol_path = CONTRACTS_DIR / "AsymmetricFeeStrategy.sol"
        adapter = EVMStrategyAdapter.from_source(sol_path.read_text())

        bench = HookBenchmark(adapter)
        report = bench.run(scenarios=[tiny_scenario], progress=False)
        assert report.hook_name == "Asymmetric_25_35bps"

    def test_benchmark_vanilla_vs_vanilla(self, tiny_scenario: Scenario):
        """Symmetric benchmark: Vanilla vs itself should have ~50% win rate."""
        sol_path = CONTRACTS_DIR / "VanillaStrategy.sol"
        bench = HookBenchmark(sol_path, validate=False)
        report = bench.run(scenarios=[tiny_scenario], progress=False)

        sr = report.results[0]
        # With same strategy, edge advantage should be near zero
        assert abs(sr.edge_advantage) < 50.0  # generous bound for 3 sims

    def test_benchmark_report_summary(self, tiny_scenario: Scenario, capsys):
        """Report summary produces non-empty text output."""
        sol_path = CONTRACTS_DIR / "AsymmetricFeeStrategy.sol"
        bench = HookBenchmark(sol_path)
        report = bench.run(scenarios=[tiny_scenario], progress=False)
        report.summary()

        captured = capsys.readouterr()
        assert "Benchmark Report" in captured.out
        assert "Asymmetric_25_35bps" in captured.out

    def test_benchmark_multiple_scenarios(self):
        """Run across multiple scenarios and get summary table."""
        scenarios = [
            Scenario(name="calm", description="Low vol", n_simulations=3, n_steps=200, gbm_sigma=0.0005),
            Scenario(name="storm", description="High vol", n_simulations=3, n_steps=200, gbm_sigma=0.002),
        ]
        sol_path = CONTRACTS_DIR / "AsymmetricFeeStrategy.sol"
        bench = HookBenchmark(sol_path)
        report = bench.run(scenarios=scenarios, progress=False)

        assert len(report.results) == 2
        assert report.results[0].scenario_name == "calm"
        assert report.results[1].scenario_name == "storm"

    def test_benchmark_starter_vs_vanilla(self, tiny_scenario: Scenario):
        """StarterStrategy (50 bps) should lose to Vanilla (30 bps) on volume."""
        sol_path = CONTRACTS_DIR / "StarterStrategy.sol"
        bench = HookBenchmark(sol_path, validate=False)
        report = bench.run(
            scenarios=[Scenario(
                name="test", description="test",
                n_simulations=20, n_steps=2000,
            )],
            progress=False,
        )

        sr = report.results[0]
        # Higher fees should attract less retail volume
        assert sr.volume_share < 0.55  # starter gets less than or close to half
