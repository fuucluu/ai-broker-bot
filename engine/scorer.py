"""Trade signal scoring with AI memory integration and exploratory bootstrap."""
import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
import pandas as pd

from engine.persistence import Database
from engine.patterns import PatternRecognizer
from engine.features import get_feature_vector, get_market_regime

logger = logging.getLogger("ai_broker.scorer")


@dataclass
class TradeSignal:
    symbol: str
    side: str
    score: float
    cluster_id: int
    cluster_quality: str
    expectancy: float
    confidence: float
    reason: str
    features: Dict


class Scorer:
    def __init__(self, db: Database, pattern_recognizer: PatternRecognizer, config: Dict):
        self.db = db
        self.patterns = pattern_recognizer

        clustering_cfg = config.get("clustering", {})
        self.min_trades = clustering_cfg.get("min_cluster_trades", 30)
        self.min_expectancy = clustering_cfg.get("min_expectancy", 0.001)

        # 🔒 Safety caps for exploratory trades
        self.max_exploratory_per_cluster = clustering_cfg.get(
            "max_exploratory_trades", 1
        )
        self.min_exploratory_expectancy = clustering_cfg.get(
            "min_exploratory_expectancy", -0.002
        )

    # ============================================================
    # ENTRY EVALUATION
    # ============================================================

    def evaluate_entry(
        self,
        symbol: str,
        features: pd.DataFrame,
        spy_features: pd.DataFrame = None,
    ) -> Optional[TradeSignal]:

        if features is None or len(features) < 1:
            return None

        vector = get_feature_vector(features)
        if vector is None:
            return None

        # 🔁 Always add sample (learning never stops)
        self.patterns.add_sample(vector)

        cluster_id = self.patterns.predict_cluster(vector)
        if cluster_id is None:
            return None

        # ------------------------------------------------------------
        # CLUSTER GATE (STRICT → EXPLORATORY FALLBACK)
        # ------------------------------------------------------------

        should_trade, reason = self.patterns.should_trade_cluster(
            cluster_id, self.min_trades, self.min_expectancy
        )

        cluster_stats = self.patterns.get_cluster_quality(cluster_id)

        # 🔍 Option A: Exploratory trade bootstrap
        exploratory = False
        if not should_trade:
            if (
                cluster_stats["trades"] < self.min_trades
                and cluster_stats["expectancy"] >= self.min_exploratory_expectancy
            ):
                exploratory_count = self.db.get_cluster_exploratory_count(cluster_id)
                if exploratory_count < self.max_exploratory_per_cluster:
                    exploratory = True
                    reason = "Exploratory bootstrap trade"
                else:
                    logger.debug(
                        f"{symbol} cluster {cluster_id}: exploratory cap reached"
                    )
                    return None
            else:
                logger.debug(f"{symbol} cluster {cluster_id}: {reason}")
                return None

        # ------------------------------------------------------------
        # SCORE CALCULATION
        # ------------------------------------------------------------

        symbol_stats = self.db.get_symbol_stats(symbol)
        score = self._calculate_score(features, cluster_stats, symbol_stats)

        side = self._determine_side(features)

        if spy_features is not None:
            regime = get_market_regime(spy_features)
            score = self._apply_regime_adjustment(score, side, regime)

        # 🔒 Score floor
        if score < 0.3:
            return None

        confidence = self._calculate_confidence(cluster_stats, symbol_stats)

        # ------------------------------------------------------------
        # LOGGING (IMPORTANT)
        # ------------------------------------------------------------

        if exploratory:
            logger.info(
                f"[EXPLORATORY] {symbol} cluster={cluster_id} "
                f"score={score:.2f} exp={cluster_stats['expectancy']:.4f}"
            )

        return TradeSignal(
            symbol=symbol,
            side=side,
            score=score,
            cluster_id=cluster_id,
            cluster_quality=cluster_stats["quality"],
            expectancy=cluster_stats["expectancy"],
            confidence=confidence,
            reason=reason,
            features={
                "rsi": features.iloc[-1].get("rsi14", 50),
                "ema_spread": features.iloc[-1].get("ema_spread", 0),
                "atr_pct": features.iloc[-1].get("atr_pct", 1),
                "volume_zscore": features.iloc[-1].get("volume_zscore", 0),
            },
        )

    # ============================================================
    # SCORING HELPERS
    # ============================================================

    def _calculate_score(
        self,
        features: pd.DataFrame,
        quality: Dict,
        symbol_stats: Optional[Dict],
    ) -> float:
        score = 0.5
        row = features.iloc[-1]

        # Cluster quality
        if quality["quality"] == "excellent":
            score += 0.3
        elif quality["quality"] == "good":
            score += 0.2
        elif quality["quality"] == "marginal":
            score += 0.1

        if quality["win_rate"] > 0.6:
            score += 0.15
        elif quality["win_rate"] > 0.55:
            score += 0.1

        if quality["expectancy"] > 0.02:
            score += 0.1

        rsi = row.get("rsi14", 50)
        if 30 < rsi < 70:
            score += 0.05

        vol_z = row.get("volume_zscore", 0)
        if vol_z > 1:
            score += 0.05

        if symbol_stats:
            trades = max(symbol_stats["total_trades"], 1)
            sym_wr = symbol_stats["wins"] / trades

            if trades > 10 and sym_wr > 0.55:
                score += 0.1

            if symbol_stats["consecutive_losses"] >= 3:
                score -= 0.2

        return min(max(score, 0.0), 1.0)

    def _determine_side(self, features: pd.DataFrame) -> str:
        row = features.iloc[-1]

        ema_spread = row.get("ema_spread", 0)
        rsi = row.get("rsi14", 50)
        ret_1bar = row.get("ret_1bar", 0)

        bull = 0
        bear = 0

        bull += ema_spread > 0.2
        bear += ema_spread < -0.2

        bull += rsi > 50
        bear += rsi <= 50

        bull += ret_1bar > 0
        bear += ret_1bar <= 0

        return "buy" if bull > bear else "sell"

    def _apply_regime_adjustment(self, score: float, side: str, regime: str) -> float:
        if regime == "high_volatility":
            score *= 0.7
        elif regime == "uptrend" and side == "buy":
            score *= 1.1
        elif regime == "downtrend" and side == "sell":
            score *= 1.1
        elif regime == "uptrend" and side == "sell":
            score *= 0.8
        elif regime == "downtrend" and side == "buy":
            score *= 0.8

        return min(score, 1.0)

    def _calculate_confidence(
        self, quality: Dict, symbol_stats: Optional[Dict]
    ) -> float:
        confidence = 0.5

        if quality["trades"] >= 100:
            confidence += 0.2
        elif quality["trades"] >= 50:
            confidence += 0.1

        if quality["win_rate"] > 0.55:
            confidence += 0.15

        if symbol_stats and symbol_stats["total_trades"] >= 20:
            wr = symbol_stats["wins"] / symbol_stats["total_trades"]
            if wr > 0.5:
                confidence += 0.1

        return min(confidence, 1.0)

    # ============================================================
    # EXIT LOGIC (UNCHANGED)
    # ============================================================

    def should_exit(
        self,
        symbol: str,
        entry_price: float,
        current_price: float,
        side: str,
        features: pd.DataFrame,
    ) -> Tuple[bool, str]:

        if features is None or len(features) < 1:
            return False, ""

        row = features.iloc[-1]
        atr_pct = row.get("atr_pct", 1)

        if side == "buy":
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
        else:
            pnl_pct = ((entry_price - current_price) / entry_price) * 100

        if pnl_pct < -atr_pct * 2:
            return True, f"Stop loss hit ({pnl_pct:.2f}%)"

        if pnl_pct > atr_pct * 3:
            return True, f"Take profit hit ({pnl_pct:.2f}%)"

        if pnl_pct > atr_pct * 1.5:
            rsi = row.get("rsi14", 50)
            if side == "buy" and rsi > 75:
                return True, "Overbought exit"
            if side == "sell" and rsi < 25:
                return True, "Oversold exit"

        return False, ""
