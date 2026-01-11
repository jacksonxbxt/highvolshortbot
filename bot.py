"""
High Volatility Short Bot
Strategy: Long BTC, Short top 20 highest volatility altcoins
Rebalances every 4 hours
"""

import os
import time
import logging
from datetime import datetime, timezone
from typing import Optional
import numpy as np
import pandas as pd
from pybit.unified_trading import HTTP

# Configuration from environment
API_KEY = os.getenv("BYBIT_API_KEY", "")
API_SECRET = os.getenv("BYBIT_API_SECRET", "")
TESTNET = os.getenv("TESTNET", "true").lower() == "true"
PAPER_TRADE = os.getenv("PAPER_TRADE", "true").lower() == "true"
CAPITAL = float(os.getenv("CAPITAL", "1000"))
N_SHORTS = int(os.getenv("N_SHORTS", "20"))
LOOKBACK = int(os.getenv("LOOKBACK", "30"))
LEVERAGE = int(os.getenv("LEVERAGE", "1"))

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)


class HighVolShortBot:
    def __init__(self):
        # For paper trading, always use mainnet (public endpoints work without auth)
        # For live trading, use testnet or mainnet based on config
        use_testnet = TESTNET and not PAPER_TRADE

        self.client = HTTP(
            testnet=use_testnet,
            api_key=API_KEY if not PAPER_TRADE else "",
            api_secret=API_SECRET if not PAPER_TRADE else "",
        )
        self.positions = {}  # symbol -> size
        self.paper_pnl = 0.0
        self.paper_positions = {}  # symbol -> {"side": "Buy/Sell", "size": float, "entry": float}

        log.info(f"Bot initialized - TESTNET={TESTNET}, PAPER_TRADE={PAPER_TRADE}")
        log.info(f"Capital: ${CAPITAL}, Shorts: {N_SHORTS}, Lookback: {LOOKBACK}")

    def get_usdt_perp_symbols(self) -> list[str]:
        """Get all active USDT perpetual symbols."""
        try:
            result = self.client.get_instruments_info(category="linear")
            symbols = [
                s["symbol"] for s in result["result"]["list"]
                if s["quoteCoin"] == "USDT"
                and s["status"] == "Trading"
                and s["contractType"] == "LinearPerpetual"
            ]
            log.info(f"Found {len(symbols)} active USDT perps")
            return symbols
        except Exception as e:
            log.error(f"Error fetching symbols: {e}")
            return []

    def get_klines(self, symbol: str, interval: str = "240", limit: int = 50) -> pd.DataFrame:
        """Fetch kline data for a symbol."""
        try:
            result = self.client.get_kline(
                category="linear",
                symbol=symbol,
                interval=interval,
                limit=limit
            )
            if result["retCode"] != 0:
                return pd.DataFrame()

            klines = result["result"]["list"]
            if not klines:
                return pd.DataFrame()

            df = pd.DataFrame(klines, columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"])
            df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms")
            df["close"] = df["close"].astype(float)
            df = df.sort_values("timestamp").reset_index(drop=True)
            return df
        except Exception as e:
            log.debug(f"Error fetching klines for {symbol}: {e}")
            return pd.DataFrame()

    def calculate_volatility(self, df: pd.DataFrame) -> float:
        """Calculate rolling volatility from price data."""
        if len(df) < LOOKBACK:
            return 0.0

        df["log_return"] = np.log(df["close"] / df["close"].shift(1))
        vol = df["log_return"].tail(LOOKBACK).std()
        return vol if not np.isnan(vol) else 0.0

    def get_top_volatile_alts(self) -> list[tuple[str, float]]:
        """Get the top N most volatile altcoins."""
        symbols = self.get_usdt_perp_symbols()
        volatilities = []

        log.info(f"Calculating volatility for {len(symbols)} symbols...")

        for i, symbol in enumerate(symbols):
            if symbol == "BTCUSDT":
                continue

            df = self.get_klines(symbol, interval="240", limit=LOOKBACK + 5)
            if df.empty:
                continue

            vol = self.calculate_volatility(df)
            if vol > 0:
                volatilities.append((symbol, vol))

            # Rate limiting
            if i % 10 == 0:
                time.sleep(0.1)

        # Sort by volatility descending
        volatilities.sort(key=lambda x: x[1], reverse=True)
        top_n = volatilities[:N_SHORTS]

        log.info(f"Top {N_SHORTS} volatile alts:")
        for sym, vol in top_n[:5]:
            log.info(f"  {sym}: {vol:.4f}")
        log.info(f"  ... and {len(top_n) - 5} more")

        return top_n

    def get_current_price(self, symbol: str) -> float:
        """Get current mark price for a symbol."""
        try:
            result = self.client.get_tickers(category="linear", symbol=symbol)
            if result["retCode"] == 0 and result["result"]["list"]:
                return float(result["result"]["list"][0]["markPrice"])
        except Exception as e:
            log.error(f"Error getting price for {symbol}: {e}")
        return 0.0

    def calculate_target_positions(self, top_volatile: list[tuple[str, float]]) -> dict:
        """Calculate target positions based on strategy."""
        targets = {}

        # Long BTC with full capital
        targets["BTCUSDT"] = {"side": "Buy", "value": CAPITAL}

        # Short each volatile alt equally
        short_value_each = CAPITAL / N_SHORTS
        for symbol, vol in top_volatile:
            targets[symbol] = {"side": "Sell", "value": short_value_each}

        return targets

    def execute_paper_trade(self, targets: dict):
        """Execute trades in paper trading mode."""
        log.info("=" * 50)
        log.info("PAPER TRADE EXECUTION")
        log.info("=" * 50)

        # Close positions not in targets
        for symbol in list(self.paper_positions.keys()):
            if symbol not in targets:
                pos = self.paper_positions[symbol]
                current_price = self.get_current_price(symbol)
                if current_price > 0:
                    if pos["side"] == "Sell":  # Short position
                        pnl = (pos["entry"] - current_price) * pos["size"]
                    else:  # Long position
                        pnl = (current_price - pos["entry"]) * pos["size"]
                    self.paper_pnl += pnl
                    log.info(f"CLOSE {symbol}: PnL ${pnl:+.2f}")
                del self.paper_positions[symbol]

        # Open/adjust positions in targets
        for symbol, target in targets.items():
            current_price = self.get_current_price(symbol)
            if current_price <= 0:
                continue

            target_size = target["value"] / current_price

            if symbol in self.paper_positions:
                # Position exists, check if same side
                pos = self.paper_positions[symbol]
                if pos["side"] == target["side"]:
                    log.info(f"HOLD {target['side']} {symbol}: {pos['size']:.4f} @ ${pos['entry']:.2f}")
                    continue
                else:
                    # Close and reverse
                    if pos["side"] == "Sell":
                        pnl = (pos["entry"] - current_price) * pos["size"]
                    else:
                        pnl = (current_price - pos["entry"]) * pos["size"]
                    self.paper_pnl += pnl
                    log.info(f"REVERSE {symbol}: Close PnL ${pnl:+.2f}")

            # Open new position
            self.paper_positions[symbol] = {
                "side": target["side"],
                "size": target_size,
                "entry": current_price
            }
            log.info(f"OPEN {target['side']} {symbol}: {target_size:.4f} @ ${current_price:.2f} (${target['value']:.0f})")

        # Summary
        log.info("-" * 50)
        log.info(f"Realized PnL: ${self.paper_pnl:+.2f}")
        log.info(f"Open positions: {len(self.paper_positions)}")

        # Calculate unrealized PnL
        unrealized = 0.0
        for symbol, pos in self.paper_positions.items():
            current_price = self.get_current_price(symbol)
            if current_price > 0:
                if pos["side"] == "Sell":
                    unrealized += (pos["entry"] - current_price) * pos["size"]
                else:
                    unrealized += (current_price - pos["entry"]) * pos["size"]

        log.info(f"Unrealized PnL: ${unrealized:+.2f}")
        log.info(f"Total PnL: ${self.paper_pnl + unrealized:+.2f}")
        log.info(f"Equity: ${CAPITAL + self.paper_pnl + unrealized:,.2f}")

    def execute_live_trade(self, targets: dict):
        """Execute real trades on Bybit."""
        log.warning("LIVE TRADING - Real money at risk!")

        # Get current positions
        try:
            result = self.client.get_positions(category="linear", settleCoin="USDT")
            current_positions = {}
            for pos in result["result"]["list"]:
                if float(pos["size"]) > 0:
                    current_positions[pos["symbol"]] = {
                        "side": pos["side"],
                        "size": float(pos["size"]),
                        "value": float(pos["positionValue"])
                    }
        except Exception as e:
            log.error(f"Error getting positions: {e}")
            return

        # Close positions not in targets
        for symbol, pos in current_positions.items():
            if symbol not in targets:
                try:
                    close_side = "Sell" if pos["side"] == "Buy" else "Buy"
                    self.client.place_order(
                        category="linear",
                        symbol=symbol,
                        side=close_side,
                        orderType="Market",
                        qty=str(pos["size"]),
                        reduceOnly=True
                    )
                    log.info(f"CLOSED {symbol}")
                except Exception as e:
                    log.error(f"Error closing {symbol}: {e}")

        # Open new positions
        for symbol, target in targets.items():
            if symbol in current_positions:
                continue  # Already have position

            try:
                # Set leverage
                self.client.set_leverage(
                    category="linear",
                    symbol=symbol,
                    buyLeverage=str(LEVERAGE),
                    sellLeverage=str(LEVERAGE)
                )

                # Get instrument info for lot size
                info = self.client.get_instruments_info(category="linear", symbol=symbol)
                min_qty = float(info["result"]["list"][0]["lotSizeFilter"]["minOrderQty"])
                qty_step = float(info["result"]["list"][0]["lotSizeFilter"]["qtyStep"])

                # Calculate quantity
                price = self.get_current_price(symbol)
                qty = target["value"] / price
                qty = max(min_qty, round(qty / qty_step) * qty_step)

                # Place order
                self.client.place_order(
                    category="linear",
                    symbol=symbol,
                    side=target["side"],
                    orderType="Market",
                    qty=str(qty)
                )
                log.info(f"OPENED {target['side']} {symbol}: {qty}")

            except Exception as e:
                log.error(f"Error opening {symbol}: {e}")

            time.sleep(0.2)  # Rate limit

    def run_once(self):
        """Run one iteration of the strategy."""
        log.info("=" * 60)
        log.info(f"REBALANCE - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        log.info("=" * 60)

        # Get top volatile alts
        top_volatile = self.get_top_volatile_alts()
        if len(top_volatile) < N_SHORTS:
            log.warning(f"Only found {len(top_volatile)} volatile alts, need {N_SHORTS}")
            return

        # Calculate target positions
        targets = self.calculate_target_positions(top_volatile)

        # Execute
        if PAPER_TRADE:
            self.execute_paper_trade(targets)
        else:
            self.execute_live_trade(targets)

        log.info("Rebalance complete")

    def get_next_rebalance_time(self) -> datetime:
        """Get the next 4-hour mark (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC)."""
        now = datetime.now(timezone.utc)
        current_hour = now.hour
        next_hour = ((current_hour // 4) + 1) * 4

        if next_hour >= 24:
            next_hour = 0
            next_day = now.date() + pd.Timedelta(days=1)
            next_time = datetime(next_day.year, next_day.month, next_day.day,
                                next_hour, 0, 0, tzinfo=timezone.utc)
        else:
            next_time = datetime(now.year, now.month, now.day,
                                next_hour, 0, 0, tzinfo=timezone.utc)

        return next_time

    def run_loop(self):
        """Run the bot continuously, rebalancing every 4 hours."""
        log.info("Starting bot loop...")

        # Run immediately on start
        self.run_once()

        while True:
            next_rebalance = self.get_next_rebalance_time()
            wait_seconds = (next_rebalance - datetime.now(timezone.utc)).total_seconds()

            if wait_seconds > 0:
                log.info(f"Next rebalance at {next_rebalance.strftime('%Y-%m-%d %H:%M')} UTC "
                        f"(in {wait_seconds/3600:.1f} hours)")
                time.sleep(wait_seconds + 60)  # +60s buffer

            self.run_once()


def main():
    log.info("=" * 60)
    log.info("HIGH VOLATILITY SHORT BOT")
    log.info("=" * 60)
    log.info("Strategy: Long BTC, Short top 20 high-vol alts")
    log.info("Rebalance: Every 4 hours")
    log.info("")

    if PAPER_TRADE:
        log.info("MODE: PAPER TRADING (no real money)")
    elif TESTNET:
        log.info("MODE: TESTNET (test money)")
    else:
        log.warning("MODE: LIVE TRADING (real money!)")

    log.info("")

    bot = HighVolShortBot()
    bot.run_loop()


if __name__ == "__main__":
    main()
