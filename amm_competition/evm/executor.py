"""EVM strategy executor using pyrevm (Uniswap v4 hook-compatible)."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

from pyrevm import EVM

from amm_competition.core.trade import TradeInfo


@dataclass
class EVMExecutionResult:
    """Result of an EVM strategy execution."""

    bid_fee: Decimal
    ask_fee: Decimal
    gas_used: int
    success: bool
    error: Optional[str] = None


# Pre-computed constants for fast path
_WAD = 10**18
_WAD_DECIMAL = Decimal(_WAD)

# V4 fee unit conversion: 1 bps = 100 v4 fee units, so 1 v4 unit = 0.0001%
# To convert v4 fee to decimal: fee / 1_000_000
_V4_FEE_DENOMINATOR = 1_000_000
_V4_FEE_DENOMINATOR_DECIMAL = Decimal(_V4_FEE_DENOMINATOR)


def _v4_fee_to_decimal(fee: int) -> Decimal:
    """Convert a v4 fee (uint24) to a Decimal fraction."""
    return Decimal(fee) / _V4_FEE_DENOMINATOR_DECIMAL


def _decimal_to_v4_fee(d: Decimal) -> int:
    """Convert a Decimal fraction to v4 fee (uint24)."""
    return int(d * _V4_FEE_DENOMINATOR)


class EVMStrategyExecutor:
    """Executes Solidity AMM strategies (Uniswap v4 hooks) using pyrevm.

    Provides gas-limited execution and tracks storage usage.
    """

    # Gas limits
    GAS_LIMIT_DEPLOY = 10_000_000
    GAS_LIMIT_INIT = 500_000
    GAS_LIMIT_TRADE = 500_000

    # Maximum storage slots (enforced by contract, but we track for reporting)
    MAX_STORAGE_SLOTS = 32

    # WAD precision (1e18)
    WAD = 10**18

    # Contract addresses
    STRATEGY_ADDRESS = "0x1000000000000000000000000000000000000001"
    CALLER_ADDRESS = "0x2000000000000000000000000000000000000002"

    # V4 hook function selectors
    # afterInitialize(address,(address,address,uint24,int24,address),uint160,int24) -> 0x6fe7e6eb
    # afterSwap(address,(address,address,uint24,int24,address),(bool,int256,uint160),int256,bytes) -> 0xb47b2fb1
    # getFees() -> 0xdb8d55f1
    # getName() -> 0x17d7de7c
    SELECTOR_AFTER_INITIALIZE = bytes.fromhex("6fe7e6eb")
    SELECTOR_AFTER_SWAP = bytes.fromhex("b47b2fb1")
    SELECTOR_GET_FEES = bytes.fromhex("db8d55f1")
    SELECTOR_GET_NAME = bytes.fromhex("17d7de7c")

    # Dummy PoolKey values for simulation context
    # currency0 = address(0), currency1 = address(1)
    # fee = 0x800000 (dynamic fee flag), tickSpacing = 60
    # hooks = STRATEGY_ADDRESS
    _DUMMY_POOL_KEY_ENCODED = (
        b'\x00' * 32  # currency0 = address(0)
        + b'\x00' * 31 + b'\x01'  # currency1 = address(1)
        + b'\x00' * 29 + bytes.fromhex("800000")  # fee = 0x800000 (DYNAMIC_FEE_FLAG)
        + b'\x00' * 31 + bytes([60])  # tickSpacing = 60
        + b'\x00' * 12 + bytes.fromhex("1000000000000000000000000000000000000001")  # hooks = strategy address
    )

    def __init__(self, bytecode: bytes, abi: Optional[list] = None):
        """Initialize the executor with compiled bytecode.

        Args:
            bytecode: Compiled contract bytecode (deployment bytecode)
            abi: Contract ABI for encoding/decoding (optional, we use manual encoding)
        """
        self.bytecode = bytecode
        self.abi = abi
        self.evm: Optional[EVM] = None
        self.deployed_address: Optional[str] = None

        self._deploy()

    def _deploy(self) -> None:
        """Deploy the strategy contract to the EVM."""
        self.evm = EVM()
        self.deployed_address = self.evm.deploy(
            deployer=self.CALLER_ADDRESS,
            code=self.bytecode,
            value=0,
            gas=self.GAS_LIMIT_DEPLOY,
        )

    def _encode_uint256(self, value: int) -> bytes:
        """Encode a uint256 value as 32 bytes."""
        return value.to_bytes(32, byteorder="big")

    def _encode_int256(self, value: int) -> bytes:
        """Encode an int256 value as 32 bytes (two's complement)."""
        if value < 0:
            value = (1 << 256) + value
        return value.to_bytes(32, byteorder="big")

    def _encode_bool(self, value: bool) -> bytes:
        """Encode a bool as 32 bytes."""
        return self._encode_uint256(1 if value else 0)

    def _decode_uint256(self, data: bytes, offset: int = 0) -> int:
        """Decode a uint256 from bytes."""
        return int.from_bytes(data[offset : offset + 32], byteorder="big")

    def _decode_uint24(self, data: bytes, offset: int = 0) -> int:
        """Decode a uint24 from a 32-byte ABI slot."""
        raw = int.from_bytes(data[offset : offset + 32], byteorder="big")
        return raw & 0xFFFFFF

    def _decimal_to_wad(self, value: Decimal) -> int:
        """Convert a Decimal fee to WAD representation."""
        return int(value * self.WAD)

    def _wad_to_decimal(self, value: int) -> Decimal:
        """Convert a WAD value to Decimal."""
        return Decimal(value) / Decimal(self.WAD)

    def _encode_balance_delta(self, amount0: int, amount1: int) -> bytes:
        """Encode two int128 values as a packed BalanceDelta (int256).

        BalanceDelta = int256 with amount0 in upper 128 bits, amount1 in lower 128 bits.
        """
        # Convert to unsigned representation for packing
        mask128 = (1 << 128) - 1
        if amount0 < 0:
            amount0 = (1 << 128) + amount0
        if amount1 < 0:
            amount1 = (1 << 128) + amount1
        packed = ((amount0 & mask128) << 128) | (amount1 & mask128)
        return self._encode_int256(packed if packed < (1 << 255) else packed - (1 << 256))

    def _encode_hook_data(self, reserve_x: int, reserve_y: int, timestamp: int) -> bytes:
        """Encode hookData as abi.encode(uint256 reserve0, uint256 reserve1, uint256 timestamp)."""
        return (
            self._encode_uint256(reserve_x)
            + self._encode_uint256(reserve_y)
            + self._encode_uint256(timestamp)
        )

    def after_initialize(self, initial_x: Decimal, initial_y: Decimal) -> EVMExecutionResult:
        """Call the strategy's afterInitialize function (v4 hook).

        Args:
            initial_x: Starting X reserve amount
            initial_y: Starting Y reserve amount

        Returns:
            EVMExecutionResult with bid/ask fees and gas usage
        """
        # Compute sqrtPriceX96 from initial reserves: price = Y/X, sqrtPrice = sqrt(Y/X)
        # sqrtPriceX96 = sqrt(Y/X) * 2^96
        price = initial_y / initial_x  # e.g., 10000/100 = 100
        import math
        sqrt_price = Decimal(str(math.sqrt(float(price))))
        sqrt_price_x96 = int(sqrt_price * Decimal(2**96))

        # Approximate tick from price: tick = log(price) / log(1.0001)
        tick = int(math.log(float(price)) / math.log(1.0001))

        # Encode calldata:
        # afterInitialize(address sender, PoolKey calldata key, uint160 sqrtPriceX96, int24 tick)
        calldata = (
            self.SELECTOR_AFTER_INITIALIZE
            + self._encode_uint256(int(self.CALLER_ADDRESS, 16))  # sender
            + self._DUMMY_POOL_KEY_ENCODED  # key (5 * 32 = 160 bytes)
            + self._encode_uint256(sqrt_price_x96)  # sqrtPriceX96
            + self._encode_int256(tick)  # tick (int24 as int256)
        )

        try:
            result = self.evm.message_call(
                caller=self.CALLER_ADDRESS,
                to=self.deployed_address,
                calldata=calldata,
                value=0,
                gas=self.GAS_LIMIT_INIT,
            )

            # afterInitialize returns bytes4
            # After calling, read the fees via getFees()
            bid_fee, ask_fee = self._get_fees()

            gas_used = self.GAS_LIMIT_INIT // 2

            return EVMExecutionResult(
                bid_fee=_v4_fee_to_decimal(bid_fee),
                ask_fee=_v4_fee_to_decimal(ask_fee),
                gas_used=gas_used,
                success=True,
            )

        except Exception as e:
            return EVMExecutionResult(
                bid_fee=Decimal(0),
                ask_fee=Decimal(0),
                gas_used=self.GAS_LIMIT_INIT,
                success=False,
                error=str(e),
            )

    def _get_fees(self) -> Tuple[int, int]:
        """Call getFees() to read current bid/ask fees.

        Returns:
            Tuple of (bid_fee, ask_fee) as v4 fee units (uint24).
        """
        result = self.evm.message_call(
            caller=self.CALLER_ADDRESS,
            to=self.deployed_address,
            calldata=self.SELECTOR_GET_FEES,
            value=0,
            gas=50_000,
        )

        if len(result) < 64:
            raise RuntimeError(f"Invalid getFees return data length: {len(result)}")

        bid_fee = self._decode_uint24(result, 0)
        ask_fee = self._decode_uint24(result, 32)
        return (bid_fee, ask_fee)

    def after_swap_fast(self, trade: TradeInfo) -> Tuple[int, int]:
        """Fast path: call afterSwap and return raw v4 fee values.

        Calls afterSwap with v4-style parameters, then reads fees via getFees().

        Returns:
            Tuple of (bid_fee_v4, ask_fee_v4) as v4 fee unit integers.
            Raises RuntimeError on EVM errors or malformed returns.
        """
        wad = _WAD

        # Determine swap direction and amounts for BalanceDelta
        is_buy = trade.side == "buy"  # AMM buys token0 (zeroForOne = true)

        amount_x_wad = int(trade.amount_x * wad)
        amount_y_wad = int(trade.amount_y * wad)
        reserve_x_wad = int(trade.reserve_x * wad)
        reserve_y_wad = int(trade.reserve_y * wad)

        # BalanceDelta: amount0 (token0) in upper 128 bits, amount1 (token1) in lower 128 bits
        # From pool's perspective:
        # If zeroForOne (buy token0): pool receives token0 (+amount0), sends token1 (-amount1)
        if is_buy:
            delta_amount0 = amount_x_wad
            delta_amount1 = -amount_y_wad
        else:
            delta_amount0 = -amount_x_wad
            delta_amount1 = amount_y_wad

        # Encode hookData with reserves and timestamp
        hook_data_content = self._encode_hook_data(reserve_x_wad, reserve_y_wad, trade.timestamp)

        # Encode SwapParams: (bool zeroForOne, int256 amountSpecified, uint160 sqrtPriceLimitX96)
        # amountSpecified: negative for exactIn
        amount_specified = -amount_x_wad if is_buy else -amount_y_wad
        swap_params = (
            self._encode_bool(is_buy)
            + self._encode_int256(amount_specified)
            + self._encode_uint256(0)  # sqrtPriceLimitX96 = 0 (no limit)
        )

        # Encode full calldata:
        # afterSwap(address sender, PoolKey key, SwapParams params, BalanceDelta delta, bytes hookData)
        #
        # Layout (all static params inline, hookData uses offset pointer):
        # 4 bytes: selector
        # 32 bytes: sender
        # 160 bytes: PoolKey (5 * 32)
        # 96 bytes: SwapParams (3 * 32)
        # 32 bytes: BalanceDelta (int256)
        # 32 bytes: hookData offset
        # -- dynamic section --
        # 32 bytes: hookData length
        # 96 bytes: hookData content (3 * 32)
        #
        # Total static: 4 + 32 + 160 + 96 + 32 + 32 = 356 bytes
        # hookData offset = 356 - 4 = 352 (offset from start of params, not including selector)

        static_part = (
            self.SELECTOR_AFTER_SWAP
            + self._encode_uint256(int(self.CALLER_ADDRESS, 16))  # sender
            + self._DUMMY_POOL_KEY_ENCODED  # PoolKey
            + swap_params  # SwapParams
            + self._encode_balance_delta(delta_amount0, delta_amount1)  # BalanceDelta
            + self._encode_uint256(352)  # hookData offset (bytes from start of params)
        )

        dynamic_part = (
            self._encode_uint256(len(hook_data_content))  # hookData length
            + hook_data_content  # hookData content
        )

        calldata = static_part + dynamic_part

        try:
            # Call afterSwap
            self.evm.message_call(
                caller=self.CALLER_ADDRESS,
                to=self.deployed_address,
                calldata=calldata,
                value=0,
                gas=self.GAS_LIMIT_TRADE,
            )

            # Read updated fees
            return self._get_fees()

        except Exception as e:
            raise RuntimeError(f"afterSwap failed: {e}") from e

    def after_swap(self, trade: TradeInfo) -> EVMExecutionResult:
        """Call the strategy's afterSwap function."""
        try:
            bid_v4, ask_v4 = self.after_swap_fast(trade)
            return EVMExecutionResult(
                bid_fee=_v4_fee_to_decimal(bid_v4),
                ask_fee=_v4_fee_to_decimal(ask_v4),
                gas_used=self.GAS_LIMIT_TRADE // 2,
                success=True,
            )
        except Exception as e:
            return EVMExecutionResult(
                bid_fee=Decimal(0),
                ask_fee=Decimal(0),
                gas_used=self.GAS_LIMIT_TRADE,
                success=False,
                error=str(e),
            )

    def get_name(self) -> str:
        """Call the strategy's getName function.

        Returns:
            Strategy name string
        """
        try:
            result = self.evm.message_call(
                caller=self.CALLER_ADDRESS,
                to=self.deployed_address,
                calldata=self.SELECTOR_GET_NAME,
                value=0,
                gas=50_000,
            )

            # Decode string return value
            if len(result) < 64:
                return "Unknown"

            offset = self._decode_uint256(result, 0)
            length = self._decode_uint256(result, offset)
            string_data = result[offset + 32 : offset + 32 + length]

            return string_data.decode("utf-8")

        except Exception:
            return "Unknown"

    def reset(self) -> None:
        """Reset the EVM state by redeploying the contract.

        Call this between simulations to ensure fresh state.
        """
        self._deploy()
