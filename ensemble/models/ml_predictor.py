"""
GlitchExecutor Model 4: ML Predictor
Loads trained LightGBM/XGBoost classifiers from the Windows VM transfer package.
Binary classifier: 0=LOSS, 1=WIN. 44-feature schema with one-hot categoricals.

LightGBM accuracy: 79.1% | XGBoost accuracy: 74.7%
Top SHAP features: ADX (1.62), RSI (0.54), SL/entry price, ATR, volume_ratio
"""
import os
import logging
import pickle
import numpy as np
from typing import Dict, Any
from datetime import datetime, timezone
from .base_model import BaseModel
from .indicators import ema, adx, atr, rsi, bollinger_bands

logger = logging.getLogger("MLPredictor")

# The 44-feature schema the trained models expect (exact order matters)
_FEATURE_NAMES = [
    'confidence', 'atr', 'entry_price', 'sl_price', 'tp_price',
    'rsi', 'adx', 'spread', 'volume_ratio', 'price_position_in_bb',
    'ml_confidence',
    # One-hot: bot (8 categories + nan)
    'bot_anaconda', 'bot_cobra', 'bot_hydra', 'bot_king_cobra',
    'bot_mamba', 'bot_taipan', 'bot_viper', 'bot_nan',
    # One-hot: symbol (8 categories + nan)
    'symbol_BTCUSD', 'symbol_EURUSD', 'symbol_GBPJPY', 'symbol_SOLUSD',
    'symbol_USDJPY', 'symbol_USOUSD', 'symbol_WTICASH-1', 'symbol_XAUUSD', 'symbol_nan',
    # One-hot: direction (3 categories + nan)
    'direction_BUY', 'direction_SELL', 'direction_TRADE_CLOSED', 'direction_nan',
    # One-hot: trigger (1 category + nan)
    'trigger_OUTCOME', 'trigger_nan',
    # One-hot: regime (nan only)
    'regime_nan',
    # One-hot: session_phase (3 categories + nan)
    'session_phase_Asian', 'session_phase_London', 'session_phase_New_York', 'session_phase_nan',
    # One-hot: h1_trend (3 categories + nan)
    'h1_trend_BOTH', 'h1_trend_BUY', 'h1_trend_SELL', 'h1_trend_nan',
    # One-hot: news_sentiment (nan only)
    'news_sentiment_nan',
]

# Symbol name mapping for one-hot encoding
_SYMBOL_MAP = {
    'BTCUSD': 'symbol_BTCUSD', 'BTC/USDT': 'symbol_BTCUSD',
    'EURUSD': 'symbol_EURUSD',
    'GBPJPY': 'symbol_GBPJPY',
    'SOLUSD': 'symbol_SOLUSD', 'SOL/USDT': 'symbol_SOLUSD',
    'USDJPY': 'symbol_USDJPY',
    'USOUSD': 'symbol_USOUSD',
    'WTICASH-1': 'symbol_WTICASH-1',
    'XAUUSD': 'symbol_XAUUSD',
}


def _get_session_phase() -> str:
    """Determine current trading session from UTC hour."""
    hour = datetime.now(timezone.utc).hour
    if 0 <= hour < 7:
        return 'Asian'
    elif 7 <= hour < 12:
        return 'London'
    elif 12 <= hour < 21:
        return 'New_York'
    return 'Asian'


class MLPredictorModel(BaseModel):
    """
    ML-based WIN/LOSS prediction model.
    Uses trained LightGBM (primary) or XGBoost (fallback) classifiers.
    """

    name = "ml_predictor"
    version = "2.0"
    active = True  # ACTIVATED — trained models loaded from Windows VM transfer

    def __init__(self):
        self.lgbm_model = None
        self.xgb_model = None
        self.feature_names = _FEATURE_NAMES
        self._load_models()

    def _load_models(self):
        """Load trained models from disk."""
        model_dir = os.environ.get("ML_MODEL_DIR", "/app/ml_models")
        # Also check local paths for development
        search_paths = [
            model_dir,
            "/opt/glitchexecutor/ensemble/ml_models",
            os.path.join(os.path.dirname(__file__), '..', 'ml_models'),
        ]

        for base in search_paths:
            lgbm_path = os.path.join(base, 'lightgbm_classifier.pkl')
            xgb_path = os.path.join(base, 'xgboost_classifier.pkl')

            if os.path.exists(lgbm_path) and self.lgbm_model is None:
                try:
                    with open(lgbm_path, 'rb') as f:
                        data = pickle.load(f)
                    self.lgbm_model = data['model']
                    logger.info(f"LightGBM classifier loaded from {lgbm_path} (79.1% accuracy)")
                except Exception as e:
                    logger.error(f"Failed to load LightGBM model: {e}")

            if os.path.exists(xgb_path) and self.xgb_model is None:
                try:
                    with open(xgb_path, 'rb') as f:
                        data = pickle.load(f)
                    self.xgb_model = data['model']
                    logger.info(f"XGBoost classifier loaded from {xgb_path} (74.7% accuracy)")
                except Exception as e:
                    logger.error(f"Failed to load XGBoost model: {e}")

            if self.lgbm_model and self.xgb_model:
                break

        if not self.lgbm_model and not self.xgb_model:
            logger.warning("No ML models found — ml_predictor will return HOLD")
            self.active = False

    def analyze(self, symbol: str, candles: Dict[str, np.ndarray]) -> Dict[str, Any]:
        """Compute features and run ML inference."""
        h1_candles = candles.get("h1")
        m15_candles = candles.get("m15")

        if h1_candles is None or len(h1_candles) < 50:
            return self._hold("Insufficient H1 data for ML features.")

        # Extract OHLCV from H1
        _, highs, lows, closes, volumes = self._extract_ohlcv(h1_candles)
        if closes is None or len(closes) < 50:
            return self._hold("Invalid close price data.")

        # Compute technical indicators
        current_close = float(closes[-1])
        atr_vals = atr(highs, lows, closes, 14)
        curr_atr = float(atr_vals[-1]) if not np.isnan(atr_vals[-1]) else 0.0
        adx_vals = adx(highs, lows, closes, 14)
        curr_adx = float(adx_vals[-1])
        rsi_vals = rsi(closes, 14)
        curr_rsi = float(rsi_vals[-1]) if not np.isnan(rsi_vals[-1]) else 50.0

        # Bollinger Bands for price position
        bb_upper, bb_mid, bb_lower = bollinger_bands(closes, 20, 2.0)
        bb_range = float(bb_upper[-1]) - float(bb_lower[-1])
        price_pos_bb = (current_close - float(bb_lower[-1])) / bb_range if bb_range > 0 else 0.5

        # Volume ratio
        vol_avg = float(np.mean(volumes[-50:])) if len(volumes) >= 50 else float(np.mean(volumes))
        vol_ratio = float(volumes[-1]) / vol_avg if vol_avg > 0 else 1.0

        # Spread (high-low of last bar)
        spread = float(highs[-1] - lows[-1])

        # H1 trend direction from EMA(50)
        h1_ema50 = ema(closes, 50)
        h1_trend = 'BUY' if current_close > float(h1_ema50[-1]) else 'SELL'

        # Session phase
        session = _get_session_phase()

        # Build the 44-feature vector (all zeros, then fill in)
        feature_vec = np.zeros(44, dtype=float)

        # Numeric features (indices 0-10)
        feature_vec[0] = 0.75          # confidence (ensemble confidence placeholder)
        feature_vec[1] = curr_atr      # atr
        feature_vec[2] = current_close  # entry_price (current price as proxy)
        feature_vec[3] = current_close - curr_atr * 1.5  # sl_price (proxy)
        feature_vec[4] = current_close + curr_atr * 3.0  # tp_price (proxy)
        feature_vec[5] = curr_rsi      # rsi
        feature_vec[6] = curr_adx      # adx
        feature_vec[7] = spread        # spread
        feature_vec[8] = vol_ratio     # volume_ratio
        feature_vec[9] = price_pos_bb  # price_position_in_bb
        feature_vec[10] = 0.0          # ml_confidence (not applicable for live)

        # One-hot: bot — set bot_nan since this is ensemble (not a specific bot)
        feature_vec[18] = 1.0  # bot_nan

        # One-hot: symbol
        sym_col = _SYMBOL_MAP.get(symbol.upper())
        if sym_col and sym_col in _FEATURE_NAMES:
            feature_vec[_FEATURE_NAMES.index(sym_col)] = 1.0
        else:
            feature_vec[_FEATURE_NAMES.index('symbol_nan')] = 1.0

        # One-hot: direction — we don't know direction yet, set nan
        feature_vec[_FEATURE_NAMES.index('direction_nan')] = 1.0

        # One-hot: trigger — set nan (no specific trigger)
        feature_vec[_FEATURE_NAMES.index('trigger_nan')] = 1.0

        # One-hot: regime — set nan
        feature_vec[_FEATURE_NAMES.index('regime_nan')] = 1.0

        # One-hot: session_phase
        session_col = f'session_phase_{session}'
        if session_col in _FEATURE_NAMES:
            feature_vec[_FEATURE_NAMES.index(session_col)] = 1.0
        else:
            feature_vec[_FEATURE_NAMES.index('session_phase_nan')] = 1.0

        # One-hot: h1_trend
        h1_trend_col = f'h1_trend_{h1_trend}'
        if h1_trend_col in _FEATURE_NAMES:
            feature_vec[_FEATURE_NAMES.index(h1_trend_col)] = 1.0
        else:
            feature_vec[_FEATURE_NAMES.index('h1_trend_nan')] = 1.0

        # One-hot: news_sentiment — set nan
        feature_vec[_FEATURE_NAMES.index('news_sentiment_nan')] = 1.0

        # Run inference
        model = self.lgbm_model or self.xgb_model
        model_name = "LightGBM" if self.lgbm_model else "XGBoost"

        if model is None:
            return self._hold("No ML model loaded.")

        try:
            X = feature_vec.reshape(1, -1)
            proba = model.predict_proba(X)[0]  # [p_loss, p_win]
            p_win = float(proba[1])
            p_loss = float(proba[0])

            # Decision logic:
            # p_win > 0.60 → BUY (lean bullish since model was trained on executed trades)
            # p_loss > 0.60 → SELL (market unfavorable)
            # Otherwise → HOLD
            if p_win >= 0.60:
                vote = "BUY"
                confidence = min(p_win, 0.95)
                reasoning = (f"{model_name}: {p_win:.1%} win probability. "
                            f"ADX={curr_adx:.1f}, RSI={curr_rsi:.1f}, vol_ratio={vol_ratio:.2f}")
            elif p_loss >= 0.60:
                vote = "SELL"
                confidence = min(p_loss, 0.95)
                reasoning = (f"{model_name}: {p_loss:.1%} loss probability (bearish). "
                            f"ADX={curr_adx:.1f}, RSI={curr_rsi:.1f}, vol_ratio={vol_ratio:.2f}")
            else:
                vote = "HOLD"
                confidence = 0.5
                reasoning = (f"{model_name}: uncertain (win={p_win:.1%}, loss={p_loss:.1%}). "
                            f"ADX={curr_adx:.1f}, RSI={curr_rsi:.1f}")

            indicators = {
                "status": "live_inference",
                "model_used": model_name,
                "p_win": round(p_win, 4),
                "p_loss": round(p_loss, 4),
                "adx": round(curr_adx, 2),
                "rsi": round(curr_rsi, 2),
                "atr": round(curr_atr, 5),
                "volume_ratio": round(vol_ratio, 2),
                "price_position_in_bb": round(price_pos_bb, 3),
                "h1_trend": h1_trend,
                "session": session,
            }

            return {
                "model": self.name,
                "vote": vote,
                "confidence": round(confidence, 2),
                "reasoning": reasoning,
                "indicators": indicators,
            }

        except Exception as e:
            logger.error(f"ML inference failed: {e}")
            return self._hold(f"ML inference error: {e}")

    def _hold(self, reasoning: str) -> Dict[str, Any]:
        return {
            "model": self.name,
            "vote": "HOLD",
            "confidence": 0.5,
            "reasoning": reasoning,
            "indicators": {"status": "error_or_no_model"},
        }
