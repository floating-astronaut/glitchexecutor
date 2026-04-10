"""
GlitchExecutor Execution Worker - MT5 Client
HTTP client that calls the MT5 Bridge Server running on Windows VM.
Same interface as exchange_client.py but routes through HTTP.
"""
import os
import logging
from typing import Dict, List, Optional

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    requests = None

logger = logging.getLogger("MT5Client")


class MT5Client:
    """
    MT5 Bridge Client — Calls the MT5 Bridge Server via HTTP API.
    Runs on Linux, connects to Windows VM running MT5 Bridge.
    """
    
    def __init__(self, bridge_url: str, api_key: str):
        """
        Initialize MT5 client.
        
        Args:
            bridge_url: e.g. "http://mt5-bridge-vm:8070" or "http://1.2.3.4:8070"
            api_key: Shared secret matching MT5_BRIDGE_KEY on the bridge
        """
        if not REQUESTS_AVAILABLE:
            raise RuntimeError("requests library not installed")
        
        self.bridge_url = bridge_url.rstrip('/')
        self.headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json"
        }
        self.timeout = 10
        
        logger.info(f"MT5 Client initialized for bridge at {bridge_url}")
    
    def _request(self, method: str, path: str, json_data: dict = None) -> dict:
        """Make HTTP request to bridge."""
        try:
            url = f"{self.bridge_url}{path}"
            resp = requests.request(
                method, 
                url, 
                json=json_data,
                headers=self.headers, 
                timeout=self.timeout
            )
            return resp.json()
            
        except requests.exceptions.Timeout:
            logger.error(f"MT5 Bridge timeout: {path}")
            return {"error": "Bridge timeout"}
        except requests.exceptions.ConnectionError:
            logger.error(f"MT5 Bridge connection failed: {path}")
            return {"error": "Bridge unreachable"}
        except Exception as e:
            logger.error(f"MT5 Bridge error: {e}")
            return {"error": str(e)}
    
    def health_check(self) -> bool:
        """Check if MT5 Bridge is online."""
        result = self._request("GET", "/health")
        return result.get("status") == "ok"
    
    async def get_balance(self) -> dict:
        """Get account balance from MT5."""
        result = self._request("GET", "/account")
        
        if "error" in result:
            return {
                "total": 0,
                "free": 0,
                "equity": 0,
                "error": result["error"]
            }
        
        return {
            "total": result.get("balance", 0),
            "free": result.get("free_margin", 0),
            "equity": result.get("equity", 0),
            "currency": result.get("currency", "USD")
        }
    
    async def place_order(self, symbol: str, side: str, amount: float,
                          price: float = None, sl: float = None, tp: float = None) -> dict:
        """
        Place an order via MT5 Bridge.
        
        Args:
            symbol: Trading symbol (e.g., "EURUSD")
            side: 'buy' or 'sell'
            amount: Order volume (lot size)
            price: Entry price (None for market orders)
            sl: Stop loss price
            tp: Take profit price
        """
        payload = {
            "symbol": symbol,
            "direction": side,  # Bridge expects 'direction' not 'side'
            "volume": amount,
            "sl": sl,
            "tp": tp
        }
        
        result = self._request("POST", "/execute", payload)
        
        if result.get("success"):
            return {
                "success": True,
                "order_id": result.get("order_id"),
                "symbol": symbol,
                "side": side,
                "amount": result.get("volume", amount),
                "price": result.get("filled_price"),
                "status": "filled",
                "message": result.get("message", f"{side.upper()} {amount} {symbol}"),
                "sl": sl,
                "tp": tp
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "symbol": symbol,
                "side": side,
                "amount": amount
            }
    
    async def get_open_positions(self) -> List[dict]:
        """Get list of open positions from MT5."""
        result = self._request("GET", "/positions")
        
        if "error" in result:
            return []
        
        positions = result.get("positions", [])
        return [
            {
                "ticket": p.get("ticket"),
                "symbol": p.get("symbol"),
                "side": p.get("type"),  # BUY or SELL
                "amount": p.get("volume"),
                "entry_price": p.get("price_open"),
                "sl": p.get("sl"),
                "tp": p.get("tp"),
                "profit": p.get("profit"),
                "magic": p.get("magic")
            }
            for p in positions
        ]
    
    async def close_position(self, symbol: str, position_id: str) -> dict:
        """
        Close a position by ticket ID.
        
        Args:
            symbol: Trading symbol
            position_id: Position ticket number
        """
        result = self._request("POST", "/close", {"ticket": int(position_id)})
        
        if result.get("success"):
            return {
                "success": True,
                "message": result.get("message", f"Closed position #{position_id}"),
                "ticket": position_id
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Close failed"),
                "ticket": position_id
            }
    
    async def modify_position(self, position_id: str, sl: float = None, tp: float = None) -> dict:
        """
        Modify SL/TP on an open position.
        
        Args:
            position_id: Position ticket number
            sl: New stop loss price (None to keep current)
            tp: New take profit price (None to keep current)
        """
        payload = {
            "ticket": int(position_id)
        }
        if sl is not None:
            payload["sl"] = sl
        if tp is not None:
            payload["tp"] = tp
        
        result = self._request("POST", "/modify", payload)
        
        if result.get("success"):
            return {
                "success": True,
                "message": f"Modified position #{position_id}",
                "ticket": position_id,
                "sl": sl,
                "tp": tp
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Modify failed"),
                "ticket": position_id
            }
