"""
GlitchExecutor Telegram Bot - Authentication
Customer tier checking and account validation.
"""
import logging
import os
from datetime import datetime
from typing import Dict, Optional, Tuple

logger = logging.getLogger("Auth")

# Admin bypass — set ADMIN_TELEGRAM_ID env var to your Telegram user ID
_raw_admin = os.environ.get("ADMIN_TELEGRAM_ID", "0").strip()
ADMIN_TELEGRAM_ID = int(_raw_admin) if _raw_admin.isdigit() else 0

# Tier limits
TIER_LIMITS = {
    "trial": 10,        # 10 queries/day during trial
    "starter": 30,      # $49 Starter plan
    "pro": 100,         # $149 Pro plan
    "elite": -1         # $499 Elite - unlimited
}


class AuthManager:
    """Handles customer authentication and tier checking."""

    async def authenticate(self, db, telegram_id: int, username: str = None) -> Tuple[Optional[Dict], str, bool]:
        """
        Authenticate or create customer.

        Returns: (customer_dict, error_message, is_new)
        is_new is True if the customer was just created this call.
        If authentication fails, customer is None and error_message is set.
        """
        # Admin bypass — full access, no trial or status checks
        if ADMIN_TELEGRAM_ID and telegram_id == ADMIN_TELEGRAM_ID:
            customer = await db.get_customer(telegram_id)
            if not customer:
                customer = await db.create_customer(telegram_id, username)
            if customer:
                customer = dict(customer)
                customer['tier'] = 'elite'
                customer['status'] = 'active'
            return customer, "", False

        # Try to get existing customer
        customer = await db.get_customer(telegram_id)

        if customer:
            # Check status
            status = customer.get('status', 'trial')

            if status in ['cancelled', 'suspended']:
                return None, "Your account is inactive. Contact support for assistance.", False

            # Check trial expiration
            if status == 'trial':
                trial_ends = customer.get('trial_ends_at')
                if trial_ends and trial_ends < datetime.utcnow():
                    return None, "TRIAL_ENDED", False

            return customer, "", False  # existing user

        # Create new customer
        customer = await db.create_customer(telegram_id, username)
        if customer:
            logger.info(f"New customer registered: {telegram_id} (@{username})")
            return customer, "", True  # brand new user

        return None, "Error creating account. Please try again later.", False

    def can_execute(self, customer: Dict) -> bool:
        """Check if customer tier allows trade execution."""
        tier = customer.get('tier', 'trial')
        return tier in ['pro', 'elite']

    def get_tier_limit(self, customer: Dict) -> int:
        """Get query limit for customer's tier."""
        tier = customer.get('tier', 'trial')
        return TIER_LIMITS.get(tier, 10)

    async def check_rate_limit(self, db, customer: Dict) -> Tuple[bool, str]:
        """
        Check if customer has queries remaining.

        Returns: (allowed, message)
        """
        customer_id = customer.get('id')
        tier = customer.get('tier', 'trial')

        # Unlimited tiers (including admin who is always set to elite)
        if tier in ['elite']:
            return True, ""

        limit = self.get_tier_limit(customer)
        current = await db.get_queries_today(customer_id)

        if current >= limit:
            return False, "RATE_LIMIT"

        return True, ""

    def get_welcome_message(self, customer: Dict, is_new: bool = True,
                            first_name: str = None, queries_used: int = 0) -> str:
        """
        Generate welcome message for customer.

        is_new=True  → full onboarding message (first time ever)
        is_new=False → short personalised "welcome back" message
        """
        tier  = customer.get('tier', 'trial')
        limit = self.get_tier_limit(customer)
        name  = first_name or "there"

        # ── New user: full onboarding ──────────────────────────────────────
        if is_new:
            return (
                f"Welcome to GlitchExecutor, {name}! 🔮\n\n"
                "9 AI models analyze any trade for you:\n"
                "• Trend Following (SMA/EMA crossover)\n"
                "• Mean Reversion (Bollinger Bands + RSI)\n"
                "• Momentum Hunter (RSI breaks)\n"
                "• ML Pattern Recognition\n"
                "• Multi-Timeframe Alignment\n"
                "• Volume Profiler\n"
                "• Session Analyst\n"
                "• News Sentiment\n"
                "• LLM Synthesis\n\n"
                f"You're on a 7-day free trial ({limit} queries/day).\n\n"
                "Try: /analyse BTCUSD\n"
                "Or just type a symbol like <code>ETHUSD</code>\n\n"
                "/help — see all commands"
            )

        # ── Returning user: personalised short greeting ────────────────────
        if tier == 'trial':
            trial_ends = customer.get('trial_ends_at')
            days_left  = max(0, (trial_ends - datetime.utcnow()).days) if trial_ends else 0
            used_str   = f"{queries_used}/{limit}" if limit > 0 else str(queries_used)
            return (
                f"Hey {name}! 👋\n\n"
                f"📊 Trial: <b>{days_left} days left</b> · {used_str} queries used today\n\n"
                "Quick access:\n"
                "• Analyse a symbol — <code>/analyse BTCUSD</code>\n"
                "• Price alerts — /alerts\n"
                "• Your watchlist — /watchlist\n"
                "• Daily briefing — /briefing\n\n"
                "/help — full command list"
            )

        if tier == 'starter':
            used_str = f"{queries_used}/{limit}"
            return (
                f"Hey {name}! 👋\n\n"
                f"⭐ <b>Starter</b> plan active\n"
                f"📊 {used_str} queries used today\n\n"
                "/help — full command list"
            )

        if tier == 'pro':
            used_str = f"{queries_used}/{limit}"
            return (
                f"Hey {name}! 👋\n\n"
                f"🤖 <b>Pro</b> plan active\n"
                f"📊 {used_str} queries used today\n\n"
                "Use /execute after any analysis to trade.\n"
                "/help — full command list"
            )

        if tier == 'elite':
            return (
                f"Hey {name}! 👋\n\n"
                "🏢 <b>Elite</b> plan active — unlimited queries\n\n"
                "Use /connect_mt5 for automated MT5 trading.\n"
                "/help — full command list"
            )

        # fallback
        return f"Welcome back, {name}! 👋\n\n/help — see all commands"
