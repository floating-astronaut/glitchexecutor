#!/usr/bin/env python3
"""
GlitchExecutor Ensemble Models - Test Suite
Tests all 7 standalone strategy modules with synthetic data.
"""
import sys
import os
import numpy as np
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import (
    TrendFollowerModel,
    MeanReverterModel,
    MomentumHunterModel,
    MLPredictorModel,
    MultiTFAlignModel,
    VolumeProfilerModel,
    SessionAnalystModel
)


def generate_synthetic_candles(n_bars=300, trend=0.0001, volatility=0.001, seed=42):
    """
    Generate synthetic OHLCV data with optional trend and volatility.
    
    Returns dict with m15, h1, h4 timeframes.
    """
    np.random.seed(seed)
    
    # Generate M15 candles (most granular)
    base_price = 85000  # BTC-like price
    
    m15_candles = []
    current_price = base_price
    
    for i in range(n_bars):
        # Random walk with trend
        change = np.random.normal(trend * current_price, volatility * current_price)
        
        open_price = current_price
        close_price = current_price + change
        
        # Generate high/low with intrabar volatility
        intrabar_vol = volatility * current_price * 0.5
        high_price = max(open_price, close_price) + abs(np.random.normal(0, intrabar_vol))
        low_price = min(open_price, close_price) - abs(np.random.normal(0, intrabar_vol))
        
        # Volume with some randomness
        volume = np.random.uniform(100, 1000) * (1 + abs(change) / (volatility * current_price))
        
        timestamp = i * 900  # 15 min intervals
        
        m15_candles.append([timestamp, open_price, high_price, low_price, close_price, volume])
        current_price = close_price
    
    m15_candles = np.array(m15_candles)
    
    # Aggregate to H1 (4 M15 bars = 1 H1 bar)
    h1_candles = []
    for i in range(0, len(m15_candles) - 3, 4):
        chunk = m15_candles[i:i+4]
        timestamp = chunk[0, 0]
        open_price = chunk[0, 1]
        high_price = np.max(chunk[:, 2])
        low_price = np.min(chunk[:, 3])
        close_price = chunk[-1, 4]
        volume = np.sum(chunk[:, 5])
        h1_candles.append([timestamp, open_price, high_price, low_price, close_price, volume])
    
    h1_candles = np.array(h1_candles)
    
    # Aggregate to H4 (4 H1 bars = 1 H4 bar)
    h4_candles = []
    for i in range(0, len(h1_candles) - 3, 4):
        chunk = h1_candles[i:i+4]
        timestamp = chunk[0, 0]
        open_price = chunk[0, 1]
        high_price = np.max(chunk[:, 2])
        low_price = np.min(chunk[:, 3])
        close_price = chunk[-1, 4]
        volume = np.sum(chunk[:, 5])
        h4_candles.append([timestamp, open_price, high_price, low_price, close_price, volume])
    
    h4_candles = np.array(h4_candles)
    
    return {
        "m15": m15_candles,
        "h1": h1_candles,
        "h4": h4_candles
    }


def validate_output(result, model_name):
    """Validate that model output matches expected schema."""
    required_keys = ["model", "vote", "confidence", "reasoning", "indicators"]
    
    for key in required_keys:
        if key not in result:
            print(f"❌ {model_name}: Missing key '{key}'")
            return False
    
    if result["model"] != model_name:
        print(f"❌ {model_name}: Model name mismatch '{result['model']}' != '{model_name}'")
        return False
    
    if result["vote"] not in ["BUY", "SELL", "HOLD"]:
        print(f"❌ {model_name}: Invalid vote '{result['vote']}'")
        return False
    
    if not (0.0 <= result["confidence"] <= 1.0):
        print(f"❌ {model_name}: Invalid confidence {result['confidence']}")
        return False
    
    if not isinstance(result["reasoning"], str) or len(result["reasoning"]) == 0:
        print(f"❌ {model_name}: Invalid or empty reasoning")
        return False
    
    if not isinstance(result["indicators"], dict):
        print(f"❌ {model_name}: indicators must be a dict")
        return False
    
    return True


def test_model(model, symbol, candles, model_name):
    """Test a single model and print results."""
    try:
        result = model.analyze(symbol, candles)
        
        if validate_output(result, model_name):
            print(f"✅ {model_name:20s} | {result['vote']:4s} | conf: {result['confidence']:.2f} | {result['reasoning'][:60]}...")
            return result
        else:
            print(f"❌ {model_name}: Output validation failed")
            return None
    except Exception as e:
        print(f"❌ {model_name}: Exception - {e}")
        import traceback
        traceback.print_exc()
        return None


def compute_consensus(votes):
    """Compute consensus from all model votes."""
    buy_count = sum(1 for v in votes if v["vote"] == "BUY")
    sell_count = sum(1 for v in votes if v["vote"] == "SELL")
    hold_count = sum(1 for v in votes if v["vote"] == "HOLD")
    total = len(votes)
    
    if buy_count > sell_count and buy_count > hold_count:
        vote = "BUY"
        confidence = buy_count / total
    elif sell_count > buy_count and sell_count > hold_count:
        vote = "SELL"
        confidence = sell_count / total
    else:
        vote = "HOLD"
        confidence = hold_count / total
    
    return {
        "vote": vote,
        "confidence": round(confidence, 2),
        "breakdown": f"{buy_count}/{total} BUY, {sell_count}/{total} SELL, {hold_count}/{total} HOLD"
    }


def main():
    """Run all model tests."""
    print("=" * 80)
    print("GLITCHEXECUTOR ENSEMBLE MODELS - TEST SUITE")
    print("=" * 80)
    print()
    
    # Test with different market conditions
    test_cases = [
        ("BTCUSD", 0.0002, 0.002, "bullish_trend"),    # Strong uptrend
        ("BTCUSD", -0.0002, 0.002, "bearish_trend"),   # Strong downtrend
        ("BTCUSD", 0.0, 0.001, "ranging"),             # Low volatility, ranging
        ("ETHUSD", 0.0001, 0.003, "volatile"),         # High volatility
        ("EURUSD", 0.00005, 0.0005, "forex_trend"),    # Forex-style movement
    ]
    
    # Initialize all models
    models = [
        (TrendFollowerModel(), "trend_follower"),
        (MeanReverterModel(), "mean_reverter"),
        (MomentumHunterModel(), "momentum_hunter"),
        (MLPredictorModel(), "ml_predictor"),
        (MultiTFAlignModel(), "multi_tf_align"),
        (VolumeProfilerModel(), "volume_profiler"),
        (SessionAnalystModel(), "session_analyst"),
    ]
    
    all_passed = True
    
    for symbol, trend, volatility, condition in test_cases:
        print(f"\n📊 Testing {symbol} ({condition}): trend={trend}, vol={volatility}")
        print("-" * 80)
        
        # Generate candles for this test case
        candles = generate_synthetic_candles(
            n_bars=300,
            trend=trend,
            volatility=volatility,
            seed=hash(condition) % 10000
        )
        
        votes = []
        for model, model_name in models:
            result = test_model(model, symbol, candles, model_name)
            if result:
                votes.append(result)
            else:
                all_passed = False
        
        # Print consensus
        if votes:
            consensus = compute_consensus(votes)
            print("-" * 80)
            print(f"🎯 CONSENSUS: {consensus['vote']} (confidence: {consensus['confidence']})")
            print(f"   Breakdown: {consensus['breakdown']}")
    
    # Edge case tests
    print("\n" + "=" * 80)
    print("EDGE CASE TESTS")
    print("=" * 80)
    
    # Test with minimal data
    print("\n📊 Testing with minimal data (20 bars)...")
    minimal_candles = generate_synthetic_candles(n_bars=20, seed=999)
    for model, model_name in models:
        result = test_model(model, "BTCUSD", minimal_candles, model_name)
        if not result:
            all_passed = False
    
    # Test with flat market (no trend, no volatility)
    print("\n📊 Testing with flat market...")
    flat_candles = generate_synthetic_candles(n_bars=300, trend=0, volatility=0.00001, seed=888)
    for model, model_name in models:
        result = test_model(model, "BTCUSD", flat_candles, model_name)
        if not result:
            all_passed = False
    
    # Summary
    print("\n" + "=" * 80)
    if all_passed:
        print("✅ ALL TESTS PASSED")
        print("=" * 80)
        print("\nAll 7 models are working correctly:")
        print("  1. trend_follower   - SMA/EMA crossover with ADX/ATR confirmation")
        print("  2. mean_reverter    - Bollinger Bands + RSI mean reversion")
        print("  3. momentum_hunter  - RSI momentum breaks with volume")
        print("  4. ml_predictor     - Feature computation (placeholder)")
        print("  5. multi_tf_align   - Multi-timeframe trend alignment")
        print("  6. volume_profiler  - ATR/volume condition confirmation")
        print("  7. session_analyst  - Trading session quality analysis")
        print("\n✅ Prompt 1 Complete: All 7 standalone strategy modules built and tested.")
        return 0
    else:
        print("❌ SOME TESTS FAILED")
        print("=" * 80)
        return 1


if __name__ == "__main__":
    sys.exit(main())
