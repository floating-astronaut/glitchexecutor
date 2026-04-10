"""
GlitchExecutor Model: Taipan Breakout
M30 Asian session range breakout at London/NY kill zone.
Best performer from Windows VM bots: 82.6% WR, +1007 PnL.

Strategy:
  1. Calculate Asian session range (00:00-06:00 UTC high/low)
  2. At kill zone (07:00-10:00 UTC), detect breakout of range
  3. H4 EMA(50) trend filter gates direction
  4. Volume confirmation on breakout bar
  5. Range size filter (0.5-3.0x ATR)
  Fallback: EMA pullback during kill zone if no breakout
"""
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Dict, Any
from .base_model import BaseModel
from .indicators import ema, atr, rsi


# Default config (from taipan_config_propfirm.json)
_DEFAULT_CFG = {
    'asian_start_hour': 0,
    'asian_end_hour': 6,
    'kill_zone_start_hour': 7,
    'kill_zone_end_hour': 10,
    'h4_ema_period': 50,
    'h4_transition_mult': 0.5,
    'atr_period': 14,
    'min_asian_bars': 4,
    'min_range_atr_mult': 0.5,
    'max_range_atr_mult': 3.0,
    'breakout_buffer_mult': 0.1,
    'breakout_vol_mult': 1.2,
    'ema_fast_period': 8,
    'ema_slow_period': 20,
    'rsi_period': 14,
}


class TaipanBreakoutModel(BaseModel):
    """
    Asian session range breakout model.
    Uses M15 candles + H4 trend filter.
    """

    name = "taipan_breakout"
    version = "1.0"

    def __init__(self, config: dict = None):
        self.cfg = {**_DEFAULT_CFG, **(config or {})}

    def analyze(self, symbol: str, candles: Dict[str, np.ndarray]) -> Dict[str, Any]:
        m15 = candles.get("m15")
        h4 = candles.get("h4")

        if m15 is None or len(m15) < 60:
            return self._hold("Insufficient M15 data for session range calculation.")

        now_utc = datetime.now(timezone.utc)

        # H4 trend filter
        h4_trend = self._get_h4_trend(h4)

        # Calculate Asian session range from M15 bars
        asian_high, asian_low, range_width, curr_atr = self._calculate_asian_range(m15, now_utc)

        if asian_high is None:
            return self._hold(
                "No valid Asian range today (insufficient bars or range out of ATR bounds).",
                indicators={"atr": round(curr_atr, 5), "h4_trend": h4_trend}
            )

        # Check if we're in the kill zone
        in_kill_zone = self._in_kill_zone(now_utc)

        if not in_kill_zone:
            return self._hold(
                f"Outside kill zone ({self.cfg['kill_zone_start_hour']:02d}:00-"
                f"{self.cfg['kill_zone_end_hour']:02d}:00 UTC). "
                f"Asian range: {asian_high:.5f}/{asian_low:.5f}, width={range_width:.5f}",
                indicators={
                    "asian_high": round(asian_high, 5),
                    "asian_low": round(asian_low, 5),
                    "range_width": round(range_width, 5),
                    "atr": round(curr_atr, 5),
                    "h4_trend": h4_trend,
                    "in_kill_zone": False,
                }
            )

        # Check for breakout signal
        signal = self._check_session_breakout(m15, asian_high, asian_low, range_width, h4_trend, curr_atr)

        indicators = {
            "asian_high": round(asian_high, 5),
            "asian_low": round(asian_low, 5),
            "range_width": round(range_width, 5),
            "atr": round(curr_atr, 5),
            "h4_trend": h4_trend,
            "in_kill_zone": True,
        }

        if signal:
            indicators["trigger"] = signal["trigger"]
            indicators["breakout_direction"] = signal["direction"]
            if signal["direction"] == "BUY":
                indicators["suggested_sl"] = round(asian_low, 5)
                indicators["suggested_tp"] = round(float(m15[-1, 4]) + range_width * 1.5, 5)
            else:
                indicators["suggested_sl"] = round(asian_high, 5)
                indicators["suggested_tp"] = round(float(m15[-1, 4]) - range_width * 1.5, 5)

            return {
                "model": self.name,
                "vote": signal["direction"],
                "confidence": signal["confidence"],
                "reasoning": signal["reason"],
                "indicators": indicators,
            }

        return self._hold("In kill zone but no breakout or pullback signal.", indicators=indicators)

    def _get_h4_trend(self, h4: np.ndarray) -> str:
        if h4 is None or len(h4) < self.cfg['h4_ema_period'] + 5:
            return "BOTH"
        closes = h4[:, 4].astype(float)
        highs = h4[:, 2].astype(float)
        lows = h4[:, 3].astype(float)
        h4_ema = ema(closes, self.cfg['h4_ema_period'])
        atr_vals = atr(highs, lows, closes, 14)
        h4_close = float(closes[-1])
        h4_ema_val = float(h4_ema[-1])
        h4_atr = float(atr_vals[-1]) if not np.isnan(atr_vals[-1]) else 0.0
        transition = h4_atr * self.cfg['h4_transition_mult']
        if h4_close > h4_ema_val + transition:
            return "BUY"
        elif h4_close < h4_ema_val - transition:
            return "SELL"
        return "BOTH"

    def _calculate_asian_range(self, m15: np.ndarray, now_utc: datetime):
        asian_start = self.cfg['asian_start_hour']
        asian_end = self.cfg['asian_end_hour']
        highs = m15[:, 2].astype(float)
        lows = m15[:, 3].astype(float)
        closes = m15[:, 4].astype(float)
        times = m15[:, 0]
        atr_vals = atr(highs, lows, closes, self.cfg['atr_period'])
        curr_atr = float(atr_vals[-1]) if not np.isnan(atr_vals[-1]) else 0.0
        if curr_atr <= 0:
            return None, None, None, 0.0

        today = now_utc.date()
        asian_highs = []
        asian_lows = []

        for i in range(len(times)):
            bar_dt = datetime.fromtimestamp(int(times[i]), tz=timezone.utc)
            bar_date = bar_dt.date()
            hour = bar_dt.hour
            if asian_start <= asian_end:
                if bar_date == today and asian_start <= hour < asian_end:
                    asian_highs.append(float(highs[i]))
                    asian_lows.append(float(lows[i]))
            else:
                yesterday = today - timedelta(days=1)
                if bar_date == yesterday and hour >= asian_start:
                    asian_highs.append(float(highs[i]))
                    asian_lows.append(float(lows[i]))
                elif bar_date == today and hour < asian_end:
                    asian_highs.append(float(highs[i]))
                    asian_lows.append(float(lows[i]))

        if len(asian_highs) < self.cfg['min_asian_bars']:
            return None, None, None, curr_atr

        asian_high = max(asian_highs)
        asian_low = min(asian_lows)
        range_width = asian_high - asian_low
        min_range = curr_atr * self.cfg['min_range_atr_mult']
        max_range = curr_atr * self.cfg['max_range_atr_mult']
        if range_width < min_range or range_width > max_range:
            return None, None, None, curr_atr
        return asian_high, asian_low, range_width, curr_atr

    def _in_kill_zone(self, now_utc: datetime) -> bool:
        hour = now_utc.hour
        start = self.cfg['kill_zone_start_hour']
        end = self.cfg['kill_zone_end_hour']
        if start <= end:
            return start <= hour < end
        return hour >= start or hour < end

    def _check_session_breakout(self, m15, asian_high, asian_low, range_width, h4_trend, curr_atr):
        closes = m15[:, 4].astype(float)
        volumes = m15[:, 5].astype(float)
        breakout_buffer = curr_atr * self.cfg['breakout_buffer_mult']
        vol_mult = self.cfg['breakout_vol_mult']
        if len(closes) < 50:
            return None

        c1 = float(closes[-2])
        vol_1 = float(volumes[-2])
        avg_vol = float(np.mean(volumes[-50:])) if len(volumes) >= 50 else float(np.mean(volumes))
        vol_ok = avg_vol <= 0 or vol_1 > avg_vol * vol_mult

        if c1 > asian_high + breakout_buffer and h4_trend in ('BUY', 'BOTH') and vol_ok:
            vol_ratio = vol_1 / avg_vol if avg_vol > 0 else 1.0
            return {
                'trigger': 'SESSION_BREAKOUT', 'direction': 'BUY', 'confidence': 0.80,
                'reason': f'Bullish breakout: close {c1:.5f} > Asian high {asian_high:.5f} + buf {breakout_buffer:.5f}, vol {vol_ratio:.1f}x, H4={h4_trend}'
            }
        if c1 < asian_low - breakout_buffer and h4_trend in ('SELL', 'BOTH') and vol_ok:
            vol_ratio = vol_1 / avg_vol if avg_vol > 0 else 1.0
            return {
                'trigger': 'SESSION_BREAKOUT', 'direction': 'SELL', 'confidence': 0.80,
                'reason': f'Bearish breakout: close {c1:.5f} < Asian low {asian_low:.5f} - buf {breakout_buffer:.5f}, vol {vol_ratio:.1f}x, H4={h4_trend}'
            }

        # Fallback: EMA pullback
        ema_fast = ema(closes, self.cfg['ema_fast_period'])
        ema_slow = ema(closes, self.cfg['ema_slow_period'])
        rsi_vals = rsi(closes, self.cfg['rsi_period'])
        ema_f = float(ema_fast[-1])
        ema_s = float(ema_slow[-1])
        close_now = float(closes[-1])
        close_prev = float(closes[-2])
        curr_rsi = float(rsi_vals[-1]) if not np.isnan(rsi_vals[-1]) else 50.0

        if h4_trend in ('BUY', 'BOTH') and ema_f > ema_s:
            if close_prev <= ema_f * 1.003 and close_now > ema_f and 35 < curr_rsi < 75:
                return {
                    'trigger': 'EMA_PULLBACK', 'direction': 'BUY', 'confidence': 0.72,
                    'reason': f'Bullish EMA pullback: close {close_now:.5f} reclaimed EMA8 {ema_f:.5f}, RSI={curr_rsi:.1f}, H4={h4_trend}'
                }
        if h4_trend in ('SELL', 'BOTH') and ema_f < ema_s:
            if close_prev >= ema_f * 0.997 and close_now < ema_f and 25 < curr_rsi < 65:
                return {
                    'trigger': 'EMA_PULLBACK', 'direction': 'SELL', 'confidence': 0.72,
                    'reason': f'Bearish EMA pullback: close {close_now:.5f} rejected EMA8 {ema_f:.5f}, RSI={curr_rsi:.1f}, H4={h4_trend}'
                }
        return None

    def _hold(self, reasoning, indicators=None):
        return {"model": self.name, "vote": "HOLD", "confidence": 0.5, "reasoning": reasoning, "indicators": indicators or {}}
