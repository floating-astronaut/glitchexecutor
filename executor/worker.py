"""
GlitchExecutor Execution Worker - Main Worker
Listens on Redis queue for trade requests and executes on exchanges.
Supports admin auto-execution on funded cTrader account with PropFirmGuard.
"""
import os
import sys
import json
import logging
import asyncio
from datetime import datetime
from typing import Dict, Optional

# Add paths
sys.path.insert(0, '/opt/glitchexecutor/ensemble')
sys.path.insert(0, '/opt/glitchexecutor/telegram_bot')

from redis_cache import EnsembleCache
from db import Database
from exchange_client import ExchangeClient
from position_manager import PositionManager
from mt5_client import MT5Client
from ctrader_client import CTraderClient
from prop_firm_guard import PropFirmGuard

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("ExecutionWorker")


class ExecutionWorker:
    """
    Main execution worker that listens for trade requests via Redis queue.
    Executes trades on TESTNET exchanges only.
    """

    def __init__(self, mock_mode: bool = False):
        """Initialize execution worker."""
        logger.info("=" * 60)
        logger.info("GLITCHEXECUTOR EXECUTION WORKER")
        logger.info("=" * 60)

        self.mock_mode = mock_mode

        # Initialize Redis
        self.redis_host = os.environ.get("REDIS_HOST", "localhost")
        self.redis_port = int(os.environ.get("REDIS_PORT", 6379))
        self.cache = EnsembleCache(host=self.redis_host, port=self.redis_port)

        # Initialize database
        self.db = Database()

        # Initialize position manager
        self.position_manager = PositionManager()

        # Track exchange clients per customer
        self.clients = {}

        # MT5 client (initialized on first MT5 trade)
        self.mt5_client = None

        # cTrader clients per customer
        self.ctrader_clients = {}

        # PropFirmGuard for funded account safety
        self.prop_guard = None
        if os.environ.get("PROP_FIRM_ENABLED", "false").lower() == "true":
            prop_config = {
                'prop_firm': {
                    'initial_capital': float(os.environ.get("PROP_FIRM_INITIAL_CAPITAL", "150000")),
                    'profit_target_pct': float(os.environ.get("PROP_FIRM_PROFIT_TARGET_PCT", "6.0")),
                    'daily_loss_halt_pct': float(os.environ.get("PROP_FIRM_DAILY_LOSS_PCT", "2.5")),
                    'trailing_dd_halt_pct': float(os.environ.get("PROP_FIRM_TRAILING_DD_PCT", "5.5")),
                    'max_total_positions': int(os.environ.get("PROP_FIRM_MAX_POSITIONS", "5")),
                }
            }
            self.prop_guard = PropFirmGuard(
                config=prop_config,
                logger=logger,
                state_file='/data/prop_guard_state.json',
            )
            logger.info(f"PropFirmGuard enabled: capital=${prop_config['prop_firm']['initial_capital']:.0f}")

        # Admin cTrader credentials (for auto-execution on funded account)
        self.admin_ctrader_creds = {
            'client_id': os.environ.get("CTRADER_CLIENT_ID", ""),
            'client_secret': os.environ.get("CTRADER_CLIENT_SECRET", ""),
            'access_token': os.environ.get("CTRADER_ACCESS_TOKEN", ""),
            'account_id': int(os.environ.get("CTRADER_ACCOUNT_ID", "0") or 0),
            'live': os.environ.get("CTRADER_LIVE", "true").lower() == "true",
        }
        self.admin_telegram_id = os.environ.get("ADMIN_TELEGRAM_ID", "")

        # Initialize Redis client for queue listening
        self.redis_client = None
        try:
            import redis as redis_lib
            self.redis_client = redis_lib.Redis(
                host=self.redis_host,
                port=self.redis_port,
                decode_responses=True
            )
            self.redis_client.ping()
            logger.info("Redis connected")
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")

        mode_str = "MOCK" if mock_mode else "LIVE"
        logger.info(f"Mode: {mode_str}")
        logger.info(f"Redis: {self.redis_host}:{self.redis_port}")

    async def connect(self):
        """Connect to database."""
        connected = await self.db.connect()
        if not connected:
            logger.error("Database connection failed")
            return False
        logger.info("Database connected")
        return True

    def get_exchange_client(self, customer_id: int, exchange: str,
                           api_key: str, api_secret: str) -> Optional[ExchangeClient]:
        """Get or create exchange client for customer."""
        client_key = f"{customer_id}:{exchange}"

        if client_key not in self.clients:
            try:
                client = ExchangeClient(exchange, api_key, api_secret, testnet=True)
                self.clients[client_key] = client
                logger.info(f"Created {exchange} client for customer {customer_id} (TESTNET)")
            except Exception as e:
                logger.error(f"Failed to create exchange client: {e}")
                return None

        return self.clients.get(client_key)

    async def validate_trade_request(self, trade_request: Dict) -> tuple:
        """
        Validate trade request.

        Returns: (valid: bool, error: str, customer: dict)
        """
        # Admin auto-execution bypass — uses env var credentials, no DB lookup
        if trade_request.get('admin_auto_execute'):
            return True, "", {
                'id': 0,
                'tier': 'admin',
                'telegram_id': self.admin_telegram_id,
            }

        required_fields = ['customer_id', 'symbol', 'direction', 'sl_price']

        for field in required_fields:
            if field not in trade_request:
                return False, f"Missing required field: {field}", None

        customer_id = trade_request['customer_id']

        # Get customer from DB
        customer = await self.db.get_customer_by_id(customer_id)
        if not customer:
            return False, f"Customer {customer_id} not found", None

        # Check tier allows execution
        tier = customer.get('tier', 'trial')
        if tier not in ['pro', 'elite']:
            return False, f"Trade execution not available for {tier} tier. Upgrade to Pro at glitchexecutor.com/pricing", customer

        # Validate SL is present
        sl = trade_request.get('sl_price')
        if not sl or sl <= 0:
            return False, "SL required — refusing to trade without stop loss", customer

        # Validate SL/TP direction relative to entry
        direction = trade_request.get('direction', '').upper()
        entry = trade_request.get('entry_price', 0)

        if entry and entry > 0:
            if direction == 'BUY' and sl >= entry:
                return False, f"SL ({sl}) must be below entry ({entry}) for BUY orders", customer
            if direction == 'SELL' and sl <= entry:
                return False, f"SL ({sl}) must be above entry ({entry}) for SELL orders", customer

            tp = trade_request.get('tp_price')
            if tp and tp > 0:
                if direction == 'BUY' and tp <= entry:
                    return False, f"TP ({tp}) must be above entry ({entry}) for BUY orders", customer
                if direction == 'SELL' and tp >= entry:
                    return False, f"TP ({tp}) must be below entry ({entry}) for SELL orders", customer

        return True, "", customer

    def get_mt5_client(self) -> Optional[MT5Client]:
        """Get or create MT5 client."""
        if self.mt5_client is None:
            bridge_url = os.environ.get("MT5_BRIDGE_URL", "")
            bridge_key = os.environ.get("MT5_BRIDGE_KEY", "")

            if not bridge_url or not bridge_key:
                logger.error("MT5 bridge not configured - set MT5_BRIDGE_URL and MT5_BRIDGE_KEY")
                return None

            try:
                self.mt5_client = MT5Client(bridge_url, bridge_key)
                logger.info(f"MT5 client initialized for bridge at {bridge_url}")
            except Exception as e:
                logger.error(f"Failed to initialize MT5 client: {e}")
                return None

        return self.mt5_client

    async def execute_trade(self, trade_request: Dict, customer: Dict) -> Dict:
        """
        Execute a trade based on exchange type.

        Routes:
        - admin_auto_execute -> Admin funded cTrader account (env var creds)
        - exchange='mt5' -> MT5 Bridge (Windows VM)
        - exchange='ctrader' -> Customer's cTrader (DB creds)
        - exchange='crypto' or any other -> Crypto exchange (ccxt)

        Returns result dict.
        """
        # Admin auto-execution path — uses env var credentials directly
        if trade_request.get('admin_auto_execute'):
            return await self._execute_admin_ctrader(trade_request)

        exchange_type = trade_request.get('exchange', 'crypto')

        if exchange_type == 'mt5':
            return await self._execute_mt5(trade_request, customer)
        elif exchange_type == 'ctrader':
            return await self._execute_ctrader(trade_request, customer)
        else:
            return await self._execute_crypto(trade_request, customer)

    async def _execute_mt5(self, trade_request: Dict, customer: Dict) -> Dict:
        """Execute trade via MT5 Bridge."""
        request_id = trade_request.get('request_id', 'unknown')

        if self.mock_mode:
            logger.info("MOCK MT5 EXECUTION")
            return await self._mock_execute(trade_request, customer)

        # Get MT5 client
        client = self.get_mt5_client()
        if not client:
            return {
                'success': False,
                'error': 'MT5 bridge not configured',
                'request_id': request_id
            }

        # Check bridge health
        if not client.health_check():
            return {
                'success': False,
                'error': 'MT5 bridge is offline',
                'request_id': request_id
            }

        # Get balance from MT5
        balance = await client.get_balance()
        free_balance = balance.get('free', 0)

        logger.info(f"MT5 Balance: ${free_balance:.2f}")

        # Validate trade
        valid, error = await self.position_manager.validate_trade(free_balance, trade_request)
        if not valid:
            return {
                'success': False,
                'error': error,
                'balance': free_balance,
                'request_id': request_id
            }

        # Execute on MT5
        symbol = trade_request['symbol']
        direction = trade_request['direction']
        sl = trade_request.get('sl_price')
        tp = trade_request.get('tp_price')

        # MT5 uses lot sizes - simplified here, would need proper lot calculation
        volume = 0.01  # Minimum lot size

        result = await client.place_order(
            symbol=symbol,
            side=direction,
            amount=volume,
            sl=sl,
            tp=tp
        )

        # Log trade
        await self.log_trade(customer['id'], trade_request, result)

        return result


    async def _execute_admin_ctrader(self, trade_request: dict) -> dict:
        """Execute trade on admin's funded cTrader account using env var credentials."""
        request_id = trade_request.get('request_id', 'unknown')

        if self.mock_mode:
            logger.info("[ADMIN] MOCK execution (mock mode enabled)")
            return await self._mock_execute(trade_request, {'id': 0, 'tier': 'admin'})

        creds = self.admin_ctrader_creds
        if not creds['client_id'] or not creds['access_token'] or not creds['account_id']:
            return {'success': False, 'error': 'Admin cTrader credentials not configured', 'request_id': request_id}

        # PropFirmGuard pre-trade check
        if self.prop_guard:
            symbol = trade_request.get('symbol', '')
            allowed, risk_mode, multiplier = self.prop_guard.can_trade(symbol=symbol)
            if not allowed:
                logger.warning(f"[ADMIN] PropFirmGuard blocked trade: {risk_mode}")
                return {'success': False, 'error': f'PropFirmGuard blocked: {risk_mode}', 'request_id': request_id}

        # Get or create admin cTrader client
        client = self.get_ctrader_client(
            0,  # admin customer_id
            creds['client_id'],
            creds['client_secret'],
            creds['access_token'],
            creds['account_id'],
            creds['live'],
        )
        if not client:
            return {'success': False, 'error': 'Admin cTrader client init failed', 'request_id': request_id}

        # Get balance
        balance = await client.get_balance()
        free_balance = balance.get('free', 0)
        if balance.get('error'):
            return {'success': False, 'error': f"cTrader balance error: {balance['error']}", 'request_id': request_id}

        logger.info(f"[ADMIN] cTrader Balance: ${free_balance:.2f}")

        # Update PropFirmGuard with current equity
        if self.prop_guard:
            self.prop_guard.update(free_balance, free_balance)

        # Calculate position size with PropFirmGuard multiplier
        entry = trade_request.get('entry_price', 0)
        sl = trade_request.get('sl_price')
        risk_pct = trade_request.get('risk_percent', 1.0)

        # Apply PropFirmGuard risk multiplier
        if self.prop_guard:
            multiplier = self.prop_guard.get_risk_multiplier()
            risk_pct = risk_pct * multiplier
            logger.info(f"[ADMIN] Risk adjusted by PropFirmGuard: {risk_pct:.2f}% (multiplier={multiplier:.3f})")

        position_size = self.position_manager.calculate_position_size(free_balance, risk_pct, entry, sl)
        if position_size <= 0:
            return {'success': False, 'error': 'Calculated position size is zero', 'request_id': request_id}

        lots = max(0.01, round(position_size / max(entry, 1) * 0.01, 2))

        result = await client.place_order(
            symbol=trade_request['symbol'],
            side=trade_request['direction'],
            amount=lots,
            sl=sl,
            tp=trade_request.get('tp_price'),
        )

        # Log trade with admin flag
        await self.log_trade(0, trade_request, result)

        # Record loss for PropFirmGuard if trade fails immediately
        if self.prop_guard and not result.get('success'):
            self.prop_guard.record_loss(trade_request.get('symbol', ''))

        logger.info(f"[ADMIN] Trade result: {result.get('success')} order={result.get('order_id')} "
                    f"lots={lots} {trade_request['direction']} {trade_request['symbol']}")

        return result

    def get_ctrader_client(self, customer_id: int, client_id: str, client_secret: str,
                           access_token: str, account_id: int, live: bool = True) -> CTraderClient:
        """Get or create cTrader client for customer."""
        client_key = f"{customer_id}:ctrader"
        if client_key not in self.ctrader_clients:
            try:
                client = CTraderClient(client_id, client_secret, access_token, account_id, live)
                self.ctrader_clients[client_key] = client
                logger.info(f"Created cTrader client for customer {customer_id} ({'LIVE' if live else 'DEMO'})")
            except Exception as e:
                logger.error(f"Failed to create cTrader client: {e}")
                return None
        return self.ctrader_clients.get(client_key)

    async def _execute_ctrader(self, trade_request: dict, customer: dict) -> dict:
        """Execute trade via cTrader Open API using customer's stored credentials."""
        request_id = trade_request.get('request_id', 'unknown')

        if self.mock_mode:
            return await self._mock_execute(trade_request, customer)

        customer_id = customer['id']

        # Load customer's cTrader credentials from DB
        creds = await self.db.get_ctrader_credentials(customer_id)
        if not creds:
            return {
                'success': False,
                'error': 'No cTrader account connected. Use /connect ctrader to link your account.',
                'request_id': request_id
            }

        client = self.get_ctrader_client(
            customer_id,
            creds['client_id'],
            creds['client_secret'],
            creds['access_token'],
            creds['account_id'],
            creds.get('live', True)
        )
        if not client:
            return {'success': False, 'error': 'cTrader client init failed', 'request_id': request_id}

        # Get balance
        balance = await client.get_balance()
        free_balance = balance.get('free', 0)
        if balance.get('error'):
            return {'success': False, 'error': f"cTrader balance error: {balance['error']}", 'request_id': request_id}

        logger.info(f"cTrader Balance: ${free_balance:.2f}")

        # Validate against position manager
        valid, error = await self.position_manager.validate_trade(free_balance, trade_request)
        if not valid:
            return {'success': False, 'error': error, 'balance': free_balance, 'request_id': request_id}

        # Calculate lot size from position manager risk
        entry = trade_request.get('entry_price', 0)
        sl = trade_request.get('sl_price')
        risk_pct = trade_request.get('risk_percent', 1.0)
        position_size = self.position_manager.calculate_position_size(free_balance, risk_pct, entry, sl)

        if position_size <= 0:
            return {'success': False, 'error': 'Calculated position size is zero', 'request_id': request_id}

        # Convert from units to lots (minimum 0.01)
        lots = max(0.01, round(position_size / max(entry, 1) * 0.01, 2))

        result = await client.place_order(
            symbol=trade_request['symbol'],
            side=trade_request['direction'],
            amount=lots,
            sl=sl,
            tp=trade_request.get('tp_price')
        )

        await self.log_trade(customer_id, trade_request, result)
        return result

    async def _execute_crypto(self, trade_request: Dict, customer: Dict) -> Dict:
        """Execute trade on crypto exchange using customer's stored API keys."""
        if self.mock_mode:
            return await self._mock_execute(trade_request, customer)

        exchange = trade_request.get('exchange', 'binance')
        customer_id = customer['id']
        # Auto-executed trades always use testnet (paper trading) for safety
        testnet = bool(trade_request.get('auto_executed', False))

        # Try customer's personal stored keys first
        keys = await self.db.get_exchange_keys(customer_id, exchange)
        if keys:
            api_key = keys['api_key']
            api_secret = keys['api_secret']
            logger.info(f"Using customer {customer_id}'s own {exchange} keys{' (testnet forced for auto-trade)' if testnet else ''}")
        else:
            # Fall back to system testnet keys
            api_key = os.environ.get("BINANCE_TESTNET_API_KEY", "")
            api_secret = os.environ.get("BINANCE_TESTNET_SECRET", "")
            testnet = True
            logger.warning(f"No stored keys for customer {customer_id} on {exchange} — using system testnet keys")

        if not api_key or not api_secret:
            logger.warning("No API credentials found — using mock execution")
            return await self._mock_execute(trade_request, customer)

        # Get exchange client (cache key includes testnet flag)
        extra_params = keys.get('extra_params', {}) if keys else {}
        client_cache_key = f"{customer_id}:{exchange}:{'testnet' if testnet else 'live'}"
        if client_cache_key not in self.clients:
            try:
                client = ExchangeClient(exchange, api_key, api_secret,
                                        testnet=testnet, extra_params=extra_params)
                self.clients[client_cache_key] = client
                logger.info(f"Created {exchange} client for customer {customer_id} ({'testnet' if testnet else 'live'})")
            except Exception as e:
                logger.error(f"Failed to create exchange client: {e}")
                return {'success': False, 'error': 'Exchange client init failed',
                        'request_id': trade_request.get('request_id')}
        client = self.clients.get(client_cache_key)

        if not client:
            return {
                'success': False,
                'error': 'Failed to initialize exchange client',
                'request_id': trade_request.get('request_id')
            }

        # Get balance
        balance = await client.get_balance()
        free_balance = balance.get('free', 0)

        logger.info(f"Balance: ${free_balance:.2f}")

        # Validate trade against balance
        valid, error = await self.position_manager.validate_trade(free_balance, trade_request)
        if not valid:
            return {
                'success': False,
                'error': error,
                'balance': free_balance,
                'request_id': trade_request.get('request_id')
            }

        # Calculate position size
        entry = trade_request.get('entry_price', 0)
        sl = trade_request.get('sl_price')
        risk_pct = trade_request.get('risk_percent', 1.0)

        symbol = trade_request['symbol']
        direction = trade_request['direction']

        # Normalize symbol format
        if '/' not in symbol:
            symbol = f"{symbol[:3]}/USDT" if symbol.endswith('USD') else f"{symbol}/USDT"

        position_size = self.position_manager.calculate_position_size(
            free_balance, risk_pct, entry, sl
        )

        if position_size <= 0:
            return {
                'success': False,
                'error': 'Calculated position size is zero',
                'request_id': trade_request.get('request_id')
            }

        # Place order
        result = await client.place_order(
            symbol=symbol,
            side=direction,
            amount=position_size,
            sl=sl,
            tp=trade_request.get('tp_price')
        )

        # Log trade to database
        await self.log_trade(customer['id'], trade_request, result)

        return result

    async def _mock_execute(self, trade_request: Dict, customer: Dict) -> Dict:
        """Mock trade execution for testing."""
        logger.info("MOCK EXECUTION (no real trade placed)")

        # Simulate balance check with fixed mock balance
        mock_balance = 1000

        valid, error = await self.position_manager.validate_trade(mock_balance, trade_request)
        if not valid:
            return {
                'success': False,
                'error': error,
                'balance': mock_balance,
                'request_id': trade_request.get('request_id'),
                'mock': True
            }

        # Simulate successful trade
        result = {
            'success': True,
            'order_id': f"mock_{datetime.utcnow().timestamp()}",
            'symbol': trade_request['symbol'],
            'side': trade_request['direction'],
            'amount': 0.01,
            'price': trade_request.get('entry_price', 0),
            'status': 'filled',
            'sl': trade_request['sl_price'],
            'tp': trade_request.get('tp_price'),
            'request_id': trade_request.get('request_id'),
            'mock': True
        }

        await self.log_trade(customer['id'], trade_request, result)

        return result

    async def log_trade(self, customer_id: int, request: Dict, result: Dict):
        """Log trade execution to database."""
        try:
            trade_id = await self.db.log_trade(
                customer_id=customer_id,
                symbol=request.get('symbol', ''),
                direction=request.get('direction', ''),
                entry_price=result.get('price', 0),
                sl_price=request.get('sl_price', 0),
                tp_price=request.get('tp_price', 0),
                volume=result.get('amount', 0),
                ensemble_vote=request.get('ensemble_vote', ''),
                status='filled' if result.get('success') else 'failed'
            )
            logger.info(f"Trade logged: ID={trade_id}, order={result.get('order_id')} for customer {customer_id}")
        except Exception as e:
            logger.error(f"Failed to log trade: {e}")

    async def process_trade_request(self, trade_request: Dict):
        """Process a single trade request."""
        request_id = trade_request.get('request_id', 'unknown')
        logger.info(f"Processing trade request: {request_id}")

        # Validate
        valid, error, customer = await self.validate_trade_request(trade_request)

        if not valid:
            result = {
                'request_id': request_id,
                'success': False,
                'error': error,
                'timestamp': datetime.utcnow().isoformat()
            }
        else:
            # Execute
            result = await self.execute_trade(trade_request, customer)
            result['request_id'] = request_id
            result['timestamp'] = datetime.utcnow().isoformat()

        # Publish result
        await self.publish_result(result)

        return result

    async def publish_result(self, result: Dict):
        """Publish trade result to Redis channel and write a polling key for the bot."""
        try:
            if not self.redis_client:
                logger.warning(f"No Redis client - result not published: {result.get('request_id')}")
                return

            serialized = json.dumps(result)
            request_id = result.get('request_id', '')

            # PubSub for any other subscribers
            self.redis_client.publish('trade_results', serialized)

            # Key with 60s TTL so the Telegram bot can poll for the result
            if request_id:
                self.redis_client.setex(f"trade_result:{request_id}", 60, serialized)

            logger.info(f"Published result for {request_id}")
        except Exception as e:
            logger.error(f"Failed to publish result: {e}")

    async def listen(self):
        """Listen for trade requests on Redis queue (BRPOP for durability)."""
        if not self.redis_client:
            logger.error("No Redis client available - entering idle loop")
            while True:
                await asyncio.sleep(60)
            return

        mode_str = "MOCK" if self.mock_mode else "LIVE (TESTNET)"
        logger.info(f"Listening on 'trade_requests' queue (BRPOP)... Mode: {mode_str}")

        while True:
            try:
                # BRPOP blocks until an item is available, timeout 5s
                result = self.redis_client.brpop('trade_requests', timeout=5)
                if result is None:
                    continue  # timeout, loop again

                _, message_data = result
                try:
                    data = json.loads(message_data)
                    logger.info(f"Received trade request: {data.get('request_id')}")
                    await self.process_trade_request(data)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON in trade request: {e}")
                except Exception as e:
                    logger.error(f"Error processing trade request: {e}")

            except Exception as e:
                logger.error(f"Queue listener error: {e}")
                await asyncio.sleep(5)  # Back off on error

    async def run(self):
        """Main run loop."""
        # Connect to database
        if not await self.connect():
            logger.error("Failed to connect to database, exiting")
            return

        # Start listening (runs forever)
        await self.listen()


async def main():
    """Main entry point."""
    # Check for mock mode
    mock_mode = os.environ.get("EXECUTOR_MOCK_MODE", "false").lower() == "true"

    worker = ExecutionWorker(mock_mode=mock_mode)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
