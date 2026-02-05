"""
News intelligence module.

This module is OPTIONAL.
If disabled in config, it will never block trading.
"""
import logging
from typing import Dict, List

logger = logging.getLogger("ai_broker.news")


class NewsIntelligence:
    def __init__(self, config: dict, db):
        """
        config: full app config dict
        db: Database instance
        """
        self.db = db
        self.config = config.get("news", {}) if isinstance(config, dict) else {}
        self.enabled = bool(self.config.get("enabled", False))

        if not self.enabled:
            logger.info("News intelligence disabled")
        else:
            logger.info("News intelligence enabled")

    def process_news(self, symbols: List[str]) -> Dict:
        """
        Process news and return trading directives.

        Returns:
        {
            "alerts": [str],
            "should_pause": bool
        }
        """
        if not self.enabled:
            return {"alerts": [], "should_pause": False}

        alerts: List[str] = []

        # Placeholder for future real news ingestion
        # This is intentionally conservative: never block trades yet
        try:
            # Example stub:
            # alerts.append("Fed announcement detected")
            pass
        except Exception as e:
            logger.warning(f"News processing error: {e}")

        return {
            "alerts": alerts,
            "should_pause": False,
        }
