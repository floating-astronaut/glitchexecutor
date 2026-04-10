"""
GlitchExecutor Telegram Bot - Rate Limiter
Query limiting per tier with daily reset.
"""
import logging
from typing import Dict, Tuple

logger = logging.getLogger("RateLimiter")


# Tier limits as defined in the spec
TIER_LIMITS = {
    "trial": 10,        # 10 queries/day during trial
    "starter": 30,      # $49 Starter plan
    "pro": 100,         # $149 Pro plan
    "elite": -1         # $499 Elite - unlimited
}


class RateLimiter:
    """Handles rate limiting based on customer tier."""
    
    def get_limit(self, tier: str) -> int:
        """Get query limit for tier."""
        return TIER_LIMITS.get(tier, 10)
    
    def is_unlimited(self, tier: str) -> bool:
        """Check if tier has unlimited queries."""
        return TIER_LIMITS.get(tier, 0) == -1
    
    async def check_and_increment(self, db, customer: Dict) -> Tuple[bool, str, int, int]:
        """
        Check rate limit and increment if allowed.
        
        Returns: (allowed, message, current_count, limit)
        """
        tier = customer.get('tier', 'trial')
        customer_id = customer.get('id')
        
        # Unlimited tiers
        if self.is_unlimited(tier):
            # Still increment for analytics
            new_count = await db.increment_queries(customer_id)
            return True, "", new_count, -1
        
        limit = self.get_limit(tier)
        current = await db.get_queries_today(customer_id)
        
        if current >= limit:
            return (
                False,
                f"⛔ You've used all your queries today ({current}/{limit}).\n\n"
                f"Upgrade for more at glitchexecutor.com/pricing",
                current,
                limit
            )
        
        # Increment and return new count
        new_count = await db.increment_queries(customer_id)
        remaining = limit - new_count
        
        return True, f"{remaining} queries remaining today", new_count, limit
    
    def get_status_message(self, current: int, limit: int, tier: str) -> str:
        """Get status message showing query usage."""
        if self.is_unlimited(tier):
            return "✅ Unlimited queries"
        
        remaining = limit - current
        percentage = (current / limit) * 100
        
        if percentage < 50:
            emoji = "🟢"
        elif percentage < 80:
            emoji = "🟡"
        else:
            emoji = "🔴"
        
        return f"{emoji} {current}/{limit} queries used ({remaining} remaining)"
