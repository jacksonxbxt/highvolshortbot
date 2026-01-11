# High Volatility Short Bot

Automated trading bot that goes **long BTC** and **shorts the 20 most volatile altcoins**.

## Strategy

- **Long**: 100% capital in BTCUSDT
- **Short**: 5% each in top 20 highest volatility alts (100% total)
- **Rebalance**: Every 4 hours (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC)
- **Volatility**: Rolling 30-period (5 day) standard deviation of log returns

## Backtest Results (Oct 2024 - Jan 2026)

| Metric | Value |
|--------|-------|
| Return | +5,230% |
| Sharpe | 3.52 |
| Max DD | -38% |
| Win Rate | 54% |

## Quick Start

### Local Testing

```bash
# Clone repo
git clone https://github.com/YOUR_USERNAME/highvol-short-bot.git
cd highvol-short-bot

# Install dependencies
pip install -r requirements.txt

# Copy and edit environment variables
cp .env.example .env
# Edit .env with your settings

# Run (paper trade mode by default)
python bot.py
```

### Deploy to Render

1. Push to GitHub
2. Go to [Render Dashboard](https://dashboard.render.com/)
3. New > Blueprint > Connect your repo
4. Render will detect `render.yaml` automatically
5. Add your API keys in Environment settings

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BYBIT_API_KEY` | - | Your Bybit API key |
| `BYBIT_API_SECRET` | - | Your Bybit API secret |
| `TESTNET` | `true` | Use testnet (`true`) or mainnet (`false`) |
| `PAPER_TRADE` | `true` | Paper trade mode - no real orders |
| `CAPITAL` | `1000` | Capital to deploy (USD) |
| `N_SHORTS` | `20` | Number of alts to short |
| `LOOKBACK` | `30` | Volatility lookback (periods) |
| `LEVERAGE` | `1` | Leverage per side |

## Modes

1. **Paper Trade** (`PAPER_TRADE=true`): Simulates trades, tracks PnL, no API keys needed
2. **Testnet** (`TESTNET=true`, `PAPER_TRADE=false`): Real orders on Bybit testnet
3. **Live** (`TESTNET=false`, `PAPER_TRADE=false`): Real money trading

## Risk Warning

This bot trades with leverage and can lose money. Past backtest performance does not guarantee future results. Start with paper trading and small capital.

## License

MIT
