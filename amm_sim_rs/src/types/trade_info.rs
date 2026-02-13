//! TradeInfo struct and ABI encoding for EVM calls (Uniswap v4 hook-compatible).

use crate::types::wad::Wad;

/// V4 fee unit conversion: 1_000_000 = 100%
pub const V4_FEE_DENOMINATOR: i128 = 1_000_000;

/// Maximum v4 fee (10% = 100_000)
pub const MAX_V4_FEE: u32 = 100_000;

/// Information about an executed trade, passed to EVM strategies.
#[derive(Debug, Clone, Copy)]
pub struct TradeInfo {
    /// true if AMM bought X (trader sold X) - maps to zeroForOne
    pub is_buy: bool,
    /// Amount of X traded (WAD precision)
    pub amount_x: Wad,
    /// Amount of Y traded (WAD precision)
    pub amount_y: Wad,
    /// Simulation step number
    pub timestamp: u64,
    /// Post-trade X reserves (WAD precision)
    pub reserve_x: Wad,
    /// Post-trade Y reserves (WAD precision)
    pub reserve_y: Wad,
}

impl TradeInfo {
    /// Create a new TradeInfo.
    pub fn new(
        is_buy: bool,
        amount_x: Wad,
        amount_y: Wad,
        timestamp: u64,
        reserve_x: Wad,
        reserve_y: Wad,
    ) -> Self {
        Self {
            is_buy,
            amount_x,
            amount_y,
            timestamp,
            reserve_x,
            reserve_y,
        }
    }

    /// Encode as ABI calldata for v4 afterSwap hook.
    ///
    /// afterSwap(address sender, PoolKey key, SwapParams params, BalanceDelta delta, bytes hookData)
    ///
    /// Layout (484 bytes total):
    /// - bytes 0-3: function selector (0xb47b2fb1)
    /// - bytes 4-35: sender (address)
    /// - bytes 36-195: PoolKey (5 * 32 = 160 bytes)
    ///   - currency0 (address), currency1 (address), fee (uint24), tickSpacing (int24), hooks (address)
    /// - bytes 196-291: SwapParams (3 * 32 = 96 bytes)
    ///   - zeroForOne (bool), amountSpecified (int256), sqrtPriceLimitX96 (uint160)
    /// - bytes 292-323: BalanceDelta (int256, packed amount0|amount1)
    /// - bytes 324-355: hookData offset (uint256, points to dynamic section)
    /// - bytes 356-387: hookData length (uint256)
    /// - bytes 388-483: hookData content (3 * 32 = 96 bytes: reserve0, reserve1, timestamp)
    #[inline]
    pub fn encode_calldata(&self, buffer: &mut [u8; 484]) {
        // Function selector for afterSwap
        buffer[0..4].copy_from_slice(&SELECTOR_AFTER_SWAP);

        // sender (CALLER_ADDRESS = 0x200...002)
        buffer[4..36].fill(0);
        buffer[23] = 0x20;
        buffer[35] = 0x02;

        // PoolKey (160 bytes at offset 36-195)
        // currency0 = address(0)
        buffer[36..68].fill(0);
        // currency1 = address(1)
        buffer[68..100].fill(0);
        buffer[99] = 1;
        // fee = 0x800000 (DYNAMIC_FEE_FLAG)
        buffer[100..132].fill(0);
        buffer[129] = 0x80;
        buffer[130] = 0x00;
        buffer[131] = 0x00;
        // tickSpacing = 60
        buffer[132..164].fill(0);
        buffer[163] = 60;
        // hooks = STRATEGY_ADDRESS (0x100...001)
        buffer[164..196].fill(0);
        buffer[183] = 0x10;
        buffer[195] = 0x01;

        // SwapParams (96 bytes at offset 196-291)
        // zeroForOne = is_buy
        buffer[196..228].fill(0);
        if self.is_buy {
            buffer[227] = 1;
        }

        // amountSpecified (int256): negative for exactIn
        let amount_specified = if self.is_buy {
            -(self.amount_x.raw())
        } else {
            -(self.amount_y.raw())
        };
        Self::encode_i256(&mut buffer[228..260], amount_specified);

        // sqrtPriceLimitX96 = 0
        buffer[260..292].fill(0);

        // BalanceDelta (int256 at offset 292-323)
        // Pack amount0 (upper 128 bits) and amount1 (lower 128 bits)
        let (delta_amount0, delta_amount1) = if self.is_buy {
            (self.amount_x.raw(), -self.amount_y.raw())
        } else {
            (-self.amount_x.raw(), self.amount_y.raw())
        };
        Self::encode_balance_delta(&mut buffer[292..324], delta_amount0, delta_amount1);

        // hookData offset = 352 (bytes from start of params, not including selector)
        // 352 = 32 + 160 + 96 + 32 + 32 (sender + PoolKey + SwapParams + BalanceDelta + offset_itself)
        buffer[324..356].fill(0);
        buffer[354] = 0x01;  // 256
        buffer[355] = 0x60;  // + 96 = 352
        
        // hookData length = 96 (3 * 32 bytes)
        buffer[356..388].fill(0);
        buffer[387] = 96;

        // hookData content: reserve0, reserve1, timestamp
        Self::encode_u256(&mut buffer[388..420], self.reserve_x.raw() as u128);
        Self::encode_u256(&mut buffer[420..452], self.reserve_y.raw() as u128);
        Self::encode_u256(&mut buffer[452..484], self.timestamp as u128);
    }

    /// Encode a u128 as big-endian 32 bytes.
    #[inline]
    fn encode_u256(buffer: &mut [u8], value: u128) {
        buffer.fill(0);
        let bytes = value.to_be_bytes();
        buffer[16..32].copy_from_slice(&bytes);
    }

    /// Encode an i128 as big-endian 32 bytes (two's complement for int256).
    #[inline]
    fn encode_i256(buffer: &mut [u8], value: i128) {
        if value >= 0 {
            buffer[0..16].fill(0);
            let bytes = (value as u128).to_be_bytes();
            buffer[16..32].copy_from_slice(&bytes);
        } else {
            buffer[0..16].fill(0xFF);
            // For negative, use two's complement representation
            let unsigned = value as u128; // wraps to two's complement
            let bytes = unsigned.to_be_bytes();
            buffer[16..32].copy_from_slice(&bytes);
        }
    }

    /// Encode BalanceDelta: pack two int128 values into int256.
    /// Upper 128 bits = amount0, lower 128 bits = amount1.
    #[inline]
    fn encode_balance_delta(buffer: &mut [u8], amount0: i128, amount1: i128) {
        let a0_bytes = (amount0 as u128).to_be_bytes();
        let a1_bytes = (amount1 as u128).to_be_bytes();
        buffer[0..16].copy_from_slice(&a0_bytes);
        buffer[16..32].copy_from_slice(&a1_bytes);
    }
}

/// Function selector for afterInitialize(address,(address,address,uint24,int24,address),uint160,int24)
pub const SELECTOR_AFTER_INITIALIZE: [u8; 4] = [0x6f, 0xe7, 0xe6, 0xeb];

/// Function selector for afterSwap(address,(address,address,uint24,int24,address),(bool,int256,uint160),int256,bytes)
pub const SELECTOR_AFTER_SWAP: [u8; 4] = [0xb4, 0x7b, 0x2f, 0xb1];

/// Function selector for getFees()
pub const SELECTOR_GET_FEES: [u8; 4] = [0xdb, 0x8d, 0x55, 0xf1];

/// Function selector for getName()
pub const SELECTOR_GET_NAME: [u8; 4] = [0x17, 0xd7, 0xde, 0x7c];

/// Encode afterInitialize calldata for v4 hook.
///
/// afterInitialize(address sender, PoolKey key, uint160 sqrtPriceX96, int24 tick)
///
/// Total: 4 + 32 + 160 + 32 + 32 = 260 bytes
#[inline]
pub fn encode_after_initialize(initial_x: Wad, initial_y: Wad) -> Vec<u8> {
    let mut buffer = vec![0u8; 260];
    buffer[0..4].copy_from_slice(&SELECTOR_AFTER_INITIALIZE);

    // sender (CALLER_ADDRESS = 0x200...002)
    buffer[23] = 0x20;
    buffer[35] = 0x02;

    // PoolKey (160 bytes at offset 36-195)
    // currency0 = address(0)  - already zeroed
    // currency1 = address(1)
    buffer[99] = 1;
    // fee = 0x800000 (DYNAMIC_FEE_FLAG)
    buffer[129] = 0x80;
    // tickSpacing = 60
    buffer[163] = 60;
    // hooks = STRATEGY_ADDRESS (0x100...001)
    buffer[183] = 0x10;
    buffer[195] = 0x01;

    // Compute sqrtPriceX96 from reserves
    // price = Y/X, sqrtPriceX96 = sqrt(Y/X) * 2^96
    let price = initial_y.to_f64() / initial_x.to_f64();
    let sqrt_price = price.sqrt();
    let sqrt_price_x96 = (sqrt_price * (2.0_f64.powi(96))) as u128;

    // sqrtPriceX96 at offset 196-227
    let bytes = sqrt_price_x96.to_be_bytes();
    buffer[212..228].copy_from_slice(&bytes);

    // tick = log(price) / log(1.0001)
    let tick = (price.ln() / 1.0001_f64.ln()) as i32;
    // Encode int24 as int256 (sign-extended)
    if tick >= 0 {
        let bytes = (tick as u32).to_be_bytes();
        buffer[256..260].copy_from_slice(&bytes);
    } else {
        buffer[228..256].fill(0xFF);
        let unsigned = tick as u32; // two's complement
        let bytes = unsigned.to_be_bytes();
        buffer[256..260].copy_from_slice(&bytes);
    }

    buffer
}

/// Decode (uint24, uint24) return value from getFees() as (bid_fee, ask_fee) in WAD.
///
/// V4 fees are uint24 where 1_000_000 = 100%. Convert to WAD: fee * WAD / 1_000_000
#[inline]
pub fn decode_fee_pair(data: &[u8]) -> Option<(Wad, Wad)> {
    if data.len() < 64 {
        return None;
    }

    let bid_v4 = decode_uint24(&data[0..32])?;
    let ask_v4 = decode_uint24(&data[32..64])?;

    if bid_v4 > MAX_V4_FEE || ask_v4 > MAX_V4_FEE {
        return None;
    }

    // Convert v4 fee to WAD: (fee / 1_000_000) * 1e18 = fee * 1e12
    let wad_per_unit: i128 = 1_000_000_000_000; // 1e12
    let bid_wad = (bid_v4 as i128) * wad_per_unit;
    let ask_wad = (ask_v4 as i128) * wad_per_unit;

    Some((Wad::new(bid_wad), Wad::new(ask_wad)))
}

/// Decode a uint24 from a 32-byte ABI slot.
#[inline]
fn decode_uint24(data: &[u8]) -> Option<u32> {
    if data.len() != 32 {
        return None;
    }
    // Check upper 29 bytes are zero
    if data[0..29].iter().any(|&b| b != 0) {
        return None;
    }
    let value = ((data[29] as u32) << 16) | ((data[30] as u32) << 8) | (data[31] as u32);
    Some(value)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::wad::WAD;

    #[test]
    fn test_encode_trade_info() {
        let trade = TradeInfo {
            is_buy: true,
            amount_x: Wad::new(WAD), // 1.0
            amount_y: Wad::new(WAD * 2), // 2.0
            timestamp: 100,
            reserve_x: Wad::new(WAD * 1000),
            reserve_y: Wad::new(WAD * 1000),
        };

        let mut buffer = [0u8; 484];
        trade.encode_calldata(&mut buffer);

        // Check selector
        assert_eq!(&buffer[0..4], &SELECTOR_AFTER_SWAP);

        // Check sender address has correct value
        assert_eq!(buffer[23], 0x20);
        assert_eq!(buffer[35], 0x02);

        // Check zeroForOne = true (in SwapParams at offset 196)
        assert_eq!(buffer[227], 1);
    }

    #[test]
    fn test_encode_after_initialize() {
        let calldata = encode_after_initialize(
            Wad::new(WAD * 100),
            Wad::new(WAD * 10000),
        );

        assert_eq!(&calldata[0..4], &SELECTOR_AFTER_INITIALIZE);
        assert_eq!(calldata.len(), 260);
    }

    #[test]
    fn test_decode_fee_pair_v4() {
        let mut data = [0u8; 64];

        // Set bid_fee = 3000 (30 bps) in last 3 bytes of first 32-byte slot
        data[29] = 0;
        data[30] = (3000 >> 8) as u8;   // 0x0B
        data[31] = (3000 & 0xFF) as u8; // 0xB8

        // Set ask_fee = 3000 (30 bps) in last 3 bytes of second 32-byte slot
        data[61] = 0;
        data[62] = (3000 >> 8) as u8;
        data[63] = (3000 & 0xFF) as u8;

        let result = decode_fee_pair(&data);
        assert!(result.is_some());

        let (bid, ask) = result.unwrap();
        // 3000 v4 units = 30 bps = 0.003 = 3e15 WAD
        assert_eq!(bid.raw(), 3_000_000_000_000_000);
        assert_eq!(ask.raw(), 3_000_000_000_000_000);
    }

    #[test]
    fn test_decode_fee_pair_rejects_out_of_range_fee() {
        let mut data = [0u8; 64];

        // Set bid_fee = MAX_V4_FEE + 1 = 100_001
        let bad = MAX_V4_FEE + 1;
        data[29] = ((bad >> 16) & 0xFF) as u8;
        data[30] = ((bad >> 8) & 0xFF) as u8;
        data[31] = (bad & 0xFF) as u8;

        // Set ask_fee = 3000
        data[62] = (3000 >> 8) as u8;
        data[63] = (3000 & 0xFF) as u8;

        assert!(decode_fee_pair(&data).is_none());
    }
}
