-- GlitchExecutor Database Initialization
-- Run automatically by PostgreSQL container on first start

-- Customers table
CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    username VARCHAR(100),
    token UUID DEFAULT gen_random_uuid(),
    tier VARCHAR(20) DEFAULT 'trial',
    status VARCHAR(20) DEFAULT 'trial',
    trial_ends_at TIMESTAMP DEFAULT (NOW() + INTERVAL '7 days'),
    created_at TIMESTAMP DEFAULT NOW(),
    queries_today INT DEFAULT 0,
    query_reset_at TIMESTAMP DEFAULT (NOW() + INTERVAL '1 day'),
    stripe_customer_id VARCHAR(100),
    stripe_subscription_id VARCHAR(100),
    stripe_price_id VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_customers_stripe ON customers(stripe_customer_id);
CREATE INDEX IF NOT EXISTS idx_customers_username ON customers(username);

-- Exchange API keys (encrypted)
CREATE TABLE IF NOT EXISTS exchange_keys (
    id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customers(id) ON DELETE CASCADE,
    exchange VARCHAR(20) NOT NULL,
    api_key_enc BYTEA NOT NULL,
    api_secret_enc BYTEA NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Trades log
CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customers(id),
    symbol VARCHAR(20) NOT NULL,
    direction VARCHAR(4) NOT NULL,
    entry_price DECIMAL(20,8),
    sl_price DECIMAL(20,8),
    tp_price DECIMAL(20,8),
    volume DECIMAL(10,4),
    ensemble_vote VARCHAR(100),
    status VARCHAR(20) DEFAULT 'pending',
    pnl DECIMAL(20,8),
    executed_at TIMESTAMP DEFAULT NOW(),
    closed_at TIMESTAMP
);

-- Query analytics log
CREATE TABLE IF NOT EXISTS query_log (
    id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customers(id),
    symbol VARCHAR(20),
    query_text TEXT,
    response_type VARCHAR(20),
    llm_cost_usd DECIMAL(8,4),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_customers_telegram ON customers(telegram_id);
CREATE INDEX IF NOT EXISTS idx_trades_customer ON trades(customer_id);
CREATE INDEX IF NOT EXISTS idx_queries_customer ON query_log(customer_id);
CREATE INDEX IF NOT EXISTS idx_queries_date ON query_log(created_at);

-- Success indicator
SELECT 'GlitchExecutor database initialized successfully' as result;
