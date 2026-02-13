"""Main benchmark orchestrator.

``HookBenchmark`` is the single entry point.  Give it a ``.sol`` file (or
compiled bytecode) and a list of scenarios, and it will:

1. Compile the hook (if source provided)
2. Compile the baseline (Vanilla 30 bps by default)
3. Run each scenario through the Rust simulation engine
4. Compute rich metrics per scenario
5. Produce a formatted text report
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Sequence

import amm_sim_rs

from amm_competition.benchmark.metrics import ScenarioResult, compute_scenario_metrics
from amm_competition.benchmark.report import format_report
from amm_competition.benchmark.scenarios import DEFAULT_SUITE, Scenario
from amm_competition.competition.config import resolve_n_workers
from amm_competition.evm.adapter import EVMStrategyAdapter
from amm_competition.evm.baseline import get_vanilla_bytecode_and_abi
from amm_competition.evm.compiler import SolidityCompiler
from amm_competition.evm.validator import SolidityValidator


class BenchmarkReport:
    """Container for benchmark results with formatting methods."""

    def __init__(
        self,
        hook_name: str,
        baseline_name: str,
        scenario_results: list[ScenarioResult],
    ):
        self.hook_name = hook_name
        self.baseline_name = baseline_name
        self.scenario_results = scenario_results

    @property
    def results(self) -> list[ScenarioResult]:
        return self.scenario_results

    def summary(self, file=None) -> None:
        """Print the full benchmark report to stdout (or a file handle)."""
        text = format_report(self.hook_name, self.baseline_name, self.scenario_results)
        print(text, file=file or sys.stdout)

    def __repr__(self) -> str:
        n = len(self.scenario_results)
        return f"BenchmarkReport({self.hook_name!r} vs {self.baseline_name!r}, {n} scenarios)"


class HookBenchmark:
    """Drop-in benchmark runner for Uniswap v4 hook strategies.

    Usage::

        bench = HookBenchmark("contracts/src/AsymmetricFeeStrategy.sol")
        report = bench.run()
        report.summary()

    Or with custom scenarios::

        from amm_competition.benchmark.scenarios import HIGH_VOL, BUY_HEAVY
        report = bench.run(scenarios=[HIGH_VOL, BUY_HEAVY])
    """

    def __init__(
        self,
        hook: str | Path | EVMStrategyAdapter,
        *,
        baseline: str | Path | EVMStrategyAdapter | None = None,
        n_workers: int | None = None,
        validate: bool = True,
    ):
        """
        Args:
            hook: Path to a .sol file, Solidity source string, or a
                pre-compiled EVMStrategyAdapter.
            baseline: Same types as *hook*.  Defaults to VanillaStrategy (30 bps).
            n_workers: Parallel Rust workers.  Defaults to ``resolve_n_workers()``.
            validate: Run static analysis on the hook source (default True).
        """
        self._n_workers = n_workers if n_workers is not None else resolve_n_workers()
        self._validate = validate

        # Resolve hook
        self._hook_bytecode, self._hook_name = self._resolve_strategy(hook, "hook")

        # Resolve baseline
        if baseline is None:
            bc, _ = get_vanilla_bytecode_and_abi()
            self._baseline_bytecode = bc
            self._baseline_name = "Vanilla_30bps"
        else:
            self._baseline_bytecode, self._baseline_name = self._resolve_strategy(
                baseline, "baseline"
            )

    def _resolve_strategy(
        self,
        source: str | Path | EVMStrategyAdapter,
        label: str,
    ) -> tuple[bytes, str]:
        """Compile or extract bytecode and name from a strategy specification."""
        if isinstance(source, EVMStrategyAdapter):
            return source._bytecode, source.get_name()

        # Determine source code
        if isinstance(source, Path) or (
            isinstance(source, str) and not source.strip().startswith("//")
            and Path(source).suffix == ".sol" and Path(source).exists()
        ):
            path = Path(source)
            source_code = path.read_text()
        else:
            source_code = source

        # Validate
        if self._validate:
            validator = SolidityValidator()
            result = validator.validate(source_code)
            if not result.valid:
                raise ValueError(
                    f"{label} validation failed: {'; '.join(result.errors)}"
                )

        # Compile — try default contract name "Strategy" first; if it fails
        # because the contract has a different name, try the available names.
        compiler = SolidityCompiler()
        compilation = compiler.compile(source_code)
        if not compilation.success and compilation.errors:
            # Check if the error is a "contract not found" with available names
            err_msg = compilation.errors[0] if compilation.errors else ""
            if "not found in output" in err_msg and "Available contracts:" in err_msg:
                import re
                m = re.search(r"Available contracts: \[(.+)\]", err_msg)
                if m:
                    names = [n.strip().strip("'\"") for n in m.group(1).split(",")]
                    for cname in names:
                        compilation = compiler.compile(source_code, contract_name=cname)
                        if compilation.success:
                            break
        if not compilation.success:
            raise RuntimeError(
                f"{label} compilation failed: {'; '.join(compilation.errors or [])}"
            )

        # Get the name via a temporary adapter
        adapter = EVMStrategyAdapter(bytecode=compilation.bytecode, abi=compilation.abi)
        name = adapter.get_name()

        return compilation.bytecode, name

    def run(
        self,
        scenarios: Sequence[Scenario] | None = None,
        *,
        progress: bool = True,
    ) -> BenchmarkReport:
        """Run the benchmark across all scenarios.

        Args:
            scenarios: List of Scenario objects.  Defaults to ``DEFAULT_SUITE``.
            progress: Print progress to stderr (default True).

        Returns:
            A BenchmarkReport with per-scenario results and formatting methods.
        """
        if scenarios is None:
            scenarios = DEFAULT_SUITE

        hook_bytes = list(self._hook_bytecode)
        baseline_bytes = list(self._baseline_bytecode)

        results: list[ScenarioResult] = []

        for i, scenario in enumerate(scenarios):
            if progress:
                print(
                    f"  [{i + 1}/{len(scenarios)}] {scenario.name} "
                    f"({scenario.n_simulations} sims)...",
                    file=sys.stderr,
                    end="",
                    flush=True,
                )

            configs = scenario.build_configs()

            batch = amm_sim_rs.run_batch(
                hook_bytes,
                baseline_bytes,
                configs,
                self._n_workers,
            )

            sr = compute_scenario_metrics(
                scenario_name=scenario.name,
                scenario_description=scenario.description,
                batch_result=batch,
                hook_name=self._hook_name,
                baseline_name=self._baseline_name,
            )
            results.append(sr)

            if progress:
                verdict = "+" if sr.win_rate > 0.5 else ("-" if sr.win_rate < 0.5 else "~")
                print(
                    f" win={sr.win_rate:.0%} edge={sr.edge_advantage:+.1f} [{verdict}]",
                    file=sys.stderr,
                    flush=True,
                )

        return BenchmarkReport(
            hook_name=self._hook_name,
            baseline_name=self._baseline_name,
            scenario_results=results,
        )
