"""
GlitchExecutor Telegram Bot - Database Layer
PostgreSQL connection with asyncpg for async compatibility.
"""
import os
import logging
from typing import Dict, Optional
from datetime import datetime, timedelta

try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    asyncpg = None

logger = logging.getLogger("DB")


class Database:
    """Async PostgreSQL database handler."""
    
    def __init__(self, database_url: str = None):
        """Initialize database connection."""
        self.database_url = database_url or os.environ.get("DATABASE_URL", 
            "postgresql://glitch:password@localhost:5432/glitchexecutor")
        self.pool = None
    
    async def connect(self):
        """Create connection pool."""
        if not ASYNCPG_AVAILABLE:
            logger.error("asyncpg not installed - database disabled")
            return False
        
        try:
            self.pool = await asyncpg.create_pool(
                self.database_url,
                min_size=2,
                max_size=10
            )
            logger.info("Database connected")
            return True
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            return False
    
    async def close(self):
        """Close connection pool."""
        if self.pool:
            await self.pool.close()
    
    async def get_customer(self, telegram_id: int) -> Optional[Dict]:
        """Get customer by Telegram ID."""
        if not self.pool:
            return None
        
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM customers WHERE telegram_id = $1",
                    telegram_id
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting customer: {e}")
            return None
    
    async def create_customer(self, telegram_id: int, username: str = None) -> Optional[Dict]:
        """Create new customer with trial tier."""
        if not self.pool:
            return None
        
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """INSERT INTO customers 
                        (telegram_id, username, tier, status, trial_ends_at) 
                        VALUES ($1, $2, 'trial', 'trial', NOW() + INTERVAL '7 days')
                        RETURNING *""",
                    telegram_id, username
                )
                logger.info(f"Created new customer: {telegram_id}")
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating customer: {e}")
            return None
    
    async def increment_queries(self, customer_id: int) -> int:
        """Increment query count and return new value."""
        if not self.pool:
            return 0
        
        try:
            async with self.pool.acquire() as conn:
                # First, check if we need to reset (new day)
                await conn.execute(
                    """UPDATE customers 
                        SET queries_today = 0, query_reset_at = NOW() + INTERVAL '1 day'
                        WHERE id = $1 AND query_reset_at < NOW()""",
                    customer_id
                )
                
                # Increment
                row = await conn.fetchrow(
                    """UPDATE customers 
                        SET queries_today = queries_today + 1
                        WHERE id = $1
                        RETURNING queries_today""",
                    customer_id
                )
                return row['queries_today'] if row else 0
        except Exception as e:
            logger.error(f"Error incrementing queries: {e}")
            return 0
    
    async def get_queries_today(self, customer_id: int) -> int:
        """Get current query count for customer."""
        if not self.pool:
            return 0
        
        try:
            async with self.pool.acquire() as conn:
                # Check if reset needed
                await conn.execute(
                    """UPDATE customers 
                        SET queries_today = 0, query_reset_at = NOW() + INTERVAL '1 day'
                        WHERE id = $1 AND query_reset_at < NOW()""",
                    customer_id
                )
                
                row = await conn.fetchrow(
                    "SELECT queries_today FROM customers WHERE id = $1",
                    customer_id
                )
                return row['queries_today'] if row else 0
        except Exception as e:
            logger.error(f"Error getting queries: {e}")
            return 0
    
    async def get_customer_by_id(self, customer_id: int) -> Optional[Dict]:
        """Get customer by internal ID."""
        if not self.pool:
            return None

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM customers WHERE id = $1",
                    customer_id
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting customer by ID: {e}")
            return None

    async def get_exchange_keys(self, customer_id: int, exchange: str = 'binance') -> Optional[Dict]:
        """Retrieve and decrypt a customer's stored exchange API keys + passphrase."""
        if not self.pool:
            return None
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT api_key_enc, api_secret_enc, extra_enc FROM exchange_keys
                        WHERE customer_id = $1 AND exchange = $2 AND is_active = true""",
                    customer_id, exchange
                )
                if not row:
                    return None

                enc_key = os.environ.get("ENCRYPTION_KEY", "")
                if not enc_key:
                    raise RuntimeError("ENCRYPTION_KEY environment variable is required — cannot handle exchange keys without it")
                from cryptography.fernet import Fernet
                import json as _json
                f = Fernet(enc_key.encode() if isinstance(enc_key, str) else enc_key)
                api_key    = f.decrypt(bytes(row['api_key_enc'])).decode()
                api_secret = f.decrypt(bytes(row['api_secret_enc'])).decode()
                extra_raw  = f.decrypt(bytes(row['extra_enc'])).decode() if row['extra_enc'] else None

                extra_params = {}
                if extra_raw:
                    try:
                        data = _json.loads(extra_raw)
                        # CCXT uses 'password' for passphrases
                        if 'passphrase' in data:
                            extra_params['password'] = data['passphrase']
                        else:
                            extra_params = data
                    except Exception:
                        pass

                return {'api_key': api_key, 'api_secret': api_secret,
                        'extra_params': extra_params}
        except Exception as e:
            logger.error(f"Error getting exchange keys for customer {customer_id}: {e}")
            return None

    async def log_trade(self, customer_id: int, symbol: str, direction: str,
                        entry_price: float, sl_price: float, tp_price: float,
                        volume: float, ensemble_vote: str, status: str) -> Optional[int]:
        """Log a trade execution to the trades table."""
        if not self.pool:
            return None

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """INSERT INTO trades
                        (customer_id, symbol, direction, entry_price, sl_price,
                         tp_price, volume, ensemble_vote, status, executed_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                        RETURNING id""",
                    customer_id, symbol, direction,
                    entry_price, sl_price, tp_price or 0,
                    volume, ensemble_vote, status
                )
                return row['id'] if row else None
        except Exception as e:
            logger.error(f"Error logging trade: {e}")
            return None

    async def log_query(self, customer_id: int, symbol: str, query_text: str,
                        response_type: str = "analysis", cost_usd: float = 0.0):
        """Log a query for analytics."""
        if not self.pool:
            return

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO query_log
                        (customer_id, symbol, query_text, response_type, llm_cost_usd)
                        VALUES ($1, $2, $3, $4, $5)""",
                    customer_id, symbol, query_text, response_type, cost_usd
                )
        except Exception as e:
            logger.error(f"Error logging query: {e}")
