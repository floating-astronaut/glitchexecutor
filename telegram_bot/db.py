"""
GlitchExecutor Telegram Bot - Database Layer
PostgreSQL connection with asyncpg for async compatibility.
"""
import os
import json
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
    
    async def store_mt5_credentials(self, customer_id: int, server: str,
                                    login: str, password: str) -> bool:
        """Store encrypted MT5 credentials for Elite tier users."""
        if not self.pool:
            return False

        try:
            # Encrypt credentials using Fernet
            import os
            enc_key = os.environ.get("ENCRYPTION_KEY", "")
            if enc_key:
                from cryptography.fernet import Fernet
                f = Fernet(enc_key.encode() if isinstance(enc_key, str) else enc_key)
                cred_data = json.dumps({"server": server, "login": login, "password": password})
                encrypted = f.encrypt(cred_data.encode())
            else:
                raise RuntimeError("ENCRYPTION_KEY environment variable is required — cannot handle exchange keys without it")

            async with self.pool.acquire() as conn:
                # Upsert: update if exists, insert if not
                await conn.execute(
                    """INSERT INTO exchange_keys (customer_id, exchange, api_key_enc, api_secret_enc, is_active)
                        VALUES ($1, 'mt5', $2, $2, true)
                        ON CONFLICT (customer_id, exchange)
                        DO UPDATE SET api_key_enc = $2, is_active = true""",
                    customer_id, encrypted
                )
                logger.info(f"MT5 credentials stored for customer {customer_id}")
                return True
        except Exception as e:
            logger.error(f"Error storing MT5 credentials: {e}")
            return False

    def _get_fernet(self):
        """Return a Fernet instance if ENCRYPTION_KEY is set, else None."""
        enc_key = os.environ.get("ENCRYPTION_KEY", "")
        if not enc_key:
            return None
        from cryptography.fernet import Fernet
        return Fernet(enc_key.encode() if isinstance(enc_key, str) else enc_key)

    async def store_exchange_keys(self, customer_id: int, exchange: str,
                                   api_key: str, api_secret: str,
                                   passphrase: str = None) -> bool:
        """Store encrypted exchange API keys (upsert). Passphrase optional."""
        if not self.pool:
            return False
        try:
            f = self._get_fernet()
            if f:
                api_key_enc    = f.encrypt(api_key.encode())
                api_secret_enc = f.encrypt(api_secret.encode())
                extra_enc = f.encrypt(
                    json.dumps({"passphrase": passphrase}).encode()
                ) if passphrase else None
            else:
                raise RuntimeError("ENCRYPTION_KEY environment variable is required — cannot handle exchange keys without it")

            async with self.pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO exchange_keys
                        (customer_id, exchange, api_key_enc, api_secret_enc, extra_enc, is_active)
                        VALUES ($1, $2, $3, $4, $5, true)
                        ON CONFLICT (customer_id, exchange)
                        DO UPDATE SET api_key_enc = $3, api_secret_enc = $4,
                                      extra_enc = $5, is_active = true""",
                    customer_id, exchange, api_key_enc, api_secret_enc, extra_enc
                )
                logger.info(f"Exchange keys stored for customer {customer_id} ({exchange})")
                return True
        except Exception as e:
            logger.error(f"Error storing exchange keys: {e}")
            return False

    async def get_exchange_keys(self, customer_id: int, exchange: str) -> Optional[Dict]:
        """Retrieve and decrypt exchange API keys including passphrase if set."""
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

                f = self._get_fernet()
                if not f:
                    raise RuntimeError("ENCRYPTION_KEY environment variable is required — cannot handle exchange keys without it")
                api_key    = f.decrypt(bytes(row['api_key_enc'])).decode()
                api_secret = f.decrypt(bytes(row['api_secret_enc'])).decode()
                extra_raw  = f.decrypt(bytes(row['extra_enc'])).decode() if row['extra_enc'] else None

                extra_params = {}
                if extra_raw:
                    try:
                        extra_params = json.loads(extra_raw)
                        # CCXT uses 'password' for passphrases
                        if 'passphrase' in extra_params:
                            extra_params['password'] = extra_params.pop('passphrase')
                    except Exception:
                        pass

                return {'api_key': api_key, 'api_secret': api_secret,
                        'extra_params': extra_params}
        except Exception as e:
            logger.error(f"Error getting exchange keys: {e}")
            return None

    async def delete_exchange_keys(self, customer_id: int, exchange: str) -> bool:
        """Deactivate exchange API keys."""
        if not self.pool:
            return False
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """UPDATE exchange_keys SET is_active = false
                        WHERE customer_id = $1 AND exchange = $2""",
                    customer_id, exchange
                )
                return True
        except Exception as e:
            logger.error(f"Error deleting exchange keys: {e}")
            return False


    async def store_ctrader_credentials(self, customer_id: int, client_id: str,
                                        client_secret: str, access_token: str,
                                        account_id: int, live: bool = True) -> bool:
        """Store encrypted cTrader OAuth credentials for a customer."""
        extra = json.dumps({
            "access_token": access_token,
            "account_id": account_id,
            "live": live
        })
        return await self.store_exchange_keys(
            customer_id, "ctrader", client_id, client_secret, passphrase=extra
        )

    async def get_ctrader_credentials(self, customer_id: int):
        """Retrieve and decrypt cTrader credentials. Returns dict or None."""
        if not self.pool:
            return None
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT api_key_enc, api_secret_enc, extra_enc FROM exchange_keys
                        WHERE customer_id = $1 AND exchange = 'ctrader' AND is_active = true""",
                    customer_id
                )
                if not row:
                    return None

                f = self._get_fernet()
                if not f:
                    raise RuntimeError("ENCRYPTION_KEY required")

                client_id     = f.decrypt(bytes(row['api_key_enc'])).decode()
                client_secret = f.decrypt(bytes(row['api_secret_enc'])).decode()
                extra         = json.loads(f.decrypt(bytes(row['extra_enc'])).decode()) if row['extra_enc'] else {}

                return {
                    "client_id":     client_id,
                    "client_secret": client_secret,
                    "access_token":  extra.get("access_token", ""),
                    "account_id":    int(extra.get("account_id", 0)),
                    "live":          bool(extra.get("live", True)),
                }
        except Exception as e:
            logger.error(f"Error getting cTrader credentials: {e}")
            return None

    async def get_connected_exchanges(self, customer_id: int) -> list:
        """Get list of active connected exchanges for a customer."""
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT exchange FROM exchange_keys
                        WHERE customer_id = $1 AND is_active = true
                        AND exchange != 'mt5'""",
                    customer_id
                )
                return [row['exchange'] for row in rows]
        except Exception as e:
            logger.error(f"Error getting connected exchanges: {e}")
            return []

    # ── User Preferences ─────────────────────────────────────────────────────

    async def ensure_user_preferences_table(self):
        """Create user_preferences table if it doesn't exist."""
        if not self.pool:
            return False
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS user_preferences (
                        id              SERIAL PRIMARY KEY,
                        customer_id     INT UNIQUE REFERENCES customers(id) ON DELETE CASCADE,
                        favorite_symbols TEXT[] DEFAULT '{}',
                        default_market  VARCHAR(20) DEFAULT NULL,
                        created_at      TIMESTAMP DEFAULT NOW(),
                        updated_at      TIMESTAMP DEFAULT NOW()
                    )
                """)
                # Strong signal + auto-execute columns
                await conn.execute("""
                    ALTER TABLE user_preferences
                        ADD COLUMN IF NOT EXISTS strong_signal_notify BOOLEAN DEFAULT TRUE
                """)
                await conn.execute("""
                    ALTER TABLE user_preferences
                        ADD COLUMN IF NOT EXISTS auto_execute_enabled BOOLEAN DEFAULT FALSE
                """)
                logger.info("user_preferences table ensured")
                return True
        except Exception as e:
            logger.error(f"Error creating user_preferences table: {e}")
            return False

    async def get_user_preferences(self, customer_id: int) -> Optional[Dict]:
        """Get user preferences."""
        if not self.pool:
            return None
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM user_preferences WHERE customer_id = $1",
                    customer_id
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting user preferences: {e}")
            return None

    async def upsert_user_preferences(self, customer_id: int,
                                       favorite_symbols: list = None,
                                       default_market: str = None) -> bool:
        """Create or update user preferences."""
        if not self.pool:
            return False
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO user_preferences (customer_id, favorite_symbols, default_market)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (customer_id) DO UPDATE SET
                        favorite_symbols = COALESCE($2, user_preferences.favorite_symbols),
                        default_market = COALESCE($3, user_preferences.default_market),
                        updated_at = NOW()
                """, customer_id, favorite_symbols or [], default_market)
                return True
        except Exception as e:
            logger.error(f"Error upserting user preferences: {e}")
            return False

    async def add_favorite_symbol(self, customer_id: int, symbol: str) -> bool:
        """Add a symbol to user's favorites (dedup)."""
        if not self.pool:
            return False
        try:
            symbol = symbol.upper()
            async with self.pool.acquire() as conn:
                # Ensure row exists first
                await conn.execute("""
                    INSERT INTO user_preferences (customer_id)
                    VALUES ($1) ON CONFLICT (customer_id) DO NOTHING
                """, customer_id)
                # Add symbol if not already present
                await conn.execute("""
                    UPDATE user_preferences
                    SET favorite_symbols = array_append(
                        array_remove(favorite_symbols, $2), $2
                    ), updated_at = NOW()
                    WHERE customer_id = $1
                """, customer_id, symbol)
                return True
        except Exception as e:
            logger.error(f"Error adding favorite symbol: {e}")
            return False

    async def remove_favorite_symbol(self, customer_id: int, symbol: str) -> bool:
        """Remove a symbol from user's favorites."""
        if not self.pool:
            return False
        try:
            symbol = symbol.upper()
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    UPDATE user_preferences
                    SET favorite_symbols = array_remove(favorite_symbols, $2),
                        updated_at = NOW()
                    WHERE customer_id = $1
                """, customer_id, symbol)
                return True
        except Exception as e:
            logger.error(f"Error removing favorite symbol: {e}")
            return False

    async def get_favorite_symbols(self, customer_id: int) -> list:
        """Get user's favorite symbols."""
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT favorite_symbols FROM user_preferences WHERE customer_id = $1",
                    customer_id
                )
                return list(row['favorite_symbols']) if row and row['favorite_symbols'] else []
        except Exception as e:
            logger.error(f"Error getting favorite symbols: {e}")
            return []

    async def get_users_with_favorite_symbol(self, symbol: str) -> list:
        """Get all users who favorited a symbol and have strong signal notifications enabled."""
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT up.customer_id, c.telegram_id, c.tier,
                           up.auto_execute_enabled
                    FROM user_preferences up
                    JOIN customers c ON c.id = up.customer_id
                    WHERE $1 = ANY(up.favorite_symbols)
                      AND COALESCE(up.strong_signal_notify, TRUE) = TRUE
                      AND c.status NOT IN ('cancelled', 'suspended')
                """, symbol.upper())
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error getting users with favorite symbol {symbol}: {e}")
            return []

    async def set_auto_execute(self, customer_id: int, enabled: bool) -> bool:
        """Enable or disable auto-execute on strong signals for a customer."""
        if not self.pool:
            return False
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO user_preferences (customer_id, auto_execute_enabled)
                    VALUES ($1, $2)
                    ON CONFLICT (customer_id) DO UPDATE SET
                        auto_execute_enabled = $2, updated_at = NOW()
                """, customer_id, enabled)
                return True
        except Exception as e:
            logger.error(f"Error setting auto_execute for customer {customer_id}: {e}")
            return False

    async def get_auto_execute_status(self, customer_id: int) -> dict:
        """Get auto-execute status and favorites for a customer."""
        if not self.pool:
            return {'enabled': False, 'favorites': []}
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT COALESCE(auto_execute_enabled, FALSE) AS auto_execute_enabled,
                           favorite_symbols
                    FROM user_preferences WHERE customer_id = $1
                """, customer_id)
                if not row:
                    return {'enabled': False, 'favorites': []}
                return {
                    'enabled': row['auto_execute_enabled'] or False,
                    'favorites': list(row['favorite_symbols']) if row['favorite_symbols'] else []
                }
        except Exception as e:
            logger.error(f"Error getting auto_execute status: {e}")
            return {'enabled': False, 'favorites': []}

    async def log_ensemble_prediction(self, symbol: str, price: float,
                                      consensus: str, confidence: float,
                                      votes: list, sentiment_direction: str = None,
                                      sentiment_score: float = None,
                                      triggered_by: int = None) -> Optional[int]:
        """Log an ensemble prediction for ML outcome tracking."""
        if not self.pool:
            return None
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """INSERT INTO ensemble_predictions
                        (symbol, price_at_prediction, consensus, consensus_confidence,
                         votes, sentiment_direction, sentiment_score, triggered_by)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                       RETURNING id""",
                    symbol, price, consensus, confidence,
                    json.dumps(votes), sentiment_direction, sentiment_score, triggered_by
                )
                return row['id'] if row else None
        except Exception as e:
            logger.error(f"Error logging ensemble prediction: {e}")
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

    # ── Price Alerts ─────────────────────────────────────────────────────────

    async def create_price_alert(self, customer_id: int, telegram_id: int,
                                  symbol: str, target_price: float,
                                  direction: str) -> Optional[int]:
        """Create a price alert. Returns new alert ID or None."""
        if not self.pool:
            return None
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """INSERT INTO price_alerts
                        (customer_id, telegram_id, symbol, target_price, direction)
                        VALUES ($1, $2, $3, $4, $5) RETURNING id""",
                    customer_id, telegram_id, symbol, target_price, direction
                )
                return row['id'] if row else None
        except Exception as e:
            logger.error(f"Error creating price alert: {e}")
            return None

    async def get_active_price_alerts(self) -> list:
        """Get all untriggered price alerts (for background job)."""
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM price_alerts WHERE triggered = FALSE ORDER BY id"
                )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error fetching active price alerts: {e}")
            return []

    async def get_user_price_alerts(self, customer_id: int) -> list:
        """Get untriggered price alerts for a specific customer."""
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT * FROM price_alerts
                        WHERE customer_id = $1 AND triggered = FALSE
                        ORDER BY created_at DESC""",
                    customer_id
                )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error fetching user price alerts: {e}")
            return []

    async def count_user_price_alerts(self, customer_id: int) -> int:
        """Count active price alerts for a user."""
        if not self.pool:
            return 0
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS n FROM price_alerts WHERE customer_id = $1 AND triggered = FALSE",
                    customer_id
                )
                return row['n'] if row else 0
        except Exception as e:
            logger.error(f"Error counting price alerts: {e}")
            return 0

    async def mark_price_alert_triggered(self, alert_id: int):
        """Mark a price alert as triggered."""
        if not self.pool:
            return
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE price_alerts SET triggered = TRUE WHERE id = $1", alert_id
                )
        except Exception as e:
            logger.error(f"Error marking alert triggered: {e}")

    async def delete_price_alert(self, customer_id: int, alert_id: int) -> bool:
        """Delete a price alert owned by the customer."""
        if not self.pool:
            return False
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM price_alerts WHERE id = $1 AND customer_id = $2",
                    alert_id, customer_id
                )
                return result.split()[-1] == '1'
        except Exception as e:
            logger.error(f"Error deleting price alert: {e}")
            return False

    # ── Signal Subscriptions ─────────────────────────────────────────────────

    async def upsert_signal_sub(self, customer_id: int, telegram_id: int,
                                 symbol: str, min_confidence: float = 0.6) -> bool:
        """Subscribe (or update) signal alerts for a symbol."""
        if not self.pool:
            return False
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO signal_subscriptions
                        (customer_id, telegram_id, symbol, min_confidence, active)
                        VALUES ($1, $2, $3, $4, TRUE)
                        ON CONFLICT (customer_id, symbol)
                        DO UPDATE SET min_confidence = $4, active = TRUE,
                                      telegram_id = $2""",
                    customer_id, telegram_id, symbol, min_confidence
                )
                return True
        except Exception as e:
            logger.error(f"Error upserting signal sub: {e}")
            return False

    async def get_active_signal_subs(self) -> list:
        """Get all active signal subscriptions (for background job)."""
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM signal_subscriptions WHERE active = TRUE ORDER BY symbol"
                )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error fetching signal subs: {e}")
            return []

    async def get_user_signal_subs(self, customer_id: int) -> list:
        """Get active signal subscriptions for a customer."""
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT * FROM signal_subscriptions
                        WHERE customer_id = $1 AND active = TRUE
                        ORDER BY symbol""",
                    customer_id
                )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error fetching user signal subs: {e}")
            return []

    async def count_user_signal_subs(self, customer_id: int) -> int:
        """Count active signal subscriptions for a user."""
        if not self.pool:
            return 0
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS n FROM signal_subscriptions WHERE customer_id = $1 AND active = TRUE",
                    customer_id
                )
                return row['n'] if row else 0
        except Exception as e:
            logger.error(f"Error counting signal subs: {e}")
            return 0

    async def delete_signal_sub(self, customer_id: int, symbol: str) -> bool:
        """Deactivate a signal subscription."""
        if not self.pool:
            return False
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(
                    """UPDATE signal_subscriptions SET active = FALSE
                        WHERE customer_id = $1 AND symbol = $2""",
                    customer_id, symbol
                )
                return result.split()[-1] == '1'
        except Exception as e:
            logger.error(f"Error deleting signal sub: {e}")
            return False

    # ── Daily Briefing Subscriptions ─────────────────────────────────────────

    async def upsert_daily_briefing_sub(self, customer_id: int, telegram_id: int) -> bool:
        """Subscribe to daily briefings (upsert)."""
        if not self.pool:
            return False
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO daily_briefing_subs (customer_id, telegram_id, active)
                        VALUES ($1, $2, TRUE)
                        ON CONFLICT (customer_id)
                        DO UPDATE SET active = TRUE, telegram_id = $2""",
                    customer_id, telegram_id
                )
                return True
        except Exception as e:
            logger.error(f"Error upserting daily briefing sub: {e}")
            return False

    async def delete_daily_briefing_sub(self, customer_id: int) -> bool:
        """Unsubscribe from daily briefings."""
        if not self.pool:
            return False
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(
                    "UPDATE daily_briefing_subs SET active = FALSE WHERE customer_id = $1",
                    customer_id
                )
                return result.split()[-1] == '1'
        except Exception as e:
            logger.error(f"Error deleting daily briefing sub: {e}")
            return False

    async def get_daily_briefing_sub(self, customer_id: int) -> Optional[Dict]:
        """Get daily briefing subscription status for a customer."""
        if not self.pool:
            return None
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM daily_briefing_subs WHERE customer_id = $1",
                    customer_id
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting daily briefing sub: {e}")
            return None

    async def get_daily_briefing_subs(self) -> list:
        """Get all active daily briefing subscriptions (for background job)."""
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM daily_briefing_subs WHERE active = TRUE"
                )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error fetching daily briefing subs: {e}")
            return []

    # ── Referral System ───────────────────────────────────────────────────────

    async def get_or_create_referral_code(self, customer_id: int) -> Optional[str]:
        """Return existing referral code or generate a new unique one."""
        if not self.pool:
            return None
        import secrets
        import string
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT referral_code FROM customers WHERE id = $1", customer_id
                )
                if row and row['referral_code']:
                    return row['referral_code']
                # Generate unique code
                charset = string.ascii_uppercase + string.digits
                for _ in range(10):
                    code = ''.join(secrets.choice(charset) for _ in range(8))
                    try:
                        await conn.execute(
                            "UPDATE customers SET referral_code = $1 WHERE id = $2",
                            code, customer_id
                        )
                        return code
                    except Exception:
                        continue  # code collision, retry
            return None
        except Exception as e:
            logger.error(f"Error getting referral code: {e}")
            return None

    async def get_customer_by_referral_code(self, code: str) -> Optional[Dict]:
        """Look up a customer by their referral code."""
        if not self.pool:
            return None
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM customers WHERE referral_code = $1", code
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error finding referral code: {e}")
            return None

    async def record_referral(self, referrer_customer_id: int, referred_customer_id: int,
                               code: str) -> bool:
        """Record the referral and extend both users' trials by bonus days."""
        if not self.pool:
            return False
        try:
            async with self.pool.acquire() as conn:
                # Skip if already referred
                exists = await conn.fetchrow(
                    "SELECT id FROM referrals WHERE referred_customer_id = $1",
                    referred_customer_id
                )
                if exists:
                    return False

                await conn.execute(
                    """INSERT INTO referrals (referrer_customer_id, referred_customer_id, code)
                        VALUES ($1, $2, $3) ON CONFLICT DO NOTHING""",
                    referrer_customer_id, referred_customer_id, code
                )
                # Referrer: +3 extra trial days (or extend existing trial)
                await conn.execute(
                    """UPDATE customers
                        SET trial_ends_at = GREATEST(trial_ends_at, NOW()) + INTERVAL '3 days'
                        WHERE id = $1""",
                    referrer_customer_id
                )
                # Referred user: +2 extra trial days
                await conn.execute(
                    """UPDATE customers
                        SET trial_ends_at = trial_ends_at + INTERVAL '2 days'
                        WHERE id = $1""",
                    referred_customer_id
                )
                # Mark reward given
                await conn.execute(
                    "UPDATE referrals SET reward_given = TRUE WHERE referred_customer_id = $1",
                    referred_customer_id
                )
                return True
        except Exception as e:
            logger.error(f"Error recording referral: {e}")
            return False

    async def get_referral_stats(self, customer_id: int) -> Dict:
        """Get referral count and total bonus days earned for a customer."""
        if not self.pool:
            return {'count': 0, 'bonus_days': 0}
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT COUNT(*) AS count,
                              COUNT(*) * 3 AS bonus_days
                       FROM referrals
                       WHERE referrer_customer_id = $1 AND reward_given = TRUE""",
                    customer_id
                )
                return dict(row) if row else {'count': 0, 'bonus_days': 0}
        except Exception as e:
            logger.error(f"Error getting referral stats: {e}")
            return {'count': 0, 'bonus_days': 0}

    # ── Broadcast ─────────────────────────────────────────────────────────────

    async def get_telegram_ids_for_broadcast(self, tier_filter: str = 'all') -> list:
        """
        Return list of (telegram_id, tier) tuples for broadcasting.
        tier_filter: 'all' | 'trial' | 'paid' (starter/pro/elite)
        """
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                if tier_filter == 'trial':
                    rows = await conn.fetch(
                        "SELECT telegram_id, tier FROM customers WHERE tier = 'trial' AND telegram_id IS NOT NULL"
                    )
                elif tier_filter == 'paid':
                    rows = await conn.fetch(
                        """SELECT telegram_id, tier FROM customers
                            WHERE tier IN ('starter','pro','elite') AND telegram_id IS NOT NULL"""
                    )
                else:  # all
                    rows = await conn.fetch(
                        "SELECT telegram_id, tier FROM customers WHERE telegram_id IS NOT NULL"
                    )
                return [(r['telegram_id'], r['tier']) for r in rows]
        except Exception as e:
            logger.error(f"Error getting telegram IDs for broadcast: {e}")
            return []

    # ── Platform Stats ────────────────────────────────────────────────────────

    async def get_user_stats(self) -> Dict:
        """Get platform-level user statistics for bot description and admin use."""
        if not self.pool:
            return {'total': 0, 'trial': 0, 'paying': 0, 'active_today': 0}
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT
                        COUNT(*)                                            AS total,
                        COUNT(*) FILTER (WHERE tier = 'trial')             AS trial,
                        COUNT(*) FILTER (WHERE tier IN ('starter','pro','elite')) AS paying,
                        COUNT(*) FILTER (WHERE query_reset_at > NOW() - INTERVAL '24 hours'
                                           AND queries_today > 0)          AS active_today
                    FROM customers"""
                )
                return dict(row) if row else {'total': 0, 'trial': 0, 'paying': 0, 'active_today': 0}
        except Exception as e:
            logger.error(f"Error getting user stats: {e}")
            return {'total': 0, 'trial': 0, 'paying': 0, 'active_today': 0}

    async def get_top_symbols(self, limit: int = 5) -> list:
        """Get the most queried symbols in the last 24 hours."""
        if not self.pool:
            return []
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT symbol, COUNT(*) AS cnt
                       FROM query_log
                       WHERE created_at > NOW() - INTERVAL '24 hours'
                       GROUP BY symbol ORDER BY cnt DESC LIMIT $1""",
                    limit
                )
                return [(r['symbol'], r['cnt']) for r in rows]
        except Exception as e:
            logger.error(f"Error getting top symbols: {e}")
            return []

    async def get_query_count_today(self) -> int:
        """Total queries across all users in the last 24 hours."""
        if not self.pool:
            return 0
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS n FROM query_log WHERE created_at > NOW() - INTERVAL '24 hours'"
                )
                return row['n'] if row else 0
        except Exception as e:
            logger.error(f"Error getting query count: {e}")
            return 0
