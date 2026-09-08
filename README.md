# Crypto Multi‑Agent AI Trading Desk

An institutional‑style, paper‑trading‑first crypto trading system powered by multiple independent AI agents coordinated by a central **Head Trader AI**.

---

## Architecture Overview

```
Market Data ──► Agent Layer ──► Signal Aggregator ──► Head Trader
                                                          │
                                              ┌──────────┤
                                              ▼          ▼
                                       Risk Manager   Portfolio Monitor
                                              │
                                              ▼
                                     Trade Proposal
                                              │
                                              ▼
                                           OMS
                                    ┌───────┴────────┐
                                    ▼                ▼
                              Paper Engine    Exchange Adapter
                                              (live only)
```

---

## Agent Layer (15 Agents)

| Agent | Package | Signal Type |
|-------|---------|-------------|
| MarketScanner | `scanner` | price/volume spikes |
| TrendAgent | `technical` | EMA crossover + ADX |
| MomentumAgent | `technical` | RSI + MACD + Stochastic |
| VolatilityAgent | `technical` | ATR + Bollinger Bands |
| SupportResistanceAgent | `technical` | Pivot point breakouts |
| PriceActionAgent | `technical` | Pin bars, inside bars |
| CandlestickAgent | `technical` | Engulfing, Doji |
| RegimeAgent | `regime` | Bull / Bear / Sideways |
| FundingAgent | `derivatives` | Funding rate extremes |
| OpenInterestAgent | `derivatives` | OI spikes |
| LiquidationAgent | `derivatives` | Liquidation clusters |
| WhaleAgent | `onchain` | Large on‑chain transfers |
| NewsAgent | `intelligence` | News sentiment |
| SentimentAgent | `intelligence` | Social sentiment |
| MacroAgent | `intelligence` | DXY, yields, S&P correlation |

---

## Quick Start

### Paper Trading (default)

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Edit .env — add your Binance testnet keys and any optional API keys
nano .env

# 3. Install dependencies (requires Python 3.12+)
pip install -r requirements.txt

# 4. Start the API server
python -m crypto_trading_desk.main
```

The API will be available at **http://localhost:8000**.

Interactive docs: **http://localhost:8000/docs**

### Docker

```bash
docker-compose up --build
```

---

## Key API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | System health check |
| GET | `/api/dashboard` | Portfolio overview |
| GET | `/api/trades` | All orders |
| GET | `/api/signals` | Agent signal stats |
| GET | `/api/risk` | Risk & emergency status |
| GET | `/api/reports/daily` | Markdown daily report |
| GET | `/api/reports/postmortems` | Recent trade post‑mortems |
| POST | `/api/control/kill-switch/activate` | Activate kill‑switch |
| POST | `/api/control/kill-switch/deactivate` | Deactivate (paper mode only) |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TRADING_MODE` | `paper` | `paper` or `live` |
| `BINANCE_API_KEY` | — | Binance API key |
| `BINANCE_API_SECRET` | — | Binance API secret |
| `BINANCE_TESTNET` | `true` | Use testnet |
| `DATABASE_URL` | SQLite (local) | Async DB URL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis URL |
| `ALERT_CHANNEL` | `console` | `console`, `telegram`, `discord` |
| `TELEGRAM_TOKEN` | — | Telegram bot token |
| `TELEGRAM_CHAT_ID` | — | Telegram chat ID |
| `DISCORD_WEBHOOK` | — | Discord webhook URL |

---

## Risk Limits (Hard — Immutable)

- Max position size per symbol: **5% of equity**
- Max total exposure: **80% of equity**
- Max drawdown before auto‑halt: **15%**
- Max leverage: **3×**
- Risk per trade: **1% of equity**

---

## Project Structure

```
crypto_trading_desk/
├── core/           # Enums, Pydantic models, EventBus, exceptions
├── config/         # Settings, RiskLimits, Assets, Exchanges
├── db/             # SQLAlchemy async engine, ORM models
├── data/           # MarketData, Historical, OnChain, News, Macro
├── agents/         # All 15 analysis agents + BaseAgent
│   ├── scanner/
│   ├── technical/
│   ├── regime/
│   ├── derivatives/
│   ├── onchain/
│   └── intelligence/
├── risk/           # HardRiskManager, PositionSizer, PortfolioMonitor, Emergency
├── head_trader/    # SignalAggregator, HeadTrader
├── execution/      # OMS, PaperEngine, ExchangeAdapter, Executor
├── analytics/      # AgentTracker, TradePostMortem, DailyReport
├── alerts/         # AlertManager (console/Telegram/Discord)
├── api/            # FastAPI app + all routes
│   └── routes/
└── main.py         # Entry point
```

---

## Disclaimer

This system is for **educational and research purposes only**. Paper‑trading mode is the default. Switch to live mode at your own risk. Always verify signals independently before committing real capital.
