"""Tests for the Asymmetric Fee Hook strategy (25/35 bps)."""

from decimal import Decimal
from pathlib import Path

import pytest

from amm_competition.core.amm import AMM
from amm_competition.core.trade import FeeQuote, TradeInfo
from amm_competition.evm.adapter import EVMStrategyAdapter
from amm_competition.evm.compiler import SolidityCompiler
from amm_competition.evm.baseline import load_vanilla_strategy


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def asymmetric_adapter() -> EVMStrategyAdapter:
    """Compile and deploy AsymmetricFeeStrategy.sol."""
    src = Path("contracts/src/AsymmetricFeeStrategy.sol").read_text()
    compiler = SolidityCompiler()
    result = compiler.compile(src, contract_name="Strategy")
    assert result.success, f"Compilation failed: {result.errors}"
    return EVMStrategyAdapter(bytecode=result.bytecode, abi=result.abi)


@pytest.fixture(scope="module")
def vanilla_adapter() -> EVMStrategyAdapter:
    """Load the Vanilla 30 bps baseline strategy."""
    return load_vanilla_strategy()


# ---------------------------------------------------------------------------
# Unit tests – verify fee values returned by the hook
# ---------------------------------------------------------------------------

class TestAsymmetricFees:
    """Verify that the hook reports the correct asymmetric fees."""

    def test_name(self, asymmetric_adapter: EVMStrategyAdapter):
        assert asymmetric_adapter.get_name() == "Asymmetric_25_35bps"

    def test_initial_fees(self, asymmetric_adapter: EVMStrategyAdapter):
        fees = asymmetric_adapter.after_initialize(Decimal("100"), Decimal("10000"))
        # 25 bps = 0.0025, 35 bps = 0.0035
        assert fees.bid_fee == Decimal("0.0025")
        assert fees.ask_fee == Decimal("0.0035")

    def test_fees_after_buy_swap(self, asymmetric_adapter: EVMStrategyAdapter):
        """After a buy-side swap the fees should stay 25/35."""
        trade = TradeInfo(
            side="buy",
            amount_x=Decimal("1"),
            amount_y=Decimal("100"),
            timestamp=1,
            reserve_x=Decimal("101"),
            reserve_y=Decimal("9900"),
        )
        fees = asymmetric_adapter.after_swap(trade)
        assert fees.bid_fee == Decimal("0.0025")
        assert fees.ask_fee == Decimal("0.0035")

    def test_fees_after_sell_swap(self, asymmetric_adapter: EVMStrategyAdapter):
        """After a sell-side swap the fees should stay 25/35."""
        trade = TradeInfo(
            side="sell",
            amount_x=Decimal("1"),
            amount_y=Decimal("100"),
            timestamp=2,
            reserve_x=Decimal("99"),
            reserve_y=Decimal("10100"),
        )
        fees = asymmetric_adapter.after_swap(trade)
        assert fees.bid_fee == Decimal("0.0025")
        assert fees.ask_fee == Decimal("0.0035")

    def test_reset_preserves_behaviour(self, asymmetric_adapter: EVMStrategyAdapter):
        """After reset, fees should come back correctly."""
        asymmetric_adapter.reset()
        fees = asymmetric_adapter.after_initialize(Decimal("100"), Decimal("10000"))
        assert fees.bid_fee == Decimal("0.0025")
        assert fees.ask_fee == Decimal("0.0035")


# ---------------------------------------------------------------------------
# Integration tests – run both strategies through a short AMM simulation
# ---------------------------------------------------------------------------

class TestAsymmetricVsVanilla:
    """Run a short simulated session and compare metrics."""

    INIT_X = Decimal("100")
    INIT_Y = Decimal("10000")
    N_STEPS = 200

    @staticmethod
    def _make_amm(strategy: EVMStrategyAdapter) -> AMM:
        amm = AMM(
            strategy=strategy,
            reserve_x=Decimal("100"),
            reserve_y=Decimal("10000"),
        )
        amm.initialize()
        return amm

    def test_asymmetric_amm_initializes(self, asymmetric_adapter: EVMStrategyAdapter):
        asymmetric_adapter.reset()
        amm = self._make_amm(asymmetric_adapter)
        assert amm.reserve_x == self.INIT_X
        assert amm.reserve_y == self.INIT_Y
        assert amm.current_fees.bid_fee == Decimal("0.0025")
        assert amm.current_fees.ask_fee == Decimal("0.0035")

    def test_vanilla_amm_initializes(self, vanilla_adapter: EVMStrategyAdapter):
        vanilla_adapter.reset()
        amm = self._make_amm(vanilla_adapter)
        assert amm.current_fees.bid_fee == Decimal("0.003")
        assert amm.current_fees.ask_fee == Decimal("0.003")

    def test_asymmetric_lower_bid_gives_better_buy_quote(
        self, asymmetric_adapter: EVMStrategyAdapter, vanilla_adapter: EVMStrategyAdapter
    ):
        """With a lower bid fee (25 vs 30 bps), the asymmetric AMM gives a
        better price for buying X (trader sells X), so trader receives more Y."""
        asymmetric_adapter.reset()
        vanilla_adapter.reset()

        amm_asym = self._make_amm(asymmetric_adapter)
        amm_van = self._make_amm(vanilla_adapter)

        # Quote how much Y each AMM outputs for 1 X input (AMM buys X)
        q_asym = amm_asym.get_quote_buy_x(Decimal("1"))
        q_van = amm_van.get_quote_buy_x(Decimal("1"))

        assert q_asym is not None and q_van is not None

        # Lower fee → more Y out for same X in
        assert q_asym.amount_out > q_van.amount_out, (
            f"Asymmetric (25 bps bid) should output more Y: "
            f"{q_asym.amount_out} vs {q_van.amount_out}"
        )

    def test_asymmetric_higher_ask_gives_worse_sell_quote(
        self, asymmetric_adapter: EVMStrategyAdapter, vanilla_adapter: EVMStrategyAdapter
    ):
        """With a higher ask fee (35 vs 30 bps), the asymmetric AMM charges
        more Y to buy X, so it costs the trader more."""
        asymmetric_adapter.reset()
        vanilla_adapter.reset()

        amm_asym = self._make_amm(asymmetric_adapter)
        amm_van = self._make_amm(vanilla_adapter)

        # Quote how much Y each AMM charges for 1 X out (AMM sells X)
        q_asym = amm_asym.get_quote_sell_x(Decimal("1"))
        q_van = amm_van.get_quote_sell_x(Decimal("1"))

        assert q_asym is not None and q_van is not None

        # Higher fee → more Y required for same X out
        assert q_asym.amount_in > q_van.amount_in, (
            f"Asymmetric (35 bps ask) should charge more Y: "
            f"{q_asym.amount_in} vs {q_van.amount_in}"
        )

    def test_multi_swap_session(
        self, asymmetric_adapter: EVMStrategyAdapter, vanilla_adapter: EVMStrategyAdapter
    ):
        """Run alternating buy/sell swaps on both AMMs, print comparison."""
        asymmetric_adapter.reset()
        vanilla_adapter.reset()

        amm_asym = self._make_amm(asymmetric_adapter)
        amm_van = self._make_amm(vanilla_adapter)

        for step in range(self.N_STEPS):
            ts = step + 1
            if step % 2 == 0:
                # Buy X: trader sells 0.5 X to AMM
                amm_asym.execute_buy_x(Decimal("0.5"), timestamp=ts)
                amm_van.execute_buy_x(Decimal("0.5"), timestamp=ts)
            else:
                # Sell X: trader buys 0.5 X from AMM (pays Y)
                amm_asym.execute_sell_x(Decimal("0.5"), timestamp=ts)
                amm_van.execute_sell_x(Decimal("0.5"), timestamp=ts)

        initial_k = self.INIT_X * self.INIT_Y

        for label, amm in [("Asymmetric 25/35", amm_asym), ("Vanilla 30/30", amm_van)]:
            k = amm.reserve_x * amm.reserve_y
            assert k >= initial_k * Decimal("0.999"), f"{label}: k should not decrease"

        # Print comparison
        print(f"\n{'='*60}")
        print(f" AMM Comparison after {self.N_STEPS} alternating swaps")
        print(f"{'='*60}")
        for label, amm in [("Asymmetric 25/35", amm_asym), ("Vanilla 30/30", amm_van)]:
            k = amm.reserve_x * amm.reserve_y
            print(f"\n  {label}:")
            print(f"    Reserves: X={amm.reserve_x:.6f}, Y={amm.reserve_y:.6f}")
            print(f"    Fees collected: X={amm.accumulated_fees_x:.6f}, Y={amm.accumulated_fees_y:.6f}")
            print(f"    k ratio: {k / initial_k:.8f}")
        print()

    def test_directional_fee_advantage(
        self, asymmetric_adapter: EVMStrategyAdapter, vanilla_adapter: EVMStrategyAdapter
    ):
        """Run a buy-heavy session where 25 bps bid fee should collect less
        per trade but potentially attract more volume."""
        asymmetric_adapter.reset()
        vanilla_adapter.reset()

        amm_asym = self._make_amm(asymmetric_adapter)
        amm_van = self._make_amm(vanilla_adapter)

        n_buys, n_sells = 150, 50

        for i in range(n_buys):
            amm_asym.execute_buy_x(Decimal("0.3"), timestamp=i + 1)
            amm_van.execute_buy_x(Decimal("0.3"), timestamp=i + 1)

        for i in range(n_sells):
            ts = n_buys + i + 1
            amm_asym.execute_sell_x(Decimal("0.3"), timestamp=ts)
            amm_van.execute_sell_x(Decimal("0.3"), timestamp=ts)

        print(f"\n{'='*60}")
        print(f" Buy-heavy session: {n_buys} buys + {n_sells} sells")
        print(f"{'='*60}")
        for label, amm in [("Asymmetric 25/35", amm_asym), ("Vanilla 30/30", amm_van)]:
            total_fee_value = (
                amm.accumulated_fees_x * (amm.reserve_y / amm.reserve_x)
                + amm.accumulated_fees_y
            )
            print(f"\n  {label}:")
            print(f"    Reserves: X={amm.reserve_x:.6f}, Y={amm.reserve_y:.6f}")
            print(f"    Fees X={amm.accumulated_fees_x:.6f}, Y={amm.accumulated_fees_y:.6f}")
            print(f"    Total fee value (in Y): {total_fee_value:.6f}")
        print()

        # Both should have collected fees
        assert amm_asym.accumulated_fees_x > 0
        assert amm_van.accumulated_fees_x > 0
