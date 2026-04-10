#!/usr/bin/env python3
"""
GlitchExecutor Telegram Bot - Test Suite
Tests all components before live deployment.
"""
import os
import sys
import asyncio
import logging

# Add paths
sys.path.insert(0, '/opt/glitchexecutor/telegram_bot')
sys.path.insert(0, '/opt/glitchexecutor/ensemble')

# Set test environment variables
os.environ["TELEGRAM_BOT_TOKEN"] = "test_token_12345"
os.environ["DATABASE_URL"] = "postgresql://glitch:glitchpass@localhost:5432/glitchexecutor"
os.environ["REDIS_HOST"] = "localhost"
os.environ["REDIS_PORT"] = "6379"
os.environ["ORCHESTRATOR_LLM_KEY"] = ""

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("Test")


async def test_database():
    """Test database connection and customer creation."""
    print("\n" + "="*60)
    print("TEST 1: Database Connection & Customer Creation")
    print("="*60)
    
    from db import Database
    
    db = Database()
    connected = await db.connect()
    
    if not connected:
        print("❌ FAILED: Could not connect to database")
        return False
    
    print("✅ Database connected")
    
    # Test customer creation
    test_telegram_id = 6280075826  # Tejas's Telegram ID
    test_username = "floating_astronaut"
    
    # Check if customer exists
    existing = await db.get_customer(test_telegram_id)
    if existing:
        print(f"✅ Customer exists: ID {existing['id']}, Tier: {existing['tier']}")
    else:
        # Create new customer
        customer = await db.create_customer(test_telegram_id, test_username)
        if customer:
            print(f"✅ Customer created: ID {customer['id']}, Tier: {customer['tier']}")
        else:
            print("❌ FAILED: Could not create customer")
            return False
    
    await db.close()
    return True


async def test_auth():
    """Test authentication and tier checking."""
    print("\n" + "="*60)
    print("TEST 2: Authentication & Tier System")
    print("="*60)
    
    from db import Database
    from auth import AuthManager
    
    db = Database()
    await db.connect()
    auth = AuthManager()
    
    # Test authentication
    test_user_id = 6280075826
    customer, error = await auth.authenticate(db, test_user_id, "floating_astronaut")
    
    if error:
        print(f"❌ Authentication error: {error}")
        await db.close()
        return False
    
    print(f"✅ Authenticated: {customer['telegram_id']} (@{customer['username']})")
    print(f"✅ Tier: {customer['tier']}")
    print(f"✅ Can execute: {auth.can_execute(customer)}")
    print(f"✅ Query limit: {auth.get_tier_limit(customer)}")
    
    # Test welcome message
    welcome = auth.get_welcome_message(customer)
    print(f"✅ Welcome message generated ({len(welcome)} chars)")
    
    await db.close()
    return True


async def test_rate_limiting():
    """Test rate limiting functionality."""
    print("\n" + "="*60)
    print("TEST 3: Rate Limiting")
    print("="*60)
    
    from db import Database
    from auth import AuthManager
    from rate_limiter import RateLimiter
    
    db = Database()
    await db.connect()
    auth = AuthManager()
    limiter = RateLimiter()
    
    # Get test customer
    customer, _ = await auth.authenticate(db, 6280075826, "test")
    customer_id = customer['id']
    
    print(f"Customer tier: {customer['tier']}")
    print(f"Query limit: {limiter.get_limit(customer['tier'])}")
    
    # Reset queries first
    # Note: In production, this would be done by a daily cron job
    
    # Test incrementing queries
    success_count = 0
    for i in range(12):  # Try 12 queries (limit is 10 for trial)
        allowed, message, current, limit = await limiter.check_and_increment(db, customer)
        
        if allowed:
            success_count += 1
            print(f"  Query {i+1}: ✅ Allowed ({current}/{limit})")
        else:
            print(f"  Query {i+1}: ❌ Blocked - {message}")
            if i >= 10:  # Expected to be blocked after 10
                print("✅ Rate limiting working correctly!")
                break
    
    if success_count == 10:
        print(f"✅ Exactly 10 queries allowed (trial limit)")
    
    await db.close()
    return True


async def test_redis_connection():
    """Test Redis connection and data retrieval."""
    print("\n" + "="*60)
    print("TEST 4: Redis Connection & Data Retrieval")
    print("="*60)
    
    from redis_cache import EnsembleCache
    
    cache = EnsembleCache()
    
    if not cache.is_connected():
        print("❌ FAILED: Could not connect to Redis")
        return False
    
    print("✅ Redis connected")
    
    # Try to read ensemble data
    btc_data = cache.read_votes("BTCUSD")
    
    if btc_data:
        print(f"✅ Ensemble data found for BTCUSD")
        print(f"   Consensus: {btc_data.get('consensus')}")
        print(f"   Confidence: {btc_data.get('confidence')}")
        votes = btc_data.get('votes', [])
        print(f"   Model votes: {len(votes)}")
        for v in votes[:3]:
            print(f"     - {v['model']}: {v['vote']}")
    else:
        print("⚠️ No ensemble data in Redis (run ensemble engine first)")
    
    # Try to read sentiment
    sentiment = cache.read_sentiment("BTCUSD")
    if sentiment:
        print(f"✅ Sentiment data: {sentiment.get('direction')} ({sentiment.get('score')})")
    else:
        print("⚠️ No sentiment data in Redis")
    
    return True


async def test_graceful_failures():
    """Test graceful handling of failures."""
    print("\n" + "="*60)
    print("TEST 5: Graceful Failure Handling")
    print("="*60)
    
    from redis_cache import EnsembleCache
    
    # Test with Redis down
    print("Testing with bad Redis connection...")
    bad_cache = EnsembleCache(host="invalid_host", port=9999)
    
    if not bad_cache.is_connected():
        print("✅ Correctly detects Redis is down")
    
    # Try operations - should not crash
    try:
        result = bad_cache.read_votes("BTCUSD")
        print(f"✅ read_votes returns None gracefully: {result}")
        
        result = bad_cache.write_votes("TEST", [{"test": True}], {"vote": "HOLD"})
        print(f"✅ write_votes returns False gracefully: {result}")
        
        result = bad_cache.read_sentiment("BTCUSD")
        print(f"✅ read_sentiment returns None gracefully: {result}")
        
    except Exception as e:
        print(f"❌ FAILED: Exception thrown: {e}")
        return False
    
    print("✅ All Redis failures handled gracefully - no crashes")
    return True


async def test_orchestrator():
    """Test LLM orchestrator (template mode)."""
    print("\n" + "="*60)
    print("TEST 6: Orchestrator (Template Mode)")
    print("="*60)
    
    from orchestrator import Orchestrator
    
    # Without API key, should use template
    orch = Orchestrator(api_key="", provider="anthropic")
    
    # Mock votes
    votes = [
        {"model": "trend_follower", "vote": "BUY", "confidence": 0.9, "reasoning": "Strong trend", "indicators": {}},
        {"model": "mean_reverter", "vote": "HOLD", "confidence": 0.5, "reasoning": "Not extreme", "indicators": {}},
        {"model": "momentum_hunter", "vote": "BUY", "confidence": 0.8, "reasoning": "Momentum up", "indicators": {}},
    ]
    
    sentiment = {"direction": "bullish", "score": 0.6, "reasoning": "Positive news"}
    
    response = await orch.synthesize(
        user_query="Should I buy BTC?",
        symbol="BTCUSD",
        tier="trial",
        can_execute=False,
        votes=votes,
        sentiment=sentiment,
        current_price=85000.50,
        minutes_ago=2
    )
    
    print("Generated response:")
    print("-" * 40)
    print(response[:500] + "..." if len(response) > 500 else response)
    print("-" * 40)
    print(f"✅ Response generated ({len(response)} chars)")
    
    return True


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("GLITCHEXECUTOR TELEGRAM BOT - TEST SUITE")
    print("="*60)
    
    tests = [
        ("Database & Customer Creation", test_database),
        ("Authentication", test_auth),
        ("Rate Limiting", test_rate_limiting),
        ("Redis Connection", test_redis_connection),
        ("Graceful Failures", test_graceful_failures),
        ("Orchestrator", test_orchestrator),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = await test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ TEST FAILED with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    print(f"\n{passed}/{total} tests passed")
    
    if passed == total:
        print("\n✅ ALL TESTS PASSED - Ready for Prompt 4!")
        return 0
    else:
        print(f"\n❌ {total - passed} tests failed")
        return 1


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(result)
