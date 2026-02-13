// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {IAMMStrategy} from "./IAMMStrategy.sol";
import {IPoolManager} from "v4-core/interfaces/IPoolManager.sol";
import {BalanceDelta} from "v4-core/types/BalanceDelta.sol";

/// @title Starter Strategy - 50 Basis Points (Uniswap v4 Hook)
/// @notice A starting point with fixed 50 bps fees. Copy and modify this file.
contract Strategy is AMMStrategyBase {
    /// @notice Fixed fee: 50 bps = 5000 in v4 fee units
    uint24 public constant FEE = 50 * BPS;

    function _onInitialize(uint160, int24) internal pure override returns (uint24, uint24) {
        return (FEE, FEE);
    }

    function _onSwap(
        IPoolManager.SwapParams calldata,
        BalanceDelta,
        bytes calldata
    ) internal pure override returns (uint24, uint24) {
        return (FEE, FEE);
    }

    function getName() external pure override returns (string memory) {
        return "StarterStrategy";
    }
}
