"""
GlitchExecutor Alert Manager
Background job callbacks: price alerts, signal alerts, daily market briefing,
strong signal notifications on favorites, auto-execute.
Scheduled via python-telegram-bot JobQueue (APScheduler).
"""
import logging
import uuid
from datetime import datetime

from telegram.ext import ContextTypes

logger = logging.getLogger("AlertManager")


class AlertManager:
    """Handles all scheduled alert/notification jobs."""

    STRONG_SIGNAL_CONFIDENCE = 0.75  # 75% threshold for strong signal alerts

    def __init__(self, db, cache):
        self.db = db
        self.cache = cache

    # ── Price Alerts ─────────────────────────────────────────────────────────

    async def check_price_alerts(self, context: ContextTypes.DEFAULT_TYPE):
        """JobQueue callback — runs every 60s. Fires price alerts when target is hit."""
        await self.db.connect()
        alerts = await self.db.get_active_price_alerts()

        for alert in alerts:
            price = self.cache.read_price(alert['symbol'])
            if price is None:
                continue

            triggered = (
                (alert['direction'] == 'above' and price >= float(alert['target_price'])) or
                (alert['direction'] == 'below' and price <= float(alert['target_price']))
            )
            if not triggered:
                continue

            try:
                arrow = '≥' if alert['direction'] == 'above' else '≤'
                await context.bot.send_message(
                    chat_id=alert['telegram_id'],
                    text=(
                        f"🔔 <b>Price Alert Triggered!</b>\n\n"
                        f"<b>{alert['symbol']}</b> is now <b>${price:,.4f}</b>\n"
                        f"Your target: {arrow} ${float(alert['target_price']):,.4f}\n\n"
                        f"Run /analyse {alert['symbol']} for a full signal."
                    ),
                    parse_mode='HTML'
                )
                await self.db.mark_price_alert_triggered(alert['id'])
            except Exception as e:
                logger.error(f"Failed to send price alert {alert['id']}: {e}")

    # ── Signal Alerts ─────────────────────────────────────────────────────────

    async def check_signal_alerts(self, context: ContextTypes.DEFAULT_TYPE):
        """JobQueue callback — runs every 5 min. Pushes ensemble signals to watchers."""
        await self.db.connect()
        subs = await self.db.get_active_signal_subs()
        if not subs:
            return

        # Group by symbol to avoid redundant Redis reads
        by_symbol: dict = {}
        for sub in subs:
            by_symbol.setdefault(sub['symbol'], []).append(sub)

        for symbol, subscribers in by_symbol.items():
            data = self.cache.read_votes(symbol)
            if not data:
                continue

            consensus = data.get('consensus', 'HOLD')
            confidence = data.get('confidence', 0.0)
            if consensus == 'HOLD':
                continue

            price = self.cache.read_price(symbol) or 0.0
            emoji = '🟢' if consensus == 'BUY' else '🔴'

            for sub in subscribers:
                if confidence < sub.get('min_confidence', 0.6):
                    continue

                # Dedup via Redis — fire each unique signal only once per 6h
                dedup_key = f"signal_fired:{sub['customer_id']}:{symbol}:{consensus}"
                if self.cache.r and self.cache.r.exists(dedup_key):
                    continue

                try:
                    conf_pct = round(confidence * 100)
                    await context.bot.send_message(
                        chat_id=sub['telegram_id'],
                        text=(
                            f"📡 <b>Signal Alert</b>\n\n"
                            f"{emoji} <b>{symbol}</b>: {consensus} ({conf_pct}% confidence)\n"
                            f"Price: ${price:,.4f}\n\n"
                            f"Run /analyse {symbol} for full analysis."
                        ),
                        parse_mode='HTML'
                    )
                    if self.cache.r:
                        self.cache.r.setex(dedup_key, 21600, '1')  # 6h dedup window
                except Exception as e:
                    logger.error(f"Failed to send signal alert to {sub['telegram_id']}: {e}")

    # ── Strong Signal Alerts on Favorites ────────────────────────────────────

    async def check_favorite_strong_signals(self, context: ContextTypes.DEFAULT_TYPE):
        """
        JobQueue callback — runs every 5 min.
        Notifies users of strong signals (≥75% confidence) on their favorite symbols.
        Auto-executes trades for Pro/Elite users who opted in.
        """
        await self.db.connect()

        symbols = self.cache.get_all_symbols()
        if not symbols:
            return

        for symbol in symbols:
            data = self.cache.read_votes(symbol)
            if not data:
                continue

            consensus = data.get('consensus', 'HOLD')
            confidence = data.get('confidence', 0.0)

            # Only fire on strong BUY/SELL signals
            if consensus == 'HOLD' or confidence < self.STRONG_SIGNAL_CONFIDENCE:
                continue

            price = self.cache.read_price(symbol) or 0.0
            conf_pct = round(confidence * 100)
            emoji = '🟢' if consensus == 'BUY' else '🔴'

            # Get all users who favorited this symbol
            users = await self.db.get_users_with_favorite_symbol(symbol)
            if not users:
                continue

            for user in users:
                customer_id = user['customer_id']
                telegram_id = user['telegram_id']
                tier = user.get('tier', 'trial')
                auto_exec = user.get('auto_execute_enabled', False)

                # Dedup: one notification per signal direction per 6h
                dedup_key = f"fav_strong:{customer_id}:{symbol}:{consensus}"
                if self.cache.r and self.cache.r.exists(dedup_key):
                    continue

                try:
                    # Build notification message
                    notif_lines = [
                        f"⚡ <b>Strong Signal on Your Favorite!</b>\n",
                        f"{emoji} <b>{symbol}</b>: {consensus} ({conf_pct}% confidence)",
                        f"Price: ${price:,.4f}\n",
                        f"Run /analyse {symbol} for full analysis.",
                    ]

                    # Auto-execute for Pro/Elite opt-in users
                    if auto_exec and tier in ('pro', 'elite'):
                        auto_trade_key = f"auto_trade:{customer_id}:{symbol}"
                        already_traded = self.cache.r and self.cache.r.exists(auto_trade_key)

                        if not already_traded:
                            connected = await self.db.get_connected_exchanges(customer_id)
                            if connected:
                                exchange = connected[0]
                                trade_request = self._build_auto_trade_request(
                                    customer_id, symbol, consensus, confidence,
                                    price, exchange
                                )
                                submitted = self.cache.submit_trade(trade_request)
                                if submitted:
                                    if self.cache.r:
                                        self.cache.r.setex(auto_trade_key, 21600, '1')
                                    sl_price = trade_request['sl_price']
                                    tp_price = trade_request['tp_price']
                                    notif_lines.append(
                                        f"\n🤖 <b>Auto-trade submitted!</b>\n"
                                        f"Exchange: {exchange.title()}\n"
                                        f"Direction: {consensus} | Risk: 1%\n"
                                        f"SL: ${sl_price:,.4f} | TP: ${tp_price:,.4f}\n"
                                        f"Request: <code>{trade_request['request_id'][:8]}</code>"
                                    )
                                    logger.info(
                                        f"Auto-trade submitted: {consensus} {symbol} "
                                        f"for customer {customer_id} on {exchange}"
                                    )

                    await context.bot.send_message(
                        chat_id=telegram_id,
                        text='\n'.join(notif_lines),
                        parse_mode='HTML'
                    )

                    # Set notification dedup key
                    if self.cache.r:
                        self.cache.r.setex(dedup_key, 21600, '1')  # 6h

                except Exception as e:
                    logger.error(
                        f"Failed to send strong signal alert to {telegram_id}: {e}"
                    )

    def _build_auto_trade_request(self, customer_id: int, symbol: str,
                                   consensus: str, confidence: float,
                                   price: float, exchange: str) -> dict:
        """Build a trade request dict matching the format expected by the executor."""
        sl_pct, tp_pct = 0.015, 0.030
        if consensus == 'BUY':
            sl_price = round(price * (1 - sl_pct), 6)
            tp_price = round(price * (1 + tp_pct), 6)
        else:
            sl_price = round(price * (1 + sl_pct), 6)
            tp_price = round(price * (1 - tp_pct), 6)

        return {
            'request_id':    str(uuid.uuid4()),
            'customer_id':   customer_id,
            'symbol':        symbol,
            'direction':     consensus,
            'entry_price':   price,
            'sl_price':      sl_price,
            'tp_price':      tp_price,
            'exchange':      exchange,
            'ensemble_vote': f"{consensus} {round(confidence * 100)}%",
            'risk_pct':      1.0,
            'auto_executed': True,
        }

    # ── Daily Market Briefing ─────────────────────────────────────────────────

    async def send_daily_briefings(self, context: ContextTypes.DEFAULT_TYPE):
        """JobQueue callback — runs daily at 07:00 UTC. Sends market summary."""
        await self.db.connect()
        subs = await self.db.get_daily_briefing_subs()
        if not subs:
            return

        symbols = self.cache.get_all_symbols()
        if not symbols:
            return

        lines = [
            f"📰 <b>Daily Market Briefing</b>",
            f"<i>{datetime.utcnow().strftime('%Y-%m-%d')} — 07:00 UTC</i>\n",
        ]

        for symbol in sorted(symbols)[:10]:
            data = self.cache.read_votes(symbol)
            price = self.cache.read_price(symbol)
            if not data or not price:
                continue
            consensus = data.get('consensus', 'HOLD')
            conf = round(data.get('confidence', 0) * 100)
            emoji = {'BUY': '🟢', 'SELL': '🔴', 'HOLD': '🟡'}.get(consensus, '⚪')
            lines.append(f"{emoji} <b>{symbol}</b>  {consensus} ({conf}%)  ${price:,.4f}")

        if len(lines) < 3:
            return

        lines.append("\nUse /analyse &lt;symbol&gt; for a deep signal.")
        msg = '\n'.join(lines)

        for sub in subs:
            try:
                await context.bot.send_message(
                    chat_id=sub['telegram_id'],
                    text=msg,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Failed to send daily briefing to {sub['telegram_id']}: {e}")

    # ── Live User Count in Bot Description ───────────────────────────────────

    async def update_bot_description(self, context: ContextTypes.DEFAULT_TYPE):
        """
        JobQueue callback — runs every 30 min.
        Updates the bot's About text with live user count so it shows in the
        bot profile header (visible to anyone who opens the bot).
        """
        await self.db.connect()
        stats = await self.db.get_user_stats()

        total = stats.get('total', 0)
        paying = stats.get('paying', 0)
        active = stats.get('active_today', 0)

        # Format counts with K suffix for large numbers
        def _fmt(n):
            return f"{n/1000:.1f}K" if n >= 1000 else str(n)

        short_desc = f"🔮 {_fmt(total)} traders — AI signals & real-time alerts"

        long_desc = (
            f"🔮 GlitchExecutor — AI Trading Signals\n\n"
            f"📊 {_fmt(total)} traders joined  •  {_fmt(paying)} paid members\n"
            f"⚡ {_fmt(active)} active today\n\n"
            f"7-model AI ensemble + live sentiment on BTC, ETH, SOL and more.\n"
            f"Set price alerts, signal watchlists, and auto-execute trades.\n\n"
            f"Type /start to begin or visit glitchexecutor.com"
        )

        try:
            await context.bot.set_my_short_description(short_desc)
            await context.bot.set_my_description(long_desc)
            logger.info(f"Bot description updated: {total} total users")
        except Exception as e:
            logger.error(f"Failed to update bot description: {e}")
