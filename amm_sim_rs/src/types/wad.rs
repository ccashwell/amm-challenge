//! WAD fixed-point arithmetic (18 decimal places).
//!
//! WAD is the standard fixed-point representation used in DeFi:
//! - 1 WAD = 1e18
//! - Fees: 30 bps = 0.003 = 30e14 WAD
//! - Max fee: 10% = 0.1 = 1e17 WAD

use std::ops::{Add, Sub, Mul, Div, Neg};

/// WAD precision constant (1e18)
pub const WAD: i128 = 1_000_000_000_000_000_000;

/// One basis point in WAD (0.0001 = 1e14)
pub const BPS: i128 = 100_000_000_000_000;

/// Maximum fee in WAD (10% = 1e17)
pub const MAX_FEE: i128 = 100_000_000_000_000_000;

/// WAD fixed-point number with 18 decimal places.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Default)]
pub struct Wad(pub i128);

impl Wad {
    /// Create a new WAD from raw i128 value.
    #[inline]
    pub const fn new(value: i128) -> Self {
        Wad(value)
    }

    /// Create a WAD from a floating point number.
    #[inline]
    pub fn from_f64(value: f64) -> Self {
        Wad((value * WAD as f64) as i128)
    }

    /// Convert WAD to floating point.
    #[inline]
    pub fn to_f64(self) -> f64 {
        self.0 as f64 / WAD as f64
    }

    /// Create a WAD representing a number of basis points.
    #[inline]
    pub const fn from_bps(bps: i128) -> Self {
        Wad(bps * BPS)
    }

    /// Convert WAD to basis points.
    #[inline]
    pub fn to_bps(self) -> i128 {
        self.0 / BPS
    }

    /// WAD multiplication: (a * b) / WAD
    #[inline]
    pub fn wmul(self, other: Wad) -> Wad {
        Wad((self.0 * other.0) / WAD)
    }

    /// WAD division: (a * WAD) / b
    #[inline]
    pub fn wdiv(self, other: Wad) -> Wad {
        if other.0 == 0 {
            return Wad(0);
        }
        Wad((self.0 * WAD) / other.0)
    }

    /// Clamp fee to valid range [0, MAX_FEE].
    #[inline]
    pub fn clamp_fee(self) -> Wad {
        Wad(self.0.max(0).min(MAX_FEE))
    }

    /// Clamp to arbitrary range.
    #[inline]
    pub fn clamp(self, min: Wad, max: Wad) -> Wad {
        Wad(self.0.max(min.0).min(max.0))
    }

    /// Absolute value.
    #[inline]
    pub fn abs(self) -> Wad {
        Wad(self.0.abs())
    }

    /// Absolute difference.
    #[inline]
    pub fn abs_diff(self, other: Wad) -> Wad {
        Wad((self.0 - other.0).abs())
    }

    /// Integer square root (Newton's method).
    #[inline]
    pub fn sqrt(self) -> Wad {
        if self.0 <= 0 {
            return Wad(0);
        }
        // Scale up by WAD for precision, then sqrt
        let scaled = self.0 * WAD;
        let mut x = scaled;
        let mut y = (x + 1) / 2;
        while y < x {
            x = y;
            y = (x + scaled / x) / 2;
        }
        Wad(x)
    }

    /// Check if zero.
    #[inline]
    pub fn is_zero(self) -> bool {
        self.0 == 0
    }

    /// Check if positive.
    #[inline]
    pub fn is_positive(self) -> bool {
        self.0 > 0
    }

    /// Check if negative.
    #[inline]
    pub fn is_negative(self) -> bool {
        self.0 < 0
    }

    /// Raw i128 value.
    #[inline]
    pub const fn raw(self) -> i128 {
        self.0
    }

    /// One WAD (1.0).
    #[inline]
    pub const fn one() -> Self {
        Wad(WAD)
    }

    /// Zero WAD.
    #[inline]
    pub const fn zero() -> Self {
        Wad(0)
    }
}

impl Add for Wad {
    type Output = Self;
    #[inline]
    fn add(self, other: Self) -> Self {
        Wad(self.0 + other.0)
    }
}

impl Sub for Wad {
    type Output = Self;
    #[inline]
    fn sub(self, other: Self) -> Self {
        Wad(self.0 - other.0)
    }
}

impl Mul for Wad {
    type Output = Self;
    /// Note: This is regular multiplication, not wmul!
    /// Use wmul() for WAD-aware multiplication.
    #[inline]
    fn mul(self, other: Self) -> Self {
        Wad(self.0 * other.0)
    }
}

impl Div for Wad {
    type Output = Self;
    /// Note: This is regular division, not wdiv!
    /// Use wdiv() for WAD-aware division.
    #[inline]
    fn div(self, other: Self) -> Self {
        Wad(self.0 / other.0)
    }
}

impl Neg for Wad {
    type Output = Self;
    #[inline]
    fn neg(self) -> Self {
        Wad(-self.0)
    }
}

impl From<i128> for Wad {
    fn from(value: i128) -> Self {
        Wad(value)
    }
}

impl From<f64> for Wad {
    fn from(value: f64) -> Self {
        Wad::from_f64(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_wad_from_f64() {
        let w = Wad::from_f64(1.0);
        assert_eq!(w.0, WAD);

        let w = Wad::from_f64(0.5);
        assert_eq!(w.0, WAD / 2);

        let w = Wad::from_f64(0.0025); // 25 bps
        assert_eq!(w.0, 25 * BPS);
    }

    #[test]
    fn test_wad_to_f64() {
        let w = Wad(WAD);
        assert!((w.to_f64() - 1.0).abs() < 1e-10);

        let w = Wad(WAD / 2);
        assert!((w.to_f64() - 0.5).abs() < 1e-10);
    }

    #[test]
    fn test_wmul() {
        let a = Wad::from_f64(2.0);
        let b = Wad::from_f64(3.0);
        let c = a.wmul(b);
        assert!((c.to_f64() - 6.0).abs() < 1e-10);
    }

    #[test]
    fn test_wdiv() {
        let a = Wad::from_f64(6.0);
        let b = Wad::from_f64(2.0);
        let c = a.wdiv(b);
        assert!((c.to_f64() - 3.0).abs() < 1e-10);
    }

    #[test]
    fn test_sqrt() {
        let a = Wad::from_f64(4.0);
        let s = a.sqrt();
        assert!((s.to_f64() - 2.0).abs() < 1e-6);

        let a = Wad::from_f64(2.0);
        let s = a.sqrt();
        assert!((s.to_f64() - 1.414213562).abs() < 1e-6);
    }

    #[test]
    fn test_bps_conversion() {
        let w = Wad::from_bps(25);
        assert!((w.to_f64() - 0.0025).abs() < 1e-10);
        assert_eq!(w.to_bps(), 25);
    }

    #[test]
    fn test_clamp_fee() {
        let w = Wad::from_f64(0.15); // 15%
        let clamped = w.clamp_fee();
        assert_eq!(clamped.0, MAX_FEE); // Clamped to 10%

        let w = Wad::from_f64(-0.01);
        let clamped = w.clamp_fee();
        assert_eq!(clamped.0, 0); // Clamped to 0
    }
}
