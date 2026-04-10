"""
GlitchExecutor Telegram Bot - Main Bot Logic
Receives customer messages, authenticates, queries ensemble, returns AI analysis.
"""
import os
import sys
import uuid
import logging
import re
import asyncio
from datetime import datetime
from typing import Optional

import httpx

# Add ensemble path for imports
sys.path.insert(0, '/opt/glitchexecutor/ensemble')

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)

from db import Database
from auth import AuthManager
from rate_limiter import RateLimiter
from orchestrator import Orchestrator
from redis_cache import EnsembleCache
from alerts import AlertManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("TelegramBot")


class GlitchExecutorBot:
    """Main Telegram bot for GlitchExecutor."""
    
    def __init__(self):
        """Initialize bot components."""
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN environment variable required")
        
        # Initialize components
        self.db = Database()
        self.auth = AuthManager()
        self.rate_limiter = RateLimiter()
        self.orchestrator = Orchestrator(
            api_key=os.environ.get("ORCHESTRATOR_LLM_KEY"),
            provider=os.environ.get("ORCHESTRATOR_LLM_PROVIDER", "anthropic")
        )
        self.cache = EnsembleCache(
            host=os.environ.get("REDIS_HOST", "localhost"),
            port=int(os.environ.get("REDIS_PORT", 6379))
        )

        # Ensemble on-demand API (port 8100 on the ensemble container)
        self.ensemble_api = os.environ.get("ENSEMBLE_API_URL", "http://ensemble:8100")
        
        # Alert manager (price alerts, signal alerts, daily briefings)
        self.alert_manager = AlertManager(self.db, self.cache)

        # RAG assistant (Vertex AI Gemini — natural language queries over trade data)
        from rag_assistant import RAGAssistant
        self.rag_assistant = RAGAssistant(
            project=os.environ.get("GCP_PROJECT", "capable-boulder-487806-j0"),
            location=os.environ.get("GCP_LOCATION", "us-central1"),
            db=self.db,
            cache=self.cache,
        )

        # Track last analysis per user for execute + context shortcuts
        self.last_analysis = {}

        # Pending trade confirmations waiting for inline button press
        # {request_id: {'trade_request': dict, 'user_id': int, 'expires_at': float}}
        self.pending_trades = {}

        # Pending admin broadcast confirmations
        # {broadcast_id: {'message': str, 'tier_filter': str, 'telegram_ids': list}}
        self.pending_broadcasts = {}

        # Admin Telegram ID (set via ADMIN_TELEGRAM_ID env var)
        _raw_admin = os.environ.get("ADMIN_TELEGRAM_ID", "0").strip()
        self._admin_id = int(_raw_admin) if _raw_admin.isdigit() else 0

        # Multi-step exchange connection state per user
        # {user_id: {'state': str, 'exchange': str, 'api_key': str,
        #            'needs_passphrase': bool, 'passphrase': str}}
        self.pending_exchange_setup = {}

        # Exchanges requiring a passphrase in addition to key+secret
        self.passphrase_exchanges = {'kucoin', 'okx', 'okex', 'okcoin', 'kucoinfutures'}

        # Popular exchanges to suggest (any valid CCXT ID is accepted)
        self.popular_exchanges = [
            'binance', 'bybit', 'okx', 'kraken', 'kucoin',
            'bitget', 'mexc', 'gateio', 'coinbase', 'bitfinex',
        ]

        logger.info("Bot initialized")
    
    # Words that should NOT be treated as stock tickers
    _STOP_WORDS = frozenset({
        'THE', 'AND', 'FOR', 'ARE', 'BUT', 'NOT', 'ALL', 'CAN', 'ITS',
        'WITH', 'THIS', 'THAT', 'FROM', 'THEY', 'WILL', 'ONE', 'BEEN',
        'HAS', 'HAD', 'WHAT', 'WHEN', 'WHO', 'HOW', 'WHY', 'USD', 'BUY',
        'SELL', 'HOLD', 'YES', 'NO', 'ANY', 'USE', 'NEW', 'GET', 'NOW',
        'LET', 'RUN', 'SET', 'PUT', 'HIT', 'WIN', 'TOP', 'LOW', 'HIGH',
        'OLD', 'TOO', 'TWO', 'SIX', 'TEN', 'DAY', 'WAY', 'SAY', 'MAY',
        'KEY', 'FAR', 'LOT', 'OUT', 'OFF', 'OWN', 'HIM', 'HER', 'HIS',
        'ITS', 'OUR', 'YOU', 'WAS', 'DID', 'LET', 'PUT', 'SEE', 'TRY',
        'ASK', 'AI', 'OK', 'GO', 'DO', 'IT', 'AT', 'AS', 'IS', 'IN',
        'ON', 'OF', 'TO', 'UP', 'AN', 'BY', 'OR', 'SO', 'IF', 'ME',
        # Common chat words that look like tickers
        'HELLO', 'HI', 'HEY', 'THANKS', 'THANK', 'GREAT', 'GOOD', 'NICE',
        'SURE', 'FINE', 'COOL', 'DONE', 'HELP', 'ABOUT', 'JUST', 'WELL',
        'ALSO', 'BACK', 'MUCH', 'LONG', 'EVEN', 'HERE', 'MAKE', 'TAKE',
        'GIVE', 'LIKE', 'KNOW', 'LOOK', 'NEED', 'WANT', 'COME', 'FIND',
        'SOME', 'ONLY', 'WORK', 'BEEN', 'MORE', 'WHEN', 'THEN', 'THAN',
        'THEM', 'EACH', 'OVER', 'MOST', 'SUCH', 'THERE', 'WHERE', 'THESE',
        'THOSE', 'OTHER', 'AFTER', 'THINK', 'COULD', 'WOULD', 'SHOULD',
        'STILL', 'WHILE', 'SINCE', 'UNTIL', 'NEVER', 'AGAIN', 'BEING',
        'THEIR', 'EVERY', 'MIGHT', 'GOING', 'WHICH', 'FIRST', 'YEAH',
        'YEP', 'NAH', 'NOPE', 'LMAO', 'LMFAO', 'LOL', 'BRO', 'DUDE',
        'OKAY', 'WHAT', 'BOTH', 'KEEP', 'SHOW', 'LAST', 'NEXT',
    })

    # ── Education keywords that should NOT trigger symbol extraction ─────────
    _EDUCATION_PHRASES = frozenset({
        'what is', 'what are', 'explain', 'how does', 'how do', 'how to',
        'tell me about', 'define', 'meaning of', 'difference between',
        'teach me', 'learn about', 'understand',
    })

    _EDUCATION_TERMS = frozenset({
        'rsi', 'macd', 'bollinger', 'fibonacci', 'moving average', 'ema', 'sma',
        'candlestick', 'doji', 'hammer', 'engulfing', 'morning star', 'evening star',
        'support', 'resistance', 'trend line', 'trendline', 'breakout', 'breakdown',
        'golden cross', 'death cross', 'head and shoulders', 'double top', 'double bottom',
        'stop loss', 'take profit', 'risk reward', 'position sizing', 'leverage',
        'margin', 'pip', 'spread', 'lot size', 'scalping', 'swing trading',
        'day trading', 'ichimoku', 'stochastic', 'atr', 'volume profile',
        'order book', 'market order', 'limit order', 'stop order',
        'bull flag', 'bear flag', 'wedge', 'triangle', 'channel',
        'divergence', 'convergence', 'overbought', 'oversold',
    })

    def _classify_intent(self, text: str, last_analysis: dict = None):
        """
        Classify user intent. Pure Python — no LLM call.
        Returns: (intent_type, data)
          "education"      → []
          "compare"        → [sym1, sym2]
          "preference_set" → {"action": "add"|"remove"|"list", "symbol": str|None}
          "analysis"       → [symbol]
          "followup"       → {"symbol": str}  (context from last analysis)
          "chat"           → []
        """
        text_lower = text.lower().strip()

        # ── 1. Education phrases — must come BEFORE symbol extraction ─────────
        # "what is RSI?", "explain bollinger bands", "how does MACD work?"
        for phrase in self._EDUCATION_PHRASES:
            if text_lower.startswith(phrase) or f' {phrase} ' in f' {text_lower} ':
                # Check if it's about a specific education topic
                for term in self._EDUCATION_TERMS:
                    if term in text_lower:
                        return ("chat", [])
                # Even without a known term, "what is X" patterns → chat
                if any(text_lower.startswith(p) for p in ('what is', 'what are', 'explain',
                                                           'how does', 'how do', 'how to',
                                                           'teach me', 'define')):
                    return ("chat", [])

        # ── 2. Compare patterns ───────────────────────────────────────────────
        # "compare AAPL vs TSLA", "BTCUSD or ETHUSD?", "AAPL versus TSLA"
        compare_patterns = [
            r'compare\s+(\S+)\s+(?:vs\.?|versus|and|or|with)\s+(\S+)',
            r'(\S+)\s+vs\.?\s+(\S+)',
            r'(\S+)\s+or\s+(\S+)\s*\??',
            r'(\S+)\s+versus\s+(\S+)',
        ]
        for pattern in compare_patterns:
            match = re.search(pattern, text_lower)
            if match:
                sym1 = self._resolve_symbol(match.group(1))
                sym2 = self._resolve_symbol(match.group(2))
                if sym1 and sym2 and sym1 != sym2:
                    return ("compare", [sym1, sym2])

        # ── 3. Preference patterns ────────────────────────────────────────────
        # "favorite BTCUSD", "add AAPL to favorites", "remove TSLA from favorites"
        # "my favorites", "show favorites"
        fav_list_patterns = [
            r'\b(?:my |show |list )?favorites?\b',
            r'\bmy (?:fav|preferred) (?:symbols?|stocks?|coins?|cryptos?)\b',
        ]
        for pattern in fav_list_patterns:
            if re.search(pattern, text_lower):
                # Check if it's also an add/remove
                add_match = re.search(r'(?:favorite|fav|add)\s+(\S+)', text_lower)
                if add_match:
                    sym = self._resolve_symbol(add_match.group(1))
                    if sym:
                        return ("preference_set", {"action": "add", "symbol": sym})
                return ("preference_set", {"action": "list", "symbol": None})

        fav_add = re.search(r'(?:favorite|fav|add to (?:fav|favorites?))\s+(\S+)', text_lower)
        if fav_add:
            sym = self._resolve_symbol(fav_add.group(1))
            if sym:
                return ("preference_set", {"action": "add", "symbol": sym})

        fav_remove = re.search(r'(?:unfavorite|remove from (?:fav|favorites?)|remove fav)\s+(\S+)', text_lower)
        if fav_remove:
            sym = self._resolve_symbol(fav_remove.group(1))
            if sym:
                return ("preference_set", {"action": "remove", "symbol": sym})

        # ── 3b. RAG data queries — questions about trade history, performance, data ──
        _rag_triggers = [
            r'\bhow did .+ perform', r'\bshow my trades?\b', r'\btrade history\b',
            r'\bmy positions?\b', r'\bmy alerts?\b', r'\bbot positions?\b',
            r'\bsignal accuracy\b', r'\bwin rate\b', r'\bpnl\b', r'\bprofit.loss\b',
            r'\bhow am i doing\b', r'\bmy performance\b', r'\bquery history\b',
            r'\bbot events?\b', r'\bwhat trades\b', r'\brecent signals?\b',
            r'\bplatform stats\b', r'\bprediction history\b',
        ]
        for pattern in _rag_triggers:
            if re.search(pattern, text_lower):
                return ("rag_query", [])

        # ── 4. Symbol extraction → analysis ───────────────────────────────────
        symbol = self._extract_symbol(text)
        if not symbol:
            symbol = self._extract_symbol_from_query(text)
        if symbol:
            return ("analysis", [symbol])

        # ── 5. Contextual follow-up (needs last_analysis) ────────────────────
        # "why sell?", "should I buy?", "explain more", "is it a good entry?"
        followup_patterns = [
            r'\bwhy\b', r'\bshould i\b', r'\bis it\b', r'\bexplain\b',
            r'\bmore detail\b', r'\btell me more\b', r'\bgood entry\b',
            r'\bgood time\b', r'\bwhat about\b', r'\bany risk\b',
            r'\bstop loss\b', r'\btarget\b', r'\bwhat do you think\b',
        ]
        if last_analysis:
            for pattern in followup_patterns:
                if re.search(pattern, text_lower):
                    return ("followup", {"symbol": last_analysis.get("symbol")})

        # ── 6. General market questions → chat ────────────────────────────────
        market_patterns = [
            r'\bmarket\b', r'\bbull\b', r'\bbear\b', r'\brally\b', r'\bcrash\b',
            r'\bpump\b', r'\bdump\b', r'\bwhat.s happening\b', r'\bwhy is\b',
            r'\btrading\b', r'\binvest\b', r'\bportfolio\b', r'\bstrategy\b',
            r'\bprofit\b', r'\bloss\b', r'\brisk\b', r'\bhedge\b',
        ]
        for pattern in market_patterns:
            if re.search(pattern, text_lower):
                return ("chat", [])

        # ── 7. Everything else → chat ─────────────────────────────────────────
        return ("chat", [])

    def _resolve_symbol(self, text: str) -> Optional[str]:
        """Try to resolve text to a valid trading symbol."""
        if not text:
            return None
        # Try direct symbol extraction
        sym = self._extract_symbol(text)
        if sym:
            return sym
        # Try keyword-based extraction
        sym = self._extract_symbol_from_query(text)
        return sym

    def _extract_symbol(self, text: str) -> Optional[str]:
        """Extract trading symbol from message text."""
        text = text.upper().strip()

        # ── 1. Explicit pair patterns (highest confidence) ───────────────────
        patterns = [
            # Crypto with quote: BTC/USDT, ETH-USDT, SOLUSDT
            r'\b([A-Z]{2,6})[/\-](USD[TC]?)\b',
            # Crypto fused: BTCUSD, ETHUSD, XRPUSDT
            r'\b(BTC|ETH|SOL|XRP|BNB|ADA|DOT|AVAX|MATIC|LINK|LTC|BCH|DOGE|SHIB|'
            r'UNI|TON|NEAR|SUI|PEPE|APT|INJ|OP|ARB|FTM|ATOM|ALGO|TRX|XLM|'
            r'HBAR|ICP|FIL|VET|FLOW|ZEC|XMR|DASH)(USD[TC]?)\b',
            # Forex / commodity pairs
            r'\b(EUR|GBP|AUD|NZD|CAD|CHF|JPY|NOK|SEK|MXN|ZAR|SGD|HKD|'
            r'XAU|XAG|XPT|XPD)[/\-]?(USD|EUR|GBP|JPY|AUD|CAD|CHF|NZD)\b',
            # Already-normalised symbols like EURUSD, GBPUSD, XAUUSD
            r'\b(EUR|GBP|AUD|NZD|CAD|CHF|XAU|XAG|XPT)(USD)\b',
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                symbol = match.group(0).replace('/', '').replace('-', '')
                if symbol.startswith('XBT'):
                    symbol = 'BTCUSD'
                elif symbol.endswith('USDT') or symbol.endswith('USDC'):
                    symbol = symbol[:-1]  # strip T/C → USDT→USD, USDC→USD
                return symbol

        # ── 2. Stock / ETF ticker (2-5 uppercase letters, standalone word) ───
        # Applied only when the original text has an obvious ticker shape
        # (all-caps word not in common English stop-word list)
        for word in re.findall(r'\b[A-Z]{2,5}\b', text):
            if word not in self._STOP_WORDS:
                return word  # Return first plausible ticker found

        return None
    
    def _extract_symbol_from_query(self, text: str) -> Optional[str]:
        """Extract symbol from natural language query (company names, crypto names, forex terms)."""
        text_lower = text.lower()

        # ── All keyword maps — longer phrases first to avoid short-match shadowing ──
        keyword_map = {
            # ── Crypto (full names first, short tickers second) ──────────────
            'bitcoin cash':  'BCHUSD',
            'bitcoin':       'BTCUSD',
            'ethereum':      'ETHUSD',
            'solana':        'SOLUSD',
            'ripple':        'XRPUSD',
            'cardano':       'ADAUSD',
            'avalanche':     'AVAXUSD',
            'polygon':       'MATICUSD',
            'polkadot':      'DOTUSD',
            'chainlink':     'LINKUSD',
            'dogecoin':      'DOGEUSD',
            'shiba inu':     'SHIBUSD',
            'litecoin':      'LTCUSD',
            'uniswap':       'UNIUSD',
            'toncoin':       'TONUSD',
            'near protocol': 'NEARUSD',
            'injective':     'INJUSD',
            'arbitrum':      'ARBUSD',
            'optimism':      'OPUSD',
            'aptos':         'APTUSD',
            'filecoin':      'FILUSD',
            'hedera':        'HBARUSD',
            'internet computer': 'ICPUSD',
            'cosmos':        'ATOMUSD',
            'algorand':      'ALGOUSD',
            'tron':          'TRXUSD',
            'stellar':       'XLMUSD',
            'fantom':        'FTMUSD',
            'aave':          'AAVEUSD',
            'curve':         'CRVUSD',
            # Short crypto tickers
            'btc': 'BTCUSD', 'eth': 'ETHUSD', 'sol': 'SOLUSD', 'xrp': 'XRPUSD',
            'bnb': 'BNBUSD', 'ada': 'ADAUSD', 'avax': 'AVAXUSD', 'matic': 'MATICUSD',
            'doge': 'DOGEUSD', 'shib': 'SHIBUSD', 'ltc': 'LTCUSD', 'bch': 'BCHUSD',
            'uni': 'UNIUSD', 'link': 'LINKUSD', 'ton': 'TONUSD', 'near': 'NEARUSD',
            'sui': 'SUIUSD', 'pepe': 'PEPEUSD', 'apt': 'APTUSD', 'inj': 'INJUSD',
            'arb': 'ARBUSD', 'ftm': 'FTMUSD', 'atom': 'ATOMUSD', 'algo': 'ALGOUSD',
            'trx': 'TRXUSD', 'xlm': 'XLMUSD', 'hbar': 'HBARUSD', 'icp': 'ICPUSD',
            'fil': 'FILUSD', 'vet': 'VETUSD', 'flow': 'FLOWUSD', 'crv': 'CRVUSD',
            # ── US Stocks / ETFs ─────────────────────────────────────────────
            'apple':         'AAPL',
            'nvidia':        'NVDA',
            'tesla':         'TSLA',
            'microsoft':     'MSFT',
            'amazon':        'AMZN',
            'alphabet':      'GOOGL',
            'google':        'GOOGL',
            'meta':          'META',
            'facebook':      'META',
            'netflix':       'NFLX',
            'palantir':      'PLTR',
            'amd':           'AMD',
            'intel':         'INTC',
            'qualcomm':      'QCOM',
            'broadcom':      'AVGO',
            'jpmorgan':      'JPM',
            'jp morgan':     'JPM',
            'goldman sachs': 'GS',
            'goldman':       'GS',
            'berkshire':     'BRK.B',
            'visa':          'V',
            'mastercard':    'MA',
            'johnson':       'JNJ',
            'pfizer':        'PFE',
            'eli lilly':     'LLY',
            'abbvie':        'ABBV',
            'exxon':         'XOM',
            'chevron':       'CVX',
            'walmart':       'WMT',
            'costco':        'COST',
            'mcdonald':      'MCD',
            'starbucks':     'SBUX',
            'boeing':        'BA',
            'disney':        'DIS',
            'salesforce':    'CRM',
            'oracle':        'ORCL',
            'ibm':           'IBM',
            'uber':          'UBER',
            'airbnb':        'ABNB',
            'coinbase':      'COIN',
            # Index ETFs
            's&p 500':       'SPY',
            'sp500':         'SPY',
            's&p':           'SPY',
            'nasdaq':        'QQQ',
            'dow jones':     'DIA',
            'russell':       'IWM',
            # ── Forex (natural-language names) ───────────────────────────────
            'euro':          'EURUSD',
            'eur usd':       'EURUSD',
            'pound':         'GBPUSD',
            'sterling':      'GBPUSD',
            'gbp usd':       'GBPUSD',
            'cable':         'GBPUSD',
            'yen':           'USDJPY',
            'usd jpy':       'USDJPY',
            'aussie':        'AUDUSD',
            'aud usd':       'AUDUSD',
            'loonie':        'USDCAD',
            'usd cad':       'USDCAD',
            'swissie':       'USDCHF',
            'usd chf':       'USDCHF',
            'kiwi':          'NZDUSD',
            'nzd usd':       'NZDUSD',
            # ── Commodities ──────────────────────────────────────────────────
            'gold':          'XAUUSD',
            'silver':        'XAGUSD',
            'platinum':      'XPTUSD',
        }

        for keyword, symbol in keyword_map.items():
            if len(keyword) <= 4:
                if re.search(r'\b' + re.escape(keyword) + r'\b', text_lower):
                    return symbol
            else:
                if keyword in text_lower:
                    return symbol

        return None
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command, including referral deep-links (?start=ref_CODE)."""
        user = update.effective_user
        await self.db.connect()

        # Check for deep-link parameter (reg_ handled by payment server; ref_ handled here)
        start_param = context.args[0] if context.args else None
        referral_code = None
        if start_param and start_param.startswith('ref_'):
            referral_code = start_param[4:]

        # Authenticate/create customer
        customer, error, is_new = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return

        # Process referral (only for new-ish users without a prior referral)
        if referral_code:
            referrer = await self.db.get_customer_by_referral_code(referral_code)
            if referrer and referrer['id'] != customer['id']:
                rewarded = await self.db.record_referral(
                    referrer['id'], customer['id'], referral_code
                )
                if rewarded:
                    await update.message.reply_text(
                        "🎁 <b>Referral bonus applied!</b>\n\n"
                        "Your trial has been extended by <b>+2 days</b>.\n"
                        "Your referrer earned +3 days too.",
                        parse_mode='HTML'
                    )

        # Fetch today's query count for the personalised returning greeting
        queries_used = 0
        if not is_new:
            queries_used = await self.db.get_queries_today(customer['id'])

        welcome_msg = self.auth.get_welcome_message(
            customer,
            is_new=is_new,
            first_name=user.first_name,
            queries_used=queries_used,
        )

        # Admin gets an extra control panel hint
        if self._is_admin(user.id):
            welcome_msg += (
                "\n\n━━━━━━━━━━━━━━━\n"
                "🛠 <b>Admin panel</b>\n"
                "/admin stats — platform dashboard\n"
                "/admin broadcast all &lt;msg&gt; — message everyone"
            )

        await update.message.reply_text(welcome_msg, parse_mode='HTML')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        help_text = """🔮 <b>GlitchExecutor Commands</b>

<b>AI Chat</b>
Just talk to me! I understand natural language:
• <i>"what is RSI?"</i> — trading education
• <i>"what's happening in the market?"</i> — commentary
• <i>"compare AAPL vs TSLA"</i> — side-by-side analysis
• <i>"why did you say sell?"</i> — follow-up questions

<b>Analysis</b>
/analyse &lt;symbol&gt; — Full AI analysis (e.g. /analyse BTCUSD)
/analyze &lt;symbol&gt; — same as above
/scan [SYM1 SYM2 ...] — Quick signal table for all markets
Type <code>BTCUSD</code> or ask <i>"should I buy bitcoin?"</i>

<b>Favorites</b>
<code>favorite BTCUSD</code> — Add to your favorites
<code>unfavorite BTCUSD</code> — Remove from favorites
<code>my favorites</code> — Show your list with live prices
<i>⚡ Strong signals (75%+) on favorites send auto-notifications!</i>

<b>Trading</b>
/execute — Review &amp; confirm a trade from last analysis (Pro/Elite)
/autoexecute — Auto-trade on strong signals (Pro/Elite)
Or type <code>execute</code> after any analysis

<b>Alerts &amp; Notifications</b>
/setalert &lt;symbol&gt; &lt;price&gt; — Price alert (e.g. /setalert BTCUSD 50000)
/alerts — List your active price alerts
/cancelalert &lt;id&gt; — Cancel a price alert
/watch &lt;symbol&gt; [confidence%] — Signal alerts
/unwatch &lt;symbol&gt; — Stop signal alerts
/watchlist — Show watched symbols
/briefing — Toggle daily 07:00 UTC briefing

<b>Account</b>
/status — Tier, query usage, connected exchange
/plans — Compare tiers &amp; upgrade
/referral — Your referral link (+3 days per invite)
/connect_exchange — Link your exchange API
/connect_mt5 — Link MT5 account (Elite only)

<b>Conversation</b>
<code>clear chat</code> — Reset conversation history
I remember context for 1 hour (last 5 exchanges).

<b>Tiers</b>
🆓 Trial (10/day) · ⭐ Starter (30/day) · 🤖 Pro (100/day) · 🏢 Elite (∞)
Upgrade: glitchexecutor.com/pricing"""
        await update.message.reply_text(help_text, parse_mode='HTML')
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command."""
        user = update.effective_user
        await self.db.connect()
        
        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return
        
        tier = customer.get('tier', 'trial')
        current = await self.db.get_queries_today(customer.get('id'))
        limit = self.rate_limiter.get_limit(tier)
        status_msg = self.rate_limiter.get_status_message(current, limit, tier)
        
        tier_emoji = {"trial": "🆓", "starter": "⭐", "pro": "🤖", "elite": "🏢"}

        response = f"{tier_emoji.get(tier, '🆓')} <b>Tier:</b> {tier.upper()}\n{status_msg}"

        if tier == 'trial':
            trial_ends = customer.get('trial_ends_at')
            if trial_ends:
                days_left = (trial_ends - datetime.utcnow()).days
                response += f"\n⏰ Trial ends in {days_left} days"

        # Show connected exchanges
        connected = await self.db.get_connected_exchanges(customer.get('id'))
        if connected:
            response += f"\n\n🔗 <b>Connected:</b> {', '.join(connected).title()}"
            if tier not in ['pro', 'elite']:
                response += "\n   <i>(upgrade to Pro for auto-execution)</i>"
        else:
            response += "\n\n🔗 No exchange connected — use /connect_exchange"

        await update.message.reply_text(response, parse_mode='HTML')
    
    async def analyze_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /analyze command."""
        user = update.effective_user
        text = update.message.text
        
        # Extract symbol from command
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text(
                "Please specify a symbol. Example: /analyze BTCUSD"
            )
            return
        
        symbol = parts[1].upper()
        await self._handle_analysis(update, user, symbol, text)
    
    async def _trigger_on_demand(self, symbol: str) -> bool:
        """
        Ask the ensemble engine to run on-demand analysis for any symbol.
        The engine writes results to Redis; we read from Redis after this returns.
        Timeout: 90 s (IB historical data can take ~15–30 s for 3 timeframes).
        """
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.get(
                    f"{self.ensemble_api}/analyze",
                    params={"symbol": symbol},
                )
                return resp.status_code == 200
        except Exception as exc:
            logger.warning(f"[on-demand] Trigger failed for {symbol}: {exc}")
            return False

    async def _handle_analysis(self, update: Update, user, symbol: str, original_text: str):
        """Handle analysis request."""
        # Connect to DB
        await self.db.connect()
        
        # Authenticate
        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return
        
        # Check rate limit
        allowed, message, current, limit = await self.rate_limiter.check_and_increment(
            self.db, customer
        )
        
        if not allowed:
            user_id = update.effective_user.id if update.effective_user else 0
            await update.message.reply_text(
                "📊 <b>Daily query limit reached.</b>\n\nUpgrade for more queries 👇",
                parse_mode='HTML',
                reply_markup=self._upgrade_keyboard(user_id, ['starter', 'pro', 'elite'])
            )
            return
        
        # Get ensemble data from Redis
        ensemble_data = self.cache.read_votes(symbol)

        if not ensemble_data:
            # No cached data — trigger a fresh on-demand run for this symbol
            loading = await update.message.reply_text(
                f"🔄 Running fresh AI analysis for *{symbol}*…\n"
                f"This takes ~10–20 seconds for new symbols.",
                parse_mode='Markdown'
            )
            await self._trigger_on_demand(symbol)
            await loading.delete()

            ensemble_data = self.cache.read_votes(symbol)
            if not ensemble_data:
                await update.message.reply_text(
                    f"⚠️ Could not fetch data for *{symbol}*.\n\n"
                    "• For stocks/ETFs: `AAPL`, `NVDA`, `TSLA`, `SPY`\n"
                    "• For forex: `EURUSD`, `GBPUSD`, `USDJPY`\n"
                    "• For crypto: `BTCUSD`, `ETHUSD`, `SOLUSD`\n\n"
                    "Make sure IB Gateway is running for stocks/forex.",
                    parse_mode='Markdown'
                )
                return
        
        # Get sentiment data
        sentiment = self.cache.read_sentiment(symbol)
        
        # Get current price from Redis cache
        current_price = self.cache.read_price(symbol) or 0.0

        # Parse timestamp to show how fresh the data is
        updated_at = ensemble_data.get('updated_at', '')
        minutes_ago = 0
        if updated_at:
            try:
                updated = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                minutes_ago = int((datetime.utcnow() - updated.replace(tzinfo=None)).total_seconds() / 60)
            except Exception:
                pass

        # Check if customer can execute trades
        can_execute = self.auth.can_execute(customer)
        tier = customer.get('tier', 'trial')

        # Send "thinking" message
        thinking_msg = await update.message.reply_text(
            f"🔮 Analyzing {symbol}... ({limit - current} queries left)"
        )

        # Get conversation history for multi-turn context
        history = self.cache.get_chat_history(user.id)

        # Build consensus_data with bias + key levels for HOLD guidance
        consensus_data = {
            "bias": ensemble_data.get("bias"),
            "key_levels": ensemble_data.get("key_levels"),
        }

        try:
            # Synthesize response via LLM
            response = await self.orchestrator.synthesize(
                user_query=original_text,
                symbol=symbol,
                tier=tier,
                can_execute=can_execute,
                votes=ensemble_data.get('votes', []),
                sentiment=sentiment or {},
                current_price=current_price,
                minutes_ago=minutes_ago,
                conversation_history=history,
                consensus_data=consensus_data
            )
        except Exception as e:
            logger.error(f"LLM synthesis failed, using template: {e}")
            try:
                response = self.orchestrator._template_response(
                    ensemble_data.get('votes', []),
                    sentiment or {},
                    current_price,
                    can_execute,
                    consensus_data
                )
            except Exception as fallback_err:
                logger.error(f"Template fallback also failed: {fallback_err}")
                response = (
                    f"Analysis for {symbol} is temporarily unavailable.\n"
                    "The ensemble data exists but response generation failed.\n"
                    "Please try again shortly."
                )

        # Store last analysis for execute command
        self.last_analysis[user.id] = {
            'symbol': symbol,
            'consensus': ensemble_data.get('consensus'),
            'timestamp': datetime.utcnow()
        }

        # Delete thinking message and send response
        await thinking_msg.delete()
        await update.message.reply_text(response)

        # Store in conversation history
        self.cache.append_chat_message(user.id, "user", original_text, symbol=symbol)
        self.cache.append_chat_message(user.id, "assistant", response[:500],
                                       symbol=symbol, had_analysis=True)

        # Starter funnel: show missed trade conversion hook
        consensus = ensemble_data.get('consensus', 'HOLD')
        if tier in ['trial', 'starter'] and consensus in ['BUY', 'SELL'] and current_price > 0:
            paper_trade = self.cache.read_paper_trade(symbol)
            if paper_trade:
                entry_price = paper_trade.get('entry_price', 0)
                direction = paper_trade.get('direction', '')
                if entry_price > 0:
                    if direction == 'BUY':
                        pnl = current_price - entry_price
                    else:
                        pnl = entry_price - current_price
                    pnl_pct = (pnl / entry_price) * 100
                    pnl_sign = "+" if pnl >= 0 else ""
                    await update.message.reply_text(
                        f"💡 Pro members auto-executed this {direction} at ${entry_price:,.2f}.\n"
                        f"Current P&L: {pnl_sign}${pnl:,.2f} ({pnl_sign}{pnl_pct:.2f}%)\n\n"
                        f"Upgrade to auto-trade the next one 👇",
                        reply_markup=self._upgrade_keyboard(user.id, ['pro', 'elite'])
                    )

        # Log query
        await self.db.log_query(
            customer.get('id'), symbol, original_text, "analysis", 0.0
        )

        # Log prediction for ML ensemble fine-tuning
        try:
            await self.db.log_ensemble_prediction(
                symbol=symbol,
                price=current_price or 0.0,
                consensus=ensemble_data.get('consensus', 'HOLD'),
                confidence=ensemble_data.get('confidence', 0.0),
                votes=ensemble_data.get('votes', []),
                sentiment_direction=sentiment.get('direction') if sentiment else None,
                sentiment_score=sentiment.get('score') if sentiment else None,
                triggered_by=user.id
            )
        except Exception as e:
            logger.warning(f"Prediction logging failed (non-fatal): {e}")

    # ── Chat Handler ─────────────────────────────────────────────────────────

    async def _handle_rag_query(self, update: Update, user, text: str):
        """Handle data questions via Vertex AI RAG pipeline."""
        await self.db.connect()

        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return

        # Rate limit check
        allowed, msg, current, limit = await self.rate_limiter.check_and_increment(self.db, customer)
        if not allowed:
            await update.message.reply_text(msg, parse_mode='HTML')
            return

        # Send thinking indicator
        thinking = await update.message.reply_text("🔍 Querying your data...")

        try:
            response = await self.rag_assistant.ask(text, customer['id'])
            await thinking.delete()
            await update.message.reply_text(response, parse_mode='HTML')
            await self.db.log_query(customer['id'], '', text, 'rag')
        except Exception as e:
            logger.error(f"RAG query error: {e}")
            try:
                await thinking.delete()
            except Exception:
                pass
            await update.message.reply_text(
                "Sorry, I couldn't process that query. Try rephrasing or use /help for commands."
            )

    async def ask_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /ask command — explicit RAG query."""
        if not context.args:
            await update.message.reply_text(
                "💡 <b>Ask me anything about your data:</b>\n\n"
                "• <code>/ask how did BTC signals perform?</code>\n"
                "• <code>/ask show my trades</code>\n"
                "• <code>/ask what's the current sentiment on ETH?</code>\n"
                "• <code>/ask bot positions last 7 days</code>\n"
                "• <code>/ask platform stats</code>",
                parse_mode='HTML'
            )
            return
        text = ' '.join(context.args)
        await self._handle_rag_query(update, update.effective_user, text)

    async def _handle_chat(self, update: Update, user, text: str):
        """Handle general trading chat — education, market commentary, etc."""
        await self.db.connect()

        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return

        # Rate limit check (chat counts as a normal query)
        allowed, message, current, limit = await self.rate_limiter.check_and_increment(
            self.db, customer
        )
        if not allowed:
            user_id = update.effective_user.id if update.effective_user else 0
            await update.message.reply_text(
                "📊 <b>Daily query limit reached.</b>\n\nUpgrade for more queries 👇",
                parse_mode='HTML',
                reply_markup=self._upgrade_keyboard(user_id, ['starter', 'pro', 'elite'])
            )
            return

        # Get conversation history from Redis
        history = self.cache.get_chat_history(user.id)

        # Build user context with favorites' market data
        tier = customer.get('tier', 'trial')
        user_context = {"tier": tier, "favorites": {}}

        try:
            favorites = await self.db.get_favorite_symbols(customer['id'])
            for sym in favorites[:5]:  # cap at 5 to keep context small
                price = self.cache.read_price(sym)
                votes = self.cache.read_votes(sym)
                user_context["favorites"][sym] = {
                    "price": f"{price:,.4f}" if price else "N/A",
                    "consensus": votes.get("consensus", "N/A") if votes else "N/A",
                }
        except Exception:
            pass  # preferences table may not exist yet

        # Call LLM
        thinking_msg = await update.message.reply_text("💭 Thinking...")
        try:
            response = await self.orchestrator.chat(
                user_message=text,
                conversation_history=history,
                user_context=user_context,
            )
        except Exception as e:
            logger.error(f"Chat LLM failed: {e}")
            response = ("I'm having trouble right now. Try asking about a specific symbol "
                        "like BTCUSD, or type /help to see all commands.")

        await thinking_msg.delete()
        await update.message.reply_text(response)

        # Store both messages in Redis history
        self.cache.append_chat_message(user.id, "user", text)
        self.cache.append_chat_message(user.id, "assistant", response)

        # Log query
        await self.db.log_query(customer['id'], None, text, "chat", 0.0)

    # ── Comparison Handler ────────────────────────────────────────────────────

    async def _handle_comparison(self, update: Update, user, symbols: list, text: str):
        """Handle symbol comparison — run ensemble for both, then LLM comparison."""
        await self.db.connect()

        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return

        # Rate limit (counts as 1 query)
        allowed, message, current, limit = await self.rate_limiter.check_and_increment(
            self.db, customer
        )
        if not allowed:
            user_id = update.effective_user.id if update.effective_user else 0
            await update.message.reply_text(
                "📊 <b>Daily query limit reached.</b>\n\nUpgrade for more queries 👇",
                parse_mode='HTML',
                reply_markup=self._upgrade_keyboard(user_id, ['starter', 'pro', 'elite'])
            )
            return

        sym1, sym2 = symbols[0], symbols[1]
        thinking_msg = await update.message.reply_text(
            f"🔄 Comparing {sym1} vs {sym2}... Running analysis on both."
        )

        # Trigger on-demand analysis for both symbols in parallel
        trigger_tasks = [self._trigger_on_demand(sym1), self._trigger_on_demand(sym2)]
        await asyncio.gather(*trigger_tasks, return_exceptions=True)

        # Read results from Redis
        analyses = []
        for sym in [sym1, sym2]:
            ensemble_data = self.cache.read_votes(sym)
            sentiment = self.cache.read_sentiment(sym)
            price = self.cache.read_price(sym) or 0.0

            if ensemble_data:
                analyses.append({
                    "symbol": sym,
                    "votes": ensemble_data.get("votes", []),
                    "consensus": ensemble_data.get("consensus", "HOLD"),
                    "confidence": ensemble_data.get("confidence", 0),
                    "sentiment": sentiment or {},
                    "price": price,
                })
            else:
                analyses.append({
                    "symbol": sym, "votes": [], "consensus": "N/A",
                    "confidence": 0, "sentiment": {}, "price": price,
                })

        if not any(a["votes"] for a in analyses):
            await thinking_msg.delete()
            await update.message.reply_text(
                f"⚠️ Could not fetch data for {sym1} or {sym2}.\n"
                "Make sure both symbols are valid and try again."
            )
            return

        # Get conversation history
        history = self.cache.get_chat_history(user.id)
        tier = customer.get('tier', 'trial')

        try:
            response = await self.orchestrator.compare(
                user_query=text,
                symbols=[sym1, sym2],
                analyses=analyses,
                conversation_history=history,
            )
        except Exception as e:
            logger.error(f"Comparison LLM failed: {e}")
            response = self.orchestrator._template_comparison(analyses)

        await thinking_msg.delete()
        await update.message.reply_text(response, parse_mode='HTML')

        # Update last_analysis with the first symbol for follow-up context
        self.last_analysis[user.id] = {
            'symbol': sym1,
            'consensus': analyses[0].get('consensus'),
            'timestamp': datetime.utcnow(),
        }

        # Store in conversation history
        self.cache.append_chat_message(user.id, "user", text, symbol=f"{sym1},{sym2}")
        self.cache.append_chat_message(user.id, "assistant", response[:500],
                                       had_analysis=True)

        # Log query
        await self.db.log_query(customer['id'], f"{sym1} vs {sym2}", text, "comparison", 0.0)

    # ── Preference Handler ────────────────────────────────────────────────────

    async def _handle_preference(self, update: Update, user, action_data: dict):
        """Handle favorite symbol management."""
        await self.db.connect()

        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return

        action = action_data.get("action")
        symbol = action_data.get("symbol")

        if action == "add" and symbol:
            ok = await self.db.add_favorite_symbol(customer['id'], symbol)
            if ok:
                await update.message.reply_text(
                    f"⭐ <b>{symbol}</b> added to your favorites!\n\n"
                    f"I'll reference {symbol} in market commentary and chat responses.\n"
                    f"Type <code>my favorites</code> to see your list.",
                    parse_mode='HTML'
                )
            else:
                await update.message.reply_text("Failed to update favorites. Try again.")

        elif action == "remove" and symbol:
            ok = await self.db.remove_favorite_symbol(customer['id'], symbol)
            if ok:
                await update.message.reply_text(
                    f"✅ <b>{symbol}</b> removed from your favorites.",
                    parse_mode='HTML'
                )
            else:
                await update.message.reply_text("Failed to update favorites. Try again.")

        elif action == "list":
            favorites = await self.db.get_favorite_symbols(customer['id'])
            if favorites:
                lines = ["⭐ <b>Your Favorite Symbols</b>\n"]
                for sym in favorites:
                    price = self.cache.read_price(sym)
                    votes = self.cache.read_votes(sym)
                    consensus = votes.get("consensus", "—") if votes else "—"
                    price_str = f"${price:,.4f}" if price else "—"
                    emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(consensus, "⚪")
                    lines.append(f"{emoji} <b>{sym}</b> — {price_str} — {consensus}")
                lines.append("\n<i>Use </i><code>favorite SYMBOL</code><i> to add more</i>")
                lines.append("<i>Use </i><code>unfavorite SYMBOL</code><i> to remove</i>")
                await update.message.reply_text('\n'.join(lines), parse_mode='HTML')
            else:
                await update.message.reply_text(
                    "You have no favorite symbols yet.\n\n"
                    "Add one with: <code>favorite BTCUSD</code>",
                    parse_mode='HTML'
                )

    async def execute_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /execute — show trade confirmation with inline buttons before submitting."""
        user = update.effective_user
        await self.db.connect()

        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return

        tier = customer.get('tier', 'trial')
        if tier not in ['pro', 'elite']:
            await update.message.reply_text(
                "⚡ <b>Auto-execution</b> is available on Pro and Elite plans.\n\n"
                "Connect your exchange, set a risk limit, and let GlitchExecutor trade for you.",
                parse_mode='HTML',
                reply_markup=self._upgrade_keyboard(user.id, ['pro', 'elite'])
            )
            return

        # Retrieve last analysis
        last = self.last_analysis.get(user.id)
        if not last:
            await update.message.reply_text(
                "No recent analysis found.\n\nRun <code>/analyse BTCUSD</code> first, then /execute.",
                parse_mode='HTML'
            )
            return

        age_seconds = (datetime.utcnow() - last['timestamp']).total_seconds()
        if age_seconds > 300:
            await update.message.reply_text(
                "⚠️ Last analysis is over 5 minutes old — price may have moved.\n\n"
                "Run a fresh <code>/analyse SYMBOL</code> then /execute.",
                parse_mode='HTML'
            )
            return

        symbol = last['symbol']
        consensus = last['consensus']

        if consensus not in ['BUY', 'SELL']:
            await update.message.reply_text(
                f"⏸️ Consensus is <b>HOLD</b> for {symbol} — no trade to execute.",
                parse_mode='HTML'
            )
            return

        current_price = self.cache.read_price(symbol)
        if not current_price or current_price <= 0:
            await update.message.reply_text("⚠️ Could not get current price. Try again in a moment.")
            return

        connected = await self.db.get_connected_exchanges(customer['id'])
        if not connected:
            await update.message.reply_text(
                "No exchange connected.\n\nUse /connect_exchange to link Binance, Bybit, Kraken, etc."
            )
            return

        exchange = connected[0]

        # SL = 1.5% from entry, TP = 3.0% (2:1 R:R)
        sl_pct, tp_pct = 0.015, 0.030
        if consensus == 'BUY':
            sl_price = round(current_price * (1 - sl_pct), 6)
            tp_price = round(current_price * (1 + tp_pct), 6)
        else:
            sl_price = round(current_price * (1 + sl_pct), 6)
            tp_price = round(current_price * (1 - tp_pct), 6)

        request_id = str(uuid.uuid4())
        confidence_pct = round((last.get('confidence') or 0) * 100)
        direction_emoji = '🟢' if consensus == 'BUY' else '🔴'

        trade_request = {
            'request_id':    request_id,
            'customer_id':   customer['id'],
            'symbol':        symbol,
            'direction':     consensus,
            'entry_price':   current_price,
            'sl_price':      sl_price,
            'tp_price':      tp_price,
            'exchange':      exchange,
            'ensemble_vote': f"{consensus} {confidence_pct}%",
            'risk_pct':      1.0,
        }

        # Store pending trade (60s expiry)
        self.pending_trades[request_id] = {
            'trade_request': trade_request,
            'user_id':       user.id,
            'expires_at':    datetime.utcnow().timestamp() + 60,
        }

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Confirm Trade", callback_data=f"confirm_trade:{request_id}"),
            InlineKeyboardButton("❌ Cancel",        callback_data=f"cancel_trade:{request_id}"),
        ]])

        await update.message.reply_text(
            f"{direction_emoji} <b>Confirm Trade — {consensus} {symbol}</b>\n\n"
            f"Exchange: <b>{exchange.title()}</b>\n"
            f"Entry:    <b>${current_price:,.4f}</b>\n"
            f"Stop-loss:  ${sl_price:,.4f}  <i>(-{sl_pct*100:.1f}%)</i>\n"
            f"Take-profit: ${tp_price:,.4f}  <i>(+{tp_pct*100:.1f}%)</i>\n"
            f"Risk:     <b>1% of account</b>\n"
            f"Signal:   {consensus} @ {confidence_pct}% confidence\n\n"
            f"⚠️ <i>This confirmation expires in 60 seconds.</i>",
            parse_mode='HTML',
            reply_markup=keyboard
        )

    async def execute_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline button presses for trade confirmation/cancellation."""
        query = update.callback_query
        await query.answer()

        data = query.data or ''
        parts = data.split(':', 1)
        action = parts[0]
        request_id = parts[1] if len(parts) > 1 else ''

        if action == 'cancel_trade':
            self.pending_trades.pop(request_id, None)
            await query.edit_message_text("❌ Trade cancelled.")
            return

        if action != 'confirm_trade':
            return

        pending = self.pending_trades.pop(request_id, None)
        if not pending:
            await query.edit_message_text(
                "⏱️ Confirmation expired — run /execute again."
            )
            return

        if datetime.utcnow().timestamp() > pending['expires_at']:
            await query.edit_message_text(
                "⏱️ Confirmation expired — run /execute again."
            )
            return

        trade_request = pending['trade_request']
        await query.edit_message_text("⏳ Submitting trade to exchange...")

        submitted = self.cache.submit_trade(trade_request)
        if not submitted:
            await query.edit_message_text("❌ Failed to submit — Redis unavailable.")
            return

        result = await self.cache.poll_trade_result(request_id, timeout=12)

        if result:
            if result.get('success'):
                await query.edit_message_text(
                    f"✅ <b>Order filled!</b>\n\n"
                    f"Fill price: ${result.get('price', 0):,.4f}\n"
                    f"Volume:     {result.get('amount', 0)}\n"
                    f"Order ID:   <code>{result.get('order_id', 'N/A')}</code>\n\n"
                    "<i>Not financial advice — you are responsible for your trades.</i>",
                    parse_mode='HTML'
                )
            else:
                await query.edit_message_text(
                    f"❌ Order rejected: {result.get('error', 'Unknown error')}"
                )
        else:
            await query.edit_message_text(
                f"⏳ Order submitted — check your exchange dashboard.\n"
                f"Request ID: <code>{request_id}</code>",
                parse_mode='HTML'
            )

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle regular text messages with intent classification and routing."""
        if not update.message or not update.message.text:
            return

        text = update.message.text
        text_lower = text.lower().strip()
        user = update.effective_user

        # ── Execute shortcut (unchanged) ──────────────────────────────────────
        if text_lower in ('execute', 'execute trade', 'yes execute', 'confirm execute'):
            await self.execute_command(update, context)
            return

        # ── Scan shortcut (unchanged) ─────────────────────────────────────────
        if text_lower in ('scan', 'scan market', 'scan markets', 'market scan'):
            await self.scan_command(update, context)
            return

        # ── Exchange setup flow (unchanged) ───────────────────────────────────
        if user.id in self.pending_exchange_setup:
            await self.db.connect()
            customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
            if not error:
                await self._handle_exchange_setup_step(update, user, text, customer)
            return

        # ── Context shortcuts (need last analysis, unchanged) ─────────────────
        last = self.last_analysis.get(user.id)

        # "set alert at 50000" / "alert me at 50000" / "alert 50000"
        alert_m = re.search(
            r'alert(?:\s+me)?(?:\s+at)?\s+\$?([\d,]+(?:\.\d+)?)', text_lower
        )
        if alert_m and last:
            price_str = alert_m.group(1).replace(',', '')
            update.message.text = f"/setalert {last['symbol']} {price_str}"
            await self.setalert_command(update, context)
            return

        # "watch this" / "watch it" / "watch" → watch last symbol
        if text_lower in ('watch this', 'watch it', 'watch', 'add to watchlist') and last:
            update.message.text = f"/watch {last['symbol']}"
            await self.watch_command(update, context)
            return

        # "analyse again" / "reanalyse" / "refresh"
        if text_lower in ('analyse again', 'analyze again', 'reanalyse', 'reanalyze', 'refresh') and last:
            await self._handle_analysis(update, user, last['symbol'], text)
            return

        # "clear chat" / "new chat" / "reset" — clear conversation history
        if text_lower in ('clear chat', 'new chat', 'reset chat', 'clear history'):
            self.cache.clear_chat_history(user.id)
            await update.message.reply_text("🗑️ Chat history cleared. Fresh start!")
            return

        # ── Intent classification ─────────────────────────────────────────────
        intent, data = self._classify_intent(text, last)

        if intent == "compare":
            await self._handle_comparison(update, user, data, text)

        elif intent == "preference_set":
            await self._handle_preference(update, user, data)

        elif intent == "analysis":
            symbol = data[0] if data else None
            if symbol:
                await self._handle_analysis(update, user, symbol, text)
            else:
                await self._handle_chat(update, user, text)

        elif intent == "rag_query":
            await self._handle_rag_query(update, user, text)

        elif intent == "followup":
            # Follow-up question about last analysis — route to chat with context
            await self._handle_chat(update, user, text)

        elif intent == "chat":
            await self._handle_chat(update, user, text)

        else:
            # Fallback (shouldn't happen, but just in case)
            await self._handle_chat(update, user, text)
    
    # ── Scan Command ──────────────────────────────────────────────────────────

    async def scan_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /scan [SYM1 SYM2 ...] — quick signal table from Redis (no LLM)."""
        user = update.effective_user
        await self.db.connect()
        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return

        parts = update.message.text.split() if update.message.text else []
        if len(parts) > 1:
            # User specified symbols: /scan BTC ETH SOL
            symbols = [p.upper() for p in parts[1:]][:10]
            # Normalize: BTCUSD, BTC → BTCUSD
            normalized = []
            for s in symbols:
                if not s.endswith('USD') and not s.endswith('USDT'):
                    s = s + 'USD'
                normalized.append(s)
            symbols = normalized
        else:
            # No symbols given — scan everything the ensemble has data for
            symbols = sorted(self.cache.get_all_symbols())[:10]

        if not symbols:
            await update.message.reply_text(
                "No market data available yet — the ensemble engine may still be warming up.\n"
                "Try again in a minute or specify symbols: /scan BTCUSD ETHUSD SOLUSD"
            )
            return

        await update.message.reply_text("🔍 Scanning markets...")

        lines = [f"📊 <b>Market Scan</b>  <i>{datetime.utcnow().strftime('%H:%M UTC')}</i>\n"]
        found = 0
        for symbol in symbols:
            data = self.cache.read_votes(symbol)
            price = self.cache.read_price(symbol)
            if not data:
                lines.append(f"⚪ <b>{symbol}</b>  — no data")
                continue
            found += 1
            consensus = data.get('consensus', 'HOLD')
            conf = round(data.get('confidence', 0) * 100)
            emoji = {'BUY': '🟢', 'SELL': '🔴', 'HOLD': '🟡'}.get(consensus, '⚪')
            price_str = f"${price:,.4f}" if price else "—"
            # Show model agreement count
            votes = data.get('votes', [])
            agree = sum(1 for v in votes if isinstance(v, dict) and v.get('vote') == consensus)
            total_models = len(votes) if votes else 7
            lines.append(
                f"{emoji} <b>{symbol}</b>  {consensus} ({conf}%)  {price_str}  "
                f"<i>{agree}/{total_models} models</i>"
            )

        if found == 0:
            lines.append("\nNo live data — check back in a minute.")
        else:
            lines.append(f"\n<i>Use /analyse &lt;symbol&gt; for a full AI deep-dive.</i>")

        await update.message.reply_text('\n'.join(lines), parse_mode='HTML')

    # ── Alert Commands ────────────────────────────────────────────────────────

    async def setalert_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /setalert SYMBOL PRICE or /setalert SYMBOL above|below PRICE."""
        user = update.effective_user
        parts = update.message.text.split()

        # Usage check
        if len(parts) < 3:
            await update.message.reply_text(
                "Usage:\n"
                "  /setalert BTCUSD 50000\n"
                "  /setalert BTCUSD above 50000\n"
                "  /setalert BTCUSD below 45000"
            )
            return

        await self.db.connect()
        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return

        symbol = parts[1].upper()

        # Parse direction + price
        if len(parts) == 3:
            # Auto-detect direction
            try:
                target = float(parts[2].replace(',', ''))
            except ValueError:
                await update.message.reply_text("Invalid price. Example: /setalert BTCUSD 50000")
                return
            current = self.cache.read_price(symbol)
            if current is None:
                await update.message.reply_text(
                    f"No price data for {symbol}. Check the symbol and try again."
                )
                return
            direction = 'above' if target > current else 'below'
        elif len(parts) == 4:
            direction = parts[2].lower()
            if direction not in ('above', 'below'):
                await update.message.reply_text(
                    "Direction must be <b>above</b> or <b>below</b>.\n"
                    "Example: /setalert BTCUSD above 50000",
                    parse_mode='HTML'
                )
                return
            try:
                target = float(parts[3].replace(',', ''))
            except ValueError:
                await update.message.reply_text("Invalid price. Example: /setalert BTCUSD above 50000")
                return
        else:
            await update.message.reply_text(
                "Usage: /setalert BTCUSD 50000  or  /setalert BTCUSD above 50000"
            )
            return

        # Limit: max 10 active alerts per user
        count = await self.db.count_user_price_alerts(customer['id'])
        if count >= 10:
            await update.message.reply_text(
                "You have reached the maximum of 10 active price alerts.\n"
                "Use /cancelalert &lt;id&gt; to remove one first.",
                parse_mode='HTML'
            )
            return

        alert_id = await self.db.create_price_alert(
            customer['id'], user.id, symbol, target, direction
        )
        if alert_id:
            arrow = '≥' if direction == 'above' else '≤'
            await update.message.reply_text(
                f"🔔 <b>Price alert set!</b>\n\n"
                f"<b>{symbol}</b> {arrow} <b>${target:,.4f}</b>\n"
                f"Alert ID: <code>{alert_id}</code>\n\n"
                f"Use /alerts to see all your alerts.",
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text("Failed to set alert. Please try again.")

    async def alerts_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /alerts — list user's active price alerts."""
        user = update.effective_user
        await self.db.connect()
        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return

        alerts = await self.db.get_user_price_alerts(customer['id'])
        if not alerts:
            await update.message.reply_text(
                "You have no active price alerts.\n\n"
                "Set one with: /setalert BTCUSD 50000"
            )
            return

        lines = ["🔔 <b>Your Price Alerts</b>\n"]
        for a in alerts:
            arrow = '≥' if a['direction'] == 'above' else '≤'
            lines.append(
                f"ID <code>{a['id']}</code> — <b>{a['symbol']}</b> {arrow} ${float(a['target_price']):,.4f}"
            )
        lines.append("\nUse /cancelalert &lt;id&gt; to remove one.")
        await update.message.reply_text('\n'.join(lines), parse_mode='HTML')

    async def cancelalert_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /cancelalert <id>."""
        user = update.effective_user
        parts = update.message.text.split()
        if len(parts) < 2:
            await update.message.reply_text("Usage: /cancelalert <id>\nFind IDs with /alerts")
            return

        try:
            alert_id = int(parts[1])
        except ValueError:
            await update.message.reply_text("Invalid ID. Usage: /cancelalert 42")
            return

        await self.db.connect()
        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return

        deleted = await self.db.delete_price_alert(customer['id'], alert_id)
        if deleted:
            await update.message.reply_text(f"✅ Alert <code>{alert_id}</code> cancelled.", parse_mode='HTML')
        else:
            await update.message.reply_text(
                f"Alert <code>{alert_id}</code> not found or already triggered.\n"
                "Use /alerts to see your active alerts.",
                parse_mode='HTML'
            )

    async def watch_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /watch SYMBOL [confidence%] — subscribe to signal alerts."""
        user = update.effective_user
        parts = update.message.text.split()
        if len(parts) < 2:
            await update.message.reply_text(
                "Usage: /watch BTCUSD\n"
                "Optional confidence threshold (default 60%):\n"
                "  /watch BTCUSD 70"
            )
            return

        symbol = parts[1].upper()
        min_conf = 0.6
        if len(parts) >= 3:
            try:
                pct = float(parts[2].replace('%', ''))
                if not 0 < pct <= 100:
                    raise ValueError()
                min_conf = pct / 100
            except ValueError:
                await update.message.reply_text("Confidence must be a number between 1 and 100. E.g. /watch BTCUSD 70")
                return

        await self.db.connect()
        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return

        # Limit: max 10 watched symbols
        count = await self.db.count_user_signal_subs(customer['id'])
        if count >= 10:
            await update.message.reply_text(
                "You're watching 10 symbols (maximum).\n"
                "Use /unwatch &lt;symbol&gt; to remove one.",
                parse_mode='HTML'
            )
            return

        ok = await self.db.upsert_signal_sub(customer['id'], user.id, symbol, min_conf)
        if ok:
            await update.message.reply_text(
                f"📡 <b>Watching {symbol}</b>\n\n"
                f"You'll be notified when the ensemble fires a BUY/SELL signal ≥{round(min_conf*100)}% confidence.\n\n"
                f"Use /watchlist to see all watched symbols.\n"
                f"Use /unwatch {symbol} to stop.",
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text("Failed to set up watch. Please try again.")

    async def unwatch_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /unwatch SYMBOL."""
        user = update.effective_user
        parts = update.message.text.split()
        if len(parts) < 2:
            await update.message.reply_text("Usage: /unwatch BTCUSD")
            return

        symbol = parts[1].upper()
        await self.db.connect()
        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return

        removed = await self.db.delete_signal_sub(customer['id'], symbol)
        if removed:
            await update.message.reply_text(f"✅ Stopped watching <b>{symbol}</b>.", parse_mode='HTML')
        else:
            await update.message.reply_text(
                f"<b>{symbol}</b> is not in your watchlist.\nUse /watchlist to see what you're watching.",
                parse_mode='HTML'
            )

    async def watchlist_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /watchlist — show watched symbols."""
        user = update.effective_user
        await self.db.connect()
        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return

        subs = await self.db.get_user_signal_subs(customer['id'])
        if not subs:
            await update.message.reply_text(
                "Your watchlist is empty.\n\n"
                "Add a symbol with: /watch BTCUSD"
            )
            return

        lines = ["📡 <b>Your Watchlist</b>\n"]
        for s in subs:
            conf_pct = round(s.get('min_confidence', 0.6) * 100)
            lines.append(f"• <b>{s['symbol']}</b>  (alerts ≥{conf_pct}% confidence)")
        lines.append("\nUse /unwatch &lt;symbol&gt; to remove one.")
        await update.message.reply_text('\n'.join(lines), parse_mode='HTML')

    async def briefing_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /briefing — toggle daily market briefing on/off."""
        user = update.effective_user
        await self.db.connect()
        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return

        existing = await self.db.get_daily_briefing_sub(customer['id'])
        if existing and existing.get('active'):
            # Already subscribed → unsubscribe
            await self.db.delete_daily_briefing_sub(customer['id'])
            await update.message.reply_text(
                "📰 Daily briefing <b>disabled</b>.\n\n"
                "Use /briefing again to re-enable.",
                parse_mode='HTML'
            )
        else:
            # Not subscribed → subscribe
            await self.db.upsert_daily_briefing_sub(customer['id'], user.id)
            await update.message.reply_text(
                "📰 Daily briefing <b>enabled</b>!\n\n"
                "You'll receive a market summary every day at <b>07:00 UTC</b>.\n"
                "Use /briefing again to disable.",
                parse_mode='HTML'
            )

    # ── Plans / Upgrade ───────────────────────────────────────────────────────

    async def plans_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /plans — show plan comparison, each plan is a tap-to-view button."""
        user = update.effective_user
        await self.db.connect()
        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return

        tier = customer.get('tier', 'trial')
        tier_emoji = {"trial": "🆓", "starter": "⭐", "pro": "🤖", "elite": "🏢"}
        current_label = tier_emoji.get(tier, '🆓') + f" You are on <b>{tier.upper()}</b>\n\n"

        plans_text = (
            f"{current_label}"
            "━━━━━━━━━━━━━━━━━━━\n"
            "🆓 <b>Trial</b>  — Free, 7 days\n"
            "• 10 AI analyses/day · Alerts · Watchlist\n\n"
            "⭐ <b>Starter — $49/mo</b>\n"
            "• 30 analyses/day · Portfolio view\n\n"
            "🤖 <b>Pro — $149/mo</b>\n"
            "• 100 analyses/day · Auto-execute trades\n\n"
            "🏢 <b>Elite — $349/mo</b>\n"
            "• Unlimited · MT5 bots on VPS\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
            "Tap a plan below to see full details and pricing 👇"
        )

        # Show upgrade options only (skip current and lower tiers)
        tiers_order = ['trial', 'starter', 'pro', 'elite']
        current_idx = tiers_order.index(tier) if tier in tiers_order else 0
        upgrade_tiers = tiers_order[current_idx + 1:]

        tier_buttons = {
            'starter': '⭐ Starter',
            'pro':     '🤖 Pro',
            'elite':   '🏢 Elite',
        }
        # All upgrade plans in a single row (max 3)
        row = [
            InlineKeyboardButton(tier_buttons[t], callback_data=f"plan_info:{t}")
            for t in upgrade_tiers if t in tier_buttons
        ]
        buttons = [row] if row else []
        keyboard = InlineKeyboardMarkup(buttons)

        await update.message.reply_text(plans_text, parse_mode='HTML', reply_markup=keyboard)

    # ── Plan info card (callback) ──────────────────────────────────────────────

    # Plan details shown when user taps a plan button
    PLAN_INFO = {
        'starter': {
            'title':    '⭐ Starter Plan',
            'monthly':  49,
            'yearly':   470,
            'features': (
                "• <b>30 AI analyses/day</b>\n"
                "• Full 9-model signal breakdown\n"
                "• Price alerts &amp; watchlist\n"
                "• Daily 7AM market briefing\n"
                "• Exchange portfolio view via API\n"
                "• Email support"
            ),
        },
        'pro': {
            'title':    '🤖 Pro Plan',
            'monthly':  149,
            'yearly':   1430,
            'features': (
                "• <b>100 AI analyses/day</b>\n"
                "• Everything in Starter\n"
                "• <b>Auto-execute trades</b> on your exchange\n"
                "• Real-time execution alerts\n"
                "• Risk management controls\n"
                "• Priority email support"
            ),
        },
        'elite': {
            'title':    '🏢 Elite Plan',
            'monthly':  349,
            'yearly':   3350,
            'features': (
                "• <b>Unlimited analyses</b>\n"
                "• Everything in Pro\n"
                "• <b>Dedicated MT5 bots</b> on your VPS\n"
                "• 24/7 automated broker trading\n"
                "• Custom bot configuration\n"
                "• Priority support &amp; onboarding"
            ),
        },
    }

    async def plan_info_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show detailed plan card with monthly/yearly checkout buttons."""
        query = update.callback_query
        await query.answer()

        tier = query.data.split(":", 1)[1]
        info = self.PLAN_INFO.get(tier)
        if not info:
            return

        monthly = info['monthly']
        yearly  = info['yearly']
        mo_equiv = round(yearly / 12)
        saving   = (monthly * 12) - yearly

        text = (
            f"<b>{info['title']}</b>\n\n"
            f"{info['features']}\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"💳 Monthly  <b>${monthly}/mo</b>\n"
            f"📅 Yearly   <b>${yearly}/yr</b>  (~${mo_equiv}/mo, save ${saving})\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
            "Choose your billing cycle 👇"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    f"💳 Monthly — ${monthly}/mo",
                    callback_data=f"plan_checkout:{tier}:monthly"
                ),
                InlineKeyboardButton(
                    f"📅 Yearly  −20%",
                    callback_data=f"plan_checkout:{tier}:yearly"
                ),
            ],
            [InlineKeyboardButton("← Back to Plans", callback_data="plans_back")],
        ])

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=keyboard)

    async def plan_checkout_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Create Stripe checkout session and send the payment link."""
        query = update.callback_query
        await query.answer("Creating your checkout link…")

        _, tier, billing = query.data.split(":", 2)
        user = query.from_user

        info    = self.PLAN_INFO.get(tier, {})
        price   = info.get('yearly' if billing == 'yearly' else 'monthly', '?')
        billing_label = f"${price}/yr (yearly)" if billing == 'yearly' else f"${price}/mo (monthly)"

        # Call payment server to create Stripe checkout session
        payment_url = os.environ.get("PAYMENT_SERVICE_URL", "http://payment:5002")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{payment_url}/api/bot/checkout",
                    json={
                        "tier":              tier,
                        "billing":           billing,
                        "telegram_id":       user.id,
                        "telegram_username": user.username or "",
                    }
                )
                data = resp.json()
        except Exception as e:
            await query.edit_message_text(
                "⚠️ Couldn't reach the payment server. Please try again in a moment.",
                parse_mode='HTML'
            )
            return

        checkout_url = data.get("url")
        if not checkout_url:
            await query.edit_message_text(
                f"⚠️ Error: {data.get('error', 'Unknown error')}. Please try again.",
                parse_mode='HTML'
            )
            return

        tier_title = info.get('title', tier.title())
        text = (
            f"✅ <b>{tier_title}</b> — {billing_label}\n\n"
            "Your secure Stripe checkout is ready.\n"
            "Tap the button below to complete payment.\n\n"
            "<i>Your account activates automatically as soon as payment clears.</i>"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Complete Payment →", url=checkout_url)],
            [InlineKeyboardButton("← Change Plan", callback_data=f"plan_info:{tier}")],
        ])

        await query.edit_message_text(text, parse_mode='HTML', reply_markup=keyboard)

    async def plans_back_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Return to the main plans overview from a plan detail card."""
        query = update.callback_query
        await query.answer()
        # Re-use plans_command logic but edit the existing message
        user = query.from_user
        await self.db.connect()
        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            msg = "⏰ Your trial has ended. Upgrade to continue." if error == "TRIAL_ENDED" else error
            await query.edit_message_text(msg, reply_markup=self._upgrade_keyboard(user.id, ['starter', 'pro', 'elite']))
            return

        tier = customer.get('tier', 'trial')
        tier_emoji = {"trial": "🆓", "starter": "⭐", "pro": "🤖", "elite": "🏢"}
        current_label = tier_emoji.get(tier, '🆓') + f" You are on <b>{tier.upper()}</b>\n\n"

        plans_text = (
            f"{current_label}"
            "━━━━━━━━━━━━━━━━━━━\n"
            "🆓 <b>Trial</b>  — Free, 7 days\n"
            "• 10 AI analyses/day · Alerts · Watchlist\n\n"
            "⭐ <b>Starter — $49/mo</b>\n"
            "• 30 analyses/day · Portfolio view\n\n"
            "🤖 <b>Pro — $149/mo</b>\n"
            "• 100 analyses/day · Auto-execute trades\n\n"
            "🏢 <b>Elite — $349/mo</b>\n"
            "• Unlimited · MT5 bots on VPS\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
            "Tap a plan below to see full details and pricing 👇"
        )

        tiers_order  = ['trial', 'starter', 'pro', 'elite']
        current_idx  = tiers_order.index(tier) if tier in tiers_order else 0
        upgrade_tiers = tiers_order[current_idx + 1:]
        tier_buttons = {'starter': '⭐ Starter', 'pro': '🤖 Pro', 'elite': '🏢 Elite'}
        row = [
            InlineKeyboardButton(tier_buttons[t], callback_data=f"plan_info:{t}")
            for t in upgrade_tiers if t in tier_buttons
        ]
        keyboard = InlineKeyboardMarkup([row] if row else [])
        await query.edit_message_text(plans_text, parse_mode='HTML', reply_markup=keyboard)

    # ── Referral ──────────────────────────────────────────────────────────────

    async def referral_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /referral — show referral link and stats."""
        user = update.effective_user
        await self.db.connect()
        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return

        code = await self.db.get_or_create_referral_code(customer['id'])
        if not code:
            await update.message.reply_text("Could not generate your referral link. Try again.")
            return

        stats = await self.db.get_referral_stats(customer['id'])
        count = stats.get('count', 0)
        bonus_days = stats.get('bonus_days', 0)

        bot_username = (await context.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start=ref_{code}"

        await update.message.reply_text(
            "🔗 <b>Your Referral Link</b>\n\n"
            f"<code>{link}</code>\n\n"
            "Share this link. When someone joins through it:\n"
            "• They get <b>+2 extra trial days</b> (9 total)\n"
            "• You get <b>+3 days</b> added to your trial\n\n"
            f"📊 <b>Your stats:</b> {count} referral{'s' if count != 1 else ''} — "
            f"+{bonus_days} bonus days earned\n\n"
            "<i>Tap the link above to copy it.</i>",
            parse_mode='HTML'
        )

    # ── Admin Commands ────────────────────────────────────────────────────────

    def _is_admin(self, user_id: int) -> bool:
        """Check if a Telegram user is the platform admin."""
        return self._admin_id != 0 and user_id == self._admin_id

    def _upgrade_keyboard(self, telegram_id: int, tiers: list) -> InlineKeyboardMarkup:
        """
        Build an inline keyboard with upgrade buttons for the given tier list.
        Tapping a button opens the plan info card with monthly/yearly checkout options.

        tiers: subset of ['starter', 'pro', 'elite'] to show as buttons.
        """
        tier_labels = {
            'starter': '⭐ Starter',
            'pro':     '🤖 Pro',
            'elite':   '🏢 Elite',
        }
        # Put all upgrade tiers in a single row (max 3)
        row = [
            InlineKeyboardButton(tier_labels[t], callback_data=f"plan_info:{t}")
            for t in tiers if t in tier_labels
        ]
        buttons = [row] if row else []
        buttons.append([InlineKeyboardButton("📋 See All Plans", callback_data="plans_back")])
        return InlineKeyboardMarkup(buttons)

    async def _reply_error(self, update: Update, error: str) -> None:
        """Send an auth/rate error; shows upgrade keyboard for trial-ended or rate-limit errors."""
        user_id = update.effective_user.id if update.effective_user else 0
        if error == "TRIAL_ENDED":
            await update.message.reply_text(
                "⏰ <b>Your trial has ended.</b>\n\n"
                "Upgrade to keep getting AI-powered trade analysis 👇",
                parse_mode='HTML',
                reply_markup=self._upgrade_keyboard(user_id, ['starter', 'pro', 'elite'])
            )
        elif error == "RATE_LIMIT":
            limit = 10  # shown generically; exact limit comes from tier
            await update.message.reply_text(
                "📊 <b>Daily query limit reached.</b>\n\n"
                "Upgrade for more queries 👇",
                parse_mode='HTML',
                reply_markup=self._upgrade_keyboard(user_id, ['starter', 'pro', 'elite'])
            )
        else:
            await update.message.reply_text(error)

    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /admin [stats | broadcast <tier> <message>]."""
        user = update.effective_user
        if not self._is_admin(user.id):
            return  # silently ignore non-admins

        parts = update.message.text.split(maxsplit=2)
        sub = parts[1].lower() if len(parts) > 1 else 'stats'

        await self.db.connect()

        # ── /admin stats ──────────────────────────────────────────────────────
        if sub == 'stats':
            stats = await self.db.get_user_stats()
            top_symbols = await self.db.get_top_symbols(5)
            queries_today = await self.db.get_query_count_today()

            total   = stats.get('total', 0)
            trial   = stats.get('trial', 0)
            paying  = stats.get('paying', 0)
            active  = stats.get('active_today', 0)

            symbol_lines = '\n'.join(
                f"  {i+1}. {s}  ({c} queries)" for i, (s, c) in enumerate(top_symbols)
            ) or "  No data yet"

            await update.message.reply_text(
                "📊 <b>GlitchExecutor — Admin Stats</b>\n\n"
                f"👥 <b>Users</b>\n"
                f"  Total:   {total}\n"
                f"  Trial:   {trial}\n"
                f"  Paying:  {paying}\n"
                f"  Active today: {active}\n\n"
                f"📈 <b>Activity (24h)</b>\n"
                f"  Total queries: {queries_today}\n"
                f"  Top symbols:\n{symbol_lines}\n\n"
                "📣 Broadcast: <code>/admin broadcast all &lt;message&gt;</code>\n"
                "Tiers: <code>all</code> | <code>trial</code> | <code>paid</code>",
                parse_mode='HTML'
            )
            return

        # ── /admin broadcast <tier> <message> ────────────────────────────────
        if sub == 'broadcast':
            # parts[2] = "all <message>" or "trial <message>" or "paid <message>"
            rest = parts[2] if len(parts) > 2 else ''
            rest_parts = rest.split(maxsplit=1)
            if len(rest_parts) < 2:
                await update.message.reply_text(
                    "Usage: /admin broadcast all &lt;message&gt;\n"
                    "Tiers: all | trial | paid",
                    parse_mode='HTML'
                )
                return

            tier_filter = rest_parts[0].lower()
            if tier_filter not in ('all', 'trial', 'paid'):
                await update.message.reply_text(
                    "Tier must be: <code>all</code> | <code>trial</code> | <code>paid</code>",
                    parse_mode='HTML'
                )
                return

            broadcast_msg = rest_parts[1]
            telegram_ids = await self.db.get_telegram_ids_for_broadcast(tier_filter)
            count = len(telegram_ids)

            if count == 0:
                await update.message.reply_text("No users match that filter.")
                return

            # Store pending broadcast
            import uuid as _uuid
            broadcast_id = str(_uuid.uuid4())[:8]
            self.pending_broadcasts[broadcast_id] = {
                'message':      broadcast_msg,
                'tier_filter':  tier_filter,
                'telegram_ids': [tid for tid, _ in telegram_ids],
            }

            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("📣 Send Now", callback_data=f"broadcast_confirm:{broadcast_id}"),
                InlineKeyboardButton("❌ Cancel",   callback_data=f"broadcast_cancel:{broadcast_id}"),
            ]])

            await update.message.reply_text(
                f"📣 <b>Broadcast Preview</b>\n\n"
                f"To: <b>{tier_filter.title()} users</b> ({count} recipients)\n\n"
                f"Message:\n<i>{broadcast_msg}</i>\n\n"
                "Confirm to send?",
                parse_mode='HTML',
                reply_markup=keyboard
            )
            return

        await update.message.reply_text(
            "Commands: <code>/admin stats</code> | <code>/admin broadcast &lt;tier&gt; &lt;msg&gt;</code>",
            parse_mode='HTML'
        )

    async def broadcast_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle broadcast confirm/cancel inline buttons."""
        query = update.callback_query
        await query.answer()

        if not self._is_admin(query.from_user.id):
            return

        data = query.data or ''
        parts = data.split(':', 1)
        action = parts[0]
        broadcast_id = parts[1] if len(parts) > 1 else ''

        if action == 'broadcast_cancel':
            self.pending_broadcasts.pop(broadcast_id, None)
            await query.edit_message_text("❌ Broadcast cancelled.")
            return

        if action != 'broadcast_confirm':
            return

        pending = self.pending_broadcasts.pop(broadcast_id, None)
        if not pending:
            await query.edit_message_text("⏱️ Broadcast expired.")
            return

        telegram_ids = pending['telegram_ids']
        message_text = (
            f"📢 <b>GlitchExecutor Announcement</b>\n\n"
            f"{pending['message']}"
        )

        await query.edit_message_text(
            f"📣 Sending to {len(telegram_ids)} users... ⏳"
        )

        sent = 0
        failed = 0
        for tid in telegram_ids:
            try:
                await context.bot.send_message(
                    chat_id=tid,
                    text=message_text,
                    parse_mode='HTML'
                )
                sent += 1
            except Exception:
                failed += 1
            # Stay well under Telegram's 30 msg/s rate limit
            await asyncio.sleep(0.05)

        await query.edit_message_text(
            f"✅ <b>Broadcast complete</b>\n\n"
            f"Sent:   {sent}\n"
            f"Failed: {failed}",
            parse_mode='HTML'
        )

    # ── Exchange Commands ─────────────────────────────────────────────────────

    async def connect_exchange_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start the /connect_exchange multi-step flow."""
        user = update.effective_user
        await self.db.connect()

        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return

        tier = customer.get('tier', 'trial')
        if tier == 'trial':
            await update.message.reply_text(
                "🔗 <b>Exchange connection</b> is available on paid plans.\n\n"
                "Connect Binance, Bybit, Kraken and more to view your portfolio — "
                "or let GlitchExecutor trade automatically on Pro and Elite.",
                parse_mode='HTML',
                reply_markup=self._upgrade_keyboard(user.id, ['starter', 'pro', 'elite'])
            )
            return

        # Start state machine
        self.pending_exchange_setup[user.id] = {'state': 'awaiting_exchange'}

        popular = ' '.join(f'<code>{e}</code>' for e in self.popular_exchanges)
        await update.message.reply_text(
            "🔗 <b>Connect Exchange API</b>\n\n"
            "Type your exchange name. Any exchange with an API is supported.\n\n"
            f"<b>Popular:</b> {popular}\n\n"
            "Or type the CCXT exchange ID for any other broker "
            "(full list: ccxt.com/exchanges).\n\n"
            "Type <code>cancel</code> to abort.",
            parse_mode='HTML'
        )

    async def disconnect_exchange_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /disconnect_exchange command."""
        user = update.effective_user
        await self.db.connect()

        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return

        connected = await self.db.get_connected_exchanges(customer.get('id'))
        if not connected:
            await update.message.reply_text("No exchange API connected.")
            return

        # Disconnect all active exchange keys
        for exchange in connected:
            await self.db.delete_exchange_keys(customer.get('id'), exchange)

        await update.message.reply_text(
            f"✅ Disconnected: <b>{', '.join(connected).title()}</b>\n\n"
            "Your API keys have been removed. Use /connect_exchange to reconnect.",
            parse_mode='HTML'
        )

    async def _handle_exchange_setup_step(self, update: Update, user, text: str, customer: dict):
        """Handle a step in the /connect_exchange multi-step flow."""
        state_data = self.pending_exchange_setup.get(user.id, {})
        state = state_data.get('state')
        text_clean = text.strip()
        text_lower = text_clean.lower()

        if text_lower == 'cancel':
            self.pending_exchange_setup.pop(user.id, None)
            await update.message.reply_text("❌ Exchange connection cancelled.")
            return

        # ── Step 1: choose exchange ──────────────────────────────────────────
        if state == 'awaiting_exchange':
            # Validate against CCXT's full exchange list
            try:
                import ccxt as _ccxt
                valid = text_lower in _ccxt.exchanges
            except Exception:
                # If ccxt unavailable, accept popular exchanges
                valid = text_lower in self.popular_exchanges

            if not valid:
                popular = ', '.join(f'<code>{e}</code>' for e in self.popular_exchanges)
                await update.message.reply_text(
                    f"❌ <b>{text_clean}</b> is not a recognised exchange.\n\n"
                    f"Popular options: {popular}\n\n"
                    "Check the full list at ccxt.com/exchanges\n"
                    "Or type <code>cancel</code> to abort.",
                    parse_mode='HTML'
                )
                return

            needs_passphrase = text_lower in self.passphrase_exchanges
            self.pending_exchange_setup[user.id] = {
                'state': 'awaiting_api_key',
                'exchange': text_lower,
                'needs_passphrase': needs_passphrase,
            }
            await update.message.reply_text(
                f"✅ Exchange: <b>{text_lower.title()}</b>\n\n"
                f"Paste your <b>{text_lower.title()} API Key</b>.\n\n"
                "⚠️ Enable <b>Spot/Futures trading</b> permission only.\n"
                "<b>Never enable withdrawal permissions.</b>\n\n"
                "Your message will be deleted immediately for security.\n"
                "Type <code>cancel</code> to abort.",
                parse_mode='HTML'
            )
            return

        # ── Step 2: receive API key ──────────────────────────────────────────
        if state == 'awaiting_api_key':
            try:
                await update.message.delete()
            except Exception:
                pass

            if len(text_clean) < 10:
                await update.effective_chat.send_message(
                    "That doesn't look like a valid API key. Please try again.\n"
                    "Type <code>cancel</code> to abort.",
                    parse_mode='HTML'
                )
                return

            self.pending_exchange_setup[user.id] = {
                **state_data,
                'state': 'awaiting_api_secret',
                'api_key': text_clean,
            }
            await update.effective_chat.send_message(
                "🔑 API key received and deleted from chat.\n\n"
                "Now paste your <b>API Secret</b>.\n"
                "This will also be deleted immediately.\n\n"
                "Type <code>cancel</code> to abort.",
                parse_mode='HTML'
            )
            return

        # ── Step 3: receive API secret ───────────────────────────────────────
        if state == 'awaiting_api_secret':
            try:
                await update.message.delete()
            except Exception:
                pass

            if len(text_clean) < 10:
                await update.effective_chat.send_message(
                    "That doesn't look like a valid API secret. Please try again.\n"
                    "Type <code>cancel</code> to abort.",
                    parse_mode='HTML'
                )
                return

            self.pending_exchange_setup[user.id] = {
                **state_data,
                'api_secret': text_clean,
            }

            # Route to passphrase step if needed, otherwise store
            if state_data.get('needs_passphrase'):
                self.pending_exchange_setup[user.id]['state'] = 'awaiting_passphrase'
                exchange = state_data.get('exchange', '')
                await update.effective_chat.send_message(
                    "🔑 Secret received and deleted.\n\n"
                    f"<b>{exchange.title()}</b> also requires a <b>Passphrase</b>.\n"
                    "Paste it now — it will be deleted immediately.\n\n"
                    "Type <code>cancel</code> to abort.",
                    parse_mode='HTML'
                )
            else:
                self.pending_exchange_setup[user.id]['state'] = 'storing'
                await self._store_exchange_keys(update, user, customer, state_data,
                                                text_clean, passphrase=None)
            return

        # ── Step 4: receive passphrase (passphrase exchanges only) ───────────
        if state == 'awaiting_passphrase':
            try:
                await update.message.delete()
            except Exception:
                pass

            if len(text_clean) < 1:
                await update.effective_chat.send_message(
                    "Passphrase cannot be empty. Try again.\n"
                    "Type <code>cancel</code> to abort.",
                    parse_mode='HTML'
                )
                return

            self.pending_exchange_setup.pop(user.id, None)
            await self._store_exchange_keys(update, user, customer, state_data,
                                            state_data.get('api_secret', ''),
                                            passphrase=text_clean)

    async def _store_exchange_keys(self, update, user, customer: dict,
                                   state_data: dict, api_secret: str,
                                   passphrase: str = None):
        """Encrypt and save exchange keys, then confirm to user."""
        exchange = state_data.get('exchange')
        api_key  = state_data.get('api_key')

        self.pending_exchange_setup.pop(user.id, None)

        thinking = await update.effective_chat.send_message("🔄 Storing your keys securely...")

        success = await self.db.store_exchange_keys(
            customer.get('id'), exchange, api_key, api_secret,
            passphrase=passphrase
        )

        await thinking.delete()

        tier = customer.get('tier', 'trial')
        if success:
            if tier in ['pro', 'elite']:
                exec_msg = "🤖 Auto-execution is <b>active</b> — trades will execute on your account when signals fire."
            else:
                exec_msg = "⭐ Upgrade to <b>Pro</b> to enable auto-execution on your account."

            await update.effective_chat.send_message(
                f"✅ <b>{exchange.title()} API connected!</b>\n\n"
                f"{exec_msg}\n\n"
                "Use /disconnect_exchange to remove your keys.\n"
                "Use /status to see your connection.",
                parse_mode='HTML'
            )
        else:
            await update.effective_chat.send_message(
                "❌ Failed to store your API keys. Please try /connect_exchange again."
            )

    async def connect_mt5_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /connect_mt5 command for Elite users."""
        user = update.effective_user
        await self.db.connect()

        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return

        tier = customer.get('tier', 'trial')
        if tier != 'elite':
            await update.message.reply_text(
                "🏢 <b>MT5 automated bots</b> are available on the Elite plan.\n\n"
                "Get a dedicated VPS bot that runs 24/7 on your MT5 broker account.",
                parse_mode='HTML',
                reply_markup=self._upgrade_keyboard(user.id, ['elite'])
            )
            return

        # Parse: /connect_mt5 <server> <login> <password>
        parts = update.message.text.split()
        if len(parts) < 4:
            await update.message.reply_text(
                "Usage: /connect_mt5 <server> <login> <password>\n\n"
                "Example: /connect_mt5 ICMarkets-Live01 12345678 MyPass123\n\n"
                "Your credentials are encrypted and stored securely."
            )
            return

        server = parts[1]
        login = parts[2]
        password = parts[3]

        # Store encrypted credentials
        success = await self.db.store_mt5_credentials(
            customer.get('id'), server, login, password
        )

        if success:
            # Delete the message containing credentials for security
            try:
                await update.message.delete()
            except Exception:
                pass
            await context.bot.send_message(
                chat_id=user.id,
                text=(
                    "✅ MT5 account registered successfully!\n\n"
                    f"Server: {server}\n"
                    f"Login: {login}\n\n"
                    "Our team will set up your VPS within 24 hours.\n"
                    "You'll receive a confirmation once your bots are live.\n\n"
                    "⚠️ Your credentials message has been deleted for security."
                )
            )
        else:
            await update.message.reply_text(
                "Failed to store MT5 credentials. Please try again or contact support."
            )

    async def autoexecute_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /autoexecute command — toggle auto-trade on strong favorite signals."""
        user = update.effective_user
        await self.db.connect()

        customer, error, _ = await self.auth.authenticate(self.db, user.id, user.username)
        if error:
            await self._reply_error(update, error)
            return

        customer_id = customer.get('id')
        tier = customer.get('tier', 'trial')

        # Parse subcommand
        parts = update.message.text.strip().split()
        subcmd = parts[1].lower() if len(parts) > 1 else 'status'

        # ── Tier gate: Pro/Elite only ──────────────────────────────────────
        if tier not in ('pro', 'elite'):
            await update.message.reply_text(
                "🤖 <b>Auto-Execute</b> is available on <b>Pro</b> and <b>Elite</b> plans.\n\n"
                "When enabled, strong signals (75%+ confidence) on your favorite symbols "
                "will automatically submit trades on your connected exchange.\n\n"
                "Upgrade to unlock this feature:",
                parse_mode='HTML',
                reply_markup=self._upgrade_keyboard(user.id, ['pro', 'elite'])
            )
            return

        # ── ON ─────────────────────────────────────────────────────────────
        if subcmd == 'on':
            # Check for connected exchange
            exchanges = await self.db.get_connected_exchanges(customer_id)
            if not exchanges:
                await update.message.reply_text(
                    "⚠️ <b>No exchange connected.</b>\n\n"
                    "Auto-execute requires a connected exchange to submit trades.\n"
                    "Use /connect_exchange to link your API keys first.",
                    parse_mode='HTML'
                )
                return

            # Check for favorites
            status = await self.db.get_auto_execute_status(customer_id)
            favorites = status.get('favorites', [])
            if not favorites:
                await update.message.reply_text(
                    "⚠️ <b>No favorite symbols.</b>\n\n"
                    "Auto-execute works on your favorite symbols. "
                    "Add some first:\n"
                    "<code>favorite BTCUSD</code>\n"
                    "<code>favorite ETHUSD</code>\n\n"
                    "Then run /autoexecute on again.",
                    parse_mode='HTML'
                )
                return

            # Enable auto-execute
            success = await self.db.set_auto_execute(customer_id, True)
            if success:
                fav_list = ', '.join(favorites)
                exchange = exchanges[0].title()
                await update.message.reply_text(
                    "✅ <b>Auto-Execute ENABLED</b>\n\n"
                    "When a strong signal (75%+ confidence BUY/SELL) fires on any "
                    "of your favorites, a trade will be automatically submitted.\n\n"
                    f"📋 <b>Your favorites:</b> {fav_list}\n"
                    f"🏦 <b>Exchange:</b> {exchange}\n"
                    f"📊 <b>Risk per trade:</b> 1% of account\n"
                    f"🛑 <b>Stop-loss:</b> 1.5% | <b>Take-profit:</b> 3.0%\n"
                    f"⏱ <b>Dedup:</b> Max 1 auto-trade per symbol per 6 hours\n\n"
                    "⚠️ <b>Trades are real.</b> You are responsible for all executions.\n"
                    "Use /autoexecute off to disable at any time.",
                    parse_mode='HTML'
                )
            else:
                await update.message.reply_text(
                    "❌ Failed to enable auto-execute. Please try again."
                )
            return

        # ── OFF ────────────────────────────────────────────────────────────
        if subcmd == 'off':
            success = await self.db.set_auto_execute(customer_id, False)
            if success:
                await update.message.reply_text(
                    "🔴 <b>Auto-Execute DISABLED</b>\n\n"
                    "Trades will no longer be auto-submitted on strong signals.\n"
                    "You'll still receive push notifications for strong signals "
                    "on your favorites.\n\n"
                    "Use /autoexecute on to re-enable.",
                    parse_mode='HTML'
                )
            else:
                await update.message.reply_text(
                    "❌ Failed to disable auto-execute. Please try again."
                )
            return

        # ── STATUS (default) ───────────────────────────────────────────────
        status = await self.db.get_auto_execute_status(customer_id)
        enabled = status.get('enabled', False)
        favorites = status.get('favorites', [])
        exchanges = await self.db.get_connected_exchanges(customer_id)

        status_emoji = '🟢' if enabled else '🔴'
        status_text = 'ENABLED' if enabled else 'DISABLED'
        fav_list = ', '.join(favorites) if favorites else '<i>None — add with</i> <code>favorite BTCUSD</code>'
        exchange_text = exchanges[0].title() if exchanges else '<i>None — use /connect_exchange</i>'

        await update.message.reply_text(
            f"🤖 <b>Auto-Execute Status</b>\n\n"
            f"{status_emoji} Status: <b>{status_text}</b>\n"
            f"📋 Favorites: {fav_list}\n"
            f"🏦 Exchange: {exchange_text}\n\n"
            f"<b>Settings (when enabled):</b>\n"
            f"• Signal threshold: 75%+ confidence\n"
            f"• Risk per trade: 1%\n"
            f"• Stop-loss: 1.5% | Take-profit: 3.0%\n"
            f"• Max 1 auto-trade per symbol per 6 hours\n\n"
            f"Commands: /autoexecute on · /autoexecute off",
            parse_mode='HTML'
        )

    def run(self):
        """Start the bot."""
        logger.info("Starting Telegram bot...")

        async def post_init(app):
            """Run on startup — ensure DB tables exist."""
            await self.db.connect()
            await self.db.ensure_user_preferences_table()
            logger.info("Post-init complete: DB tables ensured")

        application = Application.builder().token(self.token).post_init(post_init).build()

        # Analysis & trading
        application.add_handler(CommandHandler("start",    self.start))
        application.add_handler(CommandHandler("help",     self.help_command))
        application.add_handler(CommandHandler("status",   self.status_command))
        application.add_handler(CommandHandler("analyze",  self.analyze_command))
        application.add_handler(CommandHandler("analyse",  self.analyze_command))
        application.add_handler(CommandHandler("scan",     self.scan_command))
        application.add_handler(CommandHandler("execute",  self.execute_command))

        # Inline button callbacks (trade confirmation + broadcast)
        application.add_handler(CallbackQueryHandler(
            self.execute_callback,   pattern=r'^(confirm|cancel)_trade:'
        ))
        application.add_handler(CallbackQueryHandler(
            self.broadcast_callback, pattern=r'^broadcast_(confirm|cancel):'
        ))

        # Plan selection callbacks
        application.add_handler(CallbackQueryHandler(
            self.plan_info_callback,     pattern=r'^plan_info:'
        ))
        application.add_handler(CallbackQueryHandler(
            self.plan_checkout_callback, pattern=r'^plan_checkout:'
        ))
        application.add_handler(CallbackQueryHandler(
            self.plans_back_callback,    pattern=r'^plans_back$'
        ))

        # Alerts
        application.add_handler(CommandHandler("setalert",    self.setalert_command))
        application.add_handler(CommandHandler("alerts",      self.alerts_command))
        application.add_handler(CommandHandler("cancelalert", self.cancelalert_command))
        application.add_handler(CommandHandler("watch",       self.watch_command))
        application.add_handler(CommandHandler("unwatch",     self.unwatch_command))
        application.add_handler(CommandHandler("watchlist",   self.watchlist_command))
        application.add_handler(CommandHandler("briefing",    self.briefing_command))

        # Plans & referral
        application.add_handler(CommandHandler("plans",    self.plans_command))
        application.add_handler(CommandHandler("upgrade",  self.plans_command))   # alias
        application.add_handler(CommandHandler("referral", self.referral_command))
        application.add_handler(CommandHandler("refer",    self.referral_command))  # alias

        # Admin (silently ignores non-admins)
        application.add_handler(CommandHandler("admin", self.admin_command))

        # Exchange management
        application.add_handler(CommandHandler("connect_exchange",    self.connect_exchange_command))
        application.add_handler(CommandHandler("disconnect_exchange", self.disconnect_exchange_command))
        application.add_handler(CommandHandler("connect_mt5",         self.connect_mt5_command))

        # Auto-execute on strong signals
        application.add_handler(CommandHandler("autoexecute", self.autoexecute_command))

        # AI data assistant
        application.add_handler(CommandHandler("ask", self.ask_command))

        # Free-text messages
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

        # Error handler — prevents unhandled exceptions from breaking the polling loop
        async def _error_handler(update, context):
            logger.error("Telegram error: %s", context.error)
        application.add_error_handler(_error_handler)

        # Schedule background jobs via JobQueue (requires APScheduler)
        if application.job_queue:
            from datetime import time as dtime
            jq = application.job_queue
            jq.run_repeating(self.alert_manager.check_price_alerts,    interval=60,   first=15)
            jq.run_repeating(self.alert_manager.check_signal_alerts,   interval=300,  first=30)
            jq.run_repeating(self.alert_manager.check_favorite_strong_signals, interval=300, first=45)
            jq.run_repeating(self.alert_manager.update_bot_description, interval=1800, first=10)
            jq.run_daily(self.alert_manager.send_daily_briefings, time=dtime(7, 0))
            logger.info("JobQueue scheduled: price=60s, signals=5min, fav_strong=5min, description=30min, briefing=07:00 UTC")
        else:
            logger.warning("JobQueue unavailable — install python-telegram-bot[job-queue] for alerts")

        logger.info("Bot is running!")
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )


def main():
    """Main entry point."""
    bot = GlitchExecutorBot()
    bot.run()


if __name__ == "__main__":
    main()
