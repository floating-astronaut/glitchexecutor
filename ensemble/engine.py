"""
GlitchExecutor Ensemble Engine - Main Scheduler
Runs all 7 local models every 5 minutes and sentiment model every 30 minutes.
Exposes GET /analyze?symbol=XXX for on-demand analysis of any symbol.
"""
import os
import sys
import time
import json
import signal
import logging
import threading
from datetime import datetime
from typing import Dict, List
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Import ensemble components
from models import (
    TrendFollowerModel,
    MeanReverterModel,
    MomentumHunterModel,
    MLPredictorModel,
    MultiTFAlignModel,
    VolumeProfilerModel,
    SessionAnalystModel
)
from price_feed import PriceFeed
from sentiment import SentimentAnalyzer
from redis_cache import EnsembleCache
from outcome_checker import OutcomeChecker
import config

# ── Symbol auto-detection ────────────────────────────────────────────────────
# Used by /analyze?symbol=XXX on-demand endpoint to pick the right data source.

_FOREX_PAIRS = frozenset({
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF",
    "NZDUSD", "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "EURCHF",
    "EURAUD", "GBPAUD", "CADJPY", "NZDJPY", "USDNOK", "USDSEK",
    "USDMXN", "USDZAR", "USDSGD", "USDHKD", "USDNZD", "CHFJPY",
    "AUDNZD", "AUDCAD", "EURCAD", "EURNZD", "GBPCAD", "GBPNZD",
    "GBPCHF", "AUDCHF", "CADCHF", "NZDCAD", "NZDCHF", "NZDUSD",
})

_COMMODITY_PAIRS = frozenset({
    "XAUUSD",  # Gold
    "XAGUSD",  # Silver
    "XPTUSD",  # Platinum
    "XPDUSD",  # Palladium
})

_CRYPTO_BASES = frozenset({
    "BTC", "ETH", "SOL", "XRP", "BNB", "ADA", "DOT", "AVAX",
    "MATIC", "LINK", "LTC", "BCH", "DOGE", "SHIB", "UNI", "TON",
    "NEAR", "SUI", "PEPE", "APT", "INJ", "OP", "ARB", "FTM",
    "ATOM", "ALGO", "SAND", "MANA", "AAVE", "CRV", "TRX", "XLM",
    "HBAR", "ICP", "FIL", "VET", "EGLD", "THETA", "AXS", "GALA",
    "FLOW", "EOS", "ZEC", "XMR", "DASH", "NEO", "WAVES", "KAVA",
    "ONE", "ZIL", "IOTA", "BAT", "ENJ", "CHZ", "HOT", "BTT",
    "WIN", "TFUEL", "ANKR", "CELR", "SKL", "OGN", "REEF", "DODO",
})


def _auto_symbol_config(raw_symbol: str) -> dict:
    """
    Auto-detect exchange + config for an arbitrary symbol string.

    Normalisation:
      BTC/USDT → BTCUSD   BTC-USDT → BTCUSD
      BTCUSDT  → BTCUSD   EUR/USD  → EURUSD

    Classification priority:
      1. Forex pair  → MT5 Data Service (PUPrime)
      2. Commodity   → MT5 Data Service (PUPrime)
      3. Crypto base → Kraken (CCXT)
      4. Everything else → MT5 Data Service (stocks/indices)
    """
    s = raw_symbol.upper().strip()

    # Normalise separators: BTC/USDT → BTCUSD, EUR/USD → EURUSD
    for sep in ('/', '-'):
        if sep in s:
            parts = s.split(sep, 1)
            quote = parts[1]
            if quote in ('USDT', 'USDC'):
                s = parts[0] + 'USD'
            elif quote in ('USD', 'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF', 'NZD'):
                s = parts[0] + quote
            break

    # BTCUSDT → BTCUSD
    if s.endswith('USDT') and len(s) > 7:
        s = s[:-1]  # strip trailing T
    # BTCUSDC → BTCUSD
    if s.endswith('USDC') and len(s) > 7:
        s = s[:-2] + 'D'

    # 1. Forex
    if s in _FOREX_PAIRS:
        return {
            "exchange_symbol": s,
            "exchange": "mt5",
            "type": "forex",
            "ensemble_interval_seconds": 300,
            "sentiment_interval_seconds": 3600,
        }

    # 2. Commodity (gold, silver…)
    if s in _COMMODITY_PAIRS:
        return {
            "exchange_symbol": s,
            "exchange": "mt5",
            "type": "commodity",
            "ensemble_interval_seconds": 300,
            "sentiment_interval_seconds": 3600,
        }

    # 3. Crypto ending in USD: BTCUSD, ETHUSD, …
    if s.endswith('USD') and s[:-3] in _CRYPTO_BASES:
        base = s[:-3]
        return {
            "exchange_symbol": f"{base}/USDT",
            "exchange": "kraken",
            "type": "crypto",
            "ensemble_interval_seconds": 300,
            "sentiment_interval_seconds": 1800,
        }

    # 3b. Bare crypto ticker: BTC, ETH, …
    if s in _CRYPTO_BASES:
        return {
            "exchange_symbol": f"{s}/USDT",
            "exchange": "kraken",
            "type": "crypto",
            "ensemble_interval_seconds": 300,
            "sentiment_interval_seconds": 1800,
        }

    # 4. Everything else → MT5 stock/ETF/index
    return {
        "exchange_symbol": s,
        "exchange": "mt5",
        "type": "stock",
        "ensemble_interval_seconds": 300,
        "sentiment_interval_seconds": 3600,
    }


# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("EnsembleEngine")


class HealthCheckHandler(BaseHTTPRequestHandler):
    """HTTP handler for health checks and on-demand analysis."""

    def log_message(self, format, *args):
        # Suppress per-request access logs (engine logs its own output)
        pass

    def _send_json(self, code: int, data: dict):
        body = json.dumps(data, default=str).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path

        # ── GET /health ──────────────────────────────────────────────────────
        if path == '/health':
            last_run = getattr(self.server, 'last_run', None)
            self._send_json(200, {
                "status":    "ok",
                "last_run":  last_run.isoformat() if last_run else None,
                "timestamp": datetime.utcnow().isoformat(),
            })
            return

        # ── GET /analyze?symbol=AAPL ─────────────────────────────────────────
        if path == '/analyze':
            params = parse_qs(parsed.query)
            symbol = params.get('symbol', [''])[0].strip().upper()

            if not symbol:
                self._send_json(400, {"error": "symbol query parameter is required"})
                return

            engine = getattr(self.server, 'engine', None)
            if engine is None:
                self._send_json(500, {"error": "engine reference not set"})
                return

            try:
                result = engine._on_demand_analyze(symbol)
                if result:
                    self._send_json(200, result)
                else:
                    self._send_json(503, {
                        "error": f"Analysis failed for {symbol} — "
                                 "check that MT5 data service is running or symbol is valid"
                    })
            except Exception as exc:
                logger.error(f"[/analyze] Error for {symbol}: {exc}")
                self._send_json(500, {"error": str(exc)})
            return

        self.send_response(404)
        self.end_headers()


class EnsembleEngine:
    """Main ensemble engine that runs models on schedule."""
    
    def __init__(self):
        """Initialize the ensemble engine."""
        logger.info("=" * 60)
        logger.info("GLITCHEXECUTOR ENSEMBLE ENGINE v1.0")
        logger.info("=" * 60)
        
        # Initialize Redis cache
        self.cache = EnsembleCache(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            db=config.REDIS_DB
        )
        
        # Initialize price feed
        self.price_feed = PriceFeed(cache=self.cache)
        
        # Initialize models
        self.models = [
            TrendFollowerModel(),
            MeanReverterModel(),
            MomentumHunterModel(),
            MLPredictorModel(),
            MultiTFAlignModel(),
            VolumeProfilerModel(),
            SessionAnalystModel(),
        ]
        
        # Initialize sentiment analyzer
        self.sentiment_analyzer = SentimentAnalyzer(
            api_key=config.SENTIMENT_LLM_KEY,
            provider=config.SENTIMENT_LLM_PROVIDER
        )
        
        # Track last run times
        self.last_ensemble_run = {}
        self.last_sentiment_run = {}
        self.last_run = None
        
        # Health check server
        self.health_server = None
        
        logger.info(f"Loaded {len(self.models)} local models")
        logger.info(f"Monitoring symbols: {list(config.SYMBOLS.keys())}")
        logger.info(f"Redis: {config.REDIS_HOST}:{config.REDIS_PORT}")
    
    def compute_consensus(self, votes: List[Dict]) -> Dict:
        """Compute consensus from all model votes. Includes bias + key levels for HOLD."""
        buy_count = sum(1 for v in votes if v["vote"] == "BUY")
        sell_count = sum(1 for v in votes if v["vote"] == "SELL")
        hold_count = sum(1 for v in votes if v["vote"] == "HOLD")
        total = len(votes)

        if buy_count > sell_count and buy_count > hold_count:
            vote = "BUY"
            confidence = buy_count / total
        elif sell_count > buy_count and sell_count > hold_count:
            vote = "SELL"
            confidence = sell_count / total
        else:
            vote = "HOLD"
            confidence = hold_count / total

        result = {
            "vote": vote,
            "confidence": round(confidence, 2),
            "breakdown": f"{buy_count}/{total} BUY, {sell_count}/{total} SELL, {hold_count}/{total} HOLD"
        }

        # Add bias and key levels for HOLD signals — actionable guidance
        if vote == "HOLD":
            result["bias"] = self._compute_bias(votes, buy_count, sell_count)
            result["key_levels"] = self._extract_key_levels(votes)

        return result

    def _compute_bias(self, votes: List[Dict], buy_count: int, sell_count: int) -> Dict:
        """Calculate lean direction from minority votes during HOLD consensus."""
        buy_votes = [v for v in votes if v["vote"] == "BUY"]
        sell_votes = [v for v in votes if v["vote"] == "SELL"]

        # Confidence-weighted score
        buy_score = sum(v.get("confidence", 0.5) for v in buy_votes)
        sell_score = sum(v.get("confidence", 0.5) for v in sell_votes)

        if buy_score > sell_score and buy_count > 0:
            direction = "bullish_lean"
            bias_confidence = round(buy_score / (buy_score + sell_score + 0.001), 2)
            supporting = buy_votes
            model_names = [v["model"] for v in buy_votes]
        elif sell_score > buy_score and sell_count > 0:
            direction = "bearish_lean"
            bias_confidence = round(sell_score / (buy_score + sell_score + 0.001), 2)
            supporting = sell_votes
            model_names = [v["model"] for v in sell_votes]
        else:
            direction = "neutral"
            bias_confidence = 0.5
            supporting = []
            model_names = []

        return {
            "direction": direction,
            "confidence": bias_confidence,
            "reasoning": f"{len(model_names)} model(s) lean {'bullish' if direction == 'bullish_lean' else 'bearish' if direction == 'bearish_lean' else 'neutral'} ({', '.join(model_names)})" if model_names else "No directional lean — truly neutral.",
            "supporting_models": [
                {"model": v["model"], "vote": v["vote"], "confidence": v.get("confidence", 0.5), "reasoning": v.get("reasoning", "")}
                for v in supporting
            ]
        }

    def _extract_key_levels(self, votes: List[Dict]) -> Dict:
        """Extract support/resistance levels from model indicators."""
        support_levels = []
        resistance_levels = []
        atr_value = None

        for v in votes:
            indicators = v.get("indicators", {})

            # BB bands from mean_reverter
            if v.get("model") == "mean_reverter":
                bb_lower = indicators.get("bb_lower")
                bb_upper = indicators.get("bb_upper")
                if bb_lower is not None:
                    support_levels.append(round(float(bb_lower), 2))
                if bb_upper is not None:
                    resistance_levels.append(round(float(bb_upper), 2))

            # EMA values from trend_follower
            if v.get("model") == "trend_follower":
                ema_21 = indicators.get("ema_21")
                sma_9 = indicators.get("sma_9")
                atr_val = indicators.get("atr")
                if ema_21 is not None:
                    support_levels.append(round(float(ema_21), 2))
                if sma_9 is not None:
                    resistance_levels.append(round(float(sma_9), 2))
                if atr_val is not None:
                    atr_value = round(float(atr_val), 2)

            # EMA from momentum_hunter
            if v.get("model") == "momentum_hunter":
                ema_20 = indicators.get("ema_20")
                if ema_20 is not None:
                    # Use as support or resistance based on price position
                    if indicators.get("price_above_ema"):
                        support_levels.append(round(float(ema_20), 2))
                    else:
                        resistance_levels.append(round(float(ema_20), 2))

        # Sort and deduplicate
        support_levels = sorted(set(support_levels))
        resistance_levels = sorted(set(resistance_levels))

        return {
            "support": support_levels[-2:] if len(support_levels) > 2 else support_levels,  # top 2 nearest
            "resistance": resistance_levels[:2] if len(resistance_levels) > 2 else resistance_levels,  # bottom 2 nearest
            "atr": atr_value
        }
    
    def run_ensemble(self, symbol: str, symbol_config: Dict):
        """Run all models for a symbol."""
        start_time = time.time()
        
        try:
            # Fetch candles
            exchange_symbol = symbol_config["exchange_symbol"]
            exchange = symbol_config["exchange"]
            
            logger.info(f"[{symbol}] Fetching candles from {exchange}...")
            candles = self.price_feed.get_candles_multi_timeframe(
                exchange_symbol, exchange
            )
            
            if not candles:
                logger.error(f"[{symbol}] Failed to fetch candles - skipping")
                return False
            
            logger.info(f"[{symbol}] Running {len(self.models)} models...")
            
            # Run all active models
            votes = []
            for model in self.models:
                # Skip deactivated models (e.g., ML Predictor placeholder)
                if not getattr(model, 'active', True):
                    logger.debug(f"[{symbol}] {model.name}: SKIPPED (deactivated)")
                    continue
                try:
                    result = model.analyze(symbol, candles)
                    votes.append(result)
                    logger.debug(f"[{symbol}] {model.name}: {result['vote']} ({result['confidence']})")
                except Exception as e:
                    logger.error(f"[{symbol}] Model {model.name} failed: {e}")
                    # Continue with other models - don't let one failure stop everything
                    continue
            
            if not votes:
                logger.error(f"[{symbol}] No models produced valid output")
                return False
            
            # Compute consensus
            consensus = self.compute_consensus(votes)
            
            # Integrate sentiment as a vote (Model 8) if available
            cached_sentiment = self.cache.read_sentiment(symbol)
            if cached_sentiment and cached_sentiment.get('direction') != 'neutral':
                sentiment_vote = "BUY" if cached_sentiment['direction'] == 'bullish' else "SELL"
                sentiment_confidence = min(abs(cached_sentiment.get('score', 0)), 1.0)
                votes.append({
                    "model": "sentiment",
                    "vote": sentiment_vote,
                    "confidence": round(sentiment_confidence, 2),
                    "reasoning": cached_sentiment.get('reasoning', 'News sentiment analysis'),
                    "indicators": {"direction": cached_sentiment['direction'], "score": cached_sentiment.get('score', 0)}
                })

            # Compute consensus
            consensus = self.compute_consensus(votes)

            # Store in Redis
            self.cache.write_votes(symbol, votes, consensus)

            # Cache current price for bot to read
            if candles.get('m15') is not None and len(candles['m15']) > 0:
                current_price = float(candles['m15'][-1][4])  # close price of last candle
                self.cache.write_price(symbol, current_price)

                # Cache paper trade for Starter funnel conversion
                if consensus['vote'] in ['BUY', 'SELL']:
                    self.cache.write_paper_trade(symbol, consensus['vote'], current_price)

            elapsed = time.time() - start_time
            logger.info(f"[{symbol}] Consensus: {consensus['vote']} ({consensus['confidence']}) | {consensus['breakdown']} | {elapsed:.2f}s")

            return True
            
        except Exception as e:
            logger.error(f"[{symbol}] Ensemble run failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def run_sentiment(self, symbol: str):
        """Run sentiment analysis for a symbol."""
        try:
            result = self.sentiment_analyzer.analyze(symbol)
            self.cache.write_sentiment(symbol, result)
            return True
        except Exception as e:
            logger.error(f"[{symbol}] Sentiment analysis failed: {e}")
            return False

    def _on_demand_analyze(self, raw_symbol: str) -> dict:
        """
        Run the full ensemble for any symbol on-demand.

        If the symbol is in the pre-configured SYMBOLS dict, uses that config.
        Otherwise auto-detects: forex/stocks → IB Gateway, crypto → Kraken.

        Sentiment is run only if no recent cached sentiment exists.

        Returns the result dict written to Redis, or {} on failure.
        """
        symbol = raw_symbol.upper().strip()

        # Choose config: pre-configured takes priority
        if symbol in config.SYMBOLS:
            symbol_config = config.SYMBOLS[symbol]
            logger.info(f"[on-demand] {symbol} — using pre-configured profile")
        else:
            symbol_config = _auto_symbol_config(symbol)
            logger.info(
                f"[on-demand] {symbol} — auto-detected: "
                f"exchange={symbol_config['exchange']}  type={symbol_config['type']}"
            )

        # Run 7-model ensemble
        success = self.run_ensemble(symbol, symbol_config)

        if not success:
            logger.error(f"[on-demand] Ensemble failed for {symbol}")
            return {}

        # Run sentiment only when not already cached (avoid 30-60 s delay every call)
        cached_sentiment = self.cache.read_sentiment(symbol)
        if not cached_sentiment:
            logger.info(f"[on-demand] Running sentiment for {symbol}...")
            try:
                self.run_sentiment(symbol)
            except Exception as exc:
                logger.warning(f"[on-demand] Sentiment skipped for {symbol}: {exc}")

        result = self.cache.read_votes(symbol)
        return result or {}

    def run_once(self):
        """Run one iteration of the ensemble for all symbols."""
        now = datetime.utcnow()
        self.last_run = now
        
        logger.debug("Starting ensemble run cycle")
        
        for symbol, symbol_config in config.SYMBOLS.items():
            try:
                # Check if we need to run ensemble
                last_ensemble = self.last_ensemble_run.get(symbol)
                ensemble_interval = symbol_config["ensemble_interval_seconds"]
                
                if last_ensemble is None or (now - last_ensemble).total_seconds() >= ensemble_interval:
                    success = self.run_ensemble(symbol, symbol_config)
                    if success:
                        self.last_ensemble_run[symbol] = now
                
                # Check if we need to run sentiment
                last_sentiment = self.last_sentiment_run.get(symbol)
                sentiment_interval = symbol_config["sentiment_interval_seconds"]
                
                if last_sentiment is None or (now - last_sentiment).total_seconds() >= sentiment_interval:
                    success = self.run_sentiment(symbol)
                    if success:
                        self.last_sentiment_run[symbol] = now
                        
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                continue  # Continue with next symbol
    
    def start_health_server(self):
        """Start the health check HTTP server (also serves /analyze on-demand endpoint)."""
        try:
            self.health_server = HTTPServer(('', config.HEALTH_CHECK_PORT), HealthCheckHandler)
            self.health_server.last_run = None
            self.health_server.engine  = self   # expose engine to handler

            def serve():
                while True:
                    try:
                        self.health_server.handle_request()
                        self.health_server.last_run = self.last_run
                    except Exception as e:
                        logger.error(f"Health server error: {e}")

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            logger.info(
                f"Health/analyze server started on port {config.HEALTH_CHECK_PORT} "
                f"(GET /health  |  GET /analyze?symbol=XXX)"
            )
            
        except Exception as e:
            logger.error(f"Failed to start health server: {e}")
    
    def run(self):
        """Main loop - runs indefinitely."""
        logger.info("Starting ensemble engine...")

        # Graceful shutdown handler
        self._shutdown = False
        def handle_shutdown(signum, frame):
            logger.info(f"Received signal {signum}, shutting down gracefully...")
            self._shutdown = True
        signal.signal(signal.SIGTERM, handle_shutdown)
        signal.signal(signal.SIGINT, handle_shutdown)

        # Start health check server
        self.start_health_server()

        # Start ML outcome checker (hourly background thread)
        outcome_checker = OutcomeChecker(self.cache)
        outcome_checker.start_background_thread(interval_seconds=3600)

        # Initial run immediately
        logger.info("Running initial ensemble...")
        self.run_once()

        # Main loop - check every 60 seconds (scheduler handles actual intervals)
        logger.info("Entering main loop (checking every 60s, ensemble runs every 300s)...")

        while not self._shutdown:
            try:
                time.sleep(60)  # Check every minute
                if not self._shutdown:
                    self.run_once()

            except KeyboardInterrupt:
                logger.info("Keyboard interrupt, shutting down...")
                break
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                time.sleep(30)

        logger.info("Ensemble engine stopped.")


def main():
    """Main entry point."""
    engine = EnsembleEngine()
    engine.run()


if __name__ == "__main__":
    main()
