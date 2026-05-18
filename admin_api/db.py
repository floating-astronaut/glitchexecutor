import os
import sqlite3
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "")
ML_DATABASE_URL = os.environ.get("ML_DATABASE_URL", "")
SA_DATABASE_URL = os.environ.get("SA_DATABASE_URL", "")
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


def get_sa_pg():
    """Return a read-only psycopg2 connection to the Sales Agent
    (glitch_sales_agent / Glitch Budz) DB. Used by /api/grow/budz/*."""
    if not SA_DATABASE_URL:
        raise RuntimeError("SA_DATABASE_URL not configured")
    return psycopg2.connect(SA_DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


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
    # ── infra_docs — cache of the SERVER_*.md system map ────────────────────
    # Read-only operator view (admin_api/routers/infra_docs.py). Populated
    # by tasks/infra_docs_sync.py on a 5-minute background task + the
    # POST /api/infra-docs/sync button. Source of truth is the Markdown
    # files in /home/support/glitch-trade-app/docs/. The DB row is a
    # cache — every operator-visible field is derivable from re-running
    # the sync. See glitch-admin-dashboard/docs/INFRA_VIEW_PLAN.md.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS infra_docs (
            slug          TEXT PRIMARY KEY,
            title         TEXT NOT NULL,
            source_path   TEXT NOT NULL,
            section_num   INT,
            content_md    TEXT NOT NULL,
            content_hash  TEXT NOT NULL,
            bytes         INT NOT NULL,
            last_modified TIMESTAMPTZ NOT NULL,
            last_synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS infra_docs_section_idx
            ON infra_docs (section_num)
    """)
    # ── Trade-domain tables MIGRATED to PG17 (2026-05-18) ─────────────────────
    # bot_heartbeats, bot_positions, bot_events, oracle_alerts,
    # user_ctrader_connections, plus 9 other Trade tables (trades, signal_*,
    # price_alerts, exchange_keys, ensemble_predictions, user_preferences,
    # trial_*, daily_briefing_subs) now live in PG17 glitch_trade.public and are
    # exposed back into this database as FOREIGN TABLES via postgres_fdw server
    # 'pg17_trade'. Schema is managed by glitch-trade-api migrations, NOT here.
    # This function only manages admin-domain tables (admin_users, audit_log).
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
