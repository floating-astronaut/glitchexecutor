"""
GlitchExecutor Execution Worker - Position Manager
Risk management and position sizing.
"""
import logging
from typing import Tuple, Dict

logger = logging.getLogger("PositionManager")


class PositionManager:
    """
    Handles position sizing and risk management.
    Same logic as BEAST's position sizing.
    """
    
    # Risk parameters
    MIN_BALANCE = 50  # $50 minimum
    MAX_POSITION_PCT = 0.05  # Max 5% of balance per trade
    DEFAULT_RISK_PCT = 0.01  # 1% risk per trade
    MAX_OPEN_POSITIONS = 3
    
    def calculate_position_size(self, balance: float, risk_percent: float,
                                entry_price: float, stop_loss: float) -> float:
        """
        Calculate position size based on risk.
        
        Formula: position_size = (balance * risk_percent) / abs(entry - sl)
        """
        if not entry_price or not stop_loss or entry_price == stop_loss:
            logger.warning("Invalid entry/stop prices for position sizing")
            return 0
        
        risk_amount = balance * (risk_percent / 100)
        price_risk = abs(entry_price - stop_loss)
        
        if price_risk == 0:
            return 0
        
        position_size = risk_amount / price_risk
        
        # Limit to max position size
        max_position_value = balance * self.MAX_POSITION_PCT
        max_position_size = max_position_value / entry_price
        
        position_size = min(position_size, max_position_size)
        
        logger.info(f"Position size: {position_size:.6f} (risk: ${risk_amount:.2f})")
        return position_size
    
    async def validate_trade(self, balance: float, trade: Dict) -> Tuple[bool, str]:
        """
        Pre-trade validation.
        
        Checks:
        - Balance >= $50
        - SL is set (required)
        - Position size within limits
        - Max open positions not exceeded
        
        Returns: (ok, reason)
        """
        # Check minimum balance
        if balance < self.MIN_BALANCE:
            return False, f"Insufficient balance: ${balance:.2f} (minimum ${self.MIN_BALANCE})"
        
        # Check SL is set
        sl = trade.get('sl_price')
        if not sl or sl <= 0:
            return False, "SL required — refusing to trade without stop loss"
        
        # Check position size
        entry = trade.get('entry_price', 0)
        if entry > 0:
            risk_pct = trade.get('risk_percent', self.DEFAULT_RISK_PCT * 100)
            position_size = self.calculate_position_size(balance, risk_pct, entry, sl)
            
            max_size = (balance * self.MAX_POSITION_PCT) / entry
            if position_size > max_size:
                return False, f"Position size exceeds maximum ({self.MAX_POSITION_PCT*100}% of balance)"
        
        logger.info(f"Trade validated: balance=${balance:.2f}, SL={sl}")
        return True, ""
    
    def get_risk_parameters(self) -> Dict:
        """Get current risk parameters."""
        return {
            'min_balance': self.MIN_BALANCE,
            'max_position_pct': self.MAX_POSITION_PCT,
            'default_risk_pct': self.DEFAULT_RISK_PCT,
            'max_open_positions': self.MAX_OPEN_POSITIONS
        }
