"""
GlitchExecutor Model: Anaconda Breakout
H4 strict 5-condition breakout system (ExMachina-inspired).
Trades rarely but with high conviction when ALL conditions align.

CONDITIONS (ALL must be true):
  1. EMA trend direction (fast > slow or fast < slow)
  2. Trend strength — EMAs separated by minimum ATR distance
  3. Price position — close above/below both EMAs
  4. N-bar breakout — new 20-bar high/low with ATR buffer
  5. RSI in healthy zone (40-65 buy, 35-60 sell)

Fallback: EMA pullback entry when trend is intact.
"""
import numpy as np
from typing import Dict, Any
from .base_model import BaseModel
from .indicators import ema, atr, rsi


_DEFAULT_CFG = {
    'ema_fast_period': 50,
    'ema_slow_period': 200,
    'atr_period': 14,
    'breakout_lookback': 20,
    'breakout_buffer_mult': 0.3,
    'trend_strength_mult': 0.3,
    'rsi_period': 10,
    'rsi_buy_min': 40, 'rsi_buy_max': 65,
    'rsi_sell_min': 35, 'rsi_sell_max': 60,
}


class AnacondaBreakoutModel(BaseModel):
    """Strict 5-condition breakout model using H4 candles."""

    name = "anaconda_breakout"
    version = "1.0"

    def __init__(self, config: dict = None):
        self.cfg = {**_DEFAULT_CFG, **(config or {})}

    def analyze(self, symbol: str, candles: Dict[str, np.ndarray]) -> Dict[str, Any]:
        h4 = candles.get("h4")
        if h4 is None or len(h4) < self.cfg['ema_slow_period'] + 10:
            return self._hold("Insufficient H4 data for EMA(200) warm-up.")

        closes = h4[:, 4].astype(float)
        highs = h4[:, 2].astype(float)
        lows = h4[:, 3].astype(float)

        ema_fast = ema(closes, self.cfg['ema_fast_period'])
        ema_slow = ema(closes, self.cfg['ema_slow_period'])
        atr_vals = atr(highs, lows, closes, self.cfg['atr_period'])
        rsi_vals = rsi(closes, self.cfg['rsi_period'])

        curr_atr = float(atr_vals[-1]) if not np.isnan(atr_vals[-1]) else 0.0
        if curr_atr <= 0:
            return self._hold("ATR is zero.")

        ema_f = float(ema_fast[-2])
        ema_s = float(ema_slow[-2])
        curr_rsi = float(rsi_vals[-2]) if len(rsi_vals) > 1 and not np.isnan(rsi_vals[-2]) else 50.0
        c1 = float(closes[-2])
        c2 = float(closes[-3])

        # 5 conditions
        bull_trend = ema_f > ema_s
        bear_trend = ema_f < ema_s
        ema_separation = abs(ema_f - ema_s)
        trend_strong = ema_separation >= curr_atr * self.cfg['trend_strength_mult']
        above_both = c1 > ema_f and c1 > ema_s
        below_both = c1 < ema_f and c1 < ema_s

        lookback = self.cfg['breakout_lookback']
        if len(highs) < lookback + 3:
            return self._hold("Not enough lookback bars.")
        lookback_highs = highs[-(lookback + 3):-3]
        lookback_lows = lows[-(lookback + 3):-3]
        n_bar_high = float(np.max(lookback_highs))
        n_bar_low = float(np.min(lookback_lows))
        buf = curr_atr * self.cfg['breakout_buffer_mult']
        bull_breakout = c1 > (n_bar_high + buf) and c2 <= (n_bar_high + buf)
        bear_breakout = c1 < (n_bar_low - buf) and c2 >= (n_bar_low - buf)

        rsi_buy_ok = self.cfg['rsi_buy_min'] <= curr_rsi <= self.cfg['rsi_buy_max']
        rsi_sell_ok = self.cfg['rsi_sell_min'] <= curr_rsi <= self.cfg['rsi_sell_max']

        conditions_met = sum([bull_trend or bear_trend, trend_strong, above_both or below_both, bull_breakout or bear_breakout, rsi_buy_ok or rsi_sell_ok])

        indicators = {
            "ema_fast": round(ema_f, 5), "ema_slow": round(ema_s, 5),
            "ema_separation": round(ema_separation, 5), "rsi": round(curr_rsi, 2),
            "atr": round(curr_atr, 5), "n_bar_high": round(n_bar_high, 5), "n_bar_low": round(n_bar_low, 5),
            "conditions_met": conditions_met,
        }

        if bull_trend and trend_strong and above_both and bull_breakout and rsi_buy_ok:
            indicators["trigger"] = "BREAKOUT_5C"
            indicators["suggested_sl"] = round(c1 - curr_atr * 2, 5)
            indicators["suggested_tp"] = round(c1 + curr_atr * 4, 5)
            return {"model": self.name, "vote": "BUY", "confidence": 0.90,
                    "reasoning": f"5/5 BUY: EMA trend, sep={ema_separation:.5f}, above EMAs, broke {lookback}-bar high {n_bar_high:.5f}, RSI={curr_rsi:.1f}",
                    "indicators": indicators}

        if bear_trend and trend_strong and below_both and bear_breakout and rsi_sell_ok:
            indicators["trigger"] = "BREAKOUT_5C"
            indicators["suggested_sl"] = round(c1 + curr_atr * 2, 5)
            indicators["suggested_tp"] = round(c1 - curr_atr * 4, 5)
            return {"model": self.name, "vote": "SELL", "confidence": 0.90,
                    "reasoning": f"5/5 SELL: EMA trend, sep={ema_separation:.5f}, below EMAs, broke {lookback}-bar low {n_bar_low:.5f}, RSI={curr_rsi:.1f}",
                    "indicators": indicators}

        # Fallback: EMA pullback
        ema_f_now = float(ema_fast[-1])
        ema_s_now = float(ema_slow[-1])
        close_now = float(closes[-1])
        close_prev = float(closes[-2])
        rsi_now = float(rsi_vals[-1]) if not np.isnan(rsi_vals[-1]) else 50.0

        if ema_f_now > ema_s_now and close_prev <= ema_f_now * 1.002 and close_now > ema_f_now and 40 < rsi_now < 70:
            indicators["trigger"] = "EMA_PULLBACK"
            return {"model": self.name, "vote": "BUY", "confidence": 0.65,
                    "reasoning": f"EMA pullback BUY: close {close_now:.5f} reclaimed EMA50 {ema_f_now:.5f}, RSI={rsi_now:.1f}",
                    "indicators": indicators}
        if ema_f_now < ema_s_now and close_prev >= ema_f_now * 0.998 and close_now < ema_f_now and 30 < rsi_now < 60:
            indicators["trigger"] = "EMA_PULLBACK"
            return {"model": self.name, "vote": "SELL", "confidence": 0.65,
                    "reasoning": f"EMA pullback SELL: close {close_now:.5f} rejected EMA50 {ema_f_now:.5f}, RSI={rsi_now:.1f}",
                    "indicators": indicators}

        failed = []
        if not (bull_trend or bear_trend): failed.append("no_trend")
        if not trend_strong: failed.append("weak_sep")
        if not (above_both or below_both): failed.append("mixed_ema")
        if not (bull_breakout or bear_breakout): failed.append("no_breakout")
        if not (rsi_buy_ok or rsi_sell_ok): failed.append("rsi_zone")
        indicators["hold_reason"] = ",".join(failed) if failed else "unknown"

        return self._hold(f"{conditions_met}/5 conditions met ({', '.join(failed)}).", indicators=indicators)

    def _hold(self, reasoning, indicators=None):
        return {"model": self.name, "vote": "HOLD", "confidence": 0.5, "reasoning": reasoning, "indicators": indicators or {}}
