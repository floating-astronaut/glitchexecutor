"""
GlitchExecutor Telegram Bot - Orchestrator (Model 9)
LLM synthesizer that takes ensemble votes and creates customer response.
Now also handles general trading chat, symbol comparisons, and multi-turn context.
"""
import os
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    anthropic = None

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    openai = None

logger = logging.getLogger("Orchestrator")


class Orchestrator:
    """
    Model 9: LLM Synthesizer + Trading Chatbot
    - Analysis mode: Takes ensemble votes → customer response
    - Chat mode: General trading Q&A, market commentary
    - Compare mode: Side-by-side symbol comparison
    """

    name = "orchestrator"
    version = "2.0"

    def __init__(self, api_key: str = None, provider: str = "anthropic"):
        """Initialize orchestrator with LLM credentials."""
        self.api_key = api_key or os.environ.get("ORCHESTRATOR_LLM_KEY", "")
        self.provider = provider.lower()

        if not self.api_key:
            logger.warning("No orchestrator API key - using template responses")

    def _is_openrouter_key(self) -> bool:
        """Detect if the API key is an OpenRouter key."""
        return self.api_key.startswith("sk-or-")

    # ── System Prompts ────────────────────────────────────────────────────────

    def _analysis_system_prompt(self) -> str:
        """System prompt for ensemble analysis mode."""
        return """You are GlitchExecutor's AI trading analyst. You have access to independent analysis models that have already voted on this trade. Present their consensus to the trader in a clear, actionable format.

Rules:
- Lead with the consensus vote and confidence (e.g., "5/6 models vote BUY")
- Show each model's individual vote with a brief reason
- If auto-execute is available for this user, ask if they want to execute
- Always end with: "This is analysis, not financial advice. You decide."
- Be concise — traders want fast answers, not essays
- Use emoji sparingly: ✅ for BUY votes, ❌ for SELL, ⏸️ for HOLD
- If the user asks a follow-up question about a previous analysis, reference the conversation history

IMPORTANT — When consensus is HOLD:
- DO NOT just say "hold" and stop — give the trader actionable guidance
- State the lean direction: "Our models are neutral but leaning slightly bullish"
- Give specific price levels to watch from the key levels data
- Tell them WHAT TO DO at those levels: "$68,500 is the sweet spot to buy — that's where our trend follower sees EMA support"
- Explain WHY our models think that — reference specific model reasoning
- Give a sense of timing: "This setup could develop in the next few hours"
- Structure HOLD responses as:
  📊 HOLD — but here's what to watch
  📍 Key levels: Support $X | Resistance $Y
  🎯 Sweet spot: [level] is where we see the best entry
  🧠 Why: [which models see what]
  ⏰ Watch for: [specific trigger]
- HOLD should feel like expert guidance, not a dismissal
- Never say "no signal" — say "building toward a signal"
- Keep HOLD responses under 500 tokens (they need more detail than BUY/SELL)"""

    def _chat_system_prompt(self) -> str:
        """System prompt for general trading chat mode."""
        return """You are GlitchExecutor's AI trading assistant. You help traders with:
- Trading education (RSI, MACD, candlestick patterns, risk management, etc.)
- Market commentary and analysis discussions
- Strategy discussions (scalping, swing, position trading)
- General trading concepts and terminology

Rules:
- ONLY discuss trading, markets, finance, and economics. If asked about unrelated topics, politely redirect: "I'm your trading assistant — I can help with markets, strategies, and trading education. What would you like to know?"
- When live market data is provided in context, reference it naturally
- Never fabricate specific prices, percentages, or data — only reference data provided to you
- Be conversational but concise — this is Telegram, not an essay
- Use emoji sparingly to keep it professional
- Keep responses under 300 tokens
- If the user has favorite symbols, reference them when relevant
- Reference conversation history for continuity"""

    def _compare_system_prompt(self) -> str:
        """System prompt for symbol comparison mode."""
        return """You are GlitchExecutor's AI trading analyst comparing two assets side-by-side.

Rules:
- Present each symbol's ensemble consensus, confidence, and key model votes
- Highlight differences in technical signals, sentiment, and momentum
- Give a clear recommendation on which looks stronger and why
- Note any correlated or divergent price action
- End with: "This is analysis, not financial advice. You decide."
- Keep response under 500 tokens"""

    # ── Unified LLM Call ──────────────────────────────────────────────────────

    async def _call_llm(self, system_prompt: str, messages: List[Dict],
                        max_tokens: int = 400, temperature: float = 0.3) -> str:
        """
        Unified LLM call — routes to the correct provider.
        messages: list of {"role": "user"|"assistant", "content": str}
        """
        if not self.api_key:
            return ""

        try:
            if self._is_openrouter_key():
                return await self._call_openrouter_unified(
                    system_prompt, messages, max_tokens, temperature
                )
            elif self.provider == "anthropic" and ANTHROPIC_AVAILABLE:
                return await self._call_anthropic_unified(
                    system_prompt, messages, max_tokens, temperature
                )
            elif self.provider == "openai" and OPENAI_AVAILABLE:
                return await self._call_openai_unified(
                    system_prompt, messages, max_tokens, temperature
                )
            else:
                logger.warning(f"Provider {self.provider} not available")
                return ""
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return ""

    async def _call_openrouter_unified(self, system_prompt: str,
                                        messages: List[Dict],
                                        max_tokens: int,
                                        temperature: float) -> str:
        """Call OpenRouter API (OpenAI-compatible, routes to Claude)."""
        client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url="https://openrouter.ai/api/v1"
        )
        all_messages = [{"role": "system", "content": system_prompt}] + messages
        response = await client.chat.completions.create(
            model="anthropic/claude-3.5-sonnet",
            max_tokens=max_tokens,
            temperature=temperature,
            messages=all_messages
        )
        return response.choices[0].message.content if response.choices else ""

    async def _call_anthropic_unified(self, system_prompt: str,
                                       messages: List[Dict],
                                       max_tokens: int,
                                       temperature: float) -> str:
        """Call Anthropic Claude API."""
        client = anthropic.AsyncAnthropic(api_key=self.api_key)
        response = await client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=messages
        )
        return response.content[0].text if response.content else ""

    async def _call_openai_unified(self, system_prompt: str,
                                    messages: List[Dict],
                                    max_tokens: int,
                                    temperature: float) -> str:
        """Call OpenAI API."""
        client = openai.AsyncOpenAI(api_key=self.api_key)
        all_messages = [{"role": "system", "content": system_prompt}] + messages
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=max_tokens,
            temperature=temperature,
            messages=all_messages
        )
        return response.choices[0].message.content if response.choices else ""

    # ── Helper: Build conversation messages ───────────────────────────────────

    def _history_to_messages(self, conversation_history: list) -> List[Dict]:
        """Convert Redis chat history to LLM message format."""
        messages = []
        for entry in conversation_history:
            role = entry.get("role", "user")
            content = entry.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        return messages

    def _build_analysis_user_prompt(self, user_query: str, symbol: str, tier: str,
                                     can_execute: bool, votes: List[Dict],
                                     sentiment: Dict, current_price: float,
                                     minutes_ago: int,
                                     consensus_data: Dict = None) -> str:
        """Build user prompt for analysis mode. Includes bias + key levels for HOLD."""
        votes_json = json.dumps(votes, indent=2)
        if sentiment:
            sentiment_summary = {
                "direction": sentiment.get("direction", "neutral"),
                "score": round(sentiment.get("score", 0), 2),
            }
        else:
            sentiment_summary = {"direction": "neutral", "score": 0}
        sentiment_json = json.dumps(sentiment_summary)

        prompt = f"""Customer asked: "{user_query}"
Symbol: {symbol}
Customer tier: {tier} (can_execute: {can_execute})

Ensemble results for {symbol} (computed {minutes_ago} minutes ago):
{votes_json}

News sentiment: {sentiment_json}

Current price: {current_price}"""

        # Add bias and key levels for HOLD signals
        if consensus_data:
            bias = consensus_data.get("bias")
            if bias:
                prompt += f"\n\nBias direction: {bias.get('direction', 'neutral')}"
                prompt += f"\nBias confidence: {bias.get('confidence', 0.5)}"
                prompt += f"\nBias reasoning: {bias.get('reasoning', '')}"
                supporting = bias.get("supporting_models", [])
                if supporting:
                    prompt += "\nModels favoring this direction:"
                    for m in supporting:
                        prompt += f"\n  - {m.get('model', '?')}: {m.get('vote', '?')} (confidence {m.get('confidence', 0)}) — {m.get('reasoning', '')}"

            key_levels = consensus_data.get("key_levels")
            if key_levels:
                prompt += f"\n\nKey price levels from our models:"
                prompt += f"\nSupport levels: {key_levels.get('support', [])}"
                prompt += f"\nResistance levels: {key_levels.get('resistance', [])}"
                atr_val = key_levels.get("atr")
                if atr_val:
                    prompt += f"\nATR (expected move range): ±{atr_val}"

                prompt += "\n\nIMPORTANT: Give the trader specific levels to watch and what to do when price reaches them. Explain which models see what and why. Make it feel like expert advice, not a dismissal."

        prompt += "\n\nGenerate a response for the customer."
        return prompt

    # ── Analysis Mode (existing, refactored) ──────────────────────────────────

    async def synthesize(self, user_query: str, symbol: str, tier: str,
                         can_execute: bool, votes: List[Dict],
                         sentiment: Dict, current_price: float,
                         minutes_ago: int = 0,
                         conversation_history: list = None,
                         consensus_data: Dict = None) -> str:
        """
        Synthesize ensemble results into customer response.
        Supports conversation history + bias/key levels for HOLD signals.
        """
        if not self.api_key:
            return self._template_response(votes, sentiment, current_price, can_execute, consensus_data)

        try:
            # Build messages with optional conversation history
            messages = []
            if conversation_history:
                messages = self._history_to_messages(conversation_history[-6:])  # last 3 exchanges

            # Add current analysis prompt (with consensus_data for HOLD guidance)
            messages.append({
                "role": "user",
                "content": self._build_analysis_user_prompt(
                    user_query, symbol, tier, can_execute,
                    votes, sentiment, current_price, minutes_ago,
                    consensus_data=consensus_data
                )
            })

            # HOLD responses need more tokens for levels + explanation
            is_hold = consensus_data and consensus_data.get("bias")
            max_tokens = 500 if is_hold else 400

            result = await self._call_llm(
                self._analysis_system_prompt(), messages,
                max_tokens=max_tokens, temperature=0.3
            )

            if result:
                return result
            return self._template_response(votes, sentiment, current_price, can_execute, consensus_data)

        except Exception as e:
            logger.error(f"LLM synthesis failed: {e}")
            return self._template_response(votes, sentiment, current_price, can_execute, consensus_data)

    # ── Chat Mode (new) ──────────────────────────────────────────────────────

    async def chat(self, user_message: str, conversation_history: list = None,
                   user_context: dict = None) -> str:
        """
        General trading chat — education, market commentary, strategy discussion.
        user_context: {tier, favorites, market_snapshot}
        """
        if not self.api_key:
            return ("I'm your AI trading assistant, but my LLM backend is currently "
                    "unavailable. Try asking about a specific symbol like BTCUSD!")

        # Build messages from conversation history
        messages = []
        if conversation_history:
            messages = self._history_to_messages(conversation_history[-8:])  # last 4 exchanges

        # Build context block if we have market data
        context_parts = []
        if user_context:
            if user_context.get("favorites"):
                fav_lines = []
                for sym, data in user_context["favorites"].items():
                    price = data.get("price", "N/A")
                    consensus = data.get("consensus", "N/A")
                    fav_lines.append(f"  {sym}: ${price} — {consensus}")
                if fav_lines:
                    context_parts.append("User's favorite symbols:\n" + "\n".join(fav_lines))

            if user_context.get("tier"):
                context_parts.append(f"User tier: {user_context['tier']}")

        # Assemble the user message
        if context_parts:
            context_block = "\n".join(context_parts)
            full_message = f"[Live market context]\n{context_block}\n\n[User message]\n{user_message}"
        else:
            full_message = user_message

        messages.append({"role": "user", "content": full_message})

        result = await self._call_llm(
            self._chat_system_prompt(), messages,
            max_tokens=300, temperature=0.4
        )

        return result or ("I'm having trouble processing that right now. "
                          "Try asking about a specific symbol like BTCUSD!")

    # ── Compare Mode (new) ────────────────────────────────────────────────────

    async def compare(self, user_query: str, symbols: List[str],
                      analyses: List[Dict],
                      conversation_history: list = None,
                      user_context: dict = None) -> str:
        """
        Compare two symbols side-by-side.
        analyses: list of {symbol, votes, consensus, confidence, sentiment, price}
        """
        if not self.api_key:
            return self._template_comparison(analyses)

        # Build comparison data
        comparison_parts = []
        for a in analyses:
            sym = a.get("symbol", "?")
            votes = a.get("votes", [])
            consensus = a.get("consensus", "HOLD")
            confidence = a.get("confidence", 0)
            price = a.get("price", 0)
            sentiment = a.get("sentiment", {})

            buy_count = sum(1 for v in votes if isinstance(v, dict) and v.get("vote") == "BUY")
            sell_count = sum(1 for v in votes if isinstance(v, dict) and v.get("vote") == "SELL")
            hold_count = sum(1 for v in votes if isinstance(v, dict) and v.get("vote") == "HOLD")

            sent_dir = sentiment.get("direction", "neutral") if sentiment else "neutral"
            sent_score = round(sentiment.get("score", 0), 2) if sentiment else 0

            comparison_parts.append(
                f"{sym}:\n"
                f"  Price: ${price:,.4f}\n"
                f"  Consensus: {consensus} ({round(confidence * 100)}% confidence)\n"
                f"  Votes: {buy_count} BUY / {sell_count} SELL / {hold_count} HOLD\n"
                f"  Sentiment: {sent_dir} ({sent_score:+.2f})\n"
                f"  Model votes: {json.dumps(votes, indent=2)}"
            )

        comparison_text = "\n\n".join(comparison_parts)

        messages = []
        if conversation_history:
            messages = self._history_to_messages(conversation_history[-6:])

        messages.append({
            "role": "user",
            "content": f'Customer asked: "{user_query}"\n\n{comparison_text}\n\nCompare these two assets for the trader.'
        })

        result = await self._call_llm(
            self._compare_system_prompt(), messages,
            max_tokens=500, temperature=0.3
        )

        return result or self._template_comparison(analyses)

    # ── Template Fallbacks ────────────────────────────────────────────────────

    def _template_response(self, votes: List[Dict], sentiment: Dict,
                           current_price: float, can_execute: bool,
                           consensus_data: Dict = None) -> str:
        """Generate template response when LLM is unavailable."""
        buy_votes = [v for v in votes if v['vote'] == 'BUY']
        sell_votes = [v for v in votes if v['vote'] == 'SELL']
        hold_votes = [v for v in votes if v['vote'] == 'HOLD']

        total = len(votes)
        buy_count = len(buy_votes)
        sell_count = len(sell_votes)

        if buy_count > sell_count and buy_count > len(hold_votes):
            consensus = "BUY"
        elif sell_count > buy_count and sell_count > len(hold_votes):
            consensus = "SELL"
        else:
            consensus = "HOLD"

        lines = [
            f"📊 Analysis Result — {buy_count}/{total} models vote {consensus}",
            "",
        ]

        for vote in votes:
            v_emoji = "✅" if vote['vote'] == 'BUY' else "❌" if vote['vote'] == 'SELL' else "⏸️"
            lines.append(f"{v_emoji} {vote['model']}: {vote['vote']} — {vote['reasoning'][:80]}...")

        if sentiment and sentiment.get('direction') != 'neutral':
            sent_emoji = "📈" if sentiment['direction'] == 'bullish' else "📉"
            score = sentiment.get('score', 0)
            lines.append(f"\n{sent_emoji} Sentiment: {sentiment['direction'].capitalize()} ({score:+.2f})")

        lines.append(f"\n💰 Price: ${current_price:,.2f}")

        # HOLD-specific actionable guidance
        if consensus == "HOLD" and consensus_data:
            bias = consensus_data.get("bias")
            key_levels = consensus_data.get("key_levels")

            if bias and bias.get("direction") != "neutral":
                direction = bias["direction"].replace("_lean", "").replace("_", " ")
                supporting = bias.get("supporting_models", [])
                model_count = len(supporting)

                lines.append(f"\n📊 Leaning slightly {direction} ({model_count}/{total} models)")

                # Key levels
                if key_levels:
                    support = key_levels.get("support", [])
                    resistance = key_levels.get("resistance", [])
                    atr_val = key_levels.get("atr")

                    if support or resistance:
                        lines.append("\n📍 Key Levels:")
                        if support:
                            support_str = " — ".join(f"${s:,.2f}" for s in support)
                            lines.append(f"   Support: {support_str}")
                        if resistance:
                            resistance_str = " — ".join(f"${r:,.2f}" for r in resistance)
                            lines.append(f"   Resistance: {resistance_str}")

                    # Sweet spot
                    if bias["direction"] == "bullish_lean" and support:
                        lines.append(f"\n🎯 Sweet spot to buy: ${support[-1]:,.2f}")
                    elif bias["direction"] == "bearish_lean" and resistance:
                        lines.append(f"\n🎯 Sweet spot to sell: ${resistance[0]:,.2f}")

                    if atr_val:
                        lines.append(f"   Expected move range: ±${atr_val:,.2f}")

                # Model reasoning
                if supporting:
                    lines.append("\n🧠 Why our AI thinks this:")
                    for m in supporting[:3]:  # top 3
                        reasoning = m.get("reasoning", "")[:80]
                        lines.append(f"   • {m.get('model', '?')}: {reasoning}")

                # Watch trigger
                if key_levels:
                    support = key_levels.get("support", [])
                    resistance = key_levels.get("resistance", [])
                    if resistance and support:
                        lines.append(f"\n⏰ Watch for: break above ${resistance[0]:,.2f} or dip to ${support[-1]:,.2f}")

            elif bias and bias.get("direction") == "neutral":
                lines.append("\n⚖️ Truly neutral — no directional lean from any model.")
                if key_levels:
                    support = key_levels.get("support", [])
                    resistance = key_levels.get("resistance", [])
                    if support and resistance:
                        lines.append(f"📍 Range: ${support[-1]:,.2f} — ${resistance[0]:,.2f}")
                        lines.append("⏰ Wait for a breakout in either direction.")

        if can_execute and consensus in ['BUY', 'SELL']:
            lines.append(f"\n⚡ Type 'execute' to place this trade.")

        lines.append("\nThis is analysis, not financial advice. You decide.")
        return "\n".join(lines)

    def _template_comparison(self, analyses: List[Dict]) -> str:
        """Generate template comparison when LLM is unavailable."""
        lines = ["📊 <b>Symbol Comparison</b>\n"]

        for a in analyses:
            sym = a.get("symbol", "?")
            consensus = a.get("consensus", "HOLD")
            confidence = round(a.get("confidence", 0) * 100)
            price = a.get("price", 0)
            emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(consensus, "⚪")

            lines.append(f"{emoji} <b>{sym}</b> — {consensus} ({confidence}%)")
            lines.append(f"   Price: ${price:,.4f}")

            votes = a.get("votes", [])
            buy_c = sum(1 for v in votes if isinstance(v, dict) and v.get("vote") == "BUY")
            sell_c = sum(1 for v in votes if isinstance(v, dict) and v.get("vote") == "SELL")
            hold_c = sum(1 for v in votes if isinstance(v, dict) and v.get("vote") == "HOLD")
            lines.append(f"   Models: {buy_c} BUY / {sell_c} SELL / {hold_c} HOLD\n")

        lines.append("This is analysis, not financial advice. You decide.")
        return "\n".join(lines)
