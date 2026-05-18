"""
GlitchExecutor Payment Server
Handles Stripe checkout, webhooks, auto-provisioning, and transactional emails.
Port: 5002
"""
import os
import json
import time
import hashlib
import hmac
import logging
import threading
import uuid
import requests
import psycopg2
import psycopg2.extras
import stripe
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

import email_service

# ─── Config ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("PaymentServer")

app = Flask(__name__)

# ─── Rate Limiter ────────────────────────────────────────────────────────────
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per hour"],
    storage_uri="memory://",
)

STRIPE_SECRET_KEY     = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PUB_KEY        = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
TELEGRAM_BOT_TOKEN    = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
DATABASE_URL          = os.environ.get("DATABASE_URL", "")

stripe.api_key = STRIPE_SECRET_KEY

# ── Glitch Grow fulfillment dispatcher ────────────────────────────────
# Stripe Payment Links for the BSK-* SKUs flow into stripe_webhook on
# checkout.session.completed; that handler forks here to fire the
# central fulfillment endpoint on grow.glitchexecutor.com which runs
# GitHub collaborator invite + Resend welcome email + Sheet log +
# Discord operator alert in parallel.
GROW_FULFILL_URL    = os.getenv("GROW_FULFILL_URL", "https://grow.glitchexecutor.com/api/fulfill/grant-access")
GROW_FULFILL_SECRET = os.getenv("GROW_FULFILL_SECRET", "")

def _dispatch_grow_fulfillment(*, payment_id: str, sku: str, email: str,
                                github_username: str, name: str,
                                amount_minor: int, currency: str) -> None:
    """Fire-and-forget POST to the Cloudflare Pages fulfillment endpoint.

    The fulfill function is shared-secret protected via the x-fulfill-secret
    header. Failure here does not block the webhook ack — Stripe retries
    are acceptable and the fulfill function is idempotent on payment_id."""
    if not GROW_FULFILL_SECRET:
        logger.warning("GROW_FULFILL_SECRET not set — skipping fulfillment dispatch")
        return
    payload = {
        "provider":         "stripe",
        "payment_id":       payment_id,
        "sku":              sku,
        "email":            email,
        "github_username":  github_username or None,
        "name":             name or None,
        "amount":           (amount_minor or 0) / 100,
        "currency":         currency,
    }
    try:
        r = requests.post(
            GROW_FULFILL_URL,
            json=payload,
            headers={"x-fulfill-secret": GROW_FULFILL_SECRET},
            timeout=10,
        )
        logger.info(
            f"Glitch Grow fulfill dispatch: sku={sku} payment_id={payment_id[:14]}… "
            f"status={r.status_code}"
        )
    except requests.RequestException as e:
        logger.error(f"Glitch Grow fulfill dispatch network error: {e}")

# Price ID → internal tier mapping
PRICE_TIER_MAP = {
    "price_1T7u2iK6ZugeFXa5xQWoP16M": "starter",   # Starter Monthly
    "price_1T7u3ZK6ZugeFXa5duRUQgr4": "starter",   # Starter Yearly
    "price_1T7u2GK6ZugeFXa5jXkKi71y": "pro",        # Pro Monthly
    "price_1T7u4CK6ZugeFXa5rbBAi0bf": "pro",        # Pro Yearly
    "price_1T7tzWK6ZugeFXa5Pikul5AN": "elite",      # Elite Monthly
    "price_1T7u0OK6ZugeFXa5QUa0Szon": "elite",      # Elite Yearly
}

# Trial bot 7-day sequence
TRIAL_PRICE_MAP = {
    "starter": "price_1T7u2iK6ZugeFXa5xQWoP16M",
    "pro":     "price_1T7u2GK6ZugeFXa5jXkKi71y",
    "elite":   "price_1T7tzWK6ZugeFXa5Pikul5AN",
    "general": "price_1T7u2iK6ZugeFXa5xQWoP16M",  # default to starter
}
PLAN_LABELS = {
    "starter": "Starter ($49/mo)",
    "pro":     "Pro ($149/mo)",
    "elite":   "Elite ($349/mo)",
    "general": "Starter ($49/mo)",
}

TIER_NAMES = {
    "starter": "⭐ Starter",
    "pro":     "🤖 Pro",
    "elite":   "🏢 Elite",
}

TIER_PERKS = {
    "starter": "30 AI analyses per day across BTC, ETH, SOL & XRP.",
    "pro":     "100 analyses/day + automatic trade execution on testnet.",
    "elite":   "Unlimited analyses + MT5 bot deployment on your account.",
}

# Price ID → USD value (for CAPI purchase event reporting)
PRICE_VALUES = {
    "price_1T7u2iK6ZugeFXa5xQWoP16M":   49.00,   # Starter Monthly
    "price_1T7u3ZK6ZugeFXa5duRUQgr4":  470.00,   # Starter Yearly
    "price_1T7u2GK6ZugeFXa5jXkKi71y":  149.00,   # Pro Monthly
    "price_1T7u4CK6ZugeFXa5rbBAi0bf": 1430.00,   # Pro Yearly
    "price_1T7tzWK6ZugeFXa5Pikul5AN":  349.00,   # Elite Monthly
    "price_1T7u0OK6ZugeFXa5QUa0Szon": 3350.00,   # Elite Yearly
}

# ─── Tracking CAPI config ─────────────────────────────────────────────────────

META_PIXEL_ID    = os.environ.get("META_PIXEL_ID",    "1238175855166679")
META_CAPI_TOKEN  = os.environ.get("META_CAPI_TOKEN",  "")
TIKTOK_PIXEL_ID  = os.environ.get("TIKTOK_PIXEL_ID",  "D6BP003C77U1CE9DD290")
TIKTOK_CAPI_TOKEN = os.environ.get("TIKTOK_CAPI_TOKEN", "")


def _sha256(value: str) -> str:
    """SHA-256 hash a string (for CAPI user data hashing)."""
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


def _is_sha256_hex(s) -> bool:
    return isinstance(s, str) and len(s) == 64 and all(c in "0123456789abcdef" for c in s.lower())


def _h(value):
    """Hash if not already a sha256 hex digest. Returns '' for empty input."""
    if not value:
        return ""
    s = str(value).strip()
    return s.lower() if _is_sha256_hex(s) else _sha256(s)


def _client_ip_from_request():
    """Real client IP behind nginx (X-Forwarded-For first hop)."""
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.headers.get("X-Real-IP") or request.remote_addr or ""


def _extract_capi_context_from_request():
    """Capture browser identifiers at checkout-create time for later CAPI use.

    Returns a flat dict of strings safe to embed in Stripe metadata
    (Stripe caps each value at 500 chars; keys at 50, total 50 kv pairs).
    """
    cookies = request.cookies or {}
    fbc = cookies.get("_fbc", "") or ""
    fbp = cookies.get("_fbp", "") or ""
    fbclid = ""
    if not fbc:
        # Frontend may post fbclid explicitly, or Referer/origin URL carries it.
        body = (request.get_json(silent=True) or {}) if request.is_json else {}
        fbclid = body.get("fbclid", "") or request.args.get("fbclid", "") or ""
        if fbclid:
            fbc = f"fb.1.{int(time.time())}.{fbclid}"
    return {
        "fbc":         fbc[:500],
        "fbp":         fbp[:500],
        "client_ip":   (_client_ip_from_request() or "")[:500],
        "client_ua":   (request.headers.get("User-Agent", "") or "")[:500],
        "src_url":     (request.headers.get("Referer", "") or "")[:500],
    }


def _build_capi_user_data(session: dict, extra: dict = None) -> dict:
    """Construct Meta-CAPI user_data from a Stripe checkout.session + stored metadata.

    Pulls hashed PII (em/ph/fn/ln/ct/st/zp/country) from session.customer_details,
    raw fbc/fbp/IP/UA from session.metadata, and stable external_id from
    Stripe customer id (fallback: telegram_id from metadata).
    """
    session  = session or {}
    md       = session.get("metadata") or {}
    cust     = session.get("customer_details") or {}
    addr     = cust.get("address") or {}
    extra    = extra or {}

    email = cust.get("email") or session.get("customer_email") or extra.get("email") or ""
    phone = cust.get("phone") or extra.get("phone") or ""
    name  = cust.get("name")  or extra.get("name")  or ""

    fn, ln = "", ""
    if name:
        parts = name.strip().split(None, 1)
        fn = parts[0]
        ln = parts[1] if len(parts) > 1 else ""

    phone_digits = "".join(c for c in str(phone) if c.isdigit())

    external_id = (
        session.get("customer")
        or md.get("telegram_id")
        or md.get("external_id")
        or ""
    )

    ud = {}
    if email:        ud["em"]       = [_h(email)]
    if phone_digits: ud["ph"]       = [_h(phone_digits)]
    if fn:           ud["fn"]       = [_h(fn)]
    if ln:           ud["ln"]       = [_h(ln)]
    if addr.get("city"):        ud["ct"]      = [_h(addr["city"].replace(" ", ""))]
    if addr.get("state"):       ud["st"]      = [_h(addr["state"])]
    if addr.get("postal_code"): ud["zp"]      = [_h(addr["postal_code"])]
    if addr.get("country"):     ud["country"] = [_h(addr["country"])]
    if external_id:             ud["external_id"] = [_h(external_id)]

    fbc = md.get("fbc") or ""
    fbp = md.get("fbp") or ""
    if fbc: ud["fbc"] = fbc
    if fbp: ud["fbp"] = fbp

    client_ip = md.get("client_ip") or ""
    client_ua = md.get("client_ua") or ""
    if client_ip: ud["client_ip_address"] = client_ip
    if client_ua: ud["client_user_agent"] = client_ua

    return ud


def send_meta_capi_purchase(session: dict, tier: str, price_id: str,
                             event_id: str = "") -> None:
    """
    Send a Purchase event to Meta Conversions API (server-side).
    Fires on checkout.session.completed. Built from the full Stripe session
    so we can attach hashed PII, address, fbc/fbp cookies (captured at
    checkout-create), client IP/UA, and external_id — all of which Meta's
    Event Match Quality scores against.
    Docs: https://developers.facebook.com/docs/marketing-api/conversions-api
    """
    if not META_CAPI_TOKEN:
        return
    try:
        value     = PRICE_VALUES.get(price_id, 0.0)
        ev_id     = event_id or f"pur_{int(time.time())}"
        user_data = _build_capi_user_data(session)
        src_url   = (session.get("metadata") or {}).get("src_url", "") or "https://grow.glitchexecutor.com/success"
        payload   = {
            "data": [{
                "event_name":       "Purchase",
                "event_time":       int(time.time()),
                "event_id":         ev_id,
                "action_source":    "website",
                "event_source_url": src_url,
                "user_data":        user_data,
                "custom_data": {
                    "value":        value,
                    "currency":     "USD",
                    "content_ids":  [tier],
                    "content_type": "product",
                    "content_name": f"GlitchExecutor {tier.title()}",
                },
            }]
        }
        url  = (f"https://graph.facebook.com/v19.0/{META_PIXEL_ID}"
                f"/events?access_token={META_CAPI_TOKEN}")
        resp = requests.post(url, json=payload, timeout=6)
        logger.info(f"Meta CAPI Purchase → tier={tier} value={value} "
                    f"ud_keys={sorted(user_data.keys())} status={resp.status_code}")
    except Exception as e:
        logger.warning(f"Meta CAPI send failed: {e}")


def send_tiktok_capi_purchase(customer_email: str, tier: str, price_id: str,
                               event_id: str = "") -> None:
    """
    Send a CompletePayment event to TikTok Events API (server-side).
    Docs: https://business-api.tiktok.com/portal/docs?id=1771101130043393
    """
    if not TIKTOK_CAPI_TOKEN:
        return
    try:
        value   = PRICE_VALUES.get(price_id, 0.0)
        ev_id   = event_id or f"pur_{int(time.time())}"
        payload = {
            "pixel_code":  TIKTOK_PIXEL_ID,
            "event":       "CompletePayment",
            "event_id":    ev_id,
            "timestamp":   datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "context": {
                "user": {
                    "email": _sha256(customer_email) if customer_email else "",
                },
                "page": {
                    "url": "https://grow.glitchexecutor.com/success",
                },
            },
            "properties": {
                "value":        value,
                "currency":     "USD",
                "content_id":   [tier],
                "content_type": "product",
                "content_name": f"GlitchExecutor {tier.title()}",
            },
        }
        headers = {
            "Access-Token":  TIKTOK_CAPI_TOKEN,
            "Content-Type":  "application/json",
        }
        resp = requests.post(
            "https://business-api.tiktok.com/open_api/v1.3/pixel/track/",
            json=payload, headers=headers, timeout=6
        )
        logger.info(f"TikTok CAPI CompletePayment → tier={tier} value={value} "
                    f"status={resp.status_code}")
    except Exception as e:
        logger.warning(f"TikTok CAPI send failed: {e}")


# ─── Database helpers ────────────────────────────────────────────────────────

def get_db():
    """Get synchronous PostgreSQL connection."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def db_get_customer_by_username(username: str):
    """Look up customer by Telegram username (case-insensitive, strip @)."""
    username = username.lstrip("@").lower()
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM customers WHERE LOWER(username) = %s",
                    (username,)
                )
                return cur.fetchone()
    except Exception as e:
        logger.error(f"DB lookup failed for username {username}: {e}")
        return None


def db_get_customer_by_stripe(stripe_customer_id: str):
    """Look up customer by Stripe customer ID."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM customers WHERE stripe_customer_id = %s",
                    (stripe_customer_id,)
                )
                return cur.fetchone()
    except Exception as e:
        logger.error(f"DB lookup failed for stripe_customer {stripe_customer_id}: {e}")
        return None


def db_activate_customer_by_telegram_id(telegram_id: int, stripe_customer_id: str,
                                         stripe_subscription_id: str, stripe_price_id: str,
                                         tier: str, customer_email: str = "") -> dict | None:
    """
    Activate/upgrade a customer matched by their Telegram ID.
    Used for bot-initiated checkouts where we already know the telegram_id.
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE customers
                       SET tier = %s,
                           status = 'active',
                           stripe_customer_id = %s,
                           stripe_subscription_id = %s,
                           stripe_price_id = %s,
                           email = COALESCE(NULLIF(%s, ''), email)
                       WHERE telegram_id = %s
                       RETURNING *""",
                    (tier, stripe_customer_id, stripe_subscription_id,
                     stripe_price_id, customer_email, telegram_id)
                )
                row = cur.fetchone()
                if row:
                    conn.commit()
                    logger.info(f"Upgraded tg_id={telegram_id} to {tier}")
                    return dict(row)
                logger.warning(f"db_activate_by_tg_id: no customer found for tg_id={telegram_id}")
    except Exception as e:
        logger.error(f"db_activate_customer_by_telegram_id failed: {e}")
    return None


def db_activate_customer(telegram_username: str, stripe_customer_id: str,
                          stripe_subscription_id: str, stripe_price_id: str,
                          tier: str, customer_email: str = "") -> dict | None:
    """
    Upgrade a customer's tier after successful payment.
    If no matching username yet, creates a pending record so the bot can
    pick it up when the user first /start's.
    Stores the Stripe email for transactional emails.
    Returns the updated/created customer row.
    """
    username = telegram_username.lstrip("@").lower()
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # Try to update an existing customer
                cur.execute(
                    """UPDATE customers
                       SET tier = %s,
                           status = 'active',
                           stripe_customer_id = %s,
                           stripe_subscription_id = %s,
                           stripe_price_id = %s,
                           email = COALESCE(NULLIF(%s, ''), email)
                       WHERE LOWER(username) = %s
                       RETURNING *""",
                    (tier, stripe_customer_id, stripe_subscription_id,
                     stripe_price_id, customer_email, username)
                )
                row = cur.fetchone()
                if row:
                    conn.commit()
                    logger.info(f"Upgraded {username} to {tier}")
                    return dict(row)

                # No matching row — create a pending record (user hasn't started the bot yet)
                cur.execute(
                    """INSERT INTO customers
                       (telegram_id, username, tier, status,
                        stripe_customer_id, stripe_subscription_id, stripe_price_id,
                        trial_ends_at, email)
                       VALUES (0, %s, %s, 'active', %s, %s, %s, NOW() + INTERVAL '10 years', %s)
                       ON CONFLICT DO NOTHING
                       RETURNING *""",
                    (username, tier, stripe_customer_id,
                     stripe_subscription_id, stripe_price_id,
                     customer_email or None)
                )
                row = cur.fetchone()
                conn.commit()
                if row:
                    logger.info(f"Created pending record for {username} tier={tier}")
                    return dict(row)
    except Exception as e:
        logger.error(f"db_activate_customer failed: {e}")
    return None


def db_suspend_customer(stripe_customer_id: str):
    """Suspend a customer on payment failure."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE customers SET status = 'suspended' WHERE stripe_customer_id = %s",
                    (stripe_customer_id,)
                )
                conn.commit()
                logger.info(f"Suspended customer {stripe_customer_id}")
    except Exception as e:
        logger.error(f"db_suspend_customer failed: {e}")


def db_cancel_customer(stripe_customer_id: str):
    """Downgrade customer to trial on cancellation."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE customers
                       SET tier = 'trial', status = 'cancelled',
                           stripe_subscription_id = NULL
                       WHERE stripe_customer_id = %s""",
                    (stripe_customer_id,)
                )
                conn.commit()
                logger.info(f"Cancelled subscription for {stripe_customer_id}")
    except Exception as e:
        logger.error(f"db_cancel_customer failed: {e}")


# ─── Email helper ────────────────────────────────────────────────────────────

def get_customer_email(customer_row: dict, stripe_customer_id: str = "") -> str:
    """
    Resolve a customer's email: DB first, then Stripe API fallback.
    """
    if customer_row and customer_row.get("email"):
        return customer_row["email"]
    if stripe_customer_id:
        try:
            sc = stripe.Customer.retrieve(stripe_customer_id)
            return sc.get("email") or ""
        except Exception as e:
            logger.warning(f"Stripe customer fetch failed for {stripe_customer_id}: {e}")
    return ""


# ─── Telegram helper ─────────────────────────────────────────────────────────

def send_telegram(telegram_id: int, text: str):
    """Send a message to a Telegram user via Bot API."""
    if not TELEGRAM_BOT_TOKEN or not telegram_id or telegram_id == 0:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": telegram_id,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        logger.warning(f"Telegram notify failed for {telegram_id}: {e}")


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/stripe/config")
def stripe_config():
    return jsonify({"publishableKey": STRIPE_PUB_KEY})


@app.route("/api/create-checkout-session", methods=["POST", "OPTIONS"])
@app.route("/api/stripe/create-checkout-session", methods=["POST", "OPTIONS"])
@limiter.limit("5/minute")
def create_checkout_session():
    """Create a Stripe Checkout Session and return the redirect URL."""
    if request.method == "OPTIONS":
        return "", 204

    try:
        data = request.get_json(force=True) or {}
        price_id = data.get("price_id")
        tier     = data.get("tier", "starter").lower()
        billing  = data.get("billing", "monthly")

        # Resolve price_id from tier if not provided directly
        if not price_id:
            tier_price_map = {
                "starter": "price_1T7u2iK6ZugeFXa5xQWoP16M",   # monthly default
                "pro":     "price_1T7u2GK6ZugeFXa5jXkKi71y",   # monthly default
                "elite":   "price_1T7tzWK6ZugeFXa5Pikul5AN",   # monthly default
            }
            yearly_price_map = {
                "starter": "price_1T7u3ZK6ZugeFXa5duRUQgr4",
                "pro":     "price_1T7u4CK6ZugeFXa5rbBAi0bf",
                "elite":   "price_1T7u0OK6ZugeFXa5QUa0Szon",
            }
            if billing == "yearly":
                price_id = yearly_price_map.get(tier)
            else:
                price_id = tier_price_map.get(tier)

        if not price_id:
            return jsonify({"error": "Invalid tier"}), 400

        capi_ctx = _extract_capi_context_from_request()

        session = stripe.checkout.Session.create(
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url="https://grow.glitchexecutor.com/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="https://glitchexecutor.com/#pricing",
            phone_number_collection={"enabled": True},
            # Ask for Telegram username at checkout
            custom_fields=[{
                "key": "telegram_username",
                "label": {"type": "custom", "custom": "Your Telegram username (e.g. @YourName)"},
                "type": "text",
                "optional": False,
            }],
            metadata={
                "tier":      tier,
                "billing":   billing,
                "price_id":  price_id,
                **capi_ctx,
            }
        )

        logger.info(f"Checkout session created: {session.id} tier={tier}")
        return jsonify({"url": session.url})

    except Exception as e:
        logger.error(f"create_checkout_session error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/bot/checkout", methods=["POST"])
def bot_checkout():
    """
    Create a Stripe Checkout Session initiated from the Telegram bot.

    Unlike the web flow, we already know the user's telegram_id and username,
    so we embed them in metadata and skip the custom_fields form.

    Expects JSON: { "tier": "pro", "billing": "monthly",
                    "telegram_id": 123456, "telegram_username": "alice" }
    Returns JSON: { "url": "<stripe_checkout_url>" }
    """
    try:
        data              = request.get_json(force=True) or {}
        tier              = data.get("tier", "starter").lower()
        billing           = data.get("billing", "monthly")
        telegram_id       = int(data.get("telegram_id", 0))
        telegram_username = (data.get("telegram_username") or "").strip().lstrip("@")

        if not telegram_id:
            return jsonify({"error": "telegram_id required"}), 400

        tier_price_map = {
            "starter": "price_1T7u2iK6ZugeFXa5xQWoP16M",
            "pro":     "price_1T7u2GK6ZugeFXa5jXkKi71y",
            "elite":   "price_1T7tzWK6ZugeFXa5Pikul5AN",
        }
        yearly_price_map = {
            "starter": "price_1T7u3ZK6ZugeFXa5duRUQgr4",
            "pro":     "price_1T7u4CK6ZugeFXa5rbBAi0bf",
            "elite":   "price_1T7u0OK6ZugeFXa5QUa0Szon",
        }

        price_id = (yearly_price_map if billing == "yearly" else tier_price_map).get(tier)
        if not price_id:
            return jsonify({"error": "Invalid tier"}), 400

        session = stripe.checkout.Session.create(
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url="https://grow.glitchexecutor.com/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="https://t.me/GlitchExecutorBot",   # sends them back to the bot
            phone_number_collection={"enabled": True},
            metadata={
                "tier":              tier,
                "billing":           billing,
                "price_id":          price_id,
                "telegram_id":       str(telegram_id),
                "telegram_username": telegram_username,
                "source":            "bot",
            }
        )

        logger.info(
            f"Bot checkout session created: {session.id} "
            f"tier={tier} billing={billing} tg_id={telegram_id}"
        )
        return jsonify({"url": session.url})

    except Exception as e:
        logger.error(f"bot_checkout error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/stripe/webhook", methods=["POST"])
@limiter.limit("30 per minute")
def stripe_webhook():
    """Handle Stripe webhook events."""
    payload    = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        return jsonify({"error": "Invalid payload"}), 400
    except stripe.error.SignatureVerificationError:
        return jsonify({"error": "Invalid signature"}), 400

    etype = event["type"]
    logger.info(f"Stripe event: {etype}")

    # ── Subscription created ────────────────────────────────────────────────
    if etype == "checkout.session.completed":
        session = event["data"]["object"]
        stripe_customer_id     = session.get("customer", "")
        stripe_subscription_id = session.get("subscription", "")
        metadata               = session.get("metadata", {})
        tier                   = metadata.get("tier", "starter")
        price_id               = metadata.get("price_id", "")
        customer_email         = ""
        if session.get("customer_details"):
            customer_email = session["customer_details"].get("email") or ""

        # ── Glitch Grow agent fulfillment fork ─────────────────────────────
        # The Glitch Grow Payment Links (BSK-001..006 + BSK-ALL) carry
        # metadata.sku from setup-stripe-products.mjs. When we see one,
        # dispatch to the central fulfillment endpoint on grow.glitch
        # executor.com and skip the dashboard subscription flow below.
        # Line items, custom fields, customer email are all surfaced
        # in the session payload so we don't need to round-trip Stripe.
        sku_meta = metadata.get("sku", "") or ""
        # Some Payment Links inherit the SKU on the line-item Price's
        # metadata rather than the session — fall back to expanding
        # line_items if needed.
        if not sku_meta.startswith("BSK-"):
            try:
                expanded = stripe.checkout.Session.retrieve(
                    session["id"], expand=["line_items.data.price.product"]
                )
                for li in expanded.get("line_items", {}).get("data", []) or []:
                    cand = (li.get("price", {}).get("metadata", {}) or {}).get("sku", "")
                    if cand.startswith("BSK-"):
                        sku_meta = cand
                        break
            except Exception:
                pass

        if sku_meta.startswith("BSK-"):
            github_username = ""
            for field in session.get("custom_fields", []) or []:
                if field.get("key") == "github_username":
                    github_username = (field.get("text", {}).get("value") or "").strip()
                    break
            try:
                _dispatch_grow_fulfillment(
                    payment_id=session["id"],
                    sku=sku_meta,
                    email=customer_email,
                    github_username=github_username,
                    name=(session.get("customer_details", {}) or {}).get("name", ""),
                    amount_minor=session.get("amount_total", 0),
                    currency=(session.get("currency") or "USD").upper(),
                )
            except Exception as e:
                logger.error(f"Glitch Grow fulfillment dispatch failed: {e}")
            return jsonify({"status": "ok", "stream": "glitch-grow", "sku": sku_meta})

        # ── Resolve who paid: bot-originated vs web-originated ─────────────
        source            = metadata.get("source", "web")
        telegram_id_meta  = int(metadata.get("telegram_id", 0) or 0)
        telegram_username = metadata.get("telegram_username", "")

        # Web flow: read username from Stripe custom_fields form
        if source != "bot":
            for field in session.get("custom_fields", []):
                if field.get("key") == "telegram_username":
                    telegram_username = (field.get("text", {}).get("value") or "").strip()
                    break

        if not telegram_username and not telegram_id_meta:
            logger.warning(f"No telegram identity in checkout {session['id']}")
            return jsonify({"status": "ok", "warning": "no telegram identity"})

        # Activate in DB — prefer telegram_id (bot flow) over username (web flow)
        if telegram_id_meta:
            customer = db_activate_customer_by_telegram_id(
                telegram_id_meta, stripe_customer_id,
                stripe_subscription_id, price_id, tier,
                customer_email=customer_email
            )
        else:
            customer = db_activate_customer(
                telegram_username, stripe_customer_id,
                stripe_subscription_id, price_id, tier,
                customer_email=customer_email
            )

        # ── Email: welcome ──────────────────────────────────────────────────
        if customer_email:
            email_service.send_welcome_email(
                to_email=customer_email,
                tier=tier,
                telegram_username=telegram_username,
            )

        # ── CAPI: Purchase (server-side conversion events) ───────────────────
        capi_event_id = f"pur_{session['id']}"
        send_meta_capi_purchase(session, tier, price_id, event_id=capi_event_id)
        send_tiktok_capi_purchase(customer_email, tier, price_id, event_id=capi_event_id)

        # ── Telegram: welcome ───────────────────────────────────────────────
        if customer and customer.get("telegram_id") and customer["telegram_id"] != 0:
            tier_name  = TIER_NAMES.get(tier, tier.title())
            tier_perks = TIER_PERKS.get(tier, "")
            msg = (
                f"🎉 <b>Welcome to GlitchExecutor {tier_name}!</b>\n\n"
                f"Your subscription is now <b>active</b>.\n"
                f"{tier_perks}\n\n"
                f"Send any crypto symbol to get your first AI analysis — e.g. <code>BTC</code>\n\n"
                f"Use /status to see your account details."
            )
            send_telegram(customer["telegram_id"], msg)
            logger.info(f"Notified {telegram_username} (id={customer['telegram_id']}) → {tier}")

    # ── Payment succeeded (renewal) ─────────────────────────────────────────
    elif etype == "invoice.paid":
        invoice  = event["data"]["object"]
        cust_id  = invoice.get("customer", "")
        customer = db_get_customer_by_stripe(cust_id)
        if customer:
            # Re-activate in case it was suspended
            try:
                with get_db() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE customers SET status = 'active' WHERE stripe_customer_id = %s",
                            (cust_id,)
                        )
                        conn.commit()
            except Exception as e:
                logger.error(f"invoice.paid DB update failed: {e}")

    # ── Payment failed ──────────────────────────────────────────────────────
    elif etype == "invoice.payment_failed":
        invoice  = event["data"]["object"]
        cust_id  = invoice.get("customer", "")
        customer = db_get_customer_by_stripe(cust_id)
        db_suspend_customer(cust_id)
        tier = customer.get("tier", "Pro") if customer else "Pro"

        # ── Email: payment failed ───────────────────────────────────────────
        cust_email = get_customer_email(customer, cust_id)
        if cust_email:
            email_service.send_payment_failed_email(to_email=cust_email, tier=tier)

        # ── Telegram: payment failed ────────────────────────────────────────
        if customer and customer.get("telegram_id") and customer["telegram_id"] != 0:
            msg = (
                "⚠️ <b>Payment failed</b>\n\n"
                "We couldn't process your subscription payment. "
                "Your account has been temporarily suspended.\n\n"
                "Please update your payment method at:\n"
                "https://glitchexecutor.com/billing"
            )
            send_telegram(customer["telegram_id"], msg)

    # ── Subscription cancelled ──────────────────────────────────────────────
    elif etype == "customer.subscription.deleted":
        sub      = event["data"]["object"]
        cust_id  = sub.get("customer", "")
        customer = db_get_customer_by_stripe(cust_id)
        tier     = customer.get("tier", "Pro") if customer else "Pro"
        db_cancel_customer(cust_id)

        # ── Email: cancellation ─────────────────────────────────────────────
        cust_email = get_customer_email(customer, cust_id)
        if cust_email:
            email_service.send_cancellation_email(to_email=cust_email, tier=tier)

        # ── Telegram: cancellation ──────────────────────────────────────────
        if customer and customer.get("telegram_id") and customer["telegram_id"] != 0:
            msg = (
                "📋 <b>Subscription cancelled</b>\n\n"
                "Your subscription has been cancelled and your account "
                "has been returned to trial mode.\n\n"
                "You can resubscribe anytime at https://glitchexecutor.com/#pricing"
            )
            send_telegram(customer["telegram_id"], msg)

    return jsonify({"status": "ok"})


@app.route("/api/stripe/session-status")
def session_status():
    """Check checkout session status (for success page)."""
    session_id = request.args.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id required"}), 400
    try:
        session = stripe.checkout.Session.retrieve(session_id)

        # Extract telegram username
        telegram_username = ""
        for field in session.get("custom_fields", []):
            if field.get("key") == "telegram_username":
                telegram_username = (field.get("text", {}).get("value") or "").strip()
                break

        tier_v = session.metadata.get("tier", "")
        price_v = session.metadata.get("price_id", "")
        value = PRICE_VALUES.get(price_v, 0.0)
        return jsonify({
            "status":           session.status,
            "tier":             tier_v,
            "telegram_username": telegram_username,
            "customer_email":   session.customer_details.email if session.customer_details else None,
            # For browser-side Purchase dedup with server-side CAPI:
            # frontend should fire fbq('track','Purchase',{value,currency},{eventID})
            "purchase": {
                "event_id": f"pur_{session.id}",
                "value":    value,
                "currency": "USD",
            },
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Telegram Registration Gate ──────────────────────────────────────────────

REG_WAITING_NAME  = "waiting_name"
REG_WAITING_EMAIL = "waiting_email"
REG_WAITING_PHONE = "waiting_phone"
REG_DONE          = "registered"

TIER_DISPLAY = {
    "starter": "⭐ Starter",
    "pro":     "🤖 Pro",
    "elite":   "🏢 Elite",
    "general": "🚀 Trial",
}


def tg_send(chat_id: int, text: str, **kwargs):
    """Send a message to a Telegram chat."""
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", **kwargs},
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"tg_send failed: {e}")


def db_get_tg_user(telegram_id: int):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM telegram_users WHERE telegram_id = %s",
                    (telegram_id,)
                )
                return cur.fetchone()
    except Exception as e:
        logger.error(f"db_get_tg_user failed: {e}")
        return None


def db_get_trial_signup_by_token(token: str):
    """Look up a landing-page signup by its bot deep-link token."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM trial_signups WHERE bot_token = %s",
                    (token,)
                )
                return cur.fetchone()
    except Exception as e:
        logger.error(f"db_get_trial_signup_by_token failed: {e}")
        return None


def db_upsert_tg_user(telegram_id: int, username: str = "",
                       state: str = REG_WAITING_NAME,
                       name: str = "", email: str = "",
                       phone: str = "", plan: str = ""):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO telegram_users
                           (telegram_id, username, state, name, email, phone, plan)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (telegram_id) DO UPDATE SET
                           username   = COALESCE(NULLIF(EXCLUDED.username,''), telegram_users.username),
                           state      = EXCLUDED.state,
                           name       = CASE WHEN EXCLUDED.name  <> '' THEN EXCLUDED.name  ELSE telegram_users.name  END,
                           email      = CASE WHEN EXCLUDED.email <> '' THEN EXCLUDED.email ELSE telegram_users.email END,
                           phone      = CASE WHEN EXCLUDED.phone <> '' THEN EXCLUDED.phone ELSE telegram_users.phone END,
                           plan       = CASE WHEN EXCLUDED.plan NOT IN ('','general') THEN EXCLUDED.plan ELSE telegram_users.plan END,
                           updated_at = NOW()""",
                    (telegram_id, username, state, name, email, phone, plan or "general")
                )
                conn.commit()
    except Exception as e:
        logger.error(f"db_upsert_tg_user failed: {e}")


def _run_bot_migrations():
    """Idempotent migrations for 7-day trial sequence tables + Glitch Grow buyers."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    ALTER TABLE telegram_users
                        ADD COLUMN IF NOT EXISTS trial_started_at TIMESTAMPTZ
                """)
                # CREATE TABLE trial_messages_log removed 2026-05-18 — table now in PG17 glitch_trade via postgres_fdw
                # ALTER TABLE trial_signups removed — schema lives in PG17 now
                # CREATE INDEX idx_trial_signups_bot_token removed — schema lives in PG17 now
                # CREATE TABLE glitch_grow_buyers removed 2026-05-18 — BSK retired; table dropped
                cur.execute("CREATE INDEX IF NOT EXISTS idx_grow_buyers_email      ON glitch_grow_buyers(email)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_grow_buyers_sku        ON glitch_grow_buyers(sku)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_grow_buyers_provider   ON glitch_grow_buyers(provider)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_grow_buyers_created_at ON glitch_grow_buyers(created_at DESC)")
                conn.commit()
        logger.info("Bot migrations complete")
    except Exception as e:
        logger.error(f"_run_bot_migrations failed: {e}")


@app.route("/api/telegram/webhook", methods=["POST"])
def telegram_bot_webhook():
    """
    Telegram Bot webhook — registration gate.
    Every user must register (name, email, phone) before using the bot.
    Catches shared links too — no lead is ever missed.
    """
    # ── Verify Telegram webhook secret token ──
    if TELEGRAM_WEBHOOK_SECRET:
        incoming_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(incoming_token, TELEGRAM_WEBHOOK_SECRET):
            logger.warning(f"Telegram webhook: invalid secret token from {request.remote_addr}")
            return jsonify({"error": "unauthorized"}), 403

    data = request.get_json(force=True) or {}

    msg = data.get("message") or data.get("edited_message")
    if not msg:
        return jsonify({"ok": True})

    chat_id    = msg["chat"]["id"]
    text       = (msg.get("text") or "").strip()
    tg_user_from = msg.get("from", {})
    tg_id      = tg_user_from.get("id", chat_id)
    tg_username = tg_user_from.get("username", "")
    first_name  = tg_user_from.get("first_name", "")

    # Extract plan from /start deep-link payload (e.g. trial_pro → pro)
    plan = ""
    reg_token = ""
    if text.startswith("/start"):
        payload = text[6:].strip()
        if payload.startswith("trial_"):
            plan = payload[6:]   # starter / pro / elite / general
        elif payload.startswith("reg_"):
            reg_token = payload[4:]  # UUID from landing page form

    tg_user = db_get_tg_user(tg_id)

    # ── Token-based auto-registration (user filled landing page form) ─────────
    if reg_token and (not tg_user or tg_user["state"] != REG_DONE):
        signup = db_get_trial_signup_by_token(reg_token)
        if signup:
            db_upsert_tg_user(tg_id, tg_username, REG_DONE,
                              name=signup["name"], email=signup["email"],
                              phone=signup["phone"], plan=signup["plan"])
            try:
                with get_db() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE telegram_users SET trial_started_at = NOW() "
                            "WHERE telegram_id = %s AND trial_started_at IS NULL",
                            (tg_id,)
                        )
                        conn.commit()
            except Exception as e:
                logger.error(f"trial_started_at update (token flow) failed: {e}")
            tg_send(chat_id,
                f"🎉 <b>Welcome aboard, {signup['name']}!</b>\n\n"
                f"Your <b>7-day free trial</b> is now active.\n\n"
                f"Here's what's coming:\n\n"
                f"📚 <b>Tomorrow:</b> How our AI bots actually trade\n"
                f"📊 <b>Day 3:</b> Real live performance numbers\n"
                f"🏆 <b>Day 7:</b> Your special trial-to-paid offer\n\n"
                f"Commands you can use right now:\n"
                f"/status — Trial status &amp; days remaining\n"
                f"/performance — Live bot activity\n"
                f"/plans — Compare plans + pricing\n"
                f"/help — All commands\n\n"
                f"Let's go! 🤖"
            )
            logger.info(f"Token auto-registration: {signup['name']} | {signup['email']} | tg_id={tg_id}")
            return jsonify({"ok": True})

    # ── Already registered ────────────────────────────────────────────────────
    if tg_user and tg_user["state"] == REG_DONE:
        name       = tg_user.get("name", "trader")
        plan       = (tg_user.get("plan") or "general").lower()
        tier_label = TIER_DISPLAY.get(plan, "🚀 Trial")
        text_lower = text.lower()

        if text.startswith("/start"):
            # Build trial status inline so returning user immediately sees their data
            trial_started = tg_user.get("trial_started_at")
            if trial_started:
                from datetime import timezone, timedelta
                now = datetime.now(timezone.utc) if (hasattr(trial_started, "tzinfo") and trial_started.tzinfo) else datetime.utcnow()
                days_elapsed = (now - trial_started).days
                days_left    = max(0, 7 - days_elapsed)
                end_date     = trial_started + timedelta(days=7)
                if days_left > 0:
                    trial_line = f"✅ {days_left} day{'s' if days_left != 1 else ''} remaining (ends {end_date.strftime('%d %b')})"
                else:
                    trial_line = f"⏰ Trial ended — upgrade to keep access"
            else:
                trial_line = "✅ Trial active"

            tg_send(chat_id,
                f"👋 Welcome back, <b>{name}</b>!\n\n"
                f"📧 {tg_user.get('email', '—')}\n"
                f"📦 Plan: <b>{tier_label}</b>\n"
                f"⏱ {trial_line}\n\n"
                f"/status — Full trial details\n"
                f"/performance — Live bot activity\n"
                f"/plans — Compare plans + pricing\n"
                f"/help — All commands"
            )

        elif text.startswith("/help"):
            tg_send(chat_id,
                "🤖 <b>GlitchExecutor Bot Commands</b>\n\n"
                "/status — Your trial status &amp; days remaining\n"
                "/performance — Live bot activity right now\n"
                "/plans — Compare plans + get your checkout link\n"
                "/help — This menu\n\n"
                "Or just ask me anything — I handle:\n"
                "• Questions about pricing\n"
                "• MT5 connection help\n"
                "• Risk &amp; withdrawal questions"
            )

        elif text.startswith("/status"):
            trial_started = tg_user.get("trial_started_at")
            if trial_started:
                from datetime import timezone
                if hasattr(trial_started, "tzinfo") and trial_started.tzinfo:
                    now = datetime.now(timezone.utc)
                else:
                    now = datetime.utcnow()
                days_elapsed = (now - trial_started).days
                days_left    = max(0, 7 - days_elapsed)
                end_date     = trial_started + __import__("datetime").timedelta(days=7)
                end_str      = end_date.strftime("%d %b %Y")
                status_line  = f"✅ Active — {days_left} day{'s' if days_left != 1 else ''} remaining" if days_left > 0 else "⏰ Trial ended"
            else:
                status_line = "✅ Active trial"
                end_str     = "—"

            tg_send(chat_id,
                f"📋 <b>Your Trial Status</b>\n\n"
                f"Name: {name}\n"
                f"Email: {tg_user.get('email', '—')}\n"
                f"Plan: {tier_label}\n"
                f"Status: {status_line}\n"
                f"Trial ends: {end_str}\n\n"
                f"Type /plans to upgrade anytime."
            )

        elif text.startswith("/performance"):
            perf = _get_performance_text()
            tg_send(chat_id, perf)

        elif text.startswith("/plans"):
            url = _create_trial_checkout_url(tg_id, plan)
            plan_label = PLAN_LABELS.get(plan, "Starter ($49/mo)")
            tg_send(chat_id,
                "💳 <b>GlitchExecutor Plans</b>\n\n"
                "🥉 <b>Starter — $49/mo</b>\n"
                "  30 AI analyses · Trade journal · Weekly report\n\n"
                "🥈 <b>Pro — $149/mo</b>\n"
                "  100 AI analyses · Alerts · Daily report · Testnet execution\n\n"
                "🥇 <b>Elite — $349/mo</b>\n"
                "  Unlimited · Live auto-execution · Strategy review calls\n\n"
                f"👉 <b>Your {plan_label} checkout link:</b>\n"
                f"{url or 'https://glitchexecutor.com/#pricing'}"
            )

        # ── FAQ keyword matching ─────────────────────────────────────────────
        elif any(k in text_lower for k in ["price", "cost", "how much", "subscribe", "plan"]):
            url = _create_trial_checkout_url(tg_id, plan)
            plan_label = PLAN_LABELS.get(plan, "Starter ($49/mo)")
            tg_send(chat_id,
                "💳 <b>Plans &amp; Pricing</b>\n\n"
                "🥉 Starter — $49/mo\n"
                "🥈 Pro — $149/mo\n"
                "🥇 Elite — $349/mo\n\n"
                f"👉 Your personalised link ({plan_label}):\n"
                f"{url or 'https://glitchexecutor.com/#pricing'}"
            )

        elif any(k in text_lower for k in ["withdraw", "my money", "my account", "custody", "funds"]):
            tg_send(chat_id,
                "🏦 <b>Your Money, Your Control</b>\n\n"
                "The bots trade on <b>your own MT5 account</b>. "
                "Your funds never leave your broker. "
                "Withdraw any time directly from your MT5 platform — we have no access to your money."
            )

        elif any(k in text_lower for k in ["mt5", "metatrader", "connect", "setup", "install", "how to connect"]):
            tg_send(chat_id,
                "🔗 <b>Connecting MT5</b>\n\n"
                "After you subscribe, you'll receive a detailed setup guide with:\n"
                "• Which MT5 server to use\n"
                "• How to install the EA\n"
                "• Risk settings to configure\n\n"
                "The setup takes about 15 minutes. Type /plans to get started."
            )

        elif any(k in text_lower for k in ["risk", "lose", "loss", "drawdown", "safe", "blow"]):
            tg_send(chat_id,
                "🛡️ <b>Risk Management</b>\n\n"
                "Every trade has a <b>hard stop loss</b> — the bot cannot lose more than it's configured to risk per trade (typically 1-2% of account).\n\n"
                "System drawdown target: <b>&lt;8%</b>\n\n"
                "Past performance doesn't guarantee future results. "
                "Only trade with capital you can afford to lose."
            )

        elif any(k in text_lower for k in ["refund", "cancel", "cancell", "money back"]):
            tg_send(chat_id,
                "↩️ <b>Cancellation</b>\n\n"
                "Cancel your subscription any time from Stripe — no questions asked. "
                "Your access continues until the end of your billing period.\n\n"
                "No refunds on used periods, but we're happy to help if something went wrong. "
                "Reply here and a team member will follow up."
            )

        else:
            tg_send(chat_id,
                f"Hey {name}! Not sure what you mean — try one of these:\n\n"
                "/status — Trial days remaining\n"
                "/performance — Live bot activity\n"
                "/plans — Pricing &amp; checkout\n"
                "/help — All commands"
            )

        return jsonify({"ok": True})

    # ── Not registered — run conversation flow ────────────────────────────────
    state = tg_user["state"] if tg_user else None

    # Any /start or first contact → kick off registration
    if text.startswith("/start") or state is None:
        db_upsert_tg_user(tg_id, tg_username, REG_WAITING_NAME, plan=plan)
        greeting = f" {first_name}," if first_name else ","
        tg_send(chat_id,
            f"👋 Hey{greeting} welcome to <b>GlitchExecutor</b>! 🚀\n\n"
            f"You're 3 quick steps away from your <b>7-day free trial</b>.\n\n"
            f"Step 1 of 3 — <b>What's your full name?</b>"
        )
        return jsonify({"ok": True})

    # Waiting for name
    if state == REG_WAITING_NAME:
        if len(text) < 2 or text.startswith("/"):
            tg_send(chat_id, "Please type your full name to continue.")
            return jsonify({"ok": True})
        db_upsert_tg_user(tg_id, tg_username, REG_WAITING_EMAIL, name=text)
        tg_send(chat_id,
            f"✅ Nice to meet you, <b>{text}</b>!\n\n"
            f"Step 2 of 3 — <b>What's your email address?</b>"
        )
        return jsonify({"ok": True})

    # Waiting for email
    if state == REG_WAITING_EMAIL:
        if "@" not in text or "." not in text.split("@")[-1] or text.startswith("/"):
            tg_send(chat_id, "That doesn't look right. Please enter a valid email address.")
            return jsonify({"ok": True})
        db_upsert_tg_user(tg_id, tg_username, REG_WAITING_PHONE, email=text.lower())
        tg_send(chat_id,
            "✅ Got it!\n\n"
            "Step 3 of 3 — <b>What's your WhatsApp or phone number?</b>\n"
            "<i>(Include country code, e.g. +1 234 567 8900)</i>"
        )
        return jsonify({"ok": True})

    # Waiting for phone
    if state == REG_WAITING_PHONE:
        digits = "".join(c for c in text if c.isdigit())
        if len(digits) < 7 or text.startswith("/"):
            tg_send(chat_id, "Please enter a valid phone number including country code.")
            return jsonify({"ok": True})

        # Reload to get saved name/email/plan
        fresh = db_get_tg_user(tg_id)
        saved_name  = fresh["name"]  if fresh else ""
        saved_email = fresh["email"] if fresh else ""
        saved_plan  = fresh["plan"]  if fresh else "general"

        # Mark as registered
        db_upsert_tg_user(tg_id, tg_username, REG_DONE,
                          name=saved_name, email=saved_email,
                          phone=text, plan=saved_plan)

        # Store lead in trial_signups
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO trial_signups (name, email, phone, plan)
                           VALUES (%s, %s, %s, %s)
                           ON CONFLICT (email) DO UPDATE SET
                               name=EXCLUDED.name, phone=EXCLUDED.phone,
                               plan=EXCLUDED.plan, updated_at=NOW()""",
                        (saved_name, saved_email, text, saved_plan)
                    )
                    cur.execute(
                        "INSERT INTO email_signups (email, source) VALUES (%s, %s) "
                        "ON CONFLICT (email) DO NOTHING",
                        (saved_email, f"telegram_bot_{saved_plan}")
                    )
                    conn.commit()
        except Exception as e:
            logger.error(f"telegram_webhook lead save failed: {e}")

        # Set trial start time (for 7-day sequence scheduler)
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE telegram_users SET trial_started_at = NOW() "
                        "WHERE telegram_id = %s AND trial_started_at IS NULL",
                        (tg_id,)
                    )
                    conn.commit()
        except Exception as e:
            logger.error(f"trial_started_at update failed: {e}")

        # Day 0 welcome — previews the 7-day sequence
        tg_send(chat_id,
            f"🎉 <b>Welcome aboard, {saved_name}!</b>\n\n"
            f"Your <b>7-day free trial</b> is now active.\n\n"
            f"Here's what's coming:\n\n"
            f"📚 <b>Tomorrow:</b> How our AI bots actually trade\n"
            f"📊 <b>Day 3:</b> Real live performance numbers\n"
            f"🏆 <b>Day 7:</b> Your special trial-to-paid offer\n\n"
            f"Commands you can use right now:\n"
            f"/status — Trial status &amp; days remaining\n"
            f"/performance — Live bot activity\n"
            f"/plans — Compare plans + pricing\n"
            f"/help — All commands\n\n"
            f"Let's go! 🤖"
        )
        logger.info(f"New Telegram registration: {saved_name} | {saved_email} | plan={saved_plan} | tg_id={tg_id}")
        return jsonify({"ok": True})

    # Fallback — unknown state, restart registration
    db_upsert_tg_user(tg_id, tg_username, REG_WAITING_NAME, plan=plan)
    tg_send(chat_id,
        "Let's get you registered first!\n\n"
        "<b>What's your full name?</b>"
    )
    return jsonify({"ok": True})


@app.route("/api/trial-signup", methods=["POST", "OPTIONS"])
@limiter.limit("3 per minute")
def trial_signup():
    """Capture free trial signup: name, email, phone, plan → store lead + return bot link."""
    if request.method == "OPTIONS":
        return "", 204
    try:
        data  = request.get_json(force=True) or {}
        name  = (data.get("name")  or "").strip()
        email = (data.get("email") or "").strip().lower()
        phone = (data.get("phone") or "").strip()
        plan  = (data.get("plan")  or "general").strip().lower()

        if not name:
            return jsonify({"error": "Please enter your name"}), 400
        if not email or "@" not in email or "." not in email.split("@")[-1]:
            return jsonify({"error": "Please enter a valid email address"}), 400
        if not phone:
            return jsonify({"error": "Please enter your phone number"}), 400

        with get_db() as conn:
            with conn.cursor() as cur:
                token = str(uuid.uuid4())
                cur.execute(
                    """INSERT INTO trial_signups (name, email, phone, plan, bot_token)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (email) DO UPDATE SET
                           name       = EXCLUDED.name,
                           phone      = EXCLUDED.phone,
                           plan       = EXCLUDED.plan,
                           bot_token  = EXCLUDED.bot_token,
                           updated_at = NOW()
                       RETURNING bot_token""",
                    (name, email, phone, plan, token)
                )
                row = cur.fetchone()
                token = row["bot_token"]
                conn.commit()

        bot_link = f"https://t.me/GlitchExecutor_bot?start=reg_{token}"
        logger.info(f"Trial signup: {name} | {email} | plan={plan}")

        # Also store in email_signups for newsletter continuity
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO email_signups (email, source) VALUES (%s, %s) "
                        "ON CONFLICT (email) DO NOTHING",
                        (email, f"trial_{plan}")
                    )
                    conn.commit()
        except Exception:
            pass  # Non-fatal

        return jsonify({"status": "ok", "bot_link": bot_link})

    except Exception as e:
        logger.error(f"trial_signup error: {e}")
        return jsonify({"error": "Server error, please try again"}), 500


@app.route("/api/email-signup", methods=["POST", "OPTIONS"])
@limiter.limit("3 per minute")
def email_signup():
    """Capture email for early-access / marketing list."""
    if request.method == "OPTIONS":
        return "", 204
    try:
        data  = request.get_json(force=True) or {}
        email = (data.get("email") or "").strip().lower()
        if not email or "@" not in email or "." not in email.split("@")[-1]:
            return jsonify({"error": "Please enter a valid email address"}), 400
        is_new = False
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO email_signups (email, source) VALUES (%s, %s) "
                    "ON CONFLICT (email) DO NOTHING RETURNING id",
                    (email, data.get("source", "landing"))
                )
                is_new = cur.fetchone() is not None
                conn.commit()
        logger.info(f"Email signup: {email} (new={is_new})")
        # Send welcome email only for new signups (not duplicate submissions)
        if is_new:
            threading.Thread(
                target=email_service.send_newsletter_welcome_email,
                args=(email,),
                daemon=True,
            ).start()
        return jsonify({"status": "ok", "message": "You're on the list!"})
    except Exception as e:
        logger.error(f"email_signup error: {e}")
        return jsonify({"error": "Server error, please try again"}), 500


ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

def _check_admin(req) -> bool:
    """Return True if the request carries a valid admin token."""
    token = req.headers.get("X-Admin-Token", "")
    return bool(ADMIN_TOKEN and token == ADMIN_TOKEN)


@app.route("/api/admin/email-signups")
def admin_email_signups():
    """Admin: list all newsletter signups as JSON or CSV.
    Usage:
      JSON: GET /api/admin/email-signups?token=ADMIN_TOKEN
      CSV:  GET /api/admin/email-signups?token=ADMIN_TOKEN&format=csv
    """
    if not _check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    fmt = request.args.get("format", "json").lower()
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, email, source, created_at "
                    "FROM email_signups ORDER BY created_at DESC"
                )
                rows = cur.fetchall()
        if fmt == "csv":
            import io, csv
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["id", "email", "source", "signed_up_at"])
            for r in rows:
                writer.writerow([r["id"], r["email"], r["source"],
                                  r["created_at"].strftime("%Y-%m-%d %H:%M:%S UTC")])
            csv_data = output.getvalue()
            from flask import Response
            return Response(
                csv_data,
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment; filename=email-signups.csv"}
            )
        # JSON
        data = [
            {
                "id": r["id"],
                "email": r["email"],
                "source": r["source"],
                "signed_up_at": r["created_at"].strftime("%Y-%m-%d %H:%M:%S UTC"),
            }
            for r in rows
        ]
        return jsonify({"total": len(data), "signups": data})
    except Exception as e:
        logger.error(f"admin_email_signups error: {e}")
        return jsonify({"error": "Server error"}), 500


@app.route("/api/stripe/portal", methods=["POST"])
def customer_portal():
    """Redirect to Stripe Customer Portal to manage subscription."""
    try:
        data = request.get_json(force=True) or {}
        stripe_customer_id = data.get("stripe_customer_id")

        if not stripe_customer_id:
            return jsonify({"error": "stripe_customer_id required"}), 400

        portal = stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url="https://glitchexecutor.com/#pricing"
        )
        return jsonify({"url": portal.url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Glitch Grow buyer ledger ────────────────────────────────────────────────
# Three endpoints called by the Cloudflare Pages fulfillment Function on
# grow.glitchexecutor.com. All three share the same shared-secret gate
# via the `x-fulfill-secret` header, matched against GROW_FULFILL_SECRET
# (the same env var used to authenticate the Pages -> Flask handoff for
# Stripe webhook fulfillment dispatch).

def _check_fulfill_secret() -> bool:
    """Return True iff the inbound request carries the matching shared secret."""
    expected = GROW_FULFILL_SECRET
    if not expected:
        return False
    incoming = request.headers.get("x-fulfill-secret", "")
    return hmac.compare_digest(incoming, expected)


@app.route("/api/grow/record-buyer", methods=["POST"])
def grow_record_buyer():
    """Insert (or update on conflict) a row in glitch_grow_buyers.

    Body:
      provider         'stripe' | 'razorpay'        required
      payment_id       provider's session/payment id  required (UNIQUE)
      sku              'BSK-001'..'BSK-006' or 'BSK-ALL'  required
      email            buyer email                   required
      amount           amount paid in major units    required (e.g. 499 for $499)
      currency         'USD' | 'INR' | ...           required
      github_username  optional
      buyer_name       optional
      promo_code       optional ('GLITCH20' etc.)
      notes            optional dict; merged into JSONB notes column
      fulfilled        optional bool; if true, set fulfilled_at = now()
    """
    if not _check_fulfill_secret():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "bad-request"}), 400

    required = ("provider", "payment_id", "sku", "email", "amount", "currency")
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"ok": False, "error": "missing-fields", "missing": missing}), 400
    if data["provider"] not in ("stripe", "razorpay"):
        return jsonify({"ok": False, "error": "bad-provider"}), 400

    # Belt-and-braces guard: refuse synthetic smoke/verify payment_ids that
    # historically flooded this endpoint (~16K rows over 5 days, 2026-05-07
    # → 2026-05-12). CF Pages grant-access.ts has the primary block; this
    # is a second wall in case the source ever bypasses grant-access and
    # writes here directly. Returns 200 so the caller doesn't retry.
    pid = str(data.get("payment_id", ""))
    em  = str(data.get("email", "")).lower()
    if (pid.startswith("smoke_") or pid.startswith("capi_verify_")
            or em == "smoke-test@glitchexecutor.com"
            or em == "capi-verify@glitchexecutor.com"):
        return jsonify({"ok": True, "no_op": True, "reason": "smoke-or-verify-test-blocked"}), 200

    amount_minor = int(round(float(data["amount"]) * 100))
    fulfilled    = bool(data.get("fulfilled", True))
    notes_json   = json.dumps(data.get("notes") or {})

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO glitch_grow_buyers
                      (payment_id, provider, sku, email, github_username,
                       buyer_name, amount_minor, currency, promo_code, notes,
                       fulfilled_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                            CASE WHEN %s THEN now() ELSE NULL END)
                    ON CONFLICT (payment_id) DO UPDATE
                       SET fulfilled_at  = CASE WHEN EXCLUDED.fulfilled_at IS NOT NULL
                                                THEN EXCLUDED.fulfilled_at
                                                ELSE glitch_grow_buyers.fulfilled_at END,
                           github_username = COALESCE(EXCLUDED.github_username,
                                                      glitch_grow_buyers.github_username),
                           buyer_name      = COALESCE(EXCLUDED.buyer_name,
                                                      glitch_grow_buyers.buyer_name)
                    RETURNING id, created_at, fulfilled_at
                """, (
                    data["payment_id"], data["provider"], data["sku"], data["email"],
                    data.get("github_username"), data.get("buyer_name"),
                    amount_minor, data["currency"], data.get("promo_code"),
                    notes_json, fulfilled,
                ))
                row = cur.fetchone()
                conn.commit()
        # get_db() uses RealDictCursor so `row` is a dict, not a tuple.
        # The previous row[0]/row[1]/row[2] was throwing `KeyError: 0`,
        # which str()'d to "0" and surfaced as "db-error" in the response.
        return jsonify({
            "ok": True,
            "id": row["id"],
            "payment_id": data["payment_id"],
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "fulfilled_at": row["fulfilled_at"].isoformat() if row.get("fulfilled_at") else None,
        })
    except Exception as e:
        logger.error(f"grow_record_buyer failed: {type(e).__name__}: {e}")
        return jsonify({"ok": False, "error": "db-error"}), 500


@app.route("/api/grow/buyers", methods=["GET"])
def grow_list_buyers():
    """Read endpoint for ops dashboard / refund script.

    Query params:
      email      filter by email (exact)
      sku        filter by sku
      payment_id lookup by payment_id (returns at most 1 row)
      limit      default 50, max 500
    """
    if not _check_fulfill_secret():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    where = []
    params = []
    if request.args.get("email"):
        where.append("email = %s")
        params.append(request.args["email"])
    if request.args.get("sku"):
        where.append("sku = %s")
        params.append(request.args["sku"])
    if request.args.get("payment_id"):
        where.append("payment_id = %s")
        params.append(request.args["payment_id"])
    limit = min(int(request.args.get("limit", 50)), 500)

    sql = """
        SELECT id, payment_id, provider, sku, email, github_username,
               buyer_name, amount_minor, currency, promo_code, notes,
               created_at, fulfilled_at, refunded_at
        FROM glitch_grow_buyers
        {where}
        ORDER BY created_at DESC
        LIMIT %s
    """.format(where=("WHERE " + " AND ".join(where)) if where else "")
    params.append(limit)

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        out = []
        for r in rows:
            # get_db() uses RealDictCursor — access by column name, not index.
            out.append({
                "id": r["id"], "payment_id": r["payment_id"],
                "provider": r["provider"], "sku": r["sku"],
                "email": r["email"], "github_username": r["github_username"],
                "buyer_name": r["buyer_name"],
                "amount_minor": r["amount_minor"], "currency": r["currency"],
                "promo_code": r["promo_code"], "notes": r["notes"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "fulfilled_at": r["fulfilled_at"].isoformat() if r["fulfilled_at"] else None,
                "refunded_at": r["refunded_at"].isoformat() if r["refunded_at"] else None,
            })
        return jsonify({"ok": True, "count": len(out), "buyers": out})
    except Exception as e:
        logger.error(f"grow_list_buyers failed: {type(e).__name__}: {e}")
        return jsonify({"ok": False, "error": "db-error"}), 500


@app.route("/api/grow/refund-buyer", methods=["POST"])
def grow_refund_buyer():
    """Mark a buyer record as refunded. Called by scripts/process-refund.mjs
    after the provider-side refund completes."""
    if not _check_fulfill_secret():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "bad-request"}), 400
    payment_id = (data.get("payment_id") or "").strip()
    if not payment_id:
        return jsonify({"ok": False, "error": "missing-payment-id"}), 400
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE glitch_grow_buyers
                       SET refunded_at = now()
                     WHERE payment_id = %s
                    RETURNING id
                """, (payment_id,))
                row = cur.fetchone()
                conn.commit()
        if not row:
            return jsonify({"ok": False, "error": "not-found", "payment_id": payment_id}), 404
        return jsonify({"ok": True, "id": row["id"], "payment_id": payment_id})
    except Exception as e:
        logger.error(f"grow_refund_buyer failed: {e}")
        return jsonify({"ok": False, "error": "db-error"}), 500


# ─── Customer-management endpoints (stubs — bodies in follow-up) ────────────
# Auth: same x-fulfill-secret as the other /api/grow/* endpoints. The dashboard's
# admin_api proxies these and adds the secret server-side; the browser never
# sees it.

@app.route("/api/grow/buyer/<payment_id>/detail", methods=["GET"])
def grow_buyer_detail(payment_id):
    """Joined view: buyer row + Codeberg invite state + Discord membership +
    Resend welcome state + CAPI status. v1 stub returns the raw buyer row plus
    placeholder fulfillment-sink flags so the UI can render the timeline shell.
    """
    if not _check_fulfill_secret():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, payment_id, provider, sku, email, github_username,
                           buyer_name, amount_minor, currency, promo_code, notes,
                           created_at, fulfilled_at, refunded_at
                    FROM glitch_grow_buyers
                    WHERE payment_id = %s
                    LIMIT 1
                """, (payment_id,))
                r = cur.fetchone()
    except Exception as e:
        logger.error(f"grow_buyer_detail failed: {e}")
        return jsonify({"ok": False, "error": "db-error"}), 500

    if not r:
        return jsonify({"ok": False, "error": "not-found"}), 404

    notes = r["notes"] or {}
    buyer = {
        "id": r["id"], "payment_id": r["payment_id"],
        "provider": r["provider"], "sku": r["sku"],
        "email": r["email"], "github_username": r["github_username"],
        "buyer_name": r["buyer_name"],
        "amount_minor": r["amount_minor"], "currency": r["currency"],
        "promo_code": r["promo_code"], "notes": notes,
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "fulfilled_at": r["fulfilled_at"].isoformat() if r["fulfilled_at"] else None,
        "refunded_at": r["refunded_at"].isoformat() if r["refunded_at"] else None,
    }

    # Stub: derive timeline-sink state from whatever `notes` happens to contain.
    # The real implementation will live-poll Codeberg/Discord/Resend.
    sinks = {
        "payment_captured":     {"status": "ok",      "at": buyer["created_at"]},
        "ledger_write":         {"status": "ok",      "at": buyer["created_at"]},
        "welcome_email":        {"status": "ok" if notes.get("welcome_email_id") else "pending",
                                  "message_id": notes.get("welcome_email_id")},
        "codeberg_invite":      {"status": "stub",    "repos": [], "detail": "live-poll TBD"},
        "discord_role":         {"status": "stub",    "linked": bool(notes.get("discord_id"))},
        "capi_meta":            {"status": notes.get("capi_meta_status") or "pending",
                                  "event_id": buyer["payment_id"]},
        "capi_tiktok":          {"status": notes.get("capi_tiktok_status") or "pending",
                                  "event_id": buyer["payment_id"]},
    }

    return jsonify({"ok": True, "stub": True, "buyer": buyer, "sinks": sinks, "activity": []})


@app.route("/api/grow/leads", methods=["GET"])
def grow_list_leads():
    """List Vibe Kit leads. v1 stub returns an empty list — implementation pulls
    from Google Sheet `leads` + Resend `kit-leads` audience and merges by email.
    """
    if not _check_fulfill_secret():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    return jsonify({"ok": True, "stub": True, "leads": [], "count": 0})


@app.route("/api/grow/resend-welcome", methods=["POST"])
def grow_resend_welcome():
    """Re-render + send the welcome email via Resend. v1 stub validates input
    and returns ok=False with stub=True so the UI can wire its mutation without
    actually re-sending until the body lands.
    """
    if not _check_fulfill_secret():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "bad-request"}), 400
    payment_id = (data.get("payment_id") or "").strip()
    if not payment_id:
        return jsonify({"ok": False, "error": "missing-payment-id"}), 400
    return jsonify({"ok": False, "stub": True, "payment_id": payment_id,
                    "error": "not-implemented",
                    "next": "wire Resend template render + send + update notes.welcome_email_id"})


@app.route("/api/grow/reinvite-codeberg", methods=["POST"])
def grow_reinvite_codeberg():
    """Re-fire the Codeberg collaborator invite for a buyer's SKU repos. v1
    stub validates input only.
    """
    if not _check_fulfill_secret():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "bad-request"}), 400
    payment_id = (data.get("payment_id") or "").strip()
    if not payment_id:
        return jsonify({"ok": False, "error": "missing-payment-id"}), 400
    return jsonify({"ok": False, "stub": True, "payment_id": payment_id,
                    "github_username": data.get("github_username"),
                    "error": "not-implemented",
                    "next": "wire Codeberg PUT /repos/{owner}/{repo}/collaborators/{user}"})


@app.route("/api/grow/buyer-note", methods=["POST"])
def grow_buyer_note():
    """Append a free-form note onto glitch_grow_buyers.notes JSONB. Real
    implementation; not a stub — append-only ops note is small + safe.
    """
    if not _check_fulfill_secret():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "bad-request"}), 400
    payment_id = (data.get("payment_id") or "").strip()
    note = (data.get("note") or "").strip()
    if not payment_id or not note:
        return jsonify({"ok": False, "error": "missing-fields"}), 400
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE glitch_grow_buyers
                       SET notes = COALESCE(notes, '{}'::jsonb)
                                   || jsonb_build_object('ops_notes',
                                        COALESCE(notes->'ops_notes', '[]'::jsonb)
                                        || jsonb_build_array(jsonb_build_object(
                                             'at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
                                             'note', %s
                                           )))
                     WHERE payment_id = %s
                    RETURNING id
                """, (note, payment_id))
                row = cur.fetchone()
                conn.commit()
        if not row:
            return jsonify({"ok": False, "error": "not-found"}), 404
        return jsonify({"ok": True, "id": row["id"], "payment_id": payment_id})
    except Exception as e:
        logger.error(f"grow_buyer_note failed: {e}")
        return jsonify({"ok": False, "error": "db-error"}), 500


# ─── Trial Bot Helper Functions ──────────────────────────────────────────────

def _get_performance_text() -> str:
    """Pull live bot stats from PostgreSQL and return formatted HTML."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # Online bots (heartbeat < 5 min ago)
                cur.execute("""
                    SELECT bot,
                           ROUND(EXTRACT(EPOCH FROM (NOW()-last_seen))/60, 1) AS mins_ago
                    FROM bot_heartbeats
                    WHERE bot != 'oracle'
                    ORDER BY bot
                """)
                bots = cur.fetchall() or []

                # Open positions
                cur.execute("SELECT COUNT(*) AS c FROM bot_positions WHERE is_open=TRUE")
                open_pos = (cur.fetchone() or {}).get("c", 0)

                # Today's trade entries
                cur.execute("""
                    SELECT COUNT(*) AS c FROM bot_events
                    WHERE event_type='trade' AND received_at >= CURRENT_DATE
                """)
                today_entries = (cur.fetchone() or {}).get("c", 0)

                # 7-day closed trade win rate
                cur.execute("""
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN exit_reason IS NOT NULL
                                    AND exit_reason NOT LIKE '%STOP%'
                                    AND exit_reason != 'FRIDAY_FLATTEN'
                               THEN 1 ELSE 0 END) AS wins
                    FROM bot_positions
                    WHERE closed_at >= NOW() - INTERVAL '7 days'
                      AND is_open = FALSE
                """)
                wr = cur.fetchone() or {}

        online = [b["bot"] for b in bots if (b["mins_ago"] or 999) < 5]
        lines = ["🤖 <b>Live right now:</b>"]
        lines.append(f"• Bots online: <b>{len(online)}/5</b>"
                     + (f" ({', '.join(online)})" if online else ""))
        lines.append(f"• Open positions: <b>{open_pos}</b>")
        lines.append(f"• Trade entries today: <b>{today_entries}</b>")

        total = wr.get("total") or 0
        wins  = wr.get("wins")  or 0
        if total > 0:
            pct = round(wins / total * 100)
            lines.append(f"• 7-day win rate: <b>{pct}%</b> ({wins}/{total} closed trades)")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"_get_performance_text: {e}")
        return "🤖 Bots are running — check back shortly for live stats."


def _create_trial_checkout_url(telegram_id: int, plan: str):
    """Create a personalised Stripe checkout URL for a trial user."""
    plan = (plan or "general").lower()
    price_id = TRIAL_PRICE_MAP.get(plan, TRIAL_PRICE_MAP["general"])
    try:
        session = stripe.checkout.Session.create(
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url="https://grow.glitchexecutor.com/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="https://glitchexecutor.com/#pricing",
            metadata={
                "tier":        plan,
                "source":      "telegram_trial",
                "telegram_id": str(telegram_id),
            },
        )
        return session.url
    except Exception as e:
        logger.error(f"_create_trial_checkout_url: {e}")
        return None


# ─── 7-Day Trial Sequence Messages ───────────────────────────────────────────

TRIAL_DAY_MESSAGES = {
    # ── Day 1: How the AI Works ──────────────────────────────────────────────
    1: (
        "📚 <b>Day 1: How GlitchExecutor Actually Works</b>\n\n"
        "Hey {name}! Let me show you what's running behind the scenes.\n\n"
        "🧠 <b>The AI Ensemble:</b>\n"
        "Our system runs <b>6 independent AI models</b> on every trade signal:\n\n"
        "1. <b>Trend Follower</b> — detects EMA/SMA crossovers + ADX trend strength\n"
        "2. <b>Mean Reverter</b> — catches oversold/overbought zones via Bollinger Bands + RSI\n"
        "3. <b>Momentum Hunter</b> — spots RSI breakouts with volume confirmation\n"
        "4. <b>Multi-Timeframe</b> — aligns M15, H1, and H4 for trend confirmation\n"
        "5. <b>Volume Profiler</b> — validates signals with ATR volatility + volume spikes\n"
        "6. <b>Session Analyst</b> — adjusts confidence by trading session (London/NY overlap = strongest)\n\n"
        "⚡ <b>How it works:</b>\n"
        "Each model votes BUY, SELL, or HOLD independently. Only when the majority agrees do we act. "
        "No single model can force a trade.\n\n"
        "🛡️ <b>Risk First:</b>\n"
        "Every trade has a hard stop loss. Max 1-2% account risk per trade. No exceptions.\n\n"
        "👉 <b>Try it now:</b> type /analyse BTCUSD in the bot to see a live signal"
    ),

    # ── Day 2: Strategy Deep Dive ────────────────────────────────────────────
    2: (
        "📊 <b>Day 2: The Strategy Behind Every Trade</b>\n\n"
        "{name}, here's exactly how our AI decides <b>when</b> to trade.\n\n"
        "🎯 <b>Entry Checklist:</b>\n"
        "1. 6 AI models must reach majority consensus\n"
        "2. Multi-timeframe alignment (M15 + H1 + H4 agree)\n"
        "3. RSI confirms the move isn't overextended\n"
        "4. ATR confirms enough volatility to profit\n"
        "5. Session timing is favorable (London/NY preferred)\n\n"
        "🛡️ <b>Risk Management:</b>\n"
        "• Stop loss: 1.5–2× ATR from entry\n"
        "• Take profit: 2.5–4R target\n"
        "• Position size: max 1-2% account risk if stopped\n"
        "• Trailing stop activates at 1.5R profit\n\n"
        "📈 <b>System targets:</b>\n"
        "• Win rate: 58–62%\n"
        "• Average R-multiple: ~1.8R\n"
        "• Max drawdown target: &lt;8%\n\n"
        "💡 <b>Pro tip:</b> Use /scan to see signals across all markets at once\n\n"
        "Tomorrow: real live performance numbers from the running system 👇"
    ),

    # ── Day 3: Live Performance + First CTA ──────────────────────────────────
    3: (
        "📊 <b>Day 3: Real Numbers — No BS</b>\n\n"
        "{name}, here's what our AI has been doing while you've been watching.\n\n"
        "{performance}\n\n"
        "This isn't a backtest. These are live results from the same system you're trialing.\n\n"
        "🔥 {usage_line}\n\n"
        "Want these signals to auto-execute on your account? "
        "Our Pro and Elite members don't lift a finger.\n\n"
        "👉 See plans: {checkout_url}\n\n"
        "Or type /performance anytime for a fresh update 👇"
    ),

    # ── Day 4: Social Proof ──────────────────────────────────────────────────
    4: (
        "🏆 <b>Day 4: Why Traders Stay</b>\n\n"
        "{name}, here's what our subscribers say keeps them paying:\n\n"
        "💬 <i>\"The ensemble AI is what sold me. One strategy blows up — "
        "6 models voting together is robust.\"</i>\n\n"
        "💬 <i>\"Best part is transparency. I see every trade, every model vote, "
        "every stop loss. No black box.\"</i>\n\n"
        "💬 <i>\"I was doing manual TA for 3 hours a day. Now I check the bot "
        "in 5 minutes and trade with more confidence.\"</i>\n\n"
        "📊 <b>Our retention numbers speak for themselves:</b>\n"
        "• 94% of subscribers renew after month 1\n"
        "• Average tenure: 8.3 months\n"
        "• Zero platform security incidents since launch\n\n"
        "Your trial ends in <b>3 days</b>. Have you explored all the features?\n\n"
        "Try: /analyse BTCUSD · /scan · /alert BTCUSD above 70000\n\n"
        "👉 Ready to lock in? {checkout_url}"
    ),

    # ── Day 5: Plan Breakdown (accurate features) ────────────────────────────
    5: (
        "⚡ <b>Day 5: Which Plan Fits You?</b>\n\n"
        "{name}, your trial ends in <b>2 days</b>. Here's the full breakdown:\n\n"
        "⭐ <b>Starter — $49/mo</b> (save 20% yearly)\n"
        "• 30 AI analyses/day\n"
        "• Full 6-model signal breakdown\n"
        "• Price alerts &amp; watchlist\n"
        "• Daily 7AM market briefing\n"
        "• Exchange portfolio view\n"
        "• Email support\n\n"
        "🤖 <b>Pro — $149/mo</b> (save 20% yearly)\n"
        "• 100 AI analyses/day\n"
        "• Everything in Starter\n"
        "• Auto-execute trades on your exchange\n"
        "• Real-time execution alerts\n"
        "• Risk management controls\n"
        "• Priority support\n\n"
        "🏢 <b>Elite — $349/mo</b> (save 20% yearly)\n"
        "• Unlimited analyses\n"
        "• Everything in Pro\n"
        "• Dedicated MT5 bots on your VPS\n"
        "• 24/7 automated broker trading\n"
        "• Custom bot configuration\n"
        "• Priority support &amp; onboarding\n\n"
        "❓ <b>Quick answers:</b>\n"
        "<b>Can I withdraw anytime?</b> Yes. Your money stays in your broker account.\n"
        "<b>What if the bot loses?</b> Every trade has a stop loss. Max drawdown target 8%.\n"
        "<b>Can I turn bots off?</b> Yes, full control anytime.\n\n"
        "👉 Choose your plan: {checkout_url}"
    ),

    # ── Day 6: Urgency ───────────────────────────────────────────────────────
    6: (
        "⏰ <b>Day 6: Tomorrow Is Your Last Day</b>\n\n"
        "{name}, your trial ends <b>tomorrow at midnight UTC</b>.\n\n"
        "After that you'll lose access to:\n"
        "❌ AI trade analysis (6-model ensemble)\n"
        "❌ Real-time signal alerts\n"
        "❌ Daily market briefings\n"
        "❌ Price alerts &amp; watchlist\n\n"
        "{usage_summary}\n\n"
        "The AI keeps running for subscribers. Don't miss the next signal.\n\n"
        "👉 <b>Lock in your plan now:</b> {checkout_url}\n\n"
        "Or wait until tomorrow for your final offer 👇"
    ),

    # ── Day 7: Final Day ─────────────────────────────────────────────────────
    7: (
        "🚨 <b>Final Day: Your Trial Ends Today</b>\n\n"
        "{name}, this is it. Your 7-day trial ends at midnight UTC.\n\n"
        "In 7 days you've seen:\n"
        "✅ How 6 AI models analyze every trade\n"
        "✅ Real live performance data\n"
        "✅ The risk management strategy\n"
        "✅ Plan options that fit your style\n\n"
        "{usage_summary}\n\n"
        "👉 <b>Continue with {plan_label}:</b> {checkout_url}\n\n"
        "Questions? Just reply here — our team responds within hours.\n\n"
        "— The GlitchExecutor Team 🤖"
    ),

    # ── Day 8: Trial Expired — Gentle Reminder ───────────────────────────────
    8: (
        "👋 {name}, your trial ended yesterday.\n\n"
        "Your account is now read-only — you can still see past analyses "
        "but can't run new ones.\n\n"
        "Meanwhile, our AI ran <b>{signals_since} signals</b> since your trial ended. "
        "Here's what subscribers saw:\n\n"
        "{recent_signals}\n\n"
        "Miss it? Pick up where you left off:\n"
        "👉 {checkout_url}\n\n"
        "No commitment — cancel anytime."
    ),

    # ── Day 10: Value Recap ──────────────────────────────────────────────────
    10: (
        "📊 {name}, quick update from the markets.\n\n"
        "Since your trial ended, here's what's been happening:\n\n"
        "{recent_signals}\n\n"
        "Our subscribers acted on these. You could too.\n\n"
        "👉 Restart access: {checkout_url}\n\n"
        "Starter is just $49/mo — less than a single bad trade."
    ),

    # ── Day 14: Final Re-engagement ──────────────────────────────────────────
    14: (
        "💡 {name}, one last note.\n\n"
        "It's been a week since your trial ended. Our AI ensemble has been running "
        "non-stop — analyzing markets 24/7 across every major asset.\n\n"
        "If you're still trading manually, you already know how much time it takes. "
        "Our 6 models do in seconds what takes hours of chart analysis.\n\n"
        "👉 Ready when you are: {checkout_url}\n\n"
        "This is the last automated message. If you ever want to come back, "
        "just type /plans in the bot.\n\n"
        "All the best,\n"
        "The GlitchExecutor Team"
    ),
}


# ─── Dynamic Data Helpers for Trial Messages ─────────────────────────────────

def _get_user_usage_stats(telegram_id: int) -> dict:
    """Get trial usage stats for a user from the customers/query_log tables."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) AS total_queries,
                           COUNT(DISTINCT symbol) AS distinct_symbols,
                           array_agg(DISTINCT symbol) AS symbols
                    FROM query_log ql
                    JOIN customers c ON c.id = ql.customer_id
                    WHERE c.telegram_id = %s
                """, (telegram_id,))
                row = cur.fetchone()
                if row and row['total_queries'] and int(row['total_queries']) > 0:
                    symbols = [s for s in (row['symbols'] or []) if s]
                    return {
                        "total_queries": int(row['total_queries']),
                        "distinct_symbols": int(row['distinct_symbols'] or 0),
                        "symbols": symbols,
                        "has_activity": True,
                    }
    except Exception as e:
        logger.error(f"_get_user_usage_stats failed: {e}")
    return {"total_queries": 0, "distinct_symbols": 0, "symbols": [], "has_activity": False}


def _get_recent_signals(limit: int = 3) -> str:
    """Get recent actionable BUY/SELL signals for re-engagement messages."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT symbol, consensus, confidence, created_at
                    FROM ensemble_predictions
                    WHERE consensus IN ('BUY', 'SELL')
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (limit,))
                rows = cur.fetchall() or []
        if not rows:
            return "🔍 Multiple signals generated — upgrade to see them."
        lines = []
        for r in rows:
            emoji = '🟢' if r['consensus'] == 'BUY' else '🔴'
            conf = round(float(r.get('confidence', 0)) * 100)
            lines.append(f"{emoji} <b>{r['symbol']}</b>: {r['consensus']} ({conf}% confidence)")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"_get_recent_signals failed: {e}")
        return "🔍 Multiple signals generated — upgrade to see them."


def _user_has_paid(telegram_id: int) -> bool:
    """Check if user has an active paid subscription (skip re-engagement)."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tier FROM customers WHERE telegram_id = %s AND status = 'active'",
                    (telegram_id,)
                )
                row = cur.fetchone()
                return bool(row and row['tier'] not in ('trial',))
    except Exception:
        return False


def _send_trial_day_message(user: dict, day_num: int):
    """Send the day_num trial sequence message to a user and log it."""
    telegram_id = user.get("telegram_id")
    if not telegram_id:
        return

    name       = user.get("name") or "trader"
    plan       = (user.get("plan") or "general").lower()
    plan_label = PLAN_LABELS.get(plan, "Starter ($49/mo)")

    template = TRIAL_DAY_MESSAGES.get(day_num)
    if not template:
        return

    # Build format kwargs with all dynamic fields
    kwargs = {
        "name":           name,
        "plan":           plan,
        "plan_label":     plan_label,
        "performance":    "",
        "checkout_url":   "",
        "usage_line":     "",
        "usage_summary":  "",
        "recent_signals": "",
        "signals_since":  "several",
    }

    # Dynamic performance data (Day 3)
    if day_num == 3:
        kwargs["performance"] = _get_performance_text()

    # Checkout URLs (Days 3+ all get checkout links)
    if day_num >= 3:
        url = _create_trial_checkout_url(telegram_id, plan)
        kwargs["checkout_url"] = url or "https://glitchexecutor.com/#pricing"

    # Usage stats (Days 3, 6, 7)
    if day_num in (3, 6, 7):
        stats = _get_user_usage_stats(telegram_id)
        if stats["has_activity"]:
            kwargs["usage_line"] = (
                f"You've already run {stats['total_queries']} analyses "
                f"across {stats['distinct_symbols']} symbols this trial!"
            )
            syms = ", ".join(stats["symbols"][:5])
            kwargs["usage_summary"] = (
                f"During your trial, you ran <b>{stats['total_queries']} analyses</b> "
                f"across {syms}."
            )
        else:
            kwargs["usage_line"] = (
                "You haven't tried an analysis yet — "
                "type /analyse BTCUSD to see the AI in action!"
            )
            kwargs["usage_summary"] = (
                "You haven't used your analyses yet — "
                "there's still time! Try /analyse BTCUSD"
            )

    # Recent signals (Days 8, 10, 14 — post-trial re-engagement)
    if day_num in (8, 10, 14):
        kwargs["recent_signals"] = _get_recent_signals(3)
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT COUNT(*) AS c FROM ensemble_predictions
                        WHERE consensus IN ('BUY', 'SELL')
                          AND created_at >= NOW() - INTERVAL '24 hours'
                    """)
                    row = cur.fetchone()
                    count = (row or {}).get("c", 0)
                    kwargs["signals_since"] = str(count) if count else "several"
        except Exception:
            pass

    # Send dual-channel emails on key conversion days
    if day_num == 3:
        email = user.get("email")
        if email:
            try:
                email_service.send_trial_day3_email(
                    email, name, kwargs["performance"]
                )
            except Exception as e:
                logger.warning(f"Day 3 email failed (non-fatal): {e}")

    if day_num == 5:
        email = user.get("email")
        if email:
            try:
                email_service.send_trial_day5_email(
                    email, name, kwargs["checkout_url"]
                )
            except Exception as e:
                logger.warning(f"Day 5 email failed (non-fatal): {e}")

    try:
        message = template.format(**kwargs)
    except (KeyError, IndexError) as e:
        logger.error(f"trial day {day_num} format error: {e}")
        message = template

    tg_send(telegram_id, message)

    # Log it — ON CONFLICT DO NOTHING prevents double-send
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO trial_messages_log (telegram_id, day_num) "
                    "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (telegram_id, day_num)
                )
                conn.commit()
    except Exception as e:
        logger.error(f"trial_messages_log insert failed: {e}")

    logger.info(f"Trial day {day_num} sent → tg:{telegram_id} ({name})")


def _send_daily_trial_messages():
    """
    Daily job at 12:00 UTC: send the next pending trial sequence message
    to each registered user within 15-day window (7 trial + 8 re-engagement).
    Skips users who have already upgraded to a paid plan.
    """
    # Days that have message templates (not sequential — gaps are intentional)
    VALID_DAYS = [1, 2, 3, 4, 5, 6, 7, 8, 10, 14]

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT tu.*,
                           EXTRACT(DAY FROM (NOW() - tu.trial_started_at))::int AS days_elapsed,
                           COALESCE(
                               (SELECT array_agg(day_num ORDER BY day_num)
                                FROM trial_messages_log
                                WHERE telegram_id = tu.telegram_id),
                               ARRAY[]::int[]
                           ) AS sent_days
                    FROM telegram_users tu
                    WHERE tu.state = 'registered'
                      AND tu.trial_started_at IS NOT NULL
                      AND tu.trial_started_at > NOW() - INTERVAL '15 days'
                """)
                users = cur.fetchall() or []

        sent_total = 0
        skipped_paid = 0
        for user in users:
            tg_id = user.get("telegram_id")
            days_elapsed = int(user.get("days_elapsed") or 0)
            sent_days    = list(user.get("sent_days") or [])

            # Skip users who already upgraded to a paid plan
            if _user_has_paid(tg_id):
                skipped_paid += 1
                continue

            for day_num in VALID_DAYS:
                if day_num <= days_elapsed and day_num not in sent_days:
                    _send_trial_day_message(dict(user), day_num)
                    sent_total += 1

        logger.info(
            f"_send_daily_trial_messages: {len(users)} users checked, "
            f"{sent_total} messages sent, {skipped_paid} paid users skipped"
        )

    except Exception as e:
        logger.error(f"_send_daily_trial_messages failed: {e}")


# ─── Inactive User Nudge ─────────────────────────────────────────────────────

def _send_inactive_nudges():
    """
    Daily job at 15:00 UTC: nudge trial users who haven't run any analysis
    in 48+ hours. Only nudge once per user (uses trial_messages_log day_num=99).
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # Find trial users with 0 queries in last 48h who haven't been nudged
                cur.execute("""
                    SELECT tu.telegram_id, tu.name,
                           EXTRACT(DAY FROM (NOW() - tu.trial_started_at))::int AS days_elapsed
                    FROM telegram_users tu
                    WHERE tu.state = 'registered'
                      AND tu.trial_started_at IS NOT NULL
                      AND tu.trial_started_at > NOW() - INTERVAL '7 days'
                      AND tu.trial_started_at < NOW() - INTERVAL '1 day'
                      AND NOT EXISTS (
                          SELECT 1 FROM trial_messages_log tml
                          WHERE tml.telegram_id = tu.telegram_id AND tml.day_num = 99
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM customers c
                          JOIN query_log ql ON ql.customer_id = c.id
                          WHERE c.telegram_id = tu.telegram_id
                            AND ql.created_at >= NOW() - INTERVAL '48 hours'
                      )
                """)
                users = cur.fetchall() or []

        for user in users:
            name = user.get("name") or "trader"
            days_left = max(0, 7 - int(user.get("days_elapsed", 0)))
            tg_id = user["telegram_id"]

            if days_left <= 0:
                continue  # Trial already expired, skip nudge

            tg_send(tg_id,
                f"👋 Hey {name}! You haven't used GlitchExecutor in a while.\n\n"
                f"Your trial has <b>{days_left} day{'s' if days_left != 1 else ''} left</b> "
                f"— don't let it go to waste!\n\n"
                f"Try one of these right now:\n"
                f"• Type <b>BTCUSD</b> — instant AI analysis\n"
                f"• /scan — see all market signals at once\n"
                f"• /alert BTCUSD above 70000 — get notified when price hits your target\n\n"
                f"Our 6 AI models are analyzing markets 24/7. Let them work for you 🤖"
            )

            # Log as day_num=99 to prevent double-send
            try:
                with get_db() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO trial_messages_log (telegram_id, day_num) "
                            "VALUES (%s, 99) ON CONFLICT DO NOTHING",
                            (tg_id,)
                        )
                        conn.commit()
            except Exception:
                pass

            logger.info(f"Inactive nudge sent → tg:{tg_id} ({name})")

    except Exception as e:
        logger.error(f"_send_inactive_nudges failed: {e}")


# ─── Trial Ending Reminder Scheduler ─────────────────────────────────────────

def _send_trial_reminders():
    """
    Daily job: find trial accounts expiring in 1-3 days and send reminder emails.
    Uses SELECT … FOR UPDATE SKIP LOCKED so multiple gunicorn workers don't double-send.
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE customers
                       SET trial_reminder_sent_at = NOW()
                       WHERE id IN (
                           SELECT id FROM customers
                           WHERE status = 'trial'
                             AND trial_ends_at > NOW()
                             AND trial_ends_at <= NOW() + INTERVAL '3 days'
                             AND email IS NOT NULL
                             AND trial_reminder_sent_at IS NULL
                           FOR UPDATE SKIP LOCKED
                       )
                       RETURNING email,
                                 EXTRACT(EPOCH FROM (trial_ends_at - NOW()))/86400 AS days_left""",
                )
                rows = cur.fetchall()
                conn.commit()

        for row in rows:
            email   = row["email"]
            days    = max(1, int(row["days_left"]) + 1)  # round up to nearest day
            email_service.send_trial_reminder_email(to_email=email, days_left=days)
            logger.info(f"Trial reminder sent → {email} ({days} days left)")

    except Exception as e:
        logger.error(f"_send_trial_reminders failed: {e}")


def _start_scheduler():
    """Start the APScheduler background scheduler (safe with gunicorn --preload)."""
    scheduler = BackgroundScheduler(timezone="UTC")
    # Email reminders for paying customers nearing trial end
    scheduler.add_job(_send_trial_reminders, "cron", hour=9, minute=0,
                      id="trial_reminders", replace_existing=True)
    # Trial + post-trial Telegram sequence (Days 1-7 + 8, 10, 14)
    scheduler.add_job(_send_daily_trial_messages, "cron", hour=12, minute=0,
                      id="trial_sequence", replace_existing=True)
    # Inactive user nudge — trial users with no activity in 48h
    scheduler.add_job(_send_inactive_nudges, "cron", hour=15, minute=0,
                      id="inactive_nudges", replace_existing=True)
    scheduler.start()
    logger.info(
        "Scheduler started: trial_reminders@09:00, "
        "trial_sequence@12:00, inactive_nudges@15:00 UTC"
    )
    return scheduler


# Run migrations + start scheduler when module is loaded by gunicorn
_run_bot_migrations()
_scheduler = _start_scheduler()


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("GlitchExecutor Payment Server starting on port 5002")
    app.run(host="0.0.0.0", port=5002, debug=False)
