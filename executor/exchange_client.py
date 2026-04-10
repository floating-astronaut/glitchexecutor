"""
GlitchExecutor Execution Worker - Exchange Client
Universal CCXT-based exchange connector.
Supports any of the 100+ exchanges in the CCXT library.
"""
import logging
from typing import Dict, List, Optional

try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False
    ccxt = None

logger = logging.getLogger("ExchangeClient")

# Exchanges that require a passphrase/password field in addition to key+secret
PASSPHRASE_EXCHANGES = {'kucoin', 'okx', 'okex', 'okcoin', 'kucoinfutures'}


class ExchangeClient:
    """
    Universal exchange API wrapper using CCXT.
    Supports any exchange available in ccxt.exchanges (100+).
    """

    def __init__(self, exchange: str, api_key: str, api_secret: str,
                 testnet: bool = False, extra_params: dict = None):
        """
        Initialize exchange client.

        Args:
            exchange:     Any valid CCXT exchange ID (e.g. 'binance', 'okx', 'kucoin')
            api_key:      API key from the exchange
            api_secret:   API secret from the exchange
            testnet:      If True, enable sandbox mode where the exchange supports it
            extra_params: Additional CCXT config fields (e.g. {'password': 'passphrase'})
        """
        if not CCXT_AVAILABLE:
            raise RuntimeError("ccxt not installed — run: pip install ccxt")

        self.exchange_id = exchange.lower().strip()
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.extra_params = extra_params or {}

        if not self.is_supported(self.exchange_id):
            raise ValueError(
                f"'{self.exchange_id}' is not a recognised CCXT exchange. "
                f"See https://docs.ccxt.com for the full list."
            )

        self.exchange = self._init_exchange()

    @staticmethod
    def is_supported(exchange_id: str) -> bool:
        """Return True if exchange_id is a valid CCXT exchange."""
        if not CCXT_AVAILABLE:
            return False
        return exchange_id.lower() in ccxt.exchanges

    def _init_exchange(self):
        """Dynamically instantiate the CCXT exchange class."""
        exchange_class = getattr(ccxt, self.exchange_id)

        config = {
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'enableRateLimit': True,
        }

        # Merge any extra params (passphrase, uid, etc.)
        config.update(self.extra_params)

        exchange = exchange_class(config)

        # Enable sandbox/testnet mode if requested — not all exchanges support it
        if self.testnet:
            try:
                exchange.set_sandbox_mode(True)
                logger.info(f"{self.exchange_id}: sandbox mode enabled")
            except Exception:
                logger.warning(
                    f"{self.exchange_id} does not support sandbox mode — "
                    "running in live mode (EXECUTOR_MOCK_MODE controls real execution)"
                )

        logger.info(
            f"{self.exchange_id} client initialised "
            f"({'testnet' if self.testnet else 'live'})"
        )
        return exchange

    async def get_balance(self) -> Dict:
        """Get USDT/USD account balance."""
        try:
            balance = self.exchange.fetch_balance()
            usdt = balance.get('USDT') or balance.get('USD') or {}
            return {
                'total': usdt.get('total', 0) or 0,
                'free':  usdt.get('free',  0) or 0,
                'used':  usdt.get('used',  0) or 0,
            }
        except Exception as e:
            logger.error(f"Error fetching balance on {self.exchange_id}: {e}")
            return {'total': 0, 'free': 0, 'used': 0}

    async def place_order(self, symbol: str, side: str, amount: float,
                          price: float = None, sl: float = None,
                          tp: float = None) -> Dict:
        """
        Place a market or limit order.

        Args:
            symbol: Trading pair (e.g. 'BTC/USDT')
            side:   'buy' or 'sell'
            amount: Order size in base currency
            price:  Limit price (None = market order)
            sl:     Stop-loss price
            tp:     Take-profit price
        """
        try:
            order_type = 'limit' if price else 'market'
            params = {}
            if sl:
                params['stopLoss']   = {'stopPrice': sl}
            if tp:
                params['takeProfit'] = {'stopPrice': tp}

            logger.info(
                f"Placing {order_type} {side} {amount} {symbol} "
                f"@ {'market' if not price else price} on {self.exchange_id}"
            )

            order = self.exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=side.lower(),
                amount=amount,
                price=price,
                params=params
            )

            return {
                'success':  True,
                'order_id': order.get('id'),
                'symbol':   symbol,
                'side':     side,
                'amount':   amount,
                'price':    order.get('average') or order.get('price') or price,
                'status':   order.get('status', 'unknown'),
                'raw':      order,
            }

        except Exception as e:
            logger.error(f"Order placement failed on {self.exchange_id}: {e}")
            return {
                'success': False,
                'error':   str(e),
                'symbol':  symbol,
                'side':    side,
                'amount':  amount,
            }

    async def get_open_positions(self) -> List[Dict]:
        """Get list of open positions (futures/margin exchanges)."""
        try:
            positions = self.exchange.fetch_positions()
            return [
                {
                    'symbol':         p.get('symbol'),
                    'side':           p.get('side', 'long'),
                    'amount':         abs(float(p.get('contracts', 0))),
                    'entry_price':    p.get('entryPrice'),
                    'unrealized_pnl': p.get('unrealizedPnl'),
                }
                for p in positions if float(p.get('contracts', 0)) != 0
            ]
        except Exception as e:
            logger.error(f"Error fetching positions on {self.exchange_id}: {e}")
            return []

    async def close_position(self, symbol: str) -> Dict:
        """Close an open position by placing the opposite market order."""
        try:
            positions = await self.get_open_positions()
            position = next((p for p in positions if p['symbol'] == symbol), None)
            if not position:
                return {'success': False, 'error': 'Position not found'}
            close_side = 'sell' if position['side'] == 'long' else 'buy'
            return await self.place_order(symbol=symbol, side=close_side,
                                          amount=position['amount'])
        except Exception as e:
            logger.error(f"Error closing position on {self.exchange_id}: {e}")
            return {'success': False, 'error': str(e)}
