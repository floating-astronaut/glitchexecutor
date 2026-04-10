"""
AI Analytics API — Ensemble prediction performance analytics.
All endpoints require JWT auth.
"""
import json
import os
from itertools import combinations
from fastapi import APIRouter, Depends, Query
import redis

from auth import get_current_user
from db import get_pg


def _get_redis():
    return redis.Redis(
        host=os.environ.get("REDIS_HOST", "redis"),
        port=int(os.environ.get("REDIS_PORT", 6379)),
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )

router = APIRouter()

MODELS = [
    "TrendFollower", "MeanReverter", "MomentumHunter",
    "MLPredictor", "MultiTFAlign", "VolumeProfiler", "SessionAnalyst",
]


# ── GET /api/analytics/overview ───────────────────────────────────────────────

@router.get("/overview")
def overview(days: int = Query(7), current_user: dict = Depends(get_current_user)):
    """KPI summary: total predictions, avg confidence, win rates per horizon."""
    conn = get_pg()
    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*) AS total,
               ROUND(AVG(consensus_confidence)::NUMERIC, 1) AS avg_conf
        FROM ensemble_predictions
        WHERE predicted_at > NOW() - (%s * INTERVAL '1 day')
    """, (days,))
    row = cur.fetchone()
    total = row["total"]
    avg_conf = float(row["avg_conf"] or 0)

    win_rates: dict[str, float | None] = {}
    for hz in ["1h", "4h", "24h"]:
        cur.execute("""
            SELECT
              COUNT(*) FILTER (WHERE po.direction_correct = TRUE) AS wins,
              COUNT(*) AS total
            FROM prediction_outcomes po
            JOIN ensemble_predictions ep ON ep.id = po.prediction_id
            WHERE po.horizon = %s
              AND ep.predicted_at > NOW() - (%s * INTERVAL '1 day')
        """, (hz, days))
        r = cur.fetchone()
        t = r["total"]
        win_rates[hz] = round(100.0 * r["wins"] / t, 1) if t > 0 else None

    cur.execute("""
        SELECT consensus, COUNT(*) AS cnt
        FROM ensemble_predictions
        WHERE predicted_at > NOW() - (%s * INTERVAL '1 day')
        GROUP BY consensus
    """, (days,))
    consensus_breakdown = {r["consensus"]: r["cnt"] for r in cur.fetchall()}

    cur.close()
    conn.close()
    return {
        "total_predictions": total,
        "avg_confidence": avg_conf,
        "win_rate_1h":  win_rates.get("1h"),
        "win_rate_4h":  win_rates.get("4h"),
        "win_rate_24h": win_rates.get("24h"),
        "consensus_breakdown": consensus_breakdown,
    }


# ── GET /api/analytics/timeline ───────────────────────────────────────────────

@router.get("/timeline")
def timeline(days: int = Query(7), current_user: dict = Depends(get_current_user)):
    """Time-bucketed confidence trend (hourly for ≤7d, daily for 30d)."""
    conn = get_pg()
    cur = conn.cursor()

    trunc = "day" if days > 7 else "hour"
    cur.execute(f"""
        SELECT
          DATE_TRUNC('{trunc}', predicted_at) AS bucket,
          ROUND(AVG(consensus_confidence)::NUMERIC, 1) AS avg_conf,
          MODE() WITHIN GROUP (ORDER BY consensus) AS consensus,
          COUNT(*) AS count
        FROM ensemble_predictions
        WHERE predicted_at > NOW() - (%s * INTERVAL '1 day')
        GROUP BY 1
        ORDER BY 1
    """, (days,))

    result = []
    for r in cur.fetchall():
        result.append({
            "time":       r["bucket"].isoformat(),
            "confidence": float(r["avg_conf"] or 0),
            "consensus":  r["consensus"],
            "count":      r["count"],
        })

    cur.close()
    conn.close()
    return result


# ── GET /api/analytics/model-accuracy ─────────────────────────────────────────

@router.get("/model-accuracy")
def model_accuracy(days: int = Query(7), current_user: dict = Depends(get_current_user)):
    """Per-model win rate at 1h / 4h / 24h from model_scores JSONB."""
    conn = get_pg()
    cur = conn.cursor()

    result = {m: {"1h": None, "4h": None, "24h": None} for m in MODELS}

    for hz in ["1h", "4h", "24h"]:
        cur.execute("""
            SELECT po.model_scores
            FROM prediction_outcomes po
            JOIN ensemble_predictions ep ON ep.id = po.prediction_id
            WHERE po.horizon = %s
              AND ep.predicted_at > NOW() - (%s * INTERVAL '1 day')
              AND po.model_scores IS NOT NULL
        """, (hz, days))
        rows = cur.fetchall()

        wins   = {m: 0 for m in MODELS}
        totals = {m: 0 for m in MODELS}
        for row in rows:
            scores = row["model_scores"]
            if not isinstance(scores, dict):
                continue
            for m in MODELS:
                if m in scores and scores[m] is not None:
                    totals[m] += 1
                    if scores[m]:
                        wins[m] += 1

        for m in MODELS:
            result[m][hz] = round(100.0 * wins[m] / totals[m], 1) if totals[m] > 0 else None

    cur.close()
    conn.close()
    return result


# ── GET /api/analytics/confidence-distribution ────────────────────────────────

@router.get("/confidence-distribution")
def confidence_distribution(days: int = Query(7), current_user: dict = Depends(get_current_user)):
    """Histogram of consensus_confidence in 10-point buckets (0–100)."""
    conn = get_pg()
    cur = conn.cursor()

    cur.execute("""
        SELECT
          (FLOOR(consensus_confidence / 10) * 10)::int AS bucket,
          COUNT(*) AS count
        FROM ensemble_predictions
        WHERE predicted_at > NOW() - (%s * INTERVAL '1 day')
          AND consensus_confidence IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """, (days,))

    buckets = {r["bucket"]: r["count"] for r in cur.fetchall()}
    result = [
        {"range": f"{b}–{b + 10}%", "count": buckets.get(b, 0)}
        for b in range(0, 100, 10)
    ]

    cur.close()
    conn.close()
    return result


# ── GET /api/analytics/correlation ────────────────────────────────────────────

@router.get("/correlation")
def correlation(days: int = Query(7), current_user: dict = Depends(get_current_user)):
    """Pairwise model vote-agreement matrix (% of predictions where both voted the same)."""
    conn = get_pg()
    cur = conn.cursor()

    cur.execute("""
        SELECT votes
        FROM ensemble_predictions
        WHERE predicted_at > NOW() - (%s * INTERVAL '1 day')
          AND votes IS NOT NULL
    """, (days,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    agree: dict[tuple, int] = {}
    total: dict[tuple, int] = {}

    for row in rows:
        votes_raw = row["votes"]
        # psycopg2 returns JSONB as Python dict/list already
        if not isinstance(votes_raw, list):
            continue
        vote_map = {
            v["model"]: v["vote"]
            for v in votes_raw
            if isinstance(v, dict) and "model" in v and "vote" in v
        }
        models_present = [m for m in MODELS if m in vote_map]
        for m1, m2 in combinations(models_present, 2):
            key = (m1, m2)
            total[key] = total.get(key, 0) + 1
            if vote_map[m1] == vote_map[m2]:
                agree[key] = agree.get(key, 0) + 1

    matrix: dict[str, dict[str, float | None]] = {}
    for m in MODELS:
        matrix[m] = {}
        for m2 in MODELS:
            if m == m2:
                matrix[m][m2] = 100.0
            else:
                key = tuple(sorted([m, m2]))
                t = total.get(key, 0)
                a = agree.get(key, 0)
                matrix[m][m2] = round(100.0 * a / t, 1) if t > 0 else None

    return {"models": MODELS, "matrix": matrix}


# ── GET /api/analytics/history ────────────────────────────────────────────────

@router.get("/history")
def history(
    days:  int = Query(7),
    limit: int = Query(100),
    current_user: dict = Depends(get_current_user),
):
    """Full prediction history joined with 1h/4h outcomes for the detail table."""
    conn = get_pg()
    cur = conn.cursor()

    cur.execute("""
        SELECT
          ep.id, ep.symbol, ep.predicted_at,
          ep.price_at_prediction,
          ep.consensus, ep.consensus_confidence,
          ep.sentiment_direction, ep.votes,
          (SELECT direction_correct FROM prediction_outcomes
           WHERE prediction_id = ep.id AND horizon = '1h'  LIMIT 1) AS correct_1h,
          (SELECT price_change_pct  FROM prediction_outcomes
           WHERE prediction_id = ep.id AND horizon = '1h'  LIMIT 1) AS pct_1h,
          (SELECT direction_correct FROM prediction_outcomes
           WHERE prediction_id = ep.id AND horizon = '4h'  LIMIT 1) AS correct_4h,
          (SELECT price_change_pct  FROM prediction_outcomes
           WHERE prediction_id = ep.id AND horizon = '4h'  LIMIT 1) AS pct_4h
        FROM ensemble_predictions ep
        WHERE ep.predicted_at > NOW() - (%s * INTERVAL '1 day')
        ORDER BY ep.predicted_at DESC
        LIMIT %s
    """, (days, limit))

    rows = []
    for r in cur.fetchall():
        votes_raw = r["votes"] or []
        if not isinstance(votes_raw, list):
            votes_raw = []
        bullish = sum(1 for v in votes_raw if isinstance(v, dict) and v.get("vote") == "BUY")
        bearish = sum(1 for v in votes_raw if isinstance(v, dict) and v.get("vote") == "SELL")
        rows.append({
            "id":                 r["id"],
            "symbol":             r["symbol"],
            "predicted_at":       r["predicted_at"].isoformat(),
            "price":              float(r["price_at_prediction"]) if r["price_at_prediction"] else None,
            "consensus":          r["consensus"],
            "confidence":         float(r["consensus_confidence"]) if r["consensus_confidence"] else None,
            "sentiment_direction": r["sentiment_direction"],
            "bullish_count":      bullish,
            "bearish_count":      bearish,
            "correct_1h":         r["correct_1h"],
            "pct_1h":             float(r["pct_1h"])  if r["pct_1h"]  is not None else None,
            "correct_4h":         r["correct_4h"],
            "pct_4h":             float(r["pct_4h"])  if r["pct_4h"]  is not None else None,
        })

    cur.close()
    conn.close()
    return rows


# ── GET /api/analytics/live ───────────────────────────────────────────────────

@router.get("/live")
def live_ensemble(current_user: dict = Depends(get_current_user)):
    """
    Live ensemble state from Redis.
    For every active symbol returns: price, consensus, confidence,
    per-model votes, sentiment, TTL remaining.
    """
    try:
        rc = _get_redis()
        keys = rc.keys("ensemble:*")
    except Exception:
        return []

    result = []
    for key in sorted(keys):
        symbol = key.replace("ensemble:", "")
        try:
            raw = rc.get(key)
            if not raw:
                continue
            data = json.loads(raw)
        except Exception:
            continue

        # Price
        price = None
        try:
            p = rc.get(f"price:{symbol}")
            price = float(p) if p else None
        except Exception:
            pass

        # Sentiment
        sentiment_direction = None
        sentiment_score = None
        try:
            s = rc.get(f"sentiment:{symbol}")
            if s:
                sd = json.loads(s)
                sentiment_direction = sd.get("direction")
                sentiment_score = sd.get("score")
        except Exception:
            pass

        # TTL
        ttl = None
        try:
            ttl = rc.ttl(key)
        except Exception:
            pass

        # Votes → per-model dict
        votes_raw = data.get("votes", [])
        if isinstance(votes_raw, str):
            try:
                votes_raw = json.loads(votes_raw)
            except Exception:
                votes_raw = []
        vote_map: dict[str, str] = {}
        for v in votes_raw:
            if isinstance(v, dict) and "model" in v:
                vote_map[v["model"]] = v.get("vote", "HOLD")

        result.append({
            "symbol":              symbol,
            "price":               price,
            "consensus":           data.get("consensus"),
            "confidence":          data.get("confidence"),
            "breakdown":           data.get("breakdown"),
            "votes":               vote_map,
            "sentiment_direction": sentiment_direction,
            "sentiment_score":     sentiment_score,
            "updated_at":          data.get("updated_at"),
            "ttl_seconds":         ttl,
        })

    return sorted(result, key=lambda x: x["symbol"])
