//! Arbitrageur logic for extracting profit from mispriced AMMs.

use crate::amm::CFMM;

/// Result of an arbitrage attempt.
#[derive(Debug, Clone)]
pub struct ArbResult {
    /// AMM name
    pub amm_name: String,
    /// Profit from the arbitrage
    pub profit: f64,
    /// Side: "buy" or "sell" from AMM perspective
    pub side: &'static str,
    /// Amount of X traded
    pub amount_x: f64,
    /// Amount of Y traded
    pub amount_y: f64,
}

/// Arbitrageur that extracts profit from mispriced AMMs.
///
/// Uses closed-form solutions for constant product AMMs.
/// For reserves (x, y), k=xy, fee f (fee-on-input), γ = 1 - f, and fair price p (Y per X):
/// - Buy X from AMM (AMM sells X): Δx_out = x - sqrt(k / (γ·p)) (profit-maximizing)
/// - Sell X to AMM (AMM buys X): Δx_in = (sqrt(k·γ / p) - x) / γ (profit-maximizing, Δx_in is gross input)
pub struct Arbitrageur;

impl Arbitrageur {
    /// Create a new arbitrageur.
    pub fn new() -> Self {
        Self
    }

    /// Find and execute the optimal arbitrage trade.
    pub fn execute_arb(&self, amm: &mut CFMM, fair_price: f64, timestamp: u64) -> Option<ArbResult> {
        let (rx, ry) = amm.reserves();
        let spot_price = ry / rx;

        if spot_price < fair_price {
            // AMM underprices X - buy X from AMM (AMM sells X)
            self.compute_buy_arb(amm, fair_price, timestamp)
        } else if spot_price > fair_price {
            // AMM overprices X - sell X to AMM (AMM buys X)
            self.compute_sell_arb(amm, fair_price, timestamp)
        } else {
            None
        }
    }

    /// Compute and execute optimal trade when buying X from AMM.
    ///
    /// Maximize profit = Δx * p - Y_paid
    /// Closed-form (fee-on-input): Δx_out = x - sqrt(k / (γ·p))
    fn compute_buy_arb(&self, amm: &mut CFMM, fair_price: f64, timestamp: u64) -> Option<ArbResult> {
        let (rx, ry) = amm.reserves();
        let k = rx * ry;
        let fee = amm.fees().ask_fee.to_f64();
        let gamma = 1.0 - fee;

        if gamma <= 0.0 || fair_price <= 0.0 {
            return None;
        }

        // Optimal trade size
        let new_x = (k / (gamma * fair_price)).sqrt();
        let amount_x = rx - new_x;

        if amount_x <= 0.0 {
            return None;
        }

        // Cap at 99% of reserves
        let amount_x = amount_x.min(rx * 0.99);

        // Use fast quote to compute profit
        let (total_y, _) = amm.quote_sell_x(amount_x);
        if total_y <= 0.0 {
            return None;
        }

        // Profit = value of X at fair price - Y paid
        let profit = amount_x * fair_price - total_y;

        if profit <= 0.0 {
            return None;
        }

        // Execute the trade
        let _trade = amm.execute_sell_x(amount_x, timestamp)?;

        Some(ArbResult {
            amm_name: amm.name.clone(),
            profit,
            side: "sell", // AMM sells X
            amount_x,
            amount_y: total_y,
        })
    }

    /// Compute and execute optimal trade when selling X to AMM.
    ///
    /// Maximize profit = Y_received - Δx * p
    /// Closed-form (fee-on-input): Δx_in = (sqrt(k·γ / p) - x) / γ
    fn compute_sell_arb(&self, amm: &mut CFMM, fair_price: f64, timestamp: u64) -> Option<ArbResult> {
        let (rx, ry) = amm.reserves();
        let k = rx * ry;
        let fee = amm.fees().bid_fee.to_f64();
        let gamma = 1.0 - fee;

        if gamma <= 0.0 || fair_price <= 0.0 {
            return None;
        }

        // Optimal trade size (gross input):
        // x + γ·Δx_in = sqrt(k·γ/p)  =>  Δx_in = (sqrt(k·γ/p) - x) / γ
        let x_virtual = (k * gamma / fair_price).sqrt();
        let net_x = x_virtual - rx;
        let amount_x = net_x / gamma;

        if amount_x <= 0.0 {
            return None;
        }

        // Use fast quote to compute profit
        let (y_out, _) = amm.quote_buy_x(amount_x);
        if y_out <= 0.0 {
            return None;
        }

        // Profit = Y received - cost of X at fair price
        let profit = y_out - amount_x * fair_price;

        if profit <= 0.0 {
            return None;
        }

        // Execute the trade
        let _trade = amm.execute_buy_x(amount_x, timestamp)?;

        Some(ArbResult {
            amm_name: amm.name.clone(),
            profit,
            side: "buy", // AMM buys X
            amount_x,
            amount_y: y_out,
        })
    }

    /// Execute arbitrage on multiple AMMs.
    pub fn arbitrage_all(&self, amms: &mut [CFMM], fair_price: f64, timestamp: u64) -> Vec<ArbResult> {
        amms.iter_mut()
            .filter_map(|amm| self.execute_arb(amm, fair_price, timestamp))
            .collect()
    }
}

impl Default for Arbitrageur {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn quote_buy_x(reserve_x: f64, reserve_y: f64, fee: f64, amount_x_in: f64) -> f64 {
        if amount_x_in <= 0.0 {
            return 0.0;
        }
        let gamma = 1.0 - fee;
        if gamma <= 0.0 {
            return 0.0;
        }
        let k = reserve_x * reserve_y;
        let new_rx = reserve_x + amount_x_in * gamma;
        let new_ry = k / new_rx;
        reserve_y - new_ry
    }

    fn quote_sell_x(reserve_x: f64, reserve_y: f64, fee: f64, amount_x_out: f64) -> f64 {
        if amount_x_out <= 0.0 || amount_x_out >= reserve_x {
            return 0.0;
        }
        let gamma = 1.0 - fee;
        if gamma <= 0.0 {
            return 0.0;
        }
        let k = reserve_x * reserve_y;
        let new_rx = reserve_x - amount_x_out;
        let new_ry = k / new_rx;
        let net_y = new_ry - reserve_y;
        if net_y <= 0.0 {
            return 0.0;
        }
        net_y / gamma
    }

    #[test]
    fn test_arb_formulas() {
        // Test the closed-form formulas without EVM
        let rx: f64 = 1000.0;
        let ry: f64 = 1000.0;
        let k = rx * ry;
        let fee = 0.0025; // 25 bps
        let gamma = 1.0 - fee;

        // If fair price > spot price, buy X from AMM
        let fair_price = 1.1; // Above spot of 1.0
        let new_x = (k / (gamma * fair_price)).sqrt();
        let amount_x_out = rx - new_x;
        assert!(amount_x_out > 0.0); // Should want to buy X

        // If fair price < spot price, sell X to AMM
        let fair_price = 0.9; // Below spot of 1.0
        let x_virtual = (k * gamma / fair_price).sqrt();
        let amount_x_in = (x_virtual - rx) / gamma;
        assert!(amount_x_in > 0.0); // Should want to sell X
    }

    #[test]
    fn test_arb_sizes_maximize_profit() {
        let rx: f64 = 1000.0;
        let ry: f64 = 1000.0;
        let k = rx * ry;
        let fee = 0.05; // 5%
        let gamma = 1.0 - fee;

        // Buy X from AMM (AMM sells X): optimize in terms of X out
        let fair_price = 1.2;
        let x_out_opt = rx - (k / (gamma * fair_price)).sqrt();
        assert!(x_out_opt > 0.0 && x_out_opt < rx);
        let y_in_opt = quote_sell_x(rx, ry, fee, x_out_opt);
        let profit_opt = x_out_opt * fair_price - y_in_opt;

        let profit_lo = (x_out_opt * 0.999) * fair_price - quote_sell_x(rx, ry, fee, x_out_opt * 0.999);
        let profit_hi = (x_out_opt * 1.001) * fair_price - quote_sell_x(rx, ry, fee, x_out_opt * 1.001);
        assert!(profit_opt >= profit_lo - 1e-9);
        assert!(profit_opt >= profit_hi - 1e-9);

        // Sell X to AMM (AMM buys X): optimize in terms of gross X in
        let fair_price = 0.9;
        let x_virtual = (k * gamma / fair_price).sqrt();
        let x_in_opt = (x_virtual - rx) / gamma;
        assert!(x_in_opt > 0.0);
        let y_out_opt = quote_buy_x(rx, ry, fee, x_in_opt);
        let profit_opt = y_out_opt - x_in_opt * fair_price;

        let x_in_lo = x_in_opt * 0.999;
        let x_in_hi = x_in_opt * 1.001;
        let profit_lo = quote_buy_x(rx, ry, fee, x_in_lo) - x_in_lo * fair_price;
        let profit_hi = quote_buy_x(rx, ry, fee, x_in_hi) - x_in_hi * fair_price;
        assert!(profit_opt >= profit_lo - 1e-9);
        assert!(profit_opt >= profit_hi - 1e-9);
    }

    #[test]
    fn test_arb_moves_price_into_no_arb_band() {
        let rx: f64 = 1000.0;
        let ry: f64 = 1000.0;
        let fee = 0.05; // 5%
        let gamma = 1.0 - fee;

        // Underpriced: spot < fair -> buy X from AMM (AMM sells X)
        let fair_price = 1.2;
        let k = rx * ry;
        let x_out = rx - (k / (gamma * fair_price)).sqrt();
        let y_in = quote_sell_x(rx, ry, fee, x_out);
        let rx2 = rx - x_out;
        let ry2 = ry + y_in;
        let spot2 = ry2 / rx2;
        assert!(spot2 >= fair_price * gamma - 1e-9);

        // Overpriced: spot > fair -> sell X to AMM (AMM buys X)
        let fair_price = 0.9;
        let k = rx * ry;
        let x_virtual = (k * gamma / fair_price).sqrt();
        let x_in = (x_virtual - rx) / gamma;
        let y_out = quote_buy_x(rx, ry, fee, x_in);
        let rx2 = rx + x_in;
        let ry2 = ry - y_out;
        let spot2 = ry2 / rx2;
        assert!(spot2 <= fair_price / gamma + 1e-9);
    }
}
