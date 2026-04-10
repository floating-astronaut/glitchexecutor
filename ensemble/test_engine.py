#!/usr/bin/env python3
"""
GlitchExecutor Ensemble Engine - TEST MODE
Uses mock data to verify all components work.
"""
import os
import sys
import time
import json
import logging
import threading
import numpy as np
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# Import ensemble components
sys.path.insert(0, '/opt/glitchexecutor/ensemble')
from models import (
    TrendFollowerModel,
    MeanReverterModel,
    MomentumHunterModel,
    MLPredictorModel,
    MultiTFAlignModel,
    VolumeProfilerModel,
    SessionAnalystModel
)
from redis_cache import EnsembleCache
from sentiment import SentimentAnalyzer
import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("EnsembleEngine")


def generate_mock_candles(n_bars=300, trend=0.0001, volatility=0.001, seed=42):
    """Generate mock OHLCV data."""
    np.random.seed(seed)
    base_price = 85000
    candles = []
    current_price = base_price
    
    for i in range(n_bars):
        change = np.random.normal(trend * current_price, volatility * current_price)
        open_price = current_price
        close_price = current_price + change
        intrabar_vol = volatility * current_price * 0.5
        high_price = max(open_price, close_price) + abs(np.random.normal(0, intrabar_vol))
        low_price = min(open_price, close_price) - abs(np.random.normal(0, intrabar_vol))
        volume = np.random.uniform(100, 1000) * (1 + abs(change) / (volatility * current_price))
        timestamp = i * 900
        candles.append([timestamp, open_price, high_price, low_price, close_price, volume])
        current_price = close_price
    
    return np.array(candles)


class MockPriceFeed:
    """Mock price feed for testing."""
    
    def get_candles_multi_timeframe(self, symbol, exchange):
        """Return mock candles for all timeframes."""
        # Generate different data for each timeframe
        m15 = generate_mock_candles(300, trend=0.0002, volatility=0.002, seed=hash(symbol) % 10000)
        
        # Aggregate to H1
        h1 = []
        for i in range(0, len(m15) - 3, 4):
            chunk = m15[i:i+4]
            h1.append([chunk[0, 0], chunk[0, 1], max(chunk[:, 2]), min(chunk[:, 3]), chunk[-1, 4], sum(chunk[:, 5])])
        h1 = np.array(h1)
        
        # Aggregate to H4
        h4 = []
        for i in range(0, len(h1) - 3, 4):
            chunk = h1[i:i+4]
            h4.append([chunk[0, 0], chunk[0, 1], max(chunk[:, 2]), min(chunk[:, 3]), chunk[-1, 4], sum(chunk[:, 5])])
        h4 = np.array(h4)
        
        return {'m15': m15, 'h1': h1, 'h4': h4}


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for health checks."""
    
    def log_message(self, format, *args):
        pass
    
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = {
                "status": "ok",
                "timestamp": datetime.utcnow().isoformat()
            }
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()


class EnsembleEngine:
    """Main ensemble engine with mock data for testing."""
    
    def __init__(self):
        logger.info("=" * 60)
        logger.info("GLITCHEXECUTOR ENSEMBLE ENGINE - TEST MODE")
        logger.info("=" * 60)
        
        self.cache = EnsembleCache(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            db=config.REDIS_DB
        )
        
        self.price_feed = MockPriceFeed()
        
        self.models = [
            TrendFollowerModel(),
            MeanReverterModel(),
            MomentumHunterModel(),
            MLPredictorModel(),
            MultiTFAlignModel(),
            VolumeProfilerModel(),
            SessionAnalystModel(),
        ]
        
        self.sentiment_analyzer = SentimentAnalyzer(
            api_key="test",  # Will use mock data
            provider="anthropic"
        )
        
        self.last_ensemble_run = {}
        self.last_sentiment_run = {}
        self.health_server = None
        
        logger.info(f"Loaded {len(self.models)} local models")
        logger.info(f"Monitoring symbols: {list(config.SYMBOLS.keys())}")
        logger.info(f"Redis: {config.REDIS_HOST}:{config.REDIS_PORT}")
    
    def compute_consensus(self, votes):
        """Compute consensus from all model votes."""
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
        
        return {
            "vote": vote,
            "confidence": round(confidence, 2),
            "breakdown": f"{buy_count}/{total} BUY, {sell_count}/{total} SELL, {hold_count}/{total} HOLD"
        }
    
    def run_ensemble(self, symbol, symbol_config):
        """Run all models for a symbol."""
        start_time = time.time()
        
        try:
            logger.info(f"[{symbol}] Fetching mock candles...")
            candles = self.price_feed.get_candles_multi_timeframe(symbol, "binance")
            
            if not candles:
                logger.error(f"[{symbol}] Failed to fetch candles")
                return False
            
            logger.info(f"[{symbol}] Running {len(self.models)} models...")
            
            votes = []
            for model in self.models:
                try:
                    result = model.analyze(symbol, candles)
                    votes.append(result)
                    logger.debug(f"[{symbol}] {model.name}: {result['vote']} ({result['confidence']})")
                except Exception as e:
                    logger.error(f"[{symbol}] Model {model.name} failed: {e}")
                    continue
            
            if not votes:
                logger.error(f"[{symbol}] No models produced valid output")
                return False
            
            consensus = self.compute_consensus(votes)
            self.cache.write_votes(symbol, votes, consensus)
            
            elapsed = time.time() - start_time
            logger.info(f"[{symbol}] Consensus: {consensus['vote']} ({consensus['confidence']}) | {consensus['breakdown']} | {elapsed:.2f}s")
            
            return True
            
        except Exception as e:
            logger.error(f"[{symbol}] Ensemble run failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def run_sentiment(self, symbol):
        """Run sentiment analysis for a symbol."""
        try:
            result = self.sentiment_analyzer.analyze(symbol)
            self.cache.write_sentiment(symbol, result)
            return True
        except Exception as e:
            logger.error(f"[{symbol}] Sentiment analysis failed: {e}")
            return False
    
    def run_once(self):
        """Run one iteration of the ensemble for all symbols."""
        now = datetime.utcnow()
        
        for symbol, symbol_config in config.SYMBOLS.items():
            try:
                # Run ensemble for all symbols immediately (test mode)
                success = self.run_ensemble(symbol, symbol_config)
                if success:
                    self.last_ensemble_run[symbol] = now
                
                # Run sentiment for all symbols
                success = self.run_sentiment(symbol)
                if success:
                    self.last_sentiment_run[symbol] = now
                        
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                continue
    
    def start_health_server(self):
        """Start the health check HTTP server."""
        try:
            self.health_server = HTTPServer(('', 8100), HealthCheckHandler)
            thread = threading.Thread(target=self.health_server.serve_forever, daemon=True)
            thread.start()
            logger.info(f"Health check server started on port 8100")
        except Exception as e:
            logger.error(f"Failed to start health server: {e}")
    
    def run(self):
        """Main loop."""
        logger.info("Starting ensemble engine (TEST MODE)...")
        self.start_health_server()
        
        # Run immediately
        logger.info("Running initial ensemble...")
        self.run_once()
        
        # Continue running every 30 seconds for testing
        logger.info("Entering main loop (30s intervals for testing)...")
        
        cycle = 0
        while cycle < 5:  # Run 5 cycles for testing
            try:
                time.sleep(30)
                self.run_once()
                cycle += 1
            except KeyboardInterrupt:
                logger.info("Shutting down...")
                break
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                time.sleep(10)
        
        logger.info("Test run complete.")


def main():
    engine = EnsembleEngine()
    engine.run()


if __name__ == "__main__":
    main()
