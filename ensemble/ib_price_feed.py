"""
GlitchExecutor Ensemble Engine - Interactive Brokers Price Feed

Fetches OHLCV candles directly from IB Gateway (port 4001).
Supports: Crypto (PAXOS), Forex (IDEALPRO), Stocks (SMART).

Used as the primary data source for IB-type symbols (forex, stocks).
Falls back gracefully if IB Gateway is unreachable.
"""
import os
import time
import random
import logging
import numpy as np
from typing import Optional, Dict, Tuple

logger = logging.getLogger("IBPriceFeed")

IB_HOST    = os.environ.get("IB_HOST", "172.17.0.1")
IB_PORT    = int(os.environ.get("IB_PORT", "4001"))
IB_TIMEOUT = int(os.environ.get("IB_TIMEOUT", "15"))

# ── Symbol map: internal name → (sec_type, exchange, currency, ib_symbol, what_to_show)
_SYMBOL_MAP: Dict[str, Tuple[str, str, str, str, str]] = {
    # Crypto (IBKR PAXOS exchange)
    "BTCUSD": ("CRYPTO", "PAXOS",    "USD", "BTC",  "TRADES"),
    "ETHUSD": ("CRYPTO", "PAXOS",    "USD", "ETH",  "TRADES"),
    "SOLUSD": ("CRYPTO", "PAXOS",    "USD", "SOL",  "TRADES"),
    "XRPUSD": ("CRYPTO", "PAXOS",    "USD", "XRP",  "TRADES"),
    # Forex (IDEALPRO)
    "EURUSD": ("CASH",   "IDEALPRO", "USD", "EUR",  "MIDPOINT"),
    "GBPUSD": ("CASH",   "IDEALPRO", "USD", "GBP",  "MIDPOINT"),
    "USDJPY": ("CASH",   "IDEALPRO", "JPY", "USD",  "MIDPOINT"),
    "AUDUSD": ("CASH",   "IDEALPRO", "USD", "AUD",  "MIDPOINT"),
    "USDCAD": ("CASH",   "IDEALPRO", "CAD", "USD",  "MIDPOINT"),
    "USDCHF": ("CASH",   "IDEALPRO", "CHF", "USD",  "MIDPOINT"),
    "NZDUSD": ("CASH",   "IDEALPRO", "USD", "NZD",  "MIDPOINT"),
    "EURGBP": ("CASH",   "IDEALPRO", "GBP", "EUR",  "MIDPOINT"),
    "EURJPY": ("CASH",   "IDEALPRO", "JPY", "EUR",  "MIDPOINT"),
    "GBPJPY": ("CASH",   "IDEALPRO", "JPY", "GBP",  "MIDPOINT"),
    "USDMXN": ("CASH",   "IDEALPRO", "MXN", "USD",  "MIDPOINT"),
    "USDHKD": ("CASH",   "IDEALPRO", "HKD", "USD",  "MIDPOINT"),
    # Commodities — using ETF proxies on SMART (spot metals not available on IDEALPRO)
    "XAUUSD": ("STK",    "SMART",    "USD", "GLD",  "TRADES"),   # Gold → SPDR Gold Trust
    "XAGUSD": ("STK",    "SMART",    "USD", "SLV",  "TRADES"),   # Silver → iShares Silver Trust
    "XPTUSD": ("STK",    "SMART",    "USD", "PPLT", "TRADES"),   # Platinum → Aberdeen Std Phys Plat
    # US Stocks / ETFs (SMART routing)
    "AAPL":   ("STK",    "SMART",    "USD", "AAPL", "TRADES"),
    "NVDA":   ("STK",    "SMART",    "USD", "NVDA", "TRADES"),
    "TSLA":   ("STK",    "SMART",    "USD", "TSLA", "TRADES"),
    "SPY":    ("STK",    "SMART",    "USD", "SPY",  "TRADES"),
    "QQQ":    ("STK",    "SMART",    "USD", "QQQ",  "TRADES"),
    "MSFT":   ("STK",    "SMART",    "USD", "MSFT", "TRADES"),
    "AMZN":   ("STK",    "SMART",    "USD", "AMZN", "TRADES"),
    "GOOGL":  ("STK",    "SMART",    "USD", "GOOGL","TRADES"),
    "META":   ("STK",    "SMART",    "USD", "META", "TRADES"),
}

# IB bar size setting strings
_TIMEFRAME_TO_BAR_SIZE: Dict[str, str] = {
    "15m": "15 mins",
    "1h":  "1 hour",
    "4h":  "4 hours",
    "1d":  "1 day",
}

# Duration strings (generous to cover required bars + weekends/gaps)
# 300 × 15m = 75h ≈ 4 trading days → request 6 calendar days
# 200 × 1h  = 200h ≈ 8-9 trading days → request 15 calendar days
# 200 × 4h  = 800h ≈ 33+ trading days → request 2 months
_TIMEFRAME_TO_DURATION: Dict[str, str] = {
    "15m": "6 D",
    "1h":  "15 D",
    "4h":  "2 M",
}


class IBPriceFeed:
    """
    Fetches OHLCV candles from Interactive Brokers Gateway.

    Design: one IB session per multi-timeframe fetch (connect → 3 requests → disconnect).
    Each timeframe request has a small delay to respect IB pacing limits.
    """

    def __init__(self):
        self._available = False
        try:
            import ib_insync  # noqa: F401 — just checking it's installed
            self._available = True
            logger.info(
                f"IBPriceFeed ready  host={IB_HOST}  port={IB_PORT}  timeout={IB_TIMEOUT}s"
            )
        except ImportError:
            logger.warning("ib_insync not installed — IBPriceFeed disabled")

    # ── Internal helpers ────────────────────────────────────────────────────────

    def _is_available(self) -> bool:
        return self._available

    def _build_contract(self, symbol: str):
        """Return (ib_insync.Contract, what_to_show) for the given internal symbol."""
        from ib_insync import Contract

        info = _SYMBOL_MAP.get(symbol.upper())
        if info:
            sec_type, exchange, currency, ib_sym, what = info
        else:
            # Unknown symbol: best-effort Stock on SMART
            logger.warning(f"[IB] Unknown symbol '{symbol}', defaulting to STK/SMART")
            sec_type, exchange, currency, ib_sym, what = (
                "STK", "SMART", "USD", symbol.upper(), "TRADES"
            )

        contract = Contract(
            secType=sec_type,
            symbol=ib_sym,
            exchange=exchange,
            currency=currency,
        )
        return contract, what

    def _connect(self):
        """
        Create a fresh IB instance, connect to Gateway, and return it.
        Returns None on failure.
        """
        import asyncio
        from ib_insync import IB

        # ib_insync requires an asyncio event loop; HTTP handler threads don't have one
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("closed")
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())

        ib = IB()
        client_id = random.randint(100, 199)
        try:
            ib.connect(
                IB_HOST, IB_PORT,
                clientId=client_id,
                timeout=IB_TIMEOUT,
                readonly=True,
            )
            logger.debug(f"[IB] Connected (clientId={client_id})")
            return ib
        except Exception as exc:
            logger.warning(f"[IB] Gateway connect failed: {exc}")
            try:
                ib.disconnect()
            except Exception:
                pass
            return None

    @staticmethod
    def _bars_to_numpy(bars, limit: int, what_to_show: str) -> Optional[np.ndarray]:
        """Convert a list of ib_insync BarData objects to a numpy [T,O,H,L,C,V] array."""
        if not bars:
            return None

        rows = []
        for b in bars:
            # bar.date is int (epoch seconds) for TRADES, but datetime for MIDPOINT (forex)
            import datetime as _dt
            ts = b.date.timestamp() if isinstance(b.date, _dt.datetime) else float(b.date)
            # Volume: -1 for MIDPOINT bars (not applicable), treat as 0
            vol = float(b.volume) if (b.volume is not None and b.volume >= 0) else 0.0
            rows.append([ts, b.open, b.high, b.low, b.close, vol])

        arr = np.array(rows, dtype=float)

        # Return the most recent `limit` bars
        if len(arr) > limit:
            arr = arr[-limit:]

        return arr

    # ── Public API ──────────────────────────────────────────────────────────────

    def get_candles(self, symbol: str, timeframe: str, limit: int) -> Optional[np.ndarray]:
        """
        Fetch OHLCV candles for a single timeframe.

        Args:
            symbol:    Internal symbol (e.g. 'BTCUSD', 'EURUSD', 'AAPL')
            timeframe: '15m' | '1h' | '4h'
            limit:     Maximum number of bars to return

        Returns:
            numpy array [[time(s), open, high, low, close, volume], ...] or None
        """
        if not self._available:
            return None

        bar_size = _TIMEFRAME_TO_BAR_SIZE.get(timeframe)
        duration = _TIMEFRAME_TO_DURATION.get(timeframe)
        if not bar_size or not duration:
            logger.error(f"[IB] Unsupported timeframe: {timeframe}")
            return None

        ib = self._connect()
        if ib is None:
            return None

        try:
            contract, what_to_show = self._build_contract(symbol)
            logger.info(
                f"[IB] Requesting {symbol} {timeframe} "
                f"bar={bar_size}  dur={duration}  show={what_to_show}"
            )
            bars = ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow=what_to_show,
                useRTH=False,
                formatDate=2,        # epoch seconds
                keepUpToDate=False,
            )
            arr = self._bars_to_numpy(bars, limit, what_to_show)
            if arr is not None:
                logger.info(f"[IB] {symbol} {timeframe}: {len(arr)} bars")
            else:
                logger.warning(f"[IB] No data returned for {symbol} {timeframe}")
            return arr

        except Exception as exc:
            logger.warning(f"[IB] reqHistoricalData failed ({symbol} {timeframe}): {exc}")
            return None
        finally:
            try:
                ib.disconnect()
            except Exception:
                pass

    def get_candles_multi_timeframe(self, symbol: str) -> Dict[str, np.ndarray]:
        """
        Fetch m15, h1, h4 candles in a single IB Gateway session.

        Returns a dict with keys 'm15', 'h1', 'h4' (only those that succeeded).
        """
        if not self._available:
            return {}

        ib = self._connect()
        if ib is None:
            return {}

        result: Dict[str, np.ndarray] = {}
        try:
            contract, what_to_show = self._build_contract(symbol)

            specs = [
                ("m15", "15m", 300),
                ("h1",  "1h",  200),
                ("h4",  "4h",  200),
            ]

            for key, tf, limit in specs:
                bar_size = _TIMEFRAME_TO_BAR_SIZE[tf]
                duration = _TIMEFRAME_TO_DURATION[tf]
                try:
                    bars = ib.reqHistoricalData(
                        contract,
                        endDateTime="",
                        durationStr=duration,
                        barSizeSetting=bar_size,
                        whatToShow=what_to_show,
                        useRTH=False,
                        formatDate=2,
                        keepUpToDate=False,
                    )
                    arr = self._bars_to_numpy(bars, limit, what_to_show)
                    if arr is not None and len(arr) > 0:
                        result[key] = arr
                        logger.info(f"[IB] {symbol} {tf}: {len(arr)} bars ✓")
                    else:
                        logger.warning(f"[IB] {symbol} {tf}: no data")
                except Exception as exc:
                    logger.warning(f"[IB] {symbol} {tf} failed: {exc}")

                # Respect IB pacing (6 identical requests per 2 s; small pause is enough)
                time.sleep(0.6)

        finally:
            try:
                ib.disconnect()
            except Exception:
                pass

        return result

    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        Get the most-recent price by fetching the latest 15-min candle close.
        Lightweight: requests only 1 bar.
        """
        if not self._available:
            return None

        ib = self._connect()
        if ib is None:
            return None

        try:
            contract, what_to_show = self._build_contract(symbol)
            bars = ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr="1800 S",    # last 30 minutes
                barSizeSetting="15 mins",
                whatToShow=what_to_show,
                useRTH=False,
                formatDate=2,
                keepUpToDate=False,
            )
            if bars:
                price = float(bars[-1].close)
                logger.debug(f"[IB] Current price {symbol}: {price}")
                return price
            return None
        except Exception as exc:
            logger.debug(f"[IB] get_current_price failed ({symbol}): {exc}")
            return None
        finally:
            try:
                ib.disconnect()
            except Exception:
                pass
