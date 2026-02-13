// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IAMMStrategy} from "./IAMMStrategy.sol";
import {IPoolManager} from "v4-core/interfaces/IPoolManager.sol";
import {PoolKey} from "v4-core/types/PoolKey.sol";
import {BalanceDelta, BalanceDeltaLibrary} from "v4-core/types/BalanceDelta.sol";
import {BeforeSwapDelta, BeforeSwapDeltaLibrary} from "v4-core/types/BeforeSwapDelta.sol";

/// @title AMM Strategy Base Contract (Uniswap v4 Hook-Compatible)
/// @notice Base contract that all user strategies must inherit from.
/// @dev Provides v4 hook interface implementation, fixed storage slots,
///      helper functions, and fee clamping. Strategies override _onInitialize()
///      and _onSwap() to implement their fee logic.
abstract contract AMMStrategyBase is IAMMStrategy {
    /*//////////////////////////////////////////////////////////////
                               CONSTANTS
    //////////////////////////////////////////////////////////////*/

    /// @notice Maximum allowed fee in v4 units: 10% = 100_000
    uint24 public constant MAX_FEE = 100_000;

    /// @notice Minimum allowed fee: 0
    uint24 public constant MIN_FEE = 0;

    /// @notice 1 basis point in v4 fee units (0.01% = 100 units)
    uint24 public constant BPS = 100;

    /// @notice Dynamic fee flag used in v4 PoolKey.fee (0x800000)
    uint24 public constant DYNAMIC_FEE_FLAG = 0x800000;

    /// @notice 1e18 - represents 100% in WAD precision (for helper math)
    uint256 public constant WAD = 1e18;

    /*//////////////////////////////////////////////////////////////
                            STORAGE SLOTS
    //////////////////////////////////////////////////////////////*/

    /// @notice Fixed storage array - strategies can only use these 32 slots
    /// @dev This provides 1KB of persistent storage per strategy
    uint256[32] public slots;

    /// @notice Current bid fee (stored in v4 fee units)
    uint24 internal _bidFee;

    /// @notice Current ask fee (stored in v4 fee units)
    uint24 internal _askFee;

    /*//////////////////////////////////////////////////////////////
                          V4 HOOK CALLBACKS
    //////////////////////////////////////////////////////////////*/

    /// @inheritdoc IAMMStrategy
    function getFees() external view override returns (uint24 bidFee, uint24 askFee) {
        return (_bidFee, _askFee);
    }

    /// @notice Called after pool initialization. Sets initial fees via _onInitialize().
    function afterInitialize(
        address,
        PoolKey calldata,
        uint160 sqrtPriceX96,
        int24 tick
    ) external override returns (bytes4) {
        (uint24 bidFee, uint24 askFee) = _onInitialize(sqrtPriceX96, tick);
        _bidFee = clampFee(bidFee);
        _askFee = clampFee(askFee);
        return this.afterInitialize.selector;
    }

    /// @notice Called after each swap. Updates fees via _onSwap().
    function afterSwap(
        address,
        PoolKey calldata,
        IPoolManager.SwapParams calldata params,
        BalanceDelta delta,
        bytes calldata hookData
    ) external override returns (bytes4, int128) {
        (uint24 bidFee, uint24 askFee) = _onSwap(params, delta, hookData);
        _bidFee = clampFee(bidFee);
        _askFee = clampFee(askFee);
        return (this.afterSwap.selector, 0);
    }

    /// @notice beforeSwap returns the current fee for the swap direction.
    function beforeSwap(
        address,
        PoolKey calldata,
        IPoolManager.SwapParams calldata params,
        bytes calldata
    ) external view override returns (bytes4, BeforeSwapDelta, uint24) {
        // zeroForOne = true means swapping token0→token1 (AMM buys token0) → use bidFee
        // zeroForOne = false means swapping token1→token0 (AMM sells token0) → use askFee
        uint24 fee = params.zeroForOne ? _bidFee : _askFee;
        // Set the override flag (bit 23) so v4 uses this fee
        fee = fee | DYNAMIC_FEE_FLAG;
        return (this.beforeSwap.selector, BeforeSwapDeltaLibrary.ZERO_DELTA, fee);
    }

    // --- No-op implementations for unused v4 hooks ---

    function beforeInitialize(address, PoolKey calldata, uint160)
        external pure override returns (bytes4) {
        return this.beforeInitialize.selector;
    }

    function beforeAddLiquidity(
        address, PoolKey calldata, IPoolManager.ModifyLiquidityParams calldata, bytes calldata
    ) external pure override returns (bytes4) {
        return this.beforeAddLiquidity.selector;
    }

    function afterAddLiquidity(
        address, PoolKey calldata, IPoolManager.ModifyLiquidityParams calldata,
        BalanceDelta, BalanceDelta, bytes calldata
    ) external pure override returns (bytes4, BalanceDelta) {
        return (this.afterAddLiquidity.selector, BalanceDeltaLibrary.ZERO_DELTA);
    }

    function beforeRemoveLiquidity(
        address, PoolKey calldata, IPoolManager.ModifyLiquidityParams calldata, bytes calldata
    ) external pure override returns (bytes4) {
        return this.beforeRemoveLiquidity.selector;
    }

    function afterRemoveLiquidity(
        address, PoolKey calldata, IPoolManager.ModifyLiquidityParams calldata,
        BalanceDelta, BalanceDelta, bytes calldata
    ) external pure override returns (bytes4, BalanceDelta) {
        return (this.afterRemoveLiquidity.selector, BalanceDeltaLibrary.ZERO_DELTA);
    }

    function beforeDonate(address, PoolKey calldata, uint256, uint256, bytes calldata)
        external pure override returns (bytes4) {
        return this.beforeDonate.selector;
    }

    function afterDonate(address, PoolKey calldata, uint256, uint256, bytes calldata)
        external pure override returns (bytes4) {
        return this.afterDonate.selector;
    }

    /*//////////////////////////////////////////////////////////////
                      STRATEGY CALLBACKS (OVERRIDE THESE)
    //////////////////////////////////////////////////////////////*/

    /// @notice Override to set initial fees when pool is initialized.
    /// @param sqrtPriceX96 The initial sqrt price (Q64.96 format)
    /// @param tick The initial tick
    /// @return bidFee Initial fee for token0→token1 swaps (v4 units, e.g., 3000 = 30 bps)
    /// @return askFee Initial fee for token1→token0 swaps (v4 units, e.g., 3000 = 30 bps)
    function _onInitialize(uint160 sqrtPriceX96, int24 tick)
        internal virtual returns (uint24 bidFee, uint24 askFee);

    /// @notice Override to update fees after each swap.
    /// @param params The swap parameters (zeroForOne, amountSpecified, sqrtPriceLimitX96)
    /// @param delta The balance delta from the swap (amount0 and amount1 changes)
    /// @param hookData Encoded extra context (reserves, timestamp, etc.)
    /// @return bidFee Updated fee for token0→token1 swaps (v4 units)
    /// @return askFee Updated fee for token1→token0 swaps (v4 units)
    function _onSwap(
        IPoolManager.SwapParams calldata params,
        BalanceDelta delta,
        bytes calldata hookData
    ) internal virtual returns (uint24 bidFee, uint24 askFee);

    /*//////////////////////////////////////////////////////////////
                            HELPER FUNCTIONS
    //////////////////////////////////////////////////////////////*/

    /// @notice Multiply two WAD values
    function wmul(uint256 x, uint256 y) internal pure returns (uint256) {
        return (x * y) / WAD;
    }

    /// @notice Divide two WAD values
    function wdiv(uint256 x, uint256 y) internal pure returns (uint256) {
        return (x * WAD) / y;
    }

    /// @notice Clamp a value between min and max
    function clamp(uint256 value, uint256 minVal, uint256 maxVal) internal pure returns (uint256) {
        if (value < minVal) return minVal;
        if (value > maxVal) return maxVal;
        return value;
    }

    /// @notice Convert basis points to v4 fee units (1 bps = 100 v4 units)
    function bpsToFee(uint24 bps) internal pure returns (uint24) {
        return bps * BPS;
    }

    /// @notice Convert v4 fee units to basis points
    function feeToBps(uint24 fee) internal pure returns (uint24) {
        return fee / BPS;
    }

    /// @notice Clamp fee to valid range [0, MAX_FEE]
    function clampFee(uint24 fee) internal pure returns (uint24) {
        if (fee > MAX_FEE) return MAX_FEE;
        return fee;
    }

    /// @notice Calculate absolute difference between two values
    function absDiff(uint256 a, uint256 b) internal pure returns (uint256) {
        return a > b ? a - b : b - a;
    }

    /// @notice Simple integer square root (Babylonian method)
    function sqrt(uint256 x) internal pure returns (uint256 y) {
        if (x == 0) return 0;
        uint256 z = (x + 1) / 2;
        y = x;
        while (z < y) {
            y = z;
            z = (x / z + z) / 2;
        }
    }

    /*//////////////////////////////////////////////////////////////
                          SLOT HELPERS
    //////////////////////////////////////////////////////////////*/

    /// @notice Read a slot value
    function readSlot(uint256 index) internal view returns (uint256) {
        require(index < 32, "Slot index out of bounds");
        return slots[index];
    }

    /// @notice Write a value to a slot
    function writeSlot(uint256 index, uint256 value) internal {
        require(index < 32, "Slot index out of bounds");
        slots[index] = value;
    }

    /*//////////////////////////////////////////////////////////////
                       HOOKDATA DECODING HELPERS
    //////////////////////////////////////////////////////////////*/

    /// @notice Decode hookData containing reserve and timestamp info.
    /// @dev Expected encoding: abi.encode(uint256 reserve0, uint256 reserve1, uint256 timestamp)
    function decodeHookData(bytes calldata hookData)
        internal pure returns (uint256 reserve0, uint256 reserve1, uint256 timestamp)
    {
        (reserve0, reserve1, timestamp) = abi.decode(hookData, (uint256, uint256, uint256));
    }
}
