"""
GlitchExecutor Ensemble — Outcome Checker
Runs every hour; looks up what actually happened to past predictions
and records per-model accuracy for ML ensemble fine-tuning.

Data flow:
  ensemble_predictions  →  outcome_checker  →  prediction_outcomes
                               ↑
                          Redis price cache (current price per symbol)

Per-model scoring logic:
  - BUY/SELL vote: correct if price moved in predicted direction
  - HOLD vote: always marked neutral (not penalised, not rewarded)
  - model_scores JSONB: {model_name: true|false|null}
"""
import json
import logging
import time
import threading
from typing import Optional

from outcome_db import OutcomeDB, HORIZONS

logger = logging.getLogger("OutcomeChecker")


class OutcomeChecker:
    """Checks prediction outcomes and stores per-model accuracy."""

    def __init__(self, cache, database_url: str = None):
        """
        Args:
            cache: EnsembleCache instance (for reading current prices from Redis)
            database_url: PostgreSQL connection string
        """
        self.cache = cache
        self.db = OutcomeDB(database_url)
        self._connected = False

    def _ensure_db(self) -> bool:
        if not self._connected:
            self._connected = self.db.connect()
        return self._connected

    def _score_model_vote(self, model_vote: str, consensus: str,
                          price_went_up: bool) -> Optional[bool]:
        """
        Return True (correct), False (wrong), or None (HOLD — neutral).
        A model is 'correct' when its vote matched the direction the market moved.
        """
        if model_vote == 'HOLD':
            return None
        if model_vote == 'BUY':
            return price_went_up
        if model_vote == 'SELL':
            return not price_went_up
        return None

    def check_all_horizons(self):
        """Check all three horizons (1h, 4h, 24h) in one pass."""
        if not self._ensure_db():
            logger.warning("OutcomeChecker: DB not available, skipping")
            return

        total_saved = 0

        for horizon_label, hours in HORIZONS:
            pending = self.db.get_pending_predictions(horizon_label, hours)
            if not pending:
                continue

            logger.info(f"[{horizon_label}] Checking {len(pending)} pending predictions")
            saved = 0

            for row in pending:
                symbol = row['symbol']
                entry_price = float(row['price_at_prediction'])
                consensus = row['consensus']

                # Get current price from Redis
                current_price = self.cache.read_price(symbol)
                if not current_price or current_price <= 0:
                    logger.debug(f"[{horizon_label}] No price for {symbol}, skipping")
                    continue

                price_change_pct = (current_price - entry_price) / entry_price * 100
                price_went_up = current_price > entry_price

                direction_correct = (
                    (consensus == 'BUY'  and price_went_up) or
                    (consensus == 'SELL' and not price_went_up)
                )

                # Score each model individually
                votes = row.get('votes') or []
                if isinstance(votes, str):
                    try:
                        votes = json.loads(votes)
                    except Exception:
                        votes = []

                model_scores = {}
                for vote in votes:
                    model_name = vote.get('model', 'unknown')
                    model_vote = vote.get('vote', 'HOLD')
                    model_scores[model_name] = self._score_model_vote(
                        model_vote, consensus, price_went_up
                    )

                ok = self.db.save_outcome(
                    prediction_id=row['id'],
                    horizon=horizon_label,
                    price_at_outcome=current_price,
                    price_change_pct=round(price_change_pct, 4),
                    direction_correct=direction_correct,
                    model_scores=model_scores
                )
                if ok:
                    saved += 1

            logger.info(
                f"[{horizon_label}] Saved {saved}/{len(pending)} outcomes "
                f"({'%.0f' % (saved/len(pending)*100 if pending else 0)}%)"
            )
            total_saved += saved

        if total_saved:
            logger.info(f"OutcomeChecker: {total_saved} outcomes recorded this run")

    def start_background_thread(self, interval_seconds: int = 3600):
        """Launch a daemon thread that calls check_all_horizons() every hour."""
        def loop():
            # Initial delay so the engine settles first
            time.sleep(60)
            while True:
                try:
                    self.check_all_horizons()
                except Exception as e:
                    logger.error(f"OutcomeChecker loop error: {e}")
                time.sleep(interval_seconds)

        t = threading.Thread(target=loop, name="OutcomeChecker", daemon=True)
        t.start()
        logger.info(f"OutcomeChecker started (interval={interval_seconds}s)")
        return t
