from fastapi import APIRouter, Depends
from auth import get_current_user
from db import get_pg

router = APIRouter()

PLANS = [
    {
        "id": "starter",
        "name": "Starter",
        "price_mo": 49,
        "price_yr": 470,
        "analyses": 30,
        "execution": False,
        "tagline": "Learn to read AI signals",
    },
    {
        "id": "pro",
        "name": "Pro",
        "price_mo": 149,
        "price_yr": 1430,
        "analyses": 100,
        "execution": "testnet",
        "tagline": "Validate strategies risk-free",
    },
    {
        "id": "elite",
        "name": "Elite",
        "price_mo": 349,
        "price_yr": 3350,
        "analyses": -1,
        "execution": "live",
        "tagline": "Deploy a live bot. Trade while you sleep.",
    },
]

TIER_PRICES = {"starter": 49, "pro": 149, "elite": 349}


@router.get("/summary")
def summary(current_user: dict = Depends(get_current_user)):
    conn = get_pg()
    cur = conn.cursor()

    cur.execute("""
        SELECT tier, COUNT(*) AS cnt
        FROM customers
        WHERE status='active'
        GROUP BY tier
    """)
    active_by_tier = {row["tier"]: row["cnt"] for row in cur.fetchall()}

    cur.execute("SELECT COUNT(*) AS cnt FROM customers WHERE status='active'")
    total_active = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(*) AS cnt FROM customers WHERE tier='trial'")
    total_trial = cur.fetchone()["cnt"]

    cur.close()
    conn.close()

    mrr = sum(TIER_PRICES.get(tier, 0) * cnt for tier, cnt in active_by_tier.items())
    arr = mrr * 12

    by_tier_detail = {}
    for plan in PLANS:
        pid = plan["id"]
        count = active_by_tier.get(pid, 0)
        by_tier_detail[pid] = {
            "count": count,
            "revenue": TIER_PRICES.get(pid, 0) * count,
            "price_mo": plan["price_mo"],
        }

    return {
        "mrr_usd": mrr,
        "arr_usd": arr,
        "total_active": total_active,
        "total_trial": total_trial,
        "by_tier": by_tier_detail,
    }


@router.get("/plans")
def plans(current_user: dict = Depends(get_current_user)):
    conn = get_pg()
    cur = conn.cursor()
    cur.execute("SELECT tier, COUNT(*) AS cnt FROM customers WHERE status='active' GROUP BY tier")
    counts = {row["tier"]: row["cnt"] for row in cur.fetchall()}
    cur.close()
    conn.close()

    result = []
    for plan in PLANS:
        p = dict(plan)
        p["subscriber_count"] = counts.get(plan["id"], 0)
        result.append(p)
    return result


@router.get("/email-signups")
def email_signups(page: int = 1, limit: int = 50, current_user: dict = Depends(get_current_user)):
    conn = get_pg()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS cnt FROM email_signups")
    total = cur.fetchone()["cnt"]

    offset = (page - 1) * limit
    cur.execute("""
        SELECT id, email, source, signed_up_at
        FROM email_signups
        ORDER BY signed_up_at DESC
        LIMIT %s OFFSET %s
    """, (limit, offset))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    return {"total": total, "page": page, "limit": limit, "signups": rows}
