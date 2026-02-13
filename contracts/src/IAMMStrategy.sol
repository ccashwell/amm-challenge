// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IHooks} from "v4-core/interfaces/IHooks.sol";
import {IPoolManager} from "v4-core/interfaces/IPoolManager.sol";
import {PoolKey} from "v4-core/types/PoolKey.sol";
import {BalanceDelta} from "v4-core/types/BalanceDelta.sol";
import {BeforeSwapDelta} from "v4-core/types/BeforeSwapDelta.sol";

/// @title AMM Strategy Interface (Uniswap v4 Hook-Compatible)
/// @notice Interface that all AMM fee strategies must implement.
/// @dev Strategies act as Uniswap v4 hooks with dynamic fee capabilities.
///      Fees are returned as uint24 values in v4 format:
///      1 unit = 0.0001% (1/100th of a basis point), so 3000 = 30 bps = 0.30%.
///      The DYNAMIC_FEE_FLAG (0x800000) is set automatically by the base contract.
///      Maximum fee is 1_000_000 (100%).
interface IAMMStrategy is IHooks {
    /// @notice Get the strategy name for display
    /// @return Strategy name string
    function getName() external view returns (string memory);

    /// @notice Get the current bid and ask fees
    /// @return bidFee Fee when pool receives token0 (v4 fee units, e.g., 3000 = 30 bps)
    /// @return askFee Fee when pool sends token0 (v4 fee units, e.g., 3000 = 30 bps)
    function getFees() external view returns (uint24 bidFee, uint24 askFee);
}
