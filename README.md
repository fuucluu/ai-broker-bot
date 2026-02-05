# AI Broker - Automated Paper Trading System

⚠️ **PAPER MODE ONLY** - This system trades exclusively in paper (simulated) mode using Alpaca's paper trading API. No real money is ever at risk.

## Overview

AI Broker is an automated trading system that uses unsupervised machine learning (KMeans clustering) to identify patterns in market data and make trading decisions. It features:

- **Pattern Recognition**: Clusters market conditions based on technical features (RSI, EMA, ATR, volume, returns)
- **AI Memory**: SQLite-based learning system that tracks cluster performance, symbol behavior, and adapts thresholds over time
- **Risk Management**: Non-bypassable risk governor with daily loss limits, position limits, cooldowns, and kill switch
- **News Intelligence**: Optional module for adjusting risk based on news sentiment (requires NewsAPI key)
- **Continuous Operation**: Designed to run 24/7 with crash recovery and state persistence

## Prerequisites

- Python 3.10 or higher
- Alpaca paper trading account (free at https://alpaca.markets)
- Windows/Linux/Mac (tested on Windows with Ryzen 5 4600H, 16GB RAM)

## Installation

1. **Create virtual environment**:
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate
```

2. **Install dependencies**:
```bash
pip install -r requirements.txt
```

3. **Set environment variables**:

```bash
# Linux/Mac
export ALPACA_API_KEY='your_paper_api_key'
export ALPACA_API_SECRET='your_paper_api_secret'

# Optional: Enable news intelligence
export NEWSAPI_KEY='your_newsapi_key'
```

```powershell
# Windows PowerShell
$env:ALPACA_API_KEY='your_paper_api_key'
$env:ALPACA_API_SECRET='your_paper_api_secret'

# Optional
$env:NEWSAPI_KEY='your_newsapi_key'
```

**Important**: Use your Alpaca PAPER trading credentials, not live credentials.

## Running

```bash
python main.py
```

The system will:
1. Verify paper mode connection
2. Reconcile any existing positions
3. Wait for market open (NYSE hours: 9:30 AM - 4:00 PM ET)
4. Begin automated trading during market hours
5. Generate daily/weekly reports

## Stopping

### Normal Stop
Press `Ctrl+C` to gracefully shutdown.

### Kill Switch
Create a file named `STOP_TRADING` in the project root to immediately halt new trades:

```bash
touch STOP_TRADING
```

Remove the file to resume trading.

## Configuration

Edit `config/settings.yaml` to customize:

```yaml
trading:
  timeframe: "5Min"        # Bar timeframe
  polling_seconds: 30      # Data refresh interval
  max_symbols: 10          # Maximum symbols to trade

risk:
  risk_per_trade_pct: 1.0  # Risk per trade (% of account)
  max_daily_loss_pct: 2.0  # Daily loss limit
  max_trades_per_day: 5    # Maximum trades per day
  max_positions: 5         # Maximum concurrent positions

clustering:
  n_clusters: 12           # Number of pattern clusters
  min_cluster_trades: 30   # Min trades before trusting cluster
  min_expectancy: 0.001    # Min positive expectancy to trade

news:
  enabled: false           # Enable news intelligence
```

Edit `config/symbols.txt` to customize the watchlist (one symbol per line).

## Output Locations

- **Logs**: `ai_broker.log`
- **Database**: `ai_broker.db` (SQLite)
- **Reports**: `reports/` directory
  - Daily: `daily_YYYY-MM-DD.json` and `.csv`
  - Weekly: `weekly_YYYY-MM-DD.json` and `.csv`
- **Model**: `model/kmeans_model.pkl`

## Safety Features

1. **Paper Mode Lock**: System will abort if it detects live trading attempt
2. **ALLOW_LIVE Block**: System refuses to start if `ALLOW_LIVE` env var is set
3. **Kill Switch**: `STOP_TRADING` file immediately halts new trades
4. **Daily Loss Limit**: Stops trading if daily loss exceeds threshold
5. **Trade Cooldowns**: Enforced delays between trades and after losses
6. **Position Reconciliation**: Syncs with broker on every restart

## Architecture

```
ai_broker/
├── main.py              # Entry point
├── config/
│   ├── settings.yaml    # Configuration
│   └── symbols.txt      # Watchlist
├── engine/
│   ├── runtime.py       # Main trading loop
│   ├── market_hours.py  # NYSE schedule handling
│   ├── data_feed.py     # Alpaca market data
│   ├── features.py      # Technical indicators
│   ├── patterns.py      # KMeans clustering
│   ├── scorer.py        # Trade signal scoring
│   ├── risk.py          # Risk management
│   ├── execution.py     # Order execution
│   ├── portfolio.py     # Position tracking
│   ├── news.py          # News intelligence
│   ├── persistence.py   # SQLite database
│   ├── reporting.py     # Reports & dashboard
│   └── utils.py         # Utilities
├── reports/             # Generated reports
├── model/               # Saved ML model
└── requirements.txt
```

## AI Memory System

The system maintains persistent memory in SQLite:

- **Cluster Stats**: Win rate, expectancy, avg win/loss per pattern cluster
- **Symbol Stats**: Per-symbol performance, consecutive losses
- **Regime Stats**: Performance by market regime (uptrend, volatile, etc.)
- **News Impact**: Historical news events and price impact
- **Parameter Changes**: Log of adaptive threshold changes

The trading logic consults this memory and adapts over time.

## Disclaimer

This software is for educational and paper trading purposes only. It is not financial advice. The authors are not responsible for any losses incurred. Always test thoroughly in paper mode before considering any real trading.

**This system is hardcoded for paper trading only and cannot be used for live trading.**

## License

MIT License
