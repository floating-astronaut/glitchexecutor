"""
GlitchExecutor Ensemble — Outcome Database Helper
Reads pending predictions and writes outcomes for ML fine-tuning.
Uses synchronous psycopg2 to match the rest of the ensemble container.
"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional

try:
    import psycopg2
    import psycopg2.extras
    PG_AVAILABLE = True
except ImportError:
    PG_AVAILABLE = False

logger = logging.getLogger("OutcomeDB")

HORIZONS = [
    ("1h",  1),
    ("4h",  4),
    ("24h", 24),
]


class OutcomeDB:
    """Minimal synchronous DB access for prediction outcome tracking."""

    def __init__(self, database_url: str = None):
        self.database_url = database_url or os.environ.get(
            "DATABASE_URL",
            "postgresql://glitch:changeme@postgres:5432/glitchexecutor"
        )
        self._conn = None

    def connect(self) -> bool:
        if not PG_AVAILABLE:
            logger.error("psycopg2 not installed — outcome tracking disabled")
            return False
        try:
            self._conn = psycopg2.connect(
                self.database_url,
                cursor_factory=psycopg2.extras.RealDictCursor
            )
            self._conn.autocommit = False
            logger.info("OutcomeDB connected")
            return True
        except Exception as e:
            logger.error(f"OutcomeDB connection failed: {e}")
            return False

    def _ensure_connected(self):
        try:
            if self._conn is None or self._conn.closed:
                self.connect()
            else:
                # Test connection is alive
                with self._conn.cursor() as cur:
                    cur.execute("SELECT 1")
        except Exception:
            self.connect()

    def get_pending_predictions(self, horizon: str, hours: int) -> List[Dict]:
        """
        Return predictions that are old enough for this horizon
        but don't yet have an outcome recorded for it.
        """
        self._ensure_connected()
        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            with self._conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ep.id, ep.symbol, ep.predicted_at,
                           ep.price_at_prediction, ep.consensus, ep.votes
                    FROM   ensemble_predictions ep
                    WHERE  ep.predicted_at <= %s
                      AND  ep.consensus IN ('BUY', 'SELL')
                      AND  NOT EXISTS (
                              SELECT 1 FROM prediction_outcomes po
                              WHERE  po.prediction_id = ep.id
                                AND  po.horizon = %s
                           )
                    ORDER  BY ep.predicted_at
                    LIMIT  200
                    """,
                    (cutoff, horizon)
                )
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error(f"get_pending_predictions({horizon}): {e}")
            return []

    def save_outcome(self, prediction_id: int, horizon: str,
                     price_at_outcome: float, price_change_pct: float,
                     direction_correct: bool, model_scores: Dict) -> bool:
        """Insert outcome row (ON CONFLICT DO NOTHING for idempotency)."""
        self._ensure_connected()
        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO prediction_outcomes
                        (prediction_id, horizon, price_at_outcome,
                         price_change_pct, direction_correct, model_scores)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (prediction_id, horizon) DO NOTHING
                    """,
                    (prediction_id, horizon, price_at_outcome,
                     price_change_pct, direction_correct,
                     json.dumps(model_scores))
                )
            self._conn.commit()
            return True
        except Exception as e:
            self._conn.rollback()
            logger.error(f"save_outcome({prediction_id}, {horizon}): {e}")
            return False
