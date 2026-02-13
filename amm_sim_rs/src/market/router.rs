//! Order router with optimal splitting across multiple AMMs.

use crate::amm::CFMM;
use crate::market::retail::RetailOrder;

/// Result of routing a trade to an AMM.
#[derive(Debug, Clone)]
pub struct RoutedTrade {
    /// AMM name
    pub amm_name: String,
    /// Amount of Y spent (buy) or received (sell)
    pub amount_y: f64,
    /// Amount of X traded
    pub amount_x: f64,
    /// True if AMM buys X (trader sells X)
    pub amm_buys_x: bool,
}

/// Routes retail orders optimally across AMMs.
///
/// Implements optimal order splitting so that the marginal price is equal
/// across all AMMs after the trade. This maximizes execution quality for
/// the trader and creates fair competition between AMMs based on their fees.
///
/// For constant product AMMs (xy=k), the optimal split can be computed
/// analytically rather than using numerical methods.
pub struct OrderRouter;

impl OrderRouter {
    /// Create a new order router.
    pub fn new() -> Self {
        Self
    }

    /// Compute optimal Y split for buying X across two AMMs.
    ///
    /// Uses Uniswap v2 fee-on-input model with γ = 1 - f:
    /// - A_i = sqrt(x_i * γ_i * y_i), r = A_1/A_2
    /// - Δy_1* = (r * (y_2 + γ_2 * Y) - y_1) / (γ_1 + r * γ_2)
    fn split_buy_two_amms(&self, amm1: &CFMM, amm2: &CFMM, total_y: f64) -> (f64, f64) {
        let (x1, y1) = amm1.reserves();
        let (x2, y2) = amm2.reserves();
        let f1 = amm1.fees().ask_fee.to_f64();
        let f2 = amm2.fees().ask_fee.to_f64();

        let gamma1 = 1.0 - f1;
        let gamma2 = 1.0 - f2;

        // A_i = sqrt(x_i * γ_i * y_i)
        let a1 = (x1 * gamma1 * y1).sqrt();
        let a2 = (x2 * gamma2 * y2).sqrt();

        if a2 == 0.0 {
            return (total_y, 0.0);
        }

        // r = A_1 / A_2
        let r = a1 / a2;

        // Δy_1* = (r * (y_2 + γ_2 * Y) - y_1) / (γ_1 + r * γ_2)
        let numerator = r * (y2 + gamma2 * total_y) - y1;
        let denominator = gamma1 + r * gamma2;

        let y1_amount = if denominator == 0.0 {
            total_y / 2.0
        } else {
            numerator / denominator
        };

        // Clamp to valid range [0, Y]
        let y1_amount = y1_amount.max(0.0).min(total_y);
        let y2_amount = total_y - y1_amount;

        (y1_amount, y2_amount)
    }

    /// Compute optimal X split for selling X across two AMMs.
    ///
    /// Uses Uniswap v2 fee-on-input model with γ = 1 - f:
    /// - B_i = sqrt(y_i * γ_i * x_i), r = B_1/B_2
    /// - Δx_1* = (r * (x_2 + γ_2 * X) - x_1) / (γ_1 + r * γ_2)
    fn split_sell_two_amms(&self, amm1: &CFMM, amm2: &CFMM, total_x: f64) -> (f64, f64) {
        let (x1, y1) = amm1.reserves();
        let (x2, y2) = amm2.reserves();
        let f1 = amm1.fees().bid_fee.to_f64();
        let f2 = amm2.fees().bid_fee.to_f64();

        let gamma1 = 1.0 - f1;
        let gamma2 = 1.0 - f2;

        // B_i = sqrt(y_i * γ_i * x_i)
        let b1 = (y1 * gamma1 * x1).sqrt();
        let b2 = (y2 * gamma2 * x2).sqrt();

        if b2 == 0.0 {
            return (total_x, 0.0);
        }

        // r = B_1 / B_2
        let r = b1 / b2;

        // Δx_1* = (r * (x_2 + γ_2 * X) - x_1) / (γ_1 + r * γ_2)
        let numerator = r * (x2 + gamma2 * total_x) - x1;
        let denominator = gamma1 + r * gamma2;

        let x1_amount = if denominator == 0.0 {
            total_x / 2.0
        } else {
            numerator / denominator
        };

        // Clamp to valid range [0, X]
        let x1_amount = x1_amount.max(0.0).min(total_x);
        let x2_amount = total_x - x1_amount;

        (x1_amount, x2_amount)
    }

    /// Route a single retail order across AMMs.
    pub fn route_order(
        &self,
        order: &RetailOrder,
        amms: &mut [CFMM],
        fair_price: f64,
        timestamp: u64,
    ) -> Vec<RoutedTrade> {
        if amms.is_empty() {
            return Vec::new();
        }

        if amms.len() == 1 {
            return self.route_to_single_amm(order, &mut amms[0], fair_price, timestamp);
        }

        // For 2 AMMs, use optimal splitting
        if amms.len() == 2 {
            return self.route_to_two_amms(order, amms, fair_price, timestamp);
        }

        // For >2 AMMs, use iterative pairwise splitting
        // (Simplified - true optimal would require solving simultaneously)
        self.route_to_many_amms(order, amms, fair_price, timestamp)
    }

    fn route_to_single_amm(
        &self,
        order: &RetailOrder,
        amm: &mut CFMM,
        fair_price: f64,
        timestamp: u64,
    ) -> Vec<RoutedTrade> {
        let mut trades = Vec::new();

        if order.side == "buy" {
            // Trader wants to buy X, spending Y
            if let Some(result) = amm.execute_buy_x_with_y(order.size, timestamp) {
                trades.push(RoutedTrade {
                    amm_name: amm.name.clone(),
                    amount_y: order.size,
                    amount_x: result.trade_info.amount_x.to_f64(),
                    amm_buys_x: false,
                });
            }
        } else {
            // Trader wants to sell X, receiving Y
            let total_x = order.size / fair_price;
            if let Some(result) = amm.execute_buy_x(total_x, timestamp) {
                trades.push(RoutedTrade {
                    amm_name: amm.name.clone(),
                    amount_y: result.trade_info.amount_y.to_f64(),
                    amount_x: total_x,
                    amm_buys_x: true,
                });
            }
        }

        trades
    }

    fn route_to_two_amms(
        &self,
        order: &RetailOrder,
        amms: &mut [CFMM],
        fair_price: f64,
        timestamp: u64,
    ) -> Vec<RoutedTrade> {
        let mut trades = Vec::new();
        const MIN_AMOUNT: f64 = 0.0001;

        // Split amms mutably
        let (amm1, rest) = amms.split_first_mut().unwrap();
        let amm2 = &mut rest[0];

        if order.side == "buy" {
            // Trader wants to buy X, spending Y
            let (y1, y2) = self.split_buy_two_amms(amm1, amm2, order.size);

            if y1 > MIN_AMOUNT {
                if let Some(result) = amm1.execute_buy_x_with_y(y1, timestamp) {
                    trades.push(RoutedTrade {
                        amm_name: amm1.name.clone(),
                        amount_y: y1,
                        amount_x: result.trade_info.amount_x.to_f64(),
                        amm_buys_x: false,
                    });
                }
            }

            if y2 > MIN_AMOUNT {
                if let Some(result) = amm2.execute_buy_x_with_y(y2, timestamp) {
                    trades.push(RoutedTrade {
                        amm_name: amm2.name.clone(),
                        amount_y: y2,
                        amount_x: result.trade_info.amount_x.to_f64(),
                        amm_buys_x: false,
                    });
                }
            }
        } else {
            // Trader wants to sell X, receiving Y
            let total_x = order.size / fair_price;
            let (x1, x2) = self.split_sell_two_amms(amm1, amm2, total_x);

            if x1 > MIN_AMOUNT {
                if let Some(result) = amm1.execute_buy_x(x1, timestamp) {
                    trades.push(RoutedTrade {
                        amm_name: amm1.name.clone(),
                        amount_y: result.trade_info.amount_y.to_f64(),
                        amount_x: x1,
                        amm_buys_x: true,
                    });
                }
            }

            if x2 > MIN_AMOUNT {
                if let Some(result) = amm2.execute_buy_x(x2, timestamp) {
                    trades.push(RoutedTrade {
                        amm_name: amm2.name.clone(),
                        amount_y: result.trade_info.amount_y.to_f64(),
                        amount_x: x2,
                        amm_buys_x: true,
                    });
                }
            }
        }

        trades
    }

    fn route_to_many_amms(
        &self,
        order: &RetailOrder,
        amms: &mut [CFMM],
        fair_price: f64,
        timestamp: u64,
    ) -> Vec<RoutedTrade> {
        // Simplified: just use first two AMMs
        // Full implementation would need recursive splitting
        if amms.len() >= 2 {
            self.route_to_two_amms(order, &mut amms[0..2], fair_price, timestamp)
        } else {
            self.route_to_single_amm(order, &mut amms[0], fair_price, timestamp)
        }
    }

    /// Route multiple orders.
    pub fn route_orders(
        &self,
        orders: &[RetailOrder],
        amms: &mut [CFMM],
        fair_price: f64,
        timestamp: u64,
    ) -> Vec<RoutedTrade> {
        let mut all_trades = Vec::new();

        for order in orders {
            let trades = self.route_order(order, amms, fair_price, timestamp);
            all_trades.extend(trades);
        }

        all_trades
    }
}

impl Default for OrderRouter {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_split_formulas() {
        // Test the split formulas without EVM
        let x1: f64 = 1000.0;
        let y1: f64 = 1000.0;
        let x2: f64 = 1000.0;
        let y2: f64 = 1000.0;
        let f: f64 = 0.0025;
        let gamma = 1.0 - f;
        let total_y = 100.0;

        // With equal reserves and fees, split should be ~50/50
        let a1 = (x1 * gamma * y1).sqrt();
        let a2 = (x2 * gamma * y2).sqrt();
        let r = a1 / a2;

        let numerator = r * (y2 + gamma * total_y) - y1;
        let denominator = gamma + r * gamma;
        let y1_amount = numerator / denominator;

        // Should be approximately equal split
        assert!((y1_amount - 50.0).abs() < 1.0);
    }
}
