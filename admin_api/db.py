import os
import sqlite3
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "")
ML_DATABASE_URL = os.environ.get("ML_DATABASE_URL", "")
SQLITE_PATH = os.environ.get("SQLITE_PATH", "/data/trades.db")


def get_pg():
    """Return a new psycopg2 connection (caller must close)."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def get_ml_pg():
    """Return a read-only psycopg2 connection to the Ouroboros (glitch_ml) DB.
    Used by /api/trade/* endpoints. Caller must close."""
    if not ML_DATABASE_URL:
        raise RuntimeError("ML_DATABASE_URL not configured")
    return psycopg2.connect(ML_DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def get_sqlite():
    """Return a read-only sqlite3 connection to the MT5 trades DB."""
    conn = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def run_migrations():
    """Create tables required by admin_api (idempotent)."""
    import time
    # Retry connection — container may start before Docker DNS resolves
    for attempt in range(12):
        try:
            _test = get_pg()
            _test.close()
            break
        except Exception as exc:
            if attempt >= 11:
                raise
            wait = min(2 ** attempt, 15)
            print(f"[db] postgres not ready (attempt {attempt + 1}/12), retrying in {wait}s: {exc}")
            time.sleep(wait)

    conn = get_pg()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'admin',
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            last_login TIMESTAMPTZ
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id SERIAL PRIMARY KEY,
            admin_user_id INT REFERENCES admin_users(id),
            action TEXT NOT NULL,
            target_type TEXT,
            target_id TEXT,
            details JSONB,
            ip_address TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    # ── Bot trading tables ─────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_heartbeats (
            bot         TEXT PRIMARY KEY,
            account     INTEGER,
            iteration   INTEGER,
            last_seen   TIMESTAMPTZ DEFAULT NOW(),
            details     JSONB
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_positions (
            id          SERIAL PRIMARY KEY,
            bot         TEXT NOT NULL,
            account     INTEGER,
            symbol      TEXT NOT NULL,
            direction   TEXT,
            trigger     TEXT,
            strategy    TEXT,
            entry_price REAL,
            sl          REAL,
            tp          REAL,
            volume      REAL,
            timeframe   TEXT,
            confidence  REAL,
            rsi         REAL,
            atr         REAL,
            h1_trend    TEXT,
            adx         REAL,
            ticket      INTEGER,
            trail_count INTEGER DEFAULT 0,
            is_open     BOOLEAN DEFAULT TRUE,
            exit_reason TEXT,
            exit_rsi    REAL,
            opened_at   TIMESTAMPTZ,
            closed_at   TIMESTAMPTZ,
            received_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_bot_pos_open
        ON bot_positions(is_open, bot)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_bot_pos_ticket
        ON bot_positions(ticket) WHERE ticket IS NOT NULL
    """)
    # Idempotent column additions (safe to run on existing tables)
    cursor.execute("""
        ALTER TABLE bot_positions
            ADD COLUMN IF NOT EXISTS sl_updated_at TIMESTAMPTZ
    """)
    cursor.execute("""
        ALTER TABLE bot_positions
            ADD COLUMN IF NOT EXISTS details JSONB
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_events (
            id              SERIAL PRIMARY KEY,
            bot             TEXT NOT NULL,
            event_type      TEXT NOT NULL,
            account         INTEGER,
            symbol          TEXT,
            ticket          INTEGER,
            trigger         TEXT,
            direction       TEXT,
            entry_price     REAL,
            old_sl          REAL,
            new_sl          REAL,
            rsi             REAL,
            details         JSONB,
            event_timestamp TEXT,
            received_at     TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_bot_events_recv
        ON bot_events(received_at DESC)
    """)
    # ── Oracle coordinator tables ──────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS oracle_alerts (
            id          SERIAL PRIMARY KEY,
            event_type  TEXT NOT NULL,
            severity    TEXT NOT NULL DEFAULT 'warning',
            message     TEXT DEFAULT '',
            details     JSONB,
            dismissed   BOOLEAN DEFAULT FALSE,
            received_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_oracle_alerts_recv
        ON oracle_alerts(received_at DESC)
    """)
    conn.commit()
    cursor.close()
    conn.close()
    print("[db] Migrations complete")


def log_audit(admin_email: str, action: str, target_type: str = None,
              target_id: str = None, details: dict = None, ip: str = None):
    """Write an audit log entry."""
    try:
        conn = get_pg()
        cur = conn.cursor()
        cur.execute("SELECT id FROM admin_users WHERE email=%s", (admin_email,))
        row = cur.fetchone()
        admin_id = row["id"] if row else None
        import json
        cur.execute(
            """INSERT INTO audit_log (admin_user_id, action, target_type, target_id, details, ip_address)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (admin_id, action, target_type, target_id,
             json.dumps(details) if details else None, ip)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[audit] Failed to log: {e}")
