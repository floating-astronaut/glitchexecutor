"""
GlitchExecutor Ensemble Engine - MetaTrader 5 Price Feed

Fetches OHLCV candles from the MT5 Data Service (http://172.19.0.1:7777).
The service runs on the host, connects to MT5 terminal via MetaTrader5 Python API.

Supports any symbol available on the broker (forex, stocks, crypto, indices,
commodities — all from a single PUPrime account with no extra subscriptions).
"""
import os
import logging
import numpy as np
import requests
from typing import Optional, Dict

logger = logging.getLogger("MT5PriceFeed")

MT5_SERVICE_URL = os.environ.get("MT5_SERVICE_URL", "http://172.19.0.1:7777")
MT5_TIMEOUT     = int(os.environ.get("MT5_TIMEOUT", "20"))

# Map internal timeframe strings → MT5 timeframe strings
_TF_MAP = {
    "15m": "M15",
    "1h":  "H1",
    "4h":  "H4",
    "1d":  "D1",
}

# How many bars to request per timeframe (generous to cover weekends/gaps)
_TF_BARS = {
    "15m": 350,
    "1h":  220,
    "4h":  220,
    "1d":  100,
}

# Normalise internal symbol names → MT5 broker symbol names
# PUPrime uses non-standard suffixes for some symbols.
_SYMBOL_REMAP: Dict[str, str] = {
    # Forex cross pairs (no plain symbol — require .p suffix on PUPrime)
    "EURGBP":  "EURGBP.p",
    "EURJPY":  "EURJPY.p",
    "GBPJPY":  "GBPJPY.p",
    "USDMXN":  "USDMXN.p",
    # Commodities
    "XAUUSD":  "XAUUSD.p",    # Gold
    "XAGUSD":  "XAGUSD.p",    # Silver
    "XPTUSD":  "XPTUSD.s",    # Platinum
    # Indices
    "NAS100":  "NAS100.p",
    "SP500":   "SP500.p",
    "US30":    "DJ30.p",
    "GER40":   "GER40.p",
    "UK100":   "UK100.p",
    # Stocks — PUPrime uses full company names for some tickers
    "NVDA":    "NVIDIA",
    "AMZN":    "AMAZON",
    "GOOGL":   "GOOG",
}


def _broker_symbol(symbol: str) -> str:
    """Return the MT5 broker symbol name for a given internal symbol."""
    return _SYMBOL_REMAP.get(symbol.upper(), symbol.upper())


class MT5PriceFeed:
    """
    Fetches OHLCV candles from the MT5 Data Service running on the host.

    The service exposes a simple HTTP API:
        GET /ohlcv?symbol=EURUSD&tf=M15&count=350  → JSON { bars: [[time,o,h,l,c,v], ...] }
        GET /price?symbol=EURUSD                   → JSON { last: 1.0823 }
        GET /health                                → JSON { status: "ok", connected: true }
    """

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})
        self._available = self._check_available()

    def _check_available(self) -> bool:
        try:
            r = self._session.get(f"{MT5_SERVICE_URL}/health", timeout=5)
            data = r.json()
            if data.get("status") in ("ok", "reconnected"):
                logger.info(
                    f"MT5PriceFeed ready  service={MT5_SERVICE_URL}  "
                    f"broker={data.get('broker','?')}  account={data.get('account','?')}"
                )
                return True
            logger.warning(f"MT5 service unhealthy: {data}")
            return False
        except Exception as exc:
            logger.warning(f"MT5 data service not reachable at {MT5_SERVICE_URL}: {exc}")
            return False

    def is_available(self) -> bool:
        return self._available

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _fetch_ohlcv(self, symbol: str, tf: str, count: int) -> Optional[np.ndarray]:
        """Fetch OHLCV from the MT5 service and return as numpy [T,O,H,L,C,V]."""
        broker_sym = _broker_symbol(symbol)
        mt5_tf = _TF_MAP.get(tf)
        if not mt5_tf:
            logger.error(f"[MT5] Unknown timeframe: {tf}")
            return None

        try:
            url = f"{MT5_SERVICE_URL}/ohlcv"
            r = self._session.get(url, params={"symbol": broker_sym, "tf": mt5_tf, "count": count},
                                  timeout=MT5_TIMEOUT)
            data = r.json()

            if "error" in data:
                logger.warning(f"[MT5] {symbol} {tf}: {data['error']}")
                return None

            bars = data.get("bars", [])
            if not bars:
                logger.warning(f"[MT5] {symbol} {tf}: empty response")
                return None

            arr = np.array(bars, dtype=float)
            if len(arr) > count:
                arr = arr[-count:]

            logger.info(f"[MT5] {symbol} {tf}: {len(arr)} bars ✓")
            return arr

        except Exception as exc:
            logger.warning(f"[MT5] Fetch failed {symbol} {tf}: {exc}")
            # Try to mark service as unavailable so we don't spam errors
            self._available = self._check_available()
            return None

    # ── Public API ───────────────────────────────────────────────────────────

    def get_candles(self, symbol: str, timeframe: str, limit: int) -> Optional[np.ndarray]:
        """
        Fetch OHLCV candles for a single timeframe.

        Args:
            symbol:    Internal symbol (e.g. 'EURUSD', 'AAPL', 'XAUUSD')
            timeframe: '15m' | '1h' | '4h' | '1d'
            limit:     Maximum number of bars to return

        Returns:
            numpy array [[time(s), open, high, low, close, volume], ...] or None
        """
        if not self._available:
            self._available = self._check_available()
            if not self._available:
                return None

        bars = _TF_BARS.get(timeframe, limit + 50)
        arr = self._fetch_ohlcv(symbol, timeframe, max(bars, limit + 20))
        if arr is not None and len(arr) > limit:
            arr = arr[-limit:]
        return arr

    def get_candles_multi_timeframe(self, symbol: str) -> Dict[str, np.ndarray]:
        """
        Fetch m15, h1, h4 candles. Returns dict with keys 'm15', 'h1', 'h4'.
        """
        if not self._available:
            self._available = self._check_available()
            if not self._available:
                return {}

        result: Dict[str, np.ndarray] = {}

        specs = [
            ("m15", "15m", 300),
            ("h1",  "1h",  200),
            ("h4",  "4h",  200),
        ]

        for key, tf, limit in specs:
            arr = self._fetch_ohlcv(symbol, tf, _TF_BARS.get(tf, limit + 50))
            if arr is not None and len(arr) > 0:
                if len(arr) > limit:
                    arr = arr[-limit:]
                result[key] = arr
            else:
                logger.warning(f"[MT5] {symbol} {tf}: no data")

        return result

    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get the latest bid/ask midpoint price."""
        if not self._available:
            self._available = self._check_available()
            if not self._available:
                return None

        broker_sym = _broker_symbol(symbol)
        try:
            r = self._session.get(f"{MT5_SERVICE_URL}/price",
                                  params={"symbol": broker_sym}, timeout=MT5_TIMEOUT)
            data = r.json()
            if "last" in data:
                return float(data["last"])
            if "error" in data:
                logger.warning(f"[MT5] price {symbol}: {data['error']}")
            return None
        except Exception as exc:
            logger.debug(f"[MT5] get_current_price failed ({symbol}): {exc}")
            return None
