"""
GlitchExecutor Ensemble Engine - Redis Cache
Helper for reading/writing ensemble data to Redis.
"""
import os
import json
import logging
from datetime import datetime
import numpy as np

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None

logger = logging.getLogger("EnsembleCache")


class EnsembleCache:
    """Redis cache for ensemble results and candle data."""
    
    def __init__(self, host='localhost', port=6379, db=0):
        """Initialize Redis connection."""
        self.host = host
        self.port = port
        self.db = db
        self.r = None
        
        if REDIS_AVAILABLE:
            try:
                self.r = redis.Redis(
                    host=host, 
                    port=port, 
                    db=db, 
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5
                )
                # Test connection
                self.r.ping()
                logger.info(f"Connected to Redis at {host}:{port}")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                self.r = None
        else:
            logger.warning("Redis not available - cache disabled")
    
    def is_connected(self) -> bool:
        """Check if Redis is connected."""
        if self.r is None:
            return False
        try:
            self.r.ping()
            return True
        except Exception:
            return False
    
    def _convert_to_native(self, obj):
        """Convert numpy types to Python native types for JSON serialization."""
        if isinstance(obj, np.bool_):
            return bool(obj)
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, dict):
            return {k: self._convert_to_native(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_to_native(i) for i in obj]
        return obj
    
    def write_votes(self, symbol: str, votes: list, consensus: dict):
        """Write ensemble results. TTL = 10 minutes."""
        if self.r is None:
            return False
        
        try:
            key = f"ensemble:{symbol.upper()}"
            data = {
                "votes": self._convert_to_native(votes),
                "consensus": consensus["vote"],
                "confidence": consensus["confidence"],
                "breakdown": consensus.get("breakdown", ""),
                "updated_at": datetime.utcnow().isoformat()
            }
            self.r.setex(key, 600, json.dumps(data))  # 10 min TTL
            logger.debug(f"Cached ensemble data for {symbol}")
            return True
        except Exception as e:
            logger.error(f"Failed to write votes to Redis: {e}")
            return False
    
    def read_votes(self, symbol: str) -> dict:
        """Read cached ensemble results."""
        if self.r is None:
            return None
        
        try:
            data = self.r.get(f"ensemble:{symbol.upper()}")
            return json.loads(data) if data else None
        except Exception as e:
            logger.error(f"Failed to read votes from Redis: {e}")
            return None
    
    def write_sentiment(self, symbol: str, sentiment: dict):
        """Write news sentiment. TTL = 45 minutes."""
        if self.r is None:
            return False
        
        try:
            key = f"sentiment:{symbol.upper()}"
            data = {
                **sentiment,
                "updated_at": datetime.utcnow().isoformat()
            }
            self.r.setex(key, 2700, json.dumps(data))  # 45 min TTL
            logger.info(f"Cached sentiment for {symbol}: {sentiment.get('direction', 'unknown')}")
            return True
        except Exception as e:
            logger.error(f"Failed to write sentiment to Redis: {e}")
            return False
    
    def read_sentiment(self, symbol: str) -> dict:
        """Read cached sentiment."""
        if self.r is None:
            return None
        
        try:
            data = self.r.get(f"sentiment:{symbol.upper()}")
            return json.loads(data) if data else None
        except Exception as e:
            logger.error(f"Failed to read sentiment from Redis: {e}")
            return None
    
    def cache_candles(self, key: str, candles: np.ndarray, ttl: int = 60):
        """Cache raw candle data."""
        if self.r is None:
            return False
        
        try:
            self.r.setex(f"candles:{key}", ttl, json.dumps(candles.tolist()))
            return True
        except Exception as e:
            logger.error(f"Failed to cache candles: {e}")
            return False
    
    def get_cached_candles(self, key: str) -> np.ndarray:
        """Get cached candle data."""
        if self.r is None:
            return None
        
        try:
            data = self.r.get(f"candles:{key}")
            return np.array(json.loads(data)) if data else None
        except Exception as e:
            logger.error(f"Failed to get cached candles: {e}")
            return None
    
    def write_price(self, symbol: str, price: float):
        """Write current price. TTL = 10 minutes."""
        if self.r is None:
            return False
        try:
            self.r.setex(f"price:{symbol.upper()}", 600, str(price))
            return True
        except Exception as e:
            logger.error(f"Failed to write price to Redis: {e}")
            return False

    def read_price(self, symbol: str) -> float:
        """Read cached current price."""
        if self.r is None:
            return None
        try:
            data = self.r.get(f"price:{symbol.upper()}")
            return float(data) if data else None
        except Exception as e:
            logger.error(f"Failed to read price from Redis: {e}")
            return None

    def write_paper_trade(self, symbol: str, direction: str, entry_price: float):
        """Write paper trade for funnel conversion. TTL = 4 hours."""
        if self.r is None:
            return False
        try:
            data = json.dumps({
                "direction": direction,
                "entry_price": entry_price,
                "timestamp": datetime.utcnow().isoformat()
            })
            self.r.setex(f"paper_trade:{symbol.upper()}", 14400, data)
            return True
        except Exception as e:
            logger.error(f"Failed to write paper trade to Redis: {e}")
            return False

    def read_paper_trade(self, symbol: str) -> dict:
        """Read cached paper trade."""
        if self.r is None:
            return None
        try:
            data = self.r.get(f"paper_trade:{symbol.upper()}")
            return json.loads(data) if data else None
        except Exception as e:
            logger.error(f"Failed to read paper trade from Redis: {e}")
            return None

    # ── Conversation History ──────────────────────────────────────────────────

    def append_chat_message(self, telegram_id: int, role: str, content: str,
                            symbol: str = None, had_analysis: bool = False):
        """Append a message to conversation history. Keeps last 10 entries (≈5 exchanges). TTL = 1 hour."""
        if self.r is None:
            return False
        try:
            key = f"chat:{telegram_id}"
            entry = json.dumps({
                "role": role,
                "content": content[:500],  # cap stored content to avoid bloat
                "ts": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "had_analysis": had_analysis,
            })
            pipe = self.r.pipeline()
            pipe.rpush(key, entry)
            pipe.ltrim(key, -10, -1)   # keep last 10 entries
            pipe.expire(key, 3600)     # 1 hour TTL, refreshed on each message
            pipe.execute()
            return True
        except Exception as e:
            logger.error(f"Failed to append chat message: {e}")
            return False

    def get_chat_history(self, telegram_id: int) -> list:
        """Get conversation history for a user. Returns list of dicts."""
        if self.r is None:
            return []
        try:
            key = f"chat:{telegram_id}"
            raw = self.r.lrange(key, 0, -1)
            return [json.loads(entry) for entry in raw] if raw else []
        except Exception as e:
            logger.error(f"Failed to get chat history: {e}")
            return []

    def clear_chat_history(self, telegram_id: int) -> bool:
        """Clear conversation history for a user."""
        if self.r is None:
            return False
        try:
            self.r.delete(f"chat:{telegram_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear chat history: {e}")
            return False

    def get_all_symbols(self) -> list:
        """Get all symbols with cached ensemble data."""
        if self.r is None:
            return []

        try:
            keys = self.r.keys("ensemble:*")
            return [k.replace("ensemble:", "") for k in keys]
        except Exception as e:
            logger.error(f"Failed to get symbols: {e}")
            return []

    def submit_trade(self, trade_request: dict) -> bool:
        """Push trade request onto the executor queue (LPUSH; worker uses BRPOP)."""
        if self.r is None:
            return False
        try:
            self.r.lpush('trade_requests', json.dumps(trade_request))
            logger.info(f"Submitted trade request: {trade_request.get('request_id')}")
            return True
        except Exception as e:
            logger.error(f"Failed to submit trade: {e}")
            return False

    async def poll_trade_result(self, request_id: str, timeout: int = 10) -> dict:
        """Poll trade_result:{request_id} key until the executor writes the result or timeout."""
        import asyncio
        key = f"trade_result:{request_id}"
        end = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < end:
            if self.r is not None:
                try:
                    data = self.r.get(key)
                    if data:
                        return json.loads(data)
                except Exception:
                    pass
            await asyncio.sleep(0.5)
        return None
