// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import {VanillaStrategy} from "../src/VanillaStrategy.sol";
import {AMMStrategyBase} from "../src/AMMStrategyBase.sol";
import {IAMMStrategy} from "../src/IAMMStrategy.sol";
import {IPoolManager} from "v4-core/interfaces/IPoolManager.sol";
import {PoolKey} from "v4-core/types/PoolKey.sol";
import {BalanceDelta, toBalanceDelta} from "v4-core/types/BalanceDelta.sol";
import {Currency} from "v4-core/types/Currency.sol";
import {IHooks} from "v4-core/interfaces/IHooks.sol";

contract StrategyTest is Test {
    VanillaStrategy public vanilla;
    PoolKey internal dummyKey;
    address internal sender;

    function setUp() public {
        vanilla = new VanillaStrategy();
        sender = address(this);
        dummyKey = PoolKey({
            currency0: Currency.wrap(address(0)),
            currency1: Currency.wrap(address(1)),
            fee: 0x800000, // DYNAMIC_FEE_FLAG
            tickSpacing: 60,
            hooks: IHooks(address(vanilla))
        });
    }

    function test_VanillaAfterInitialize() public {
        // sqrtPriceX96 for price=100: sqrt(100) * 2^96 = 10 * 2^96
        uint160 sqrtPriceX96 = 792281625142643375935439503360;
        int24 tick = 46054; // approx tick for price 100

        bytes4 selector = vanilla.afterInitialize(sender, dummyKey, sqrtPriceX96, tick);
        assertEq(selector, vanilla.afterInitialize.selector, "Should return afterInitialize selector");

        (uint24 bidFee, uint24 askFee) = vanilla.getFees();
        // 30 bps = 30 * 100 = 3000 in v4 fee units
        assertEq(bidFee, 3000, "Bid fee should be 30 bps (3000)");
        assertEq(askFee, 3000, "Ask fee should be 30 bps (3000)");
    }

    function test_VanillaAfterSwap() public {
        // Initialize first
        vanilla.afterInitialize(sender, dummyKey, 792281625142643375935439503360, 46054);

        IPoolManager.SwapParams memory params = IPoolManager.SwapParams({
            zeroForOne: true,
            amountSpecified: -1e18, // exactIn: 1 token0
            sqrtPriceLimitX96: 0
        });

        BalanceDelta delta = toBalanceDelta(int128(1e18), -int128(100e18));
        bytes memory hookData = abi.encode(uint256(101e18), uint256(9900e18), uint256(1));

        (bytes4 selector, int128 hookDelta) = vanilla.afterSwap(sender, dummyKey, params, delta, hookData);
        assertEq(selector, vanilla.afterSwap.selector, "Should return afterSwap selector");
        assertEq(hookDelta, 0, "Hook delta should be 0");

        (uint24 bidFee, uint24 askFee) = vanilla.getFees();
        assertEq(bidFee, 3000, "Bid fee should be 30 bps (3000)");
        assertEq(askFee, 3000, "Ask fee should be 30 bps (3000)");
    }

    function test_VanillaBeforeSwap() public {
        // Initialize first
        vanilla.afterInitialize(sender, dummyKey, 792281625142643375935439503360, 46054);

        // Test zeroForOne=true (should return bidFee)
        IPoolManager.SwapParams memory params = IPoolManager.SwapParams({
            zeroForOne: true,
            amountSpecified: -1e18,
            sqrtPriceLimitX96: 0
        });

        (bytes4 selector,, uint24 fee) = vanilla.beforeSwap(sender, dummyKey, params, "");
        assertEq(selector, vanilla.beforeSwap.selector, "Should return beforeSwap selector");
        // Fee should be 3000 | 0x800000 (dynamic fee flag)
        assertEq(fee, 3000 | 0x800000, "Fee should include dynamic fee flag");
        assertEq(fee & 0x7FFFFF, 3000, "Base fee should be 3000 (30 bps)");

        // Test zeroForOne=false (should return askFee)
        params.zeroForOne = false;
        (,, fee) = vanilla.beforeSwap(sender, dummyKey, params, "");
        assertEq(fee & 0x7FFFFF, 3000, "Ask fee should be 3000 (30 bps)");
    }

    function test_VanillaGetName() public view {
        string memory name = vanilla.getName();
        assertEq(name, "Vanilla_30bps");
    }

    function test_Constants() public view {
        assertEq(vanilla.MAX_FEE(), 100_000, "MAX_FEE should be 100_000 (10%)");
        assertEq(vanilla.BPS(), 100, "BPS should be 100");
        assertEq(vanilla.WAD(), 1e18, "WAD should be 1e18");
        assertEq(vanilla.DYNAMIC_FEE_FLAG(), 0x800000, "DYNAMIC_FEE_FLAG should be 0x800000");
    }

    function test_SlotsInitializedToZero() public view {
        for (uint256 i = 0; i < 32; i++) {
            assertEq(vanilla.slots(i), 0, "Slots should be initialized to zero");
        }
    }
}

/// @notice Test contract to verify helper functions work correctly
contract HelperFunctionsTest is AMMStrategyBase {
    function _onInitialize(uint160, int24) internal pure override returns (uint24, uint24) {
        return (0, 0);
    }

    function _onSwap(
        IPoolManager.SwapParams calldata,
        BalanceDelta,
        bytes calldata
    ) internal pure override returns (uint24, uint24) {
        return (0, 0);
    }

    function getName() external pure override returns (string memory) {
        return "HelperTest";
    }

    // Expose internal functions for testing
    function exposeWmul(uint256 x, uint256 y) external pure returns (uint256) {
        return wmul(x, y);
    }

    function exposeWdiv(uint256 x, uint256 y) external pure returns (uint256) {
        return wdiv(x, y);
    }

    function exposeClamp(uint256 value, uint256 minVal, uint256 maxVal) external pure returns (uint256) {
        return clamp(value, minVal, maxVal);
    }

    function exposeBpsToFee(uint24 bps) external pure returns (uint24) {
        return bpsToFee(bps);
    }

    function exposeFeeToBps(uint24 fee) external pure returns (uint24) {
        return feeToBps(fee);
    }

    function exposeClampFee(uint24 fee) external pure returns (uint24) {
        return clampFee(fee);
    }

    function exposeAbsDiff(uint256 a, uint256 b) external pure returns (uint256) {
        return absDiff(a, b);
    }

    function exposeSqrt(uint256 x) external pure returns (uint256) {
        return sqrt(x);
    }

    function exposeReadSlot(uint256 index) external view returns (uint256) {
        return readSlot(index);
    }

    function exposeWriteSlot(uint256 index, uint256 value) external {
        writeSlot(index, value);
    }

    function exposeDecodeHookData(bytes calldata hookData)
        external pure returns (uint256, uint256, uint256)
    {
        return decodeHookData(hookData);
    }
}

contract HelperTest is Test {
    HelperFunctionsTest public helper;

    function setUp() public {
        helper = new HelperFunctionsTest();
    }

    function test_Wmul() public view {
        // 2 WAD * 3 WAD = 6 WAD
        uint256 result = helper.exposeWmul(2e18, 3e18);
        assertEq(result, 6e18);

        // 0.5 WAD * 0.5 WAD = 0.25 WAD
        result = helper.exposeWmul(5e17, 5e17);
        assertEq(result, 25e16);
    }

    function test_Wdiv() public view {
        // 6 WAD / 2 WAD = 3 WAD
        uint256 result = helper.exposeWdiv(6e18, 2e18);
        assertEq(result, 3e18);

        // 1 WAD / 4 WAD = 0.25 WAD
        result = helper.exposeWdiv(1e18, 4e18);
        assertEq(result, 25e16);
    }

    function test_Clamp() public view {
        // Value in range
        assertEq(helper.exposeClamp(50, 0, 100), 50);
        // Value below min
        assertEq(helper.exposeClamp(0, 10, 100), 10);
        // Value above max
        assertEq(helper.exposeClamp(150, 0, 100), 100);
    }

    function test_BpsToFee() public view {
        // 25 bps = 25 * 100 = 2500
        assertEq(helper.exposeBpsToFee(25), 2500);
        // 100 bps (1%) = 100 * 100 = 10000
        assertEq(helper.exposeBpsToFee(100), 10000);
    }

    function test_FeeToBps() public view {
        assertEq(helper.exposeFeeToBps(2500), 25);
        assertEq(helper.exposeFeeToBps(10000), 100);
    }

    function test_ClampFee() public view {
        // Valid fee
        assertEq(helper.exposeClampFee(3000), 3000);
        // Above max (100_000 = 10%)
        assertEq(helper.exposeClampFee(200_000), 100_000);
        // Zero is valid
        assertEq(helper.exposeClampFee(0), 0);
    }

    function test_AbsDiff() public view {
        assertEq(helper.exposeAbsDiff(10, 7), 3);
        assertEq(helper.exposeAbsDiff(7, 10), 3);
        assertEq(helper.exposeAbsDiff(5, 5), 0);
    }

    function test_Sqrt() public view {
        assertEq(helper.exposeSqrt(0), 0);
        assertEq(helper.exposeSqrt(1), 1);
        assertEq(helper.exposeSqrt(4), 2);
        assertEq(helper.exposeSqrt(9), 3);
        assertEq(helper.exposeSqrt(100), 10);
        // Non-perfect square rounds down
        assertEq(helper.exposeSqrt(10), 3);
    }

    function test_SlotReadWrite() public {
        // Initial value is zero
        assertEq(helper.exposeReadSlot(0), 0);

        // Write and read back
        helper.exposeWriteSlot(5, 12345);
        assertEq(helper.exposeReadSlot(5), 12345);

        // Write to last slot
        helper.exposeWriteSlot(31, 99999);
        assertEq(helper.exposeReadSlot(31), 99999);
    }

    function test_SlotOutOfBounds() public {
        vm.expectRevert("Slot index out of bounds");
        helper.exposeReadSlot(32);

        vm.expectRevert("Slot index out of bounds");
        helper.exposeWriteSlot(32, 100);
    }

    function test_DecodeHookData() public view {
        bytes memory hookData = abi.encode(uint256(100e18), uint256(10000e18), uint256(42));
        (uint256 reserve0, uint256 reserve1, uint256 timestamp) = helper.exposeDecodeHookData(hookData);
        assertEq(reserve0, 100e18);
        assertEq(reserve1, 10000e18);
        assertEq(timestamp, 42);
    }
}
