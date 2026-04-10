# GlitchExecutor — System Architecture

> Internal documentation for the GlitchExecutor trading intelligence platform.
> Last updated: 2026-03-12

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Service Map](#2-service-map)
3. [Telegram Bot](#3-telegram-bot)
4. [AI Ensemble Engine](#4-ai-ensemble-engine)
5. [Price Feed System](#5-price-feed-system)
6. [Executor Service](#6-executor-service)
7. [Payment Service](#7-payment-service)
8. [Admin API](#8-admin-api)
9. [Infrastructure & Host Services](#9-infrastructure--host-services)
10. [Database Schema](#10-database-schema)
11. [Redis Key Reference](#11-redis-key-reference)
12. [Environment Variables](#12-environment-variables)
13. [Data Flow Diagrams](#13-data-flow-diagrams)

---

## 1. System Overview

GlitchExecutor is a multi-service trading intelligence platform that provides AI-powered trade analysis and execution across crypto, forex, stocks, commodities, and indices.

**Core capabilities:**
- 9-model AI ensemble (7 technical + 1 sentiment + 1 LLM orchestrator)
- Real-time analysis via Telegram bot
- Auto-trade execution across 100+ exchanges
- SaaS billing with Stripe (Trial → Starter → Pro → Elite)
- Admin dashboard with live position tracking

**Tech stack:** Python 3.11, Docker Compose, PostgreSQL 16, Redis 7, MetaTrader 5, Interactive Brokers, Stripe, Telegram Bot API, Anthropic Claude / OpenAI

---

## 2. Service Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                        TELEGRAM USERS                               │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
        ┌──────────────────▼──────────────────┐
        │        TELEGRAM BOT                  │
        │        (container: glitch-telegram)  │
        │  Commands, analysis, trade confirm   │
        └──┬───────────────┬──────────────┬───┘
           │               │              │
     analyze?symbol=X    LPUSH         POST /api/
           │            trade_req      bot/checkout
           ▼               ▼              ▼
  ┌────────────────┐ ┌──────────┐ ┌──────────────────┐
  │ ENSEMBLE       │ │  REDIS   │ │ PAYMENT SERVICE  │
  │ (port 8100)    │ │  (6379)  │ │ (port 5002)      │
  │ 7 models +     │ │ cache,   │ │ Stripe, SES,     │
  │ sentiment      │ │ queues   │ │ Meta/TikTok CAPI │
  └──┬─────────────┘ └────┬─────┘ └──────────────────┘
     │                     │
     │ price data    BRPOP │ trade_requests
     ▼                     ▼
  ┌────────────────┐ ┌──────────────────┐
  │ MT5 DATA SVC   │ │ EXECUTOR         │
  │ (port 7777)    │ │ (container)      │
  │ Wine + MT5 API │ │ CCXT / MT5       │
  │ PUPrime broker │ │ Risk management  │
  └────────────────┘ └──────────────────┘

  ┌──────────────────┐   ┌──────────────────┐
  │ ADMIN API        │   │ POSTGRES         │
  │ (port 5003)      │   │ (internal)       │
  │ FastAPI dashboard │   │ All persistent   │
  │ WebSocket live    │   │ data             │
  └──────────────────┘   └──────────────────┘
```

| Service | Container | Port | Tech |
|---------|-----------|------|------|
| Redis | `glitch-redis` | 6379 (internal) | Redis 7 Alpine |
| PostgreSQL | `glitch-postgres` | 5432 (internal) | Postgres 16 Alpine |
| Ensemble Engine | `glitch-ensemble` | 8100 | Python 3.11 |
| Telegram Bot | `glitch-telegram-bot` | — (polling) | python-telegram-bot |
| Executor | `glitch-executor` | — (queue worker) | Python + CCXT |
| Payment | `glitch-payment` | 5002 | Python + Flask |
| Admin API | `glitch-admin-api` | 5003 | Python + FastAPI |
| MT5 Data Service | — (systemd) | 7777 | Wine + Python 3.10 |
| IB Gateway Bridge | — (systemd) | 4003→4002 | socat |

---

## 3. Telegram Bot

**Location:** `/opt/glitchexecutor/telegram_bot/`
**Entry point:** `bot.py` → `GlitchExecutorBot` class

### 3.1 Files

| File | Purpose |
|------|---------|
| `bot.py` | Main bot — 40+ command handlers, callback handlers, message routing |
| `db.py` | PostgreSQL async layer (asyncpg) — customers, alerts, subscriptions |
| `orchestrator.py` | Model 9 — LLM synthesizer (Claude/OpenAI) that converts votes to natural language |
| `auth.py` | Customer authentication, tier validation, trial expiry checks |
| `redis_cache.py` | Redis I/O — ensemble votes, sentiment, prices, trade queue |
| `rate_limiter.py` | Per-tier query rate limiting with daily reset |
| `alerts.py` | Background jobs — price alerts (60s), signal alerts (5min), daily briefing (07:00 UTC) |

### 3.2 Command Reference

| Command | Description | Tier |
|---------|-------------|------|
| `/start` | Onboarding, referral deep-link processing | All |
| `/analyze <SYMBOL>` | Run 9-model ensemble analysis | All |
| `/scan` | Quick signal table from Redis cache (no LLM) | All |
| `/execute` | Confirm trade with SL/TP inline buttons | Pro+ |
| `/setalert <SYMBOL> <PRICE>` | Set price alert (auto-detects above/below) | All |
| `/alerts` | List active price alerts | All |
| `/watch <SYMBOL> [confidence%]` | Subscribe to BUY/SELL signal alerts | All |
| `/watchlist` | Show watched symbols | All |
| `/briefing` | Toggle daily 07:00 UTC market summary | All |
| `/plans` | Show plan comparison, Stripe checkout | All |
| `/referral` | Show referral link & stats | All |
| `/status` | Tier, usage, connected exchanges | All |
| `/connect_exchange` | 4-step exchange API key setup (encrypted) | Starter+ |
| `/connect_mt5` | MT5 credentials (encrypted) | Elite |
| `/admin stats` | User dashboard, top symbols | Admin |
| `/admin broadcast` | Broadcast to trial/paid/all users | Admin |

### 3.3 Free-Text Routing

Users can type naturally — the bot extracts symbols via regex + keyword maps:
- `"BTCUSD"`, `"BTC/USDT"`, `"EUR/USD"` → symbol regex
- `"bitcoin"`, `"gold"`, `"apple"` → keyword map
- `"alert at 50000"` → routes to `/setalert`
- `"watch this"` → routes to `/watch`
- `"execute"` → routes to `/execute`

### 3.4 Analysis Flow (User → Response)

```
1. User sends "/analyze AAPL" or just "AAPL"
2. auth.authenticate() → check tier, trial expiry
3. rate_limiter.check_and_increment() → enforce daily limit
4. Check Redis cache for ensemble:AAPL (TTL 10min)
5. If miss → HTTP GET http://ensemble:8100/analyze?symbol=AAPL
6. Ensemble engine runs 7 models → writes to Redis
7. Bot reads: votes, sentiment, price from Redis
8. orchestrator.synthesize() → Claude/OpenAI generates response
9. Log to ensemble_predictions + query_log tables
10. Send formatted response to user
```

### 3.5 Background Jobs

| Job | Interval | Function |
|-----|----------|----------|
| `check_price_alerts` | 60s | Compares Redis prices vs alert targets, sends notification |
| `check_signal_alerts` | 5min | Pushes BUY/SELL signals to watchers (6h dedup) |
| `update_bot_description` | 30min | Updates Telegram bot profile with live user count |
| `send_daily_briefings` | Daily 07:00 UTC | Market summary to subscribers |

### 3.6 Tier System

| Tier | Queries/Day | Features | Price |
|------|-------------|----------|-------|
| Trial | 10 | Analysis, alerts, watchlist | Free (7 days) |
| Starter | 30 | + Portfolio view via API | $49/mo |
| Pro | 100 | + Auto-execute trades | $149/mo |
| Elite | Unlimited | + MT5 bots on VPS | $349/mo |

---

## 4. AI Ensemble Engine

**Location:** `/opt/glitchexecutor/ensemble/`
**Entry point:** `engine.py` → `EnsembleEngine` class

### 4.1 Files

| File | Purpose |
|------|---------|
| `engine.py` | Main scheduler — runs models on schedule, serves `/health` and `/analyze` |
| `config.py` | Symbol configs (exchange routing, intervals) + env var loading |
| `price_feed.py` | Unified price router — dispatches to MT5 / IB / Kraken / CoinGecko |
| `mt5_price_feed.py` | MT5 data service HTTP client (PUPrime broker) |
| `ib_price_feed.py` | Interactive Brokers Gateway connector (ib_insync) |
| `sentiment.py` | Model 8 — LLM-based news sentiment analysis |
| `redis_cache.py` | Redis cache for votes, sentiment, prices, candles |
| `outcome_checker.py` | Background thread — checks if past predictions were correct (1h/4h/24h) |
| `outcome_db.py` | PostgreSQL client for prediction outcome storage |

### 4.2 The 9 Models

#### Models 1-7: Technical Analysis (local, NumPy-based)

All models implement: `analyze(symbol, candles) → {model, vote, confidence, reasoning, indicators}`

Input candles: `{"m15": np.array, "h1": np.array, "h4": np.array}` — columns: `[time, open, high, low, close, volume]`

| # | Model | Strategy | Key Indicators | Entry Signal | Timeframe |
|---|-------|----------|----------------|--------------|-----------|
| 1 | **Trend Follower** | SMA/EMA crossover | SMA(9), EMA(21), ADX(14), ATR(14) | SMA crosses EMA + ADX > 20 + ATR > median | H1 |
| 2 | **Mean Reverter** | Bollinger Bands reversion | BB(20,2), RSI(14), ADX(14) | Price at BB extreme + RSI < 30 or > 70 + ADX < 25 | H1 |
| 3 | **Momentum Hunter** | RSI breakout momentum | RSI(14), EMA(20), Volume ratio | RSI breaks 55/45 + price/EMA aligned | M15 |
| 4 | **ML Predictor** | XGBoost classification | 20+ features (SMA, EMA, ADX, ATR, session, volume) | Placeholder — returns HOLD 0.5 (training data collection) | H1 |
| 5 | **Multi-TF Align** | Cross-timeframe confirmation | EMA(20) on M15, H1, H4 | All 3 TFs aligned (0.9) or 2/3 majority (0.6) | Multi |
| 6 | **Volume Profiler** | Volatility + volume confirmation | ATR percentile, Volume ratio, EMA(20) | ATR > 70th pctl + Volume > 1.5x + EMA direction | H1 |
| 7 | **Session Analyst** | Forex session timing | UTC hour, session detection, EMA(20) | EMA direction in good session; forex avoids Asian | H1 |

#### Model 8: Sentiment Analyzer (`sentiment.py`)

- Fetches headlines from CryptoPanic API or CoinDesk RSS
- Sends to Claude / OpenAI: "classify these headlines as bullish/bearish/neutral"
- Returns: `{direction, score (-1.0 to 1.0), reasoning}`
- Cached in Redis for 45 minutes

#### Model 9: LLM Orchestrator (`telegram_bot/orchestrator.py`)

- Receives all model votes + sentiment + price
- Claude / OpenAI synthesizes into natural language trading report
- Formats: consensus, individual model votes, entry/exit levels, disclaimer

### 4.3 Indicators Library (`models/indicators.py`)

Pure NumPy implementations (no TA-Lib dependency):

| Function | Description |
|----------|-------------|
| `sma(prices, period)` | Simple Moving Average |
| `ema(prices, period)` | Exponential Moving Average |
| `rsi(prices, period=14)` | Relative Strength Index |
| `atr(highs, lows, closes, period=14)` | Average True Range |
| `adx(highs, lows, closes, period=14)` | Average Directional Index |
| `bollinger_bands(closes, period=20, std=2.0)` | Upper, middle, lower bands |
| `detect_crossover(fast, slow, lookback=3)` | Detect MA crossovers |
| `percentile_rank(arr, value)` | Where value ranks in array |
| `get_ema_slope(ema_line, lookback=5)` | Rising/falling direction |

### 4.4 Consensus Voting

```python
# engine.py::compute_consensus(votes)
1. Count BUY, SELL, HOLD across all model votes
2. Majority wins → consensus direction
3. Confidence = winning_count / total_count
4. Example: "5/7 BUY, 1/7 SELL, 1/7 HOLD" → BUY @ 0.71

# Sentiment integration (if cached and non-neutral):
#   Added as 8th vote → re-compute consensus
```

### 4.5 Scheduling

| What | Interval | Details |
|------|----------|---------|
| Ensemble (7 models) | 300s (5 min) | Per symbol, configurable |
| Sentiment (Model 8) | 1800s crypto / 3600s forex | LLM API call |
| Outcome checker | 3600s (1 hour) | Checks 1h/4h/24h prediction accuracy |
| Main loop tick | 60s | Checks if intervals have elapsed |

### 4.6 On-Demand Analysis Endpoint

```
GET /analyze?symbol=AAPL

1. Auto-detect exchange: forex → MT5, crypto → Kraken, stocks → MT5
2. Fetch candles: M15 (300 bars), H1 (200 bars), H4 (200 bars)
3. Run 7 models sequentially → 7 votes
4. Integrate cached sentiment as 8th vote (if available)
5. Compute consensus
6. Write to Redis: ensemble:{SYMBOL}, price:{SYMBOL}
7. Optionally run sentiment if not cached
8. Return JSON: {votes, consensus, confidence, breakdown, updated_at}

Typical latency: 3-7s without sentiment, 20-40s with sentiment
```

### 4.7 Pre-Configured Symbols

| Symbol | Exchange | Type |
|--------|----------|------|
| BTCUSD, ETHUSD, SOLUSD, XRPUSD | Kraken (CCXT) | Crypto |
| EURUSD, GBPUSD, USDJPY | MT5 (PUPrime) | Forex |
| XAUUSD | MT5 (PUPrime) | Commodity |
| AAPL, TSLA, NVDA, MSFT, META | MT5 (PUPrime) | Stock |

Any symbol can also be analyzed on-demand via `/analyze?symbol=XXX` — the engine auto-detects the correct data source.

---

## 5. Price Feed System

### 5.1 Routing Logic (`price_feed.py`)

```
exchange_id == "mt5"    → MT5PriceFeed  → HTTP to MT5 Data Service (port 7777)
exchange_id == "ib"     → IBPriceFeed   → ib_insync to IB Gateway (port 4003)
exchange_id == "kraken" → CCXT Kraken   → Kraken public API
                        → CoinGecko     → Fallback for crypto OHLCV
```

### 5.2 MT5 Data Service (`mt5_price_feed.py`)

- Connects to `MT5_SERVICE_URL` (default: `http://host.docker.internal:7777`)
- Symbol remapping for PUPrime broker:

| Internal | PUPrime Broker |
|----------|---------------|
| XAUUSD | XAUUSD.p |
| XAGUSD | XAGUSD.p |
| XPTUSD | XPTUSD.s |
| EURGBP | EURGBP.p |
| EURJPY | EURJPY.p |
| GBPJPY | GBPJPY.p |
| USDMXN | USDMXN.p |
| NAS100 | NAS100.p |
| SP500 | SP500.p |
| US30 | DJ30.p |
| NVDA | NVIDIA |
| AMZN | AMAZON |
| GOOGL | GOOG |

### 5.3 Current Price Sources (Priority Order)

1. MT5 `/price` endpoint (forex, stocks, commodities)
2. IB Gateway last 15m candle close
3. CoinMarketCap Pro API
4. FreeCryptoAPI
5. Kraken ticker (CCXT)
6. CoinGecko simple/price

---

## 6. Executor Service

**Location:** `/opt/glitchexecutor/executor/`
**Entry point:** `worker.py` → `ExecutionWorker` class

### 6.1 How It Works

```
1. BRPOP from Redis queue "trade_requests" (blocking)
2. Validate: customer tier (Pro+), balance, SL/TP
3. Calculate position size: balance × risk% / SL distance
4. Route to exchange:
   - Crypto → CCXT (Binance, OKX, Kraken, etc.)
   - Forex/Stocks → MT5 Bridge (Windows VM)
5. Execute order
6. Log to PostgreSQL trades table
7. Publish result to Redis: trade_result:{request_id} (60s TTL)
```

### 6.2 Risk Management

- Max 5% balance per trade
- Kelly criterion position sizing
- SL/TP validation before execution
- Mock mode available (`EXECUTOR_MOCK_MODE=true`)

---

## 7. Payment Service

**Location:** `/opt/glitchexecutor/payment/`
**Entry point:** `server.py` (Flask)

### 7.1 Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/api/create-checkout-session` | POST | Create Stripe checkout |
| `/api/stripe/webhook` | POST | Handle Stripe events |
| `/api/stripe/session-status` | GET | Check checkout status |
| `/api/stripe/portal` | POST | Customer billing portal |
| `/api/bot/checkout` | POST | Bot-initiated checkout |
| `/api/trial-signup` | POST | Create trial user |
| `/api/email-signup` | POST | Email lead capture |

### 7.2 Integrations

- **Stripe** — Subscriptions (monthly/yearly), webhooks for payment events
- **Amazon SES** — Transactional email (welcome, receipt, trial expiry)
- **Meta CAPI** — Server-side conversion tracking (purchase events)
- **TikTok CAPI** — Server-side conversion tracking

---

## 8. Admin API

**Location:** `/opt/glitchexecutor/admin_api/`
**Entry point:** `main.py` (FastAPI + Uvicorn)

### 8.1 Route Groups

| Prefix | Module | Key Endpoints |
|--------|--------|---------------|
| `/auth` | `auth.py` | `/login`, `/logout` |
| `/api/dashboard` | `dashboard.py` | `/kpis`, `/stats`, `/mrr` |
| `/api/clients` | `clients.py` | List, detail, tier update |
| `/api/trading` | `trading.py` | Bot profiles, positions |
| `/api/bots` | `bots.py` | Bot list, heartbeats |
| `/api/oracle` | `oracle.py` | Oracle coordinator status |
| `/api/billing` | `billing.py` | Invoices, refunds |
| `/api/infra` | `infra.py` | Docker status, system metrics, logs |
| `/api/analytics` | `analytics.py` | Performance insights |
| `/api/settings` | `settings.py` | Feature flags |

### 8.2 Features

- JWT authentication for admin users
- Live WebSocket for position updates
- Position reconciliation (polls Oracle every 60s)
- Docker container management (via mounted socket)
- Audit logging for all admin actions

---

## 9. Infrastructure & Host Services

### 9.1 MT5 Data Service

```
Service:  mt5-data-service.service (systemd)
Binary:   wine C:\Python310\python.exe /opt/mt5dataservice/mt5server.py
Port:     7777
Broker:   PUPrime-Live (account 23999744)
```

**Endpoints:**
| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Terminal status, broker info |
| `GET /ohlcv?symbol=EURUSD&tf=M15&count=300` | OHLCV bars |
| `GET /price?symbol=EURUSD` | Current bid/ask/last |
| `GET /symbols` | All 954 available symbols |

**Supported timeframes:** M1, M5, M15, M30, H1, H2, H3, H4, H6, H8, H12, D1, W1, MN1

### 9.2 IB Gateway Bridge

```
Service:  ib-gateway-bridge.service (systemd)
Binary:   socat TCP4-LISTEN:4003,reuseaddr,fork TCP4:127.0.0.1:4002
Purpose:  Relay Docker container connections to IB Gateway API
```

### 9.3 Docker Networking

- All services run on `glitchexecutor_default` bridge network
- Host services (MT5, IB) accessed via `host.docker.internal` (set via `extra_hosts: host-gateway`)
- Ports 8100, 5002, 5003 exposed on `127.0.0.1` only (reverse proxied by Nginx)

---

## 10. Database Schema

### Core Tables

```sql
customers
├── id (PK), telegram_id (UNIQUE), username, email
├── token (UUID), tier (trial/starter/pro/elite), status
├── trial_ends_at, stripe_customer_id, stripe_subscription_id
├── queries_today, query_reset_at, referral_code
└── created_at, updated_at

exchange_keys
├── id (PK), customer_id (FK → customers)
├── exchange (binance/okx/kraken/...)
├── api_key_enc, api_secret_enc, extra_enc (Fernet encrypted)
└── is_active, created_at

trades
├── id (PK), customer_id (FK → customers)
├── symbol, direction (BUY/SELL), volume
├── entry_price, sl_price, tp_price
├── ensemble_vote, status (pending/filled/failed), pnl
└── executed_at, closed_at

price_alerts
├── id (PK), customer_id (FK → customers)
├── symbol, target_price, direction (above/below)
└── triggered (bool), created_at

signal_subscriptions
├── id (PK), customer_id (FK → customers)
├── symbol, min_confidence (float)
└── active (bool), created_at

daily_briefing_subs
├── id (PK), customer_id (FK → customers)
├── telegram_id
└── active (bool)

query_log
├── id (PK), customer_id (FK → customers)
├── symbol, query_text, response_type
├── llm_cost_usd
└── created_at

referrals
├── id (PK), referrer_customer_id (FK), referred_customer_id (FK)
├── code, reward_given (bool)
└── created_at
```

### Analytics Tables

```sql
ensemble_predictions
├── id (PK), symbol, predicted_at
├── price_at_prediction, consensus, confidence
├── votes (JSONB), sentiment_direction, sentiment_score
└── created_at

prediction_outcomes
├── id (PK), prediction_id (FK → ensemble_predictions)
├── horizon (1h/4h/24h)
├── price_at_outcome, price_change_pct
├── direction_correct (bool)
└── model_scores (JSONB — per-model accuracy)
```

### Bot/Admin Tables

```sql
bot_positions
├── id (PK), bot (viper3/anaconda/hawk/cobra/mamba/taipan/oracle)
├── symbol, direction, strategy, trigger
├── entry_price, sl, tp, volume, ticket (MT5 ticket)
├── confidence, rsi, atr, adx, h1_trend
├── is_open, exit_reason, trail_count
└── opened_at, closed_at, received_at

bot_heartbeats
├── bot (PK), account, iteration
├── last_seen, details (JSONB)

admin_users
├── id (PK), email (UNIQUE), password_hash
├── role, is_active
└── created_at, last_login

audit_log
├── id (PK), admin_user_id (FK)
├── action, details (JSONB)
└── created_at
```

---

## 11. Redis Key Reference

| Key Pattern | TTL | Written By | Read By | Content |
|-------------|-----|------------|---------|---------|
| `ensemble:{SYMBOL}` | 600s (10 min) | Ensemble | Bot, Admin | `{votes, consensus, confidence, breakdown}` |
| `sentiment:{SYMBOL}` | 2700s (45 min) | Ensemble | Bot | `{direction, score, reasoning}` |
| `price:{SYMBOL}` | 600s (10 min) | Ensemble | Bot, Alerts | Float price |
| `candles:{key}` | 60s | PriceFeed | PriceFeed | OHLCV array (JSON) |
| `paper_trade:{SYMBOL}` | 14400s (4 hrs) | Ensemble | Bot | `{direction, entry_price}` |
| `signal_fired:{CUST}:{SYM}:{DIR}` | 21600s (6 hrs) | Bot | Bot | Dedup flag |
| `trade_requests` | — (list) | Bot | Executor | LPUSH/BRPOP queue |
| `trade_result:{REQUEST_ID}` | 60s | Executor | Bot | Execution result |

---

## 12. Environment Variables

### Database & Cache
| Variable | Default | Used By |
|----------|---------|---------|
| `DATABASE_URL` | `postgresql://glitch:changeme@postgres:5432/glitchexecutor` | Bot, Executor, Payment, Admin |
| `PG_USER` | `glitch` | Postgres container |
| `PG_PASSWORD` | `changeme` | Postgres container |
| `REDIS_HOST` | `redis` / `localhost` | All services |
| `REDIS_PORT` | `6379` | All services |
| `ENCRYPTION_KEY` | — | Bot, Executor (Fernet key) |

### AI & LLM
| Variable | Default | Used By |
|----------|---------|---------|
| `SENTIMENT_LLM_KEY` | — | Ensemble (sentiment) |
| `SENTIMENT_LLM_PROVIDER` | `anthropic` | Ensemble |
| `ORCHESTRATOR_LLM_KEY` | — | Bot (Model 9) |
| `ORCHESTRATOR_LLM_PROVIDER` | `anthropic` | Bot |

### Data Sources
| Variable | Default | Used By |
|----------|---------|---------|
| `MT5_SERVICE_URL` | `http://host.docker.internal:7777` | Ensemble |
| `IB_HOST` | `host.docker.internal` | Ensemble |
| `IB_PORT` | `4003` | Ensemble |
| `COINGECKO_API_KEY` | — | Ensemble |
| `CMC_API_KEY` | — | Ensemble |

### Telegram
| Variable | Default | Used By |
|----------|---------|---------|
| `TELEGRAM_BOT_TOKEN` | — | Bot, Payment |
| `ADMIN_TELEGRAM_ID` | — | Bot |

### Payments
| Variable | Default | Used By |
|----------|---------|---------|
| `STRIPE_SECRET_KEY` | — | Payment |
| `STRIPE_PUBLISHABLE_KEY` | — | Payment |
| `STRIPE_WEBHOOK_SECRET` | — | Payment |

### Execution
| Variable | Default | Used By |
|----------|---------|---------|
| `EXECUTOR_MOCK_MODE` | `true` | Executor |
| `MT5_BRIDGE_URL` | — | Executor |
| `MT5_BRIDGE_KEY` | — | Executor |

---

## 13. Data Flow Diagrams

### 13.1 Analysis Request (End-to-End)

```
User: "/analyze AAPL"
       │
       ▼
  ┌─ TELEGRAM BOT ─────────────────────────────────────────────┐
  │  1. auth.authenticate() → check tier, trial_ends_at        │
  │  2. rate_limiter.check() → queries_today < limit?           │
  │  3. cache.read_votes("AAPL") → Redis HIT or MISS           │
  │     ├─ HIT → skip to step 5                                │
  │     └─ MISS → HTTP GET ensemble:8100/analyze?symbol=AAPL   │
  └────────────────────────────┬────────────────────────────────┘
                               │
                               ▼
  ┌─ ENSEMBLE ENGINE ──────────────────────────────────────────┐
  │  4a. _auto_symbol_config("AAPL") → exchange=mt5, type=stock│
  │  4b. MT5PriceFeed → GET :7777/ohlcv?symbol=AAPL&tf=M15    │
  │      → 300× M15, 200× H1, 200× H4 bars                   │
  │  4c. Run 7 models → 7 votes                                │
  │  4d. Integrate sentiment (if cached) → 8th vote            │
  │  4e. compute_consensus() → BUY/SELL/HOLD + confidence      │
  │  4f. Write to Redis: ensemble:AAPL, price:AAPL             │
  └────────────────────────────┬────────────────────────────────┘
                               │
                               ▼
  ┌─ TELEGRAM BOT (continued) ─────────────────────────────────┐
  │  5. Read ensemble:AAPL + sentiment:AAPL from Redis          │
  │  6. orchestrator.synthesize() → Claude generates report     │
  │  7. Log to ensemble_predictions + query_log                 │
  │  8. Send formatted message to user                          │
  └─────────────────────────────────────────────────────────────┘
```

### 13.2 Trade Execution Flow

```
User taps [Confirm BUY AAPL]
       │
       ▼
  ┌─ TELEGRAM BOT ─────────────────────────────────────────────┐
  │  1. Validate pending_trade (60s expiry)                     │
  │  2. LPUSH trade request to Redis "trade_requests"           │
  │  3. Poll trade_result:{request_id} (timeout 30s)            │
  └────────────────────────────┬────────────────────────────────┘
                               │
                               ▼
  ┌─ EXECUTOR ─────────────────────────────────────────────────┐
  │  4. BRPOP from "trade_requests"                             │
  │  5. Validate customer tier (Pro+)                           │
  │  6. Decrypt exchange API keys from DB                       │
  │  7. Calculate position size (risk-based)                    │
  │  8. Execute via CCXT or MT5 Bridge                          │
  │  9. Log to trades table                                     │
  │ 10. SET trade_result:{request_id} in Redis (60s TTL)        │
  └─────────────────────────────────────────────────────────────┘
```

### 13.3 Scheduled Ensemble Loop

```
Every 60 seconds:
  ┌─ ENGINE.run_once() ────────────────────────────────────────┐
  │  For each symbol in config.SYMBOLS:                         │
  │    ├─ If last_ensemble > 5min ago:                          │
  │    │    run_ensemble() → fetch candles, 7 models, consensus │
  │    │    → write to Redis                                    │
  │    └─ If last_sentiment > 30-60min ago:                     │
  │         run_sentiment() → fetch headlines, LLM classify     │
  │         → write to Redis                                    │
  └─────────────────────────────────────────────────────────────┘

Every 3600 seconds (background thread):
  ┌─ OutcomeChecker ───────────────────────────────────────────┐
  │  For each horizon (1h, 4h, 24h):                            │
  │    Get pending predictions from DB                          │
  │    Compare predicted direction vs actual price change        │
  │    Score each model's accuracy                              │
  │    Write to prediction_outcomes table                        │
  └─────────────────────────────────────────────────────────────┘
```

---

*This document covers the full GlitchExecutor architecture as of March 2026. For deployment and operations, see the docker-compose.yml and systemd service files.*
