// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {IAMMStrategy} from "./IAMMStrategy.sol";
import {IPoolManager} from "v4-core/interfaces/IPoolManager.sol";
import {BalanceDelta} from "v4-core/types/BalanceDelta.sol";

/// @title Vanilla AMM Strategy (Uniswap v4 Hook)
/// @notice Default strategy with fixed 30 basis point fees.
/// @dev This runs as the second AMM in simulations to normalize scoring.
contract VanillaStrategy is AMMStrategyBase {
    /// @notice Fixed fee: 30 bps = 3000 in v4 fee units
    uint24 public constant FEE = 30 * BPS;

    /// @inheritdoc AMMStrategyBase
    function _onInitialize(uint160, int24) internal pure override returns (uint24, uint24) {
        return (FEE, FEE);
    }

    /// @inheritdoc AMMStrategyBase
    function _onSwap(
        IPoolManager.SwapParams calldata,
        BalanceDelta,
        bytes calldata
    ) internal pure override returns (uint24, uint24) {
        return (FEE, FEE);
    }

    /// @inheritdoc IAMMStrategy
    function getName() external pure override returns (string memory) {
        return "Vanilla_30bps";
    }
}
