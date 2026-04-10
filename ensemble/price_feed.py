"""
GlitchExecutor Ensemble Engine - Price Feed
Primary sources:
  - MT5 Data Service (for symbols with exchange="mt5": forex, stocks, commodities, indices)
  - Interactive Brokers Gateway (for symbols with exchange="ib": forex, stocks, crypto)
  - Kraken via ccxt (for crypto with exchange="kraken")
  - CoinGecko (fallback for crypto)
Current price from CoinMarketCap Pro / FreeCryptoAPI / Kraken / CoinGecko.
"""
import os
import time
import logging
import numpy as np
import requests
from typing import Optional, Dict

from ib_price_feed import IBPriceFeed
from mt5_price_feed import MT5PriceFeed
from ctrader_price_feed import CTraderPriceFeed

try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False
    ccxt = None

logger = logging.getLogger("PriceFeed")


class PriceFeed:
    """Fetches OHLCV data from exchanges with caching support."""

    def __init__(self, cache=None):
        """
        Initialize price feed.

        Args:
            cache: Optional EnsembleCache instance for caching
        """
        self.cache = cache
        self.exchanges = {}
        self.last_request_time = {}
        self.rate_limit_delay = 1.0
        self.coingecko_api_key = os.environ.get("COINGECKO_API_KEY", "")
        self.cmc_api_key = os.environ.get("CMC_API_KEY", "")
        self.freecrypto_token = os.environ.get("FREECRYPTO_TOKEN", "")

        # MT5 Data Service (primary source for forex / stocks / commodities / indices)
        self.mt5_feed = MT5PriceFeed()

        # IB Gateway price feed (secondary source for ib-designated symbols)
        self.ib_feed = IBPriceFeed()

        # cTrader price feed (admin live account — forex, commodities, stocks)
        self.ctrader_feed = CTraderPriceFeed()

        # CoinGecko coin IDs (fallback only)
        self.coin_ids = {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
            "XRP": "ripple",
            "BNB": "binancecoin",
            "ADA": "cardano",
            "DOT": "polkadot",
            "AVAX": "avalanche-2",
            "MATIC": "matic-network",
            "LINK": "chainlink"
        }

    def _get_exchange(self, exchange_id: str):
        """Get or create exchange instance."""
        if not CCXT_AVAILABLE:
            return None

        if exchange_id not in self.exchanges:
            try:
                exchange_class = getattr(ccxt, exchange_id)
                self.exchanges[exchange_id] = exchange_class({
                    'enableRateLimit': True,
                    'options': {
                        'defaultType': 'spot',
                    }
                })
                logger.info(f"Initialized exchange: {exchange_id}")
            except Exception as e:
                logger.error(f"Failed to initialize exchange {exchange_id}: {e}")
                return None
        return self.exchanges.get(exchange_id)

    def _rate_limit(self, exchange_id: str):
        """Enforce rate limiting."""
        now = time.time()
        last_request = self.last_request_time.get(exchange_id, 0)
        elapsed = now - last_request

        if elapsed < self.rate_limit_delay:
            sleep_time = self.rate_limit_delay - elapsed
            time.sleep(sleep_time)

        self.last_request_time[exchange_id] = time.time()

    def _symbol_to_pair(self, symbol: str) -> str:
        """Convert internal symbol (BTCUSD) to exchange pair (BTC/USDT)."""
        if '/' in symbol:
            return symbol
        # Extract base (e.g. BTC from BTCUSD)
        base = symbol[:3].upper() if len(symbol) >= 6 else symbol.upper()
        return f"{base}/USDT"

    def _get_coin_id(self, symbol: str) -> str:
        """Get CoinGecko coin ID from symbol."""
        base = symbol[:3].upper() if len(symbol) >= 6 else symbol.upper()
        return self.coin_ids.get(base, base.lower())

    # ─── OHLCV Sources ─────────────────────────────────────────

    def _fetch_kraken_ohlcv(self, symbol: str, timeframe: str, limit: int) -> Optional[np.ndarray]:
        """Fetch OHLCV from Kraken via ccxt (primary source)."""
        if not CCXT_AVAILABLE:
            return None

        exchange = self._get_exchange("kraken")
        if exchange is None:
            return None

        pair = self._symbol_to_pair(symbol)
        self._rate_limit("kraken")

        try:
            logger.info(f"Fetching {limit} {timeframe} candles for {pair} from Kraken...")
            ohlcv = exchange.fetch_ohlcv(pair, timeframe, limit=limit)

            if not ohlcv or len(ohlcv) == 0:
                logger.warning(f"No data from Kraken for {pair} {timeframe}")
                return None

            candles = np.array(ohlcv, dtype=float)

            if candles.shape[1] != 6:
                logger.error(f"Invalid candle shape from Kraken: {candles.shape}")
                return None

            # Convert timestamps from ms to seconds
            candles[:, 0] = candles[:, 0] / 1000.0

            logger.info(f"Fetched {len(candles)} {timeframe} candles from Kraken for {pair}")
            return candles

        except Exception as e:
            logger.warning(f"Kraken fetch failed for {pair} {timeframe}: {e}")
            return None

    def _fetch_coingecko_ohlc(self, symbol: str, timeframe: str, limit: int) -> Optional[np.ndarray]:
        """Fetch OHLCV from CoinGecko API (fallback)."""
        try:
            coin_id = self._get_coin_id(symbol)

            # Map timeframe to days
            days_map = {
                '15m': 1,
                '1h': 14,
                '4h': 30
            }
            days = days_map.get(timeframe, 14)

            url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
            params = {
                'vs_currency': 'usd',
                'days': days
            }

            headers = {}
            if self.coingecko_api_key:
                headers['x-cg-demo-api-key'] = self.coingecko_api_key

            logger.info(f"Fetching {timeframe} OHLC for {symbol} from CoinGecko (fallback)...")

            response = requests.get(url, params=params, headers=headers, timeout=30)

            if response.status_code == 429:
                logger.warning("CoinGecko rate limit hit, waiting...")
                time.sleep(60)
                return None

            response.raise_for_status()
            data = response.json()

            if not data or len(data) == 0:
                logger.warning(f"No data from CoinGecko for {symbol}")
                return None

            # Convert to our format: [time, open, high, low, close, volume]
            candles = []
            for candle in data:
                timestamp_ms = candle[0]
                open_p = candle[1]
                high_p = candle[2]
                low_p = candle[3]
                close_p = candle[4]
                volume = abs(close_p - open_p) * 1000  # Estimated
                candles.append([timestamp_ms / 1000, open_p, high_p, low_p, close_p, volume])

            candles_array = np.array(candles, dtype=float)

            logger.info(f"Fetched {len(candles_array)} candles from CoinGecko for {symbol}")
            return candles_array

        except requests.exceptions.RequestException as e:
            logger.error(f"CoinGecko request failed: {e}")
            return None
        except Exception as e:
            logger.error(f"CoinGecko fetch error: {e}")
            return None

    # ─── Current Price Sources ──────────────────────────────────

    def _fetch_price_cmc(self, symbol: str) -> Optional[float]:
        """Fetch current price from CoinMarketCap Pro."""
        if not self.cmc_api_key:
            return None
        try:
            base = symbol[:3].upper() if len(symbol) >= 6 else symbol.upper()
            url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
            params = {'symbol': base, 'convert': 'USD'}
            headers = {'X-CMC_PRO_API_KEY': self.cmc_api_key}

            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            return float(data['data'][base]['quote']['USD']['price'])
        except Exception as e:
            logger.debug(f"CMC price fetch failed: {e}")
            return None

    def _fetch_price_freecrypto(self, symbol: str) -> Optional[float]:
        """Fetch current price from FreeCryptoAPI."""
        if not self.freecrypto_token:
            return None
        try:
            base = symbol[:3].upper() if len(symbol) >= 6 else symbol.upper()
            url = f"https://api.freecryptoapi.com/v1/getData?symbol={base}&token={self.freecrypto_token}"

            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get('status') == 'success' and data.get('symbols'):
                return float(data['symbols'][0]['last'])
            return None
        except Exception as e:
            logger.debug(f"FreeCryptoAPI price fetch failed: {e}")
            return None

    def _fetch_price_coingecko(self, symbol: str) -> Optional[float]:
        """Fetch current price from CoinGecko."""
        try:
            coin_id = self._get_coin_id(symbol)
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {'ids': coin_id, 'vs_currencies': 'usd'}

            headers = {}
            if self.coingecko_api_key:
                headers['x-cg-demo-api-key'] = self.coingecko_api_key

            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            return float(data[coin_id]['usd'])
        except Exception as e:
            logger.debug(f"CoinGecko price fetch failed: {e}")
            return None

    # ─── Public API ─────────────────────────────────────────────

    def get_candles(self, symbol: str, timeframe: str, limit: int,
                    exchange_id: str = "kraken") -> Optional[np.ndarray]:
        """
        Fetch OHLCV candles. Kraken primary, CoinGecko fallback.

        Args:
            symbol: Trading pair (e.g., "BTC/USDT" or "BTCUSD")
            timeframe: Candle timeframe ('15m', '1h', '4h')
            limit: Number of bars to fetch
            exchange_id: Primary exchange (default: kraken)

        Returns:
            numpy array of [time, open, high, low, close, volume] or None
        """
        # Check cache first
        cache_key = f"{exchange_id}:{symbol}:{timeframe}:{limit}"
        if self.cache:
            cached = self.cache.get_cached_candles(cache_key)
            if cached is not None:
                logger.debug(f"Using cached candles for {symbol} {timeframe}")
                return cached

        # ── MT5 path (forex, stocks, commodities, indices via PUPrime) ──────────
        if exchange_id == "mt5":
            candles = self.mt5_feed.get_candles(symbol, timeframe, limit)
            if candles is not None and len(candles) > 0:
                if self.cache:
                    self.cache.cache_candles(cache_key, candles, ttl=120)
                return candles
            logger.error(f"[MT5] All sources failed for {symbol} {timeframe}")
            return None

        # ── IB Gateway path (forex, stocks, and IB-designated crypto) ──────────
        if exchange_id == "ib":
            candles = self.ib_feed.get_candles(symbol, timeframe, limit)
            if candles is not None and len(candles) > 0:
                if self.cache:
                    self.cache.cache_candles(cache_key, candles, ttl=120)
                return candles
            logger.error(f"[IB] All sources failed for {symbol} {timeframe}")
            return None

        # ── cTrader path (admin live account — forex, commodities, stocks) ─────────
        if exchange_id == "ctrader":
            candles = self.ctrader_feed.get_candles(symbol, timeframe, limit)
            if candles is not None and len(candles) > 0:
                if self.cache:
                    self.cache.cache_candles(cache_key, candles, ttl=120)
                return candles
            logger.error(f"[cTrader] All sources failed for {symbol} {timeframe}")
            return None

        # ── Kraken / ccxt path (crypto) ─────────────────────────────────────────
        # 1. Try Kraken (primary — real intraday OHLCV)
        candles = self._fetch_kraken_ohlcv(symbol, timeframe, limit)

        if candles is not None and len(candles) > 0:
            if self.cache:
                self.cache.cache_candles(cache_key, candles, ttl=120)
            return candles

        # 2. Fallback to CoinGecko
        logger.warning(f"Kraken failed, trying CoinGecko fallback for {symbol} {timeframe}...")
        candles = self._fetch_coingecko_ohlc(symbol, timeframe, limit)

        if candles is not None and len(candles) > 0:
            if self.cache:
                self.cache.cache_candles(cache_key, candles, ttl=60)
            return candles

        logger.error(f"All OHLCV sources failed for {symbol} {timeframe}")
        return None

    def get_candles_multi_timeframe(self, symbol: str, exchange_id: str = "kraken") -> Dict[str, np.ndarray]:
        """
        Fetch candles for all required timeframes (m15, h1, h4).

        For IB-type symbols: uses a single Gateway session (3 requests, then disconnect).
        For Kraken-type symbols: uses Kraken → CoinGecko fallback per timeframe.

        Returns dict with keys: m15, h1, h4
        """
        # ── MT5 path: single HTTP session, all timeframes ───────────────────────
        if exchange_id == "mt5":
            result = self.mt5_feed.get_candles_multi_timeframe(symbol)
            if result:
                logger.info(f"[MT5] Multi-TF candles fetched for {symbol}: {list(result.keys())}")
            else:
                logger.error(f"[MT5] Failed to fetch any candles for {symbol}")
            return result

        # ── IB path: single session, all timeframes ─────────────────────────────
        if exchange_id == "ib":
            result = self.ib_feed.get_candles_multi_timeframe(symbol)
            if result:
                logger.info(f"[IB] Multi-TF candles fetched for {symbol}: {list(result.keys())}")
            else:
                logger.error(f"[IB] Failed to fetch any candles for {symbol}")
            return result

        # ── cTrader path: single session, all timeframes ─────────────────────────
        if exchange_id == "ctrader":
            result = self.ctrader_feed.get_candles_multi_timeframe(symbol)
            if result:
                logger.info(f"[cTrader] Multi-TF candles fetched for {symbol}: {list(result.keys())}")
            else:
                logger.error(f"[cTrader] Failed to fetch any candles for {symbol}")
            return result

        # ── Kraken / ccxt path: per-timeframe fetch ─────────────────────────────
        result = {}

        # M15: 300 bars
        m15 = self.get_candles(symbol, '15m', 300, exchange_id)
        if m15 is not None:
            result['m15'] = m15

        # H1: 200 bars
        h1 = self.get_candles(symbol, '1h', 200, exchange_id)
        if h1 is not None:
            result['h1'] = h1

        # H4: 200 bars
        h4 = self.get_candles(symbol, '4h', 200, exchange_id)
        if h4 is not None:
            result['h4'] = h4

        return result

    def get_current_price(self, symbol: str, exchange_id: str = "kraken") -> Optional[float]:
        """
        Get current price.
        IB path  : IB Gateway (last 15m close)
        Crypto path: CMC → FreeCrypto → Kraken → CoinGecko
        """
        # 0a. MT5 for MT5-type symbols
        if exchange_id == "mt5":
            price = self.mt5_feed.get_current_price(symbol)
            if price is not None:
                return price
            logger.error(f"[MT5] get_current_price failed for {symbol}")
            return None

        # 0b. IB Gateway for IB-type symbols
        if exchange_id == "ib":
            price = self.ib_feed.get_current_price(symbol)
            if price is not None:
                return price
            logger.error(f"[IB] get_current_price failed for {symbol}")
            return None

        # 0c. cTrader for ctrader-designated symbols
        if exchange_id == "ctrader":
            price = self.ctrader_feed.get_current_price(symbol)
            if price is not None:
                return price
            logger.error(f"[cTrader] get_current_price failed for {symbol}")
            return None

        # 1. CoinMarketCap Pro (fastest, most reliable)
        price = self._fetch_price_cmc(symbol)
        if price is not None:
            return price

        # 2. FreeCryptoAPI
        price = self._fetch_price_freecrypto(symbol)
        if price is not None:
            return price

        # 3. Kraken ticker
        if CCXT_AVAILABLE:
            try:
                exchange = self._get_exchange("kraken")
                if exchange:
                    pair = self._symbol_to_pair(symbol)
                    ticker = exchange.fetch_ticker(pair)
                    if ticker and ticker.get('last'):
                        return float(ticker['last'])
            except Exception as e:
                logger.debug(f"Kraken ticker failed: {e}")

        # 4. CoinGecko fallback
        price = self._fetch_price_coingecko(symbol)
        if price is not None:
            return price

        logger.error(f"All price sources failed for {symbol}")
        return None
