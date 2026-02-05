"""Portfolio manager: opens/closes positions and keeps DB consistent."""
import logging
from typing import Optional

from engine.persistence import Database
from engine.execution import ExecutionEngine
from engine.data_feed import DataFeed

logger = logging.getLogger("ai_broker.portfolio")


class PortfolioManager:
    def __init__(self, db: Database, execution: ExecutionEngine, data_feed: DataFeed):
        self.db = db
        self.execution = execution
        self.data_feed = data_feed

    # ============================================================
    # OPEN POSITION
    # ============================================================

    def open_position(
        self,
        *,
        symbol: str,
        side: str,
        qty: int,
        price: float,
        cluster_id: Optional[int] = None,
        exploratory: bool = True,
    ) -> Optional[int]:
        """
        Open a new position:
        1) submit broker order
        2) record trade in DB
        """
        # Submit order (KEYWORD-ONLY, SAFE)
        result = self.execution.submit_order(
            symbol=symbol,
            side=side,
            quantity=qty,
        )

        if not result:
            logger.warning(f"Execution failed for {symbol}")
            return None

        # Record trade in DB
        self.db.insert_trade(
            symbol=symbol,
            side=side,
            qty=qty,
            entry_price=price,
            cluster_id=cluster_id,
            exploratory=exploratory,
        )

        logger.info(
            f"Portfolio OPEN {symbol} {side.upper()} qty={qty} @ {price:.2f}"
        )
        return 1  # simple success indicator

    # ============================================================
    # CLOSE POSITION
    # ============================================================

    def close_position(self, symbol: str) -> Optional[float]:
        """
        Close an existing open position and record P&L.
        """
        # Find open DB position
        db_pos = self.db.get_position_by_symbol(symbol)
        if not db_pos:
            logger.warning(f"No open DB position for {symbol}")
            return None

        # Get latest price
        current_price = self.data_feed.get_latest_price(symbol)
        if current_price is None:
            logger.error(f"Cannot get latest price for {symbol}")
            return None

        # Calculate P&L
        if db_pos["side"] == "buy":
            pnl = (current_price - db_pos["entry_price"]) * db_pos["qty"]
        else:
            pnl = (db_pos["entry_price"] - current_price) * db_pos["qty"]

        # Submit close order
        result = self.execution.close_position(symbol)
        if not result:
            logger.error(f"Failed to close broker position for {symbol}")
            return None

        # Update DB
        self.db.close_trade(
            trade_id=db_pos["id"],
            exit_price=current_price,
            pnl=pnl,
            cluster_id=db_pos.get("cluster_id"),
        )

        # Update symbol stats
        self.db.update_symbol_stats(symbol, pnl)

        logger.info(
            f"Portfolio CLOSE {symbol} @ {current_price:.2f} PnL={pnl:.2f}"
        )
        return pnl
