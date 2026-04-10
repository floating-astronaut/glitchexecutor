"""
GlitchExecutor RAG Assistant
AI-powered natural language query engine over trade data.
Uses Google Vertex AI (Gemini 2.5 Flash) for intent understanding and response synthesis.
Data retrieval via safe, parameterised query templates — no raw SQL generation.
"""
import json
import logging
import os
from datetime import datetime
from typing import Optional

from google import genai

logger = logging.getLogger("RAGAssistant")

# ─── Query templates (security-first: no user-generated SQL) ─────────────────

QUERY_TEMPLATES = {
    "trade_history": {
        "desc": "User's recent trades with PnL, direction, status",
        "sql": """
            SELECT symbol, direction, entry_price, sl_price, tp_price,
                   volume, ensemble_vote, status, pnl, executed_at, closed_at
            FROM trades WHERE customer_id = $1
            ORDER BY executed_at DESC LIMIT $2
        """,
        "params": ["customer_id", "limit"],
        "user_scoped": True,
    },
    "trade_performance": {
        "desc": "User's trade performance over N days",
        "sql": """
            SELECT symbol, direction, pnl, status, executed_at
            FROM trades WHERE customer_id = $1
            AND executed_at > NOW() - INTERVAL '{days} days'
        """,
        "params": ["customer_id", "days"],
        "user_scoped": True,
    },
    "signal_performance": {
        "desc": "Ensemble prediction history for a symbol",
        "sql": """
            SELECT symbol, consensus, consensus_confidence, votes, created_at
            FROM ensemble_predictions
            WHERE symbol ILIKE $1
            AND created_at > NOW() - INTERVAL '{days} days'
            ORDER BY created_at DESC LIMIT $2
        """,
        "params": ["symbol", "limit", "days"],
        "user_scoped": False,
    },
    "bot_positions": {
        "desc": "Bot trading positions (open or closed) for a symbol",
        "sql": """
            SELECT symbol, direction, entry_price, sl, tp, volume,
                   strategy, confidence, is_open, opened_at, closed_at, exit_reason
            FROM bot_positions
            WHERE ($1 = 'ALL' OR symbol ILIKE $1)
            AND opened_at > NOW() - INTERVAL '{days} days'
            ORDER BY opened_at DESC LIMIT $2
        """,
        "params": ["symbol", "limit", "days"],
        "user_scoped": False,
    },
    "bot_events": {
        "desc": "Bot events (entries, exits, SL updates) for a symbol",
        "sql": """
            SELECT event_type, symbol, direction, entry_price, details, event_timestamp
            FROM bot_events
            WHERE ($1 = 'ALL' OR symbol ILIKE $1)
            AND event_timestamp > NOW() - INTERVAL '{days} days'
            ORDER BY event_timestamp DESC LIMIT $2
        """,
        "params": ["symbol", "limit", "days"],
        "user_scoped": False,
    },
    "platform_stats": {
        "desc": "Overall platform prediction stats",
        "sql": """
            SELECT COUNT(*) as total_predictions,
                   AVG(consensus_confidence) as avg_confidence
            FROM ensemble_predictions
            WHERE created_at > NOW() - INTERVAL '{days} days'
        """,
        "params": ["days"],
        "user_scoped": False,
    },
    "user_alerts": {
        "desc": "User's active price alerts",
        "sql": """
            SELECT symbol, target_price, direction, triggered, created_at
            FROM price_alerts WHERE customer_id = $1 AND triggered = false
            ORDER BY created_at DESC
        """,
        "params": ["customer_id"],
        "user_scoped": True,
    },
    "query_history": {
        "desc": "User's past queries to the bot",
        "sql": """
            SELECT symbol, query_text, response_type, created_at
            FROM query_log WHERE customer_id = $1
            ORDER BY created_at DESC LIMIT $2
        """,
        "params": ["customer_id", "limit"],
        "user_scoped": True,
    },
}

# ─── System prompts ──────────────────────────────────────────────────────────

PLANNER_SYSTEM_PROMPT = """You are a data query planner for a crypto trading bot called GlitchExecutor.
Given a user's natural language question, decide which data queries to run.

Available query templates:
{templates}

Available real-time data (Redis):
- ensemble: Current AI ensemble predictions (consensus direction, confidence, model votes) for symbols: BTCUSD, ETHUSD, SOLUSD, XRPUSD
- sentiment: Current news sentiment analysis for symbols
- price: Current cached price for symbols

Respond with ONLY valid JSON (no markdown, no backticks):
{{
  "queries": [
    {{"template": "<template_name>", "params": {{"symbol": "BTCUSD", "days": 7, "limit": 20}}}},
    {{"template": "redis_ensemble", "params": {{"symbol": "BTCUSD"}}}},
    {{"template": "redis_sentiment", "params": {{"symbol": "BTCUSD"}}}},
    {{"template": "redis_price", "params": {{"symbol": "BTCUSD"}}}}
  ]
}}

Rules:
- Only use templates listed above or redis_ prefixed ones (redis_ensemble, redis_sentiment, redis_price)
- For user-specific data (trades, alerts, query history), the system auto-adds customer_id
- Default to 30 days and limit 20 if not specified (data may be sparse, use wider windows)
- Maximum days: 90, maximum limit: 50
- If the question is about a specific symbol, extract it (e.g., "BTC" → "BTCUSD", "ETH" → "ETHUSD", "SOL" → "SOLUSD", "XRP" → "XRPUSD")
- If the question is general (e.g., "how am I doing?"), use user-scoped templates
- Pick only the templates that are relevant — don't query everything"""

SYNTHESIZER_SYSTEM_PROMPT = """You are GlitchExecutor's AI trading assistant responding via Telegram.
Answer the user's question using ONLY the data provided below. Format for Telegram (HTML tags allowed: <b>, <i>, <code>).

Rules:
- Be concise — max 3-4 short paragraphs
- Use real numbers from the data, never fabricate
- If data is empty or unavailable, say so honestly
- Include a brief ⚡ insight or pattern if you spot one
- End with: <i>This is AI analysis, not financial advice.</i>
- Use bullet points for lists
- Format prices with $ and 2 decimal places
- Format percentages with 1 decimal place"""


DAILY_GEMINI_CALL_LIMIT = 200  # max Gemini API calls per day (~$0.12/day max)


class RAGAssistant:
    """AI-powered query engine over GlitchExecutor trade data."""

    def __init__(self, project: str, location: str, db, cache):
        self.db = db
        self.cache = cache
        self.project = project
        self.location = location
        self._client = None

    def _check_daily_budget(self) -> bool:
        """Check if we're within the daily Gemini call budget. Uses Redis counter."""
        if self.cache.r is None:
            return True
        try:
            key = f"gemini_calls:{datetime.utcnow().strftime('%Y-%m-%d')}"
            count = self.cache.r.get(key)
            return int(count or 0) < DAILY_GEMINI_CALL_LIMIT
        except Exception:
            return True

    def _increment_daily_calls(self):
        """Increment the daily Gemini call counter."""
        if self.cache.r is None:
            return
        try:
            key = f"gemini_calls:{datetime.utcnow().strftime('%Y-%m-%d')}"
            pipe = self.cache.r.pipeline()
            pipe.incr(key)
            pipe.expire(key, 90000)  # 25 hours TTL
            pipe.execute()
        except Exception:
            pass

    @property
    def client(self):
        if self._client is None:
            self._client = genai.Client(
                vertexai=True,
                project=self.project,
                location=self.location,
            )
        return self._client

    # ── Phase 1: Query planning ──────────────────────────────────────────────

    async def _plan_queries(self, question: str) -> list:
        """Ask Gemini which query templates to run."""
        template_desc = "\n".join(
            f"- {name}: {t['desc']} (params: {', '.join(t['params'])})"
            for name, t in QUERY_TEMPLATES.items()
        )
        system = PLANNER_SYSTEM_PROMPT.format(templates=template_desc)

        try:
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=question,
                config=genai.types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0.1,
                    max_output_tokens=500,
                ),
            )
            text = response.text.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            plan = json.loads(text)
            return plan.get("queries", [])
        except Exception as e:
            logger.error(f"Query planning failed: {e}")
            return []

    # ── Phase 2: Safe data retrieval ─────────────────────────────────────────

    async def _execute_queries(self, planned: list, customer_id: int) -> list:
        """Execute planned queries against DB and Redis."""
        results = []

        for q in planned[:5]:  # max 5 queries per request
            template_name = q.get("template", "")
            params = q.get("params", {})

            # ── Redis queries ──
            if template_name == "redis_ensemble":
                symbol = params.get("symbol", "BTCUSD")
                data = self.cache.read_votes(symbol)
                results.append({
                    "source": f"Current ensemble for {symbol}",
                    "data": data or "No ensemble data available",
                })
                continue

            if template_name == "redis_sentiment":
                symbol = params.get("symbol", "BTCUSD")
                data = self.cache.read_sentiment(symbol)
                results.append({
                    "source": f"Current sentiment for {symbol}",
                    "data": data or "No sentiment data available",
                })
                continue

            if template_name == "redis_price":
                symbol = params.get("symbol", "BTCUSD")
                price = self.cache.read_price(symbol)
                results.append({
                    "source": f"Current price for {symbol}",
                    "data": {"price": price} if price else "No price data",
                })
                continue

            # ── SQL template queries ──
            template = QUERY_TEMPLATES.get(template_name)
            if not template:
                logger.warning(f"Unknown template: {template_name}")
                continue

            # Clamp params
            days = min(int(params.get("days", 30)), 90)
            limit = min(int(params.get("limit", 20)), 50)
            symbol = params.get("symbol", "ALL")

            # Build the SQL with safe parameter substitution
            sql = template["sql"].format(days=days)

            # Build positional args based on template
            args = []
            for p in template["params"]:
                if p == "customer_id":
                    args.append(customer_id)
                elif p == "symbol":
                    args.append(symbol)
                elif p == "limit":
                    args.append(limit)
                elif p == "days":
                    pass  # already substituted via .format()

            try:
                await self.db.connect()
                rows = await self.db.pool.fetch(sql, *args)
                data = [dict(r) for r in rows]

                # Sanitize: convert datetime objects to strings
                for row in data:
                    for k, v in row.items():
                        if isinstance(v, datetime):
                            row[k] = v.isoformat()

                results.append({
                    "source": template["desc"],
                    "data": data if data else "No data found",
                })
            except Exception as e:
                logger.error(f"Query {template_name} failed: {e}")
                results.append({
                    "source": template["desc"],
                    "data": f"Query error: {str(e)[:100]}",
                })

        return results

    # ── Phase 3: Response synthesis ──────────────────────────────────────────

    async def _synthesize(self, question: str, data: list) -> str:
        """Generate a natural language response from query results."""
        data_text = json.dumps(data, indent=2, default=str)
        # Truncate if too large
        if len(data_text) > 8000:
            data_text = data_text[:8000] + "\n... (truncated)"

        prompt = f"User question: {question}\n\nRetrieved data:\n{data_text}"

        try:
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    system_instruction=SYNTHESIZER_SYSTEM_PROMPT,
                    temperature=0.3,
                    max_output_tokens=800,
                ),
            )
            return response.text.strip()
        except Exception as e:
            logger.error(f"Response synthesis failed: {e}")
            return "Sorry, I couldn't generate a response. Please try again."

    # ── Public API ───────────────────────────────────────────────────────────

    async def ask(self, question: str, customer_id: int) -> str:
        """Full RAG pipeline: plan → retrieve → synthesize."""
        # Budget guard
        if not self._check_daily_budget():
            return "⚠️ The AI assistant has reached its daily usage limit. It resets at midnight UTC. Please use /analyze or other commands in the meantime."

        try:
            # Phase 1: Plan queries
            self._increment_daily_calls()
            planned = await self._plan_queries(question)
            if not planned:
                # Fallback: just ask Gemini directly with no data context
                return await self._synthesize(question, [{"source": "No specific data queried", "data": "N/A"}])

            # Phase 2: Retrieve data
            data = await self._execute_queries(planned, customer_id)

            # Phase 3: Synthesize response
            self._increment_daily_calls()
            return await self._synthesize(question, data)

        except Exception as e:
            logger.error(f"RAG pipeline error: {e}")
            return "Sorry, something went wrong processing your question. Please try again."
