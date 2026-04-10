"""
Interactive Brokers Gateway integration.
Connects to IB Pro Gateway on IB_HOST:IB_PORT (default 172.17.0.1:4001).

All endpoints require JWT auth and open a fresh IB connection per request.
IB Gateway must have API access enabled and the server IP whitelisted.
"""
import os
import random
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException
from ib_insync import IB, Stock, Forex, Crypto, CFD, Contract

from auth import get_current_user

router = APIRouter()

IB_HOST     = os.environ.get("IB_HOST",     "172.17.0.1")
IB_PORT     = int(os.environ.get("IB_PORT", "4001"))
IB_TIMEOUT  = int(os.environ.get("IB_TIMEOUT", "10"))


# ── Contract builder ──────────────────────────────────────────────────────────

def _build_contract(symbol: str, sec_type: str, exchange: str, currency: str) -> Contract:
    """Build an ib_insync Contract from user-supplied params."""
    sec_type = sec_type.upper()
    symbol   = symbol.upper()

    if sec_type == "STK":
        return Stock(symbol, exchange or "SMART", currency or "USD")

    if sec_type in ("CASH", "FOREX"):
        # symbol like "EURUSD" → pair "EUR", currency "USD"
        if len(symbol) == 6:
            pair = symbol[:3]
            cur  = symbol[3:]
        else:
            pair, cur = symbol, currency or "USD"
        return Forex(pair + cur, exchange or "IDEALPRO")

    if sec_type == "CRYPTO":
        return Crypto(symbol, exchange or "PAXOS", currency or "USD")

    if sec_type == "CFD":
        return CFD(symbol, exchange or "SMART", currency or "USD")

    # Generic fallback
    c = Contract()
    c.symbol   = symbol
    c.secType  = sec_type
    c.exchange  = exchange or "SMART"
    c.currency  = currency or "USD"
    return c


# ── IB connection context ─────────────────────────────────────────────────────

class _IBConn:
    """Context manager: fresh IB connection per request."""

    def __enter__(self):
        self.ib = IB()
        client_id = random.randint(200, 999)
        try:
            self.ib.connect(IB_HOST, IB_PORT, clientId=client_id,
                            timeout=IB_TIMEOUT, readonly=True)
        except Exception as e:
            raise HTTPException(status_code=503,
                                detail=f"IB Gateway unreachable at {IB_HOST}:{IB_PORT} — {e}")
        return self.ib

    def __exit__(self, *_):
        try:
            self.ib.disconnect()
        except Exception:
            pass


# ── GET /api/ib/status ────────────────────────────────────────────────────────

@router.get("/status")
def status(current_user: dict = Depends(get_current_user)):
    """Test IB Gateway connectivity and return server version info."""
    try:
        with _IBConn() as ib:
            return {
                "connected":        True,
                "host":             IB_HOST,
                "port":             IB_PORT,
                "server_version":   ib.client.serverVersion(),
                "connection_time":  ib.client.twsConnectionTime(),
                "client_id":        ib.client.clientId,
            }
    except HTTPException:
        return {"connected": False, "host": IB_HOST, "port": IB_PORT,
                "error": f"Cannot reach IB Gateway at {IB_HOST}:{IB_PORT}"}


# ── GET /api/ib/historical ────────────────────────────────────────────────────

@router.get("/historical")
def historical(
    symbol:       str   = Query("AAPL",    description="Ticker symbol"),
    sec_type:     str   = Query("STK",     description="STK | FOREX | CRYPTO | CFD"),
    exchange:     str   = Query("SMART",   description="Exchange (SMART, IDEALPRO, PAXOS…)"),
    currency:     str   = Query("USD",     description="Currency"),
    bar_size:     str   = Query("1 day",   description="Bar size: 1 min, 5 mins, 15 mins, 1 hour, 4 hours, 1 day"),
    duration:     str   = Query("1 M",     description="Duration: 1 D, 1 W, 1 M, 3 M, 6 M, 1 Y"),
    what_to_show: str   = Query("TRADES",  description="TRADES | MIDPOINT | BID | ASK"),
    current_user: dict  = Depends(get_current_user),
):
    """Fetch historical OHLCV bars from IB Gateway."""
    contract = _build_contract(symbol, sec_type, exchange, currency)

    with _IBConn() as ib:
        # Qualify the contract so IB fills in conId etc.
        qualified = ib.qualifyContracts(contract)
        if not qualified:
            raise HTTPException(status_code=404,
                                detail=f"IB could not qualify contract: {symbol} ({sec_type})")

        bars = ib.reqHistoricalData(
            qualified[0],
            endDateTime="",          # empty = now
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow=what_to_show,
            useRTH=False,
            formatDate=1,
            keepUpToDate=False,
        )

    result = []
    for b in bars:
        result.append({
            "time":   b.date.isoformat() if hasattr(b.date, "isoformat") else str(b.date),
            "open":   b.open,
            "high":   b.high,
            "low":    b.low,
            "close":  b.close,
            "volume": b.volume,
        })

    return {
        "symbol":    symbol.upper(),
        "sec_type":  sec_type.upper(),
        "bar_size":  bar_size,
        "duration":  duration,
        "bars":      result,
    }


# ── GET /api/ib/quote ─────────────────────────────────────────────────────────

@router.get("/quote")
def quote(
    symbol:       str  = Query("AAPL"),
    sec_type:     str  = Query("STK"),
    exchange:     str  = Query("SMART"),
    currency:     str  = Query("USD"),
    current_user: dict = Depends(get_current_user),
):
    """Snapshot market data: bid, ask, last, volume, close."""
    contract = _build_contract(symbol, sec_type, exchange, currency)

    with _IBConn() as ib:
        qualified = ib.qualifyContracts(contract)
        if not qualified:
            raise HTTPException(status_code=404, detail=f"Cannot qualify {symbol}")

        ticker = ib.reqMktData(qualified[0], "", snapshot=True, regulatorySnapshot=False)
        ib.sleep(2)   # wait for snapshot data to arrive
        ib.cancelMktData(qualified[0])

    return {
        "symbol":   symbol.upper(),
        "bid":      ticker.bid,
        "ask":      ticker.ask,
        "last":     ticker.last,
        "close":    ticker.close,
        "volume":   ticker.volume,
        "high":     ticker.high,
        "low":      ticker.low,
        "time":     datetime.now(timezone.utc).isoformat(),
    }


# ── GET /api/ib/account ───────────────────────────────────────────────────────

@router.get("/account")
def account(current_user: dict = Depends(get_current_user)):
    """IB account summary: net liquidation, cash, unrealized P&L, buying power."""
    with _IBConn() as ib:
        summary = ib.accountSummary()

    WANT = {
        "NetLiquidation", "TotalCashValue", "UnrealizedPnL",
        "RealizedPnL", "BuyingPower", "GrossPositionValue",
        "AvailableFunds", "MaintMarginReq", "Currency",
    }

    result: dict = {}
    for item in summary:
        if item.tag in WANT:
            try:
                result[item.tag] = float(item.value)
            except (ValueError, TypeError):
                result[item.tag] = item.value

    result["account"] = summary[0].account if summary else "unknown"
    return result


# ── GET /api/ib/positions ─────────────────────────────────────────────────────

@router.get("/positions")
def positions(current_user: dict = Depends(get_current_user)):
    """Current open positions held in the IB account."""
    with _IBConn() as ib:
        pos_list = ib.positions()

    result = []
    for p in pos_list:
        c = p.contract
        result.append({
            "account":    p.account,
            "symbol":     c.symbol,
            "sec_type":   c.secType,
            "exchange":   c.exchange,
            "currency":   c.currency,
            "position":   p.position,
            "avg_cost":   p.avgCost,
            "market_value": round(p.position * p.avgCost, 2) if p.position and p.avgCost else None,
        })

    return sorted(result, key=lambda x: x["symbol"])
