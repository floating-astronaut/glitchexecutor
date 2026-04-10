"""
GlitchExecutor Ensemble Engine - Configuration
"""
import os
from typing import Dict, Any


# Symbol configurations
SYMBOLS = {
    # ── Crypto (Kraken via ccxt) ─────────────────────────────────────────────
    "BTCUSD": {
        "exchange_symbol": "BTC/USDT",
        "exchange": "kraken",
        "type": "crypto",
        "ensemble_interval_seconds": 300,   # 5 minutes
        "sentiment_interval_seconds": 1800, # 30 minutes
    },
    "ETHUSD": {
        "exchange_symbol": "ETH/USDT",
        "exchange": "kraken",
        "type": "crypto",
        "ensemble_interval_seconds": 300,
        "sentiment_interval_seconds": 1800,
    },
    "SOLUSD": {
        "exchange_symbol": "SOL/USDT",
        "exchange": "kraken",
        "type": "crypto",
        "ensemble_interval_seconds": 300,
        "sentiment_interval_seconds": 1800,
    },
    "XRPUSD": {
        "exchange_symbol": "XRP/USDT",
        "exchange": "kraken",
        "type": "crypto",
        "ensemble_interval_seconds": 300,
        "sentiment_interval_seconds": 1800,
    },
    # ── Forex (cTrader Live Account) ─────────────────────────────────────────
    "EURUSD": {
        "exchange_symbol": "EURUSD",
        "exchange": "ctrader",
        "type": "forex",
        "ensemble_interval_seconds": 300,
        "sentiment_interval_seconds": 3600,
    },
    "GBPUSD": {
        "exchange_symbol": "GBPUSD",
        "exchange": "ctrader",
        "type": "forex",
        "ensemble_interval_seconds": 300,
        "sentiment_interval_seconds": 3600,
    },
    "USDJPY": {
        "exchange_symbol": "USDJPY",
        "exchange": "ctrader",
        "type": "forex",
        "ensemble_interval_seconds": 300,
        "sentiment_interval_seconds": 3600,
    },
    # ── Commodities (cTrader Live Account) ───────────────────────────────────
    "XAUUSD": {
        "exchange_symbol": "XAUUSD",
        "exchange": "ctrader",
        "type": "commodity",
        "ensemble_interval_seconds": 300,
        "sentiment_interval_seconds": 3600,
    },
    # ── Stocks (cTrader Live Account) ────────────────────────────────────────
    "AAPL": {
        "exchange_symbol": "AAPL",
        "exchange": "ctrader",
        "type": "stock",
        "ensemble_interval_seconds": 300,
        "sentiment_interval_seconds": 3600,
    },
    "TSLA": {
        "exchange_symbol": "TSLA",
        "exchange": "ctrader",
        "type": "stock",
        "ensemble_interval_seconds": 300,
        "sentiment_interval_seconds": 3600,
    },
    "NVDA": {
        "exchange_symbol": "NVDA",
        "exchange": "ctrader",
        "type": "stock",
        "ensemble_interval_seconds": 300,
        "sentiment_interval_seconds": 3600,
    },
    "MSFT": {
        "exchange_symbol": "MSFT",
        "exchange": "ctrader",
        "type": "stock",
        "ensemble_interval_seconds": 300,
        "sentiment_interval_seconds": 3600,
    },
    "META": {
        "exchange_symbol": "META",
        "exchange": "ctrader",
        "type": "stock",
        "ensemble_interval_seconds": 300,
        "sentiment_interval_seconds": 3600,
    },
}

# Redis configuration
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_DB = int(os.environ.get("REDIS_DB", 0))

# LLM configuration
SENTIMENT_LLM_KEY = os.environ.get("SENTIMENT_LLM_KEY", "")
SENTIMENT_LLM_PROVIDER = os.environ.get("SENTIMENT_LLM_PROVIDER", "anthropic")

# Health check
HEALTH_CHECK_PORT = int(os.environ.get("HEALTH_CHECK_PORT", 8100))

# Logging
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")


def get_symbol_config(symbol: str) -> Dict[str, Any]:
    """Get configuration for a symbol."""
    return SYMBOLS.get(symbol.upper(), SYMBOLS["BTCUSD"])
