"""Hook benchmarking framework.

Drop in a Uniswap v4 hook ``.sol`` file and get routing + economic
performance compared against a standard CFMM baseline.

Quick start::

    from amm_competition.benchmark import HookBenchmark

    bench = HookBenchmark("contracts/src/MyHook.sol")
    report = bench.run()
    report.summary()
"""

from amm_competition.benchmark.analyzer import BenchmarkReport, HookBenchmark
from amm_competition.benchmark.metrics import ScenarioResult, StrategyStats
from amm_competition.benchmark.scenarios import Scenario

__all__ = [
    "HookBenchmark",
    "BenchmarkReport",
    "Scenario",
    "ScenarioResult",
    "StrategyStats",
]
