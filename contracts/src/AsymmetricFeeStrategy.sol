// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {IAMMStrategy} from "./IAMMStrategy.sol";
import {IPoolManager} from "v4-core/interfaces/IPoolManager.sol";
import {BalanceDelta} from "v4-core/types/BalanceDelta.sol";

/// @title Asymmetric Fee Strategy (Uniswap v4 Hook)
/// @notice Applies different LP fees by swap direction:
///         25 bps for zeroForOne (bid), 35 bps for oneForZero (ask).
contract Strategy is AMMStrategyBase {
    /// @notice Fee when swapping token0 -> token1 (zeroForOne / bid)
    uint24 public constant BID_FEE = 25 * BPS; // 25 bps = 2500

    /// @notice Fee when swapping token1 -> token0 (oneForZero / ask)
    uint24 public constant ASK_FEE = 35 * BPS; // 35 bps = 3500

    function _onInitialize(uint160, int24) internal pure override returns (uint24, uint24) {
        return (BID_FEE, ASK_FEE);
    }

    function _onSwap(
        IPoolManager.SwapParams calldata,
        BalanceDelta,
        bytes calldata
    ) internal pure override returns (uint24, uint24) {
        return (BID_FEE, ASK_FEE);
    }

    function getName() external pure override returns (string memory) {
        return "Asymmetric_25_35bps";
    }
}
