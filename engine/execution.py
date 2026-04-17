"""Order execution engine (PAPER MODE ONLY)."""
import logging
from typing import Optional, Set

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

logger = logging.getLogger("ai_broker.execution")


class ExecutionEngine:
    def __init__(self, api_key: str, api_secret: str, db):
        self.client = TradingClient(
            api_key=api_key,
            secret_key=api_secret,
            paper=True,  # CRITICAL
        )
        self.db = db
        logger.info("ExecutionEngine initialized - PAPER MODE ONLY")

    # ============================================================
    # ACCOUNT
    # ============================================================

    def get_account(self) -> Optional[dict]:
        try:
            account = self.client.get_account()
            return {
                "equity": float(account.equity),
                "cash": float(account.cash),
                "buying_power": float(account.buying_power),
            }
        except Exception as e:
            logger.error(f"Failed to get account: {e}")
            return None

    # ============================================================
    # ORDERS
    # ============================================================

    def submit_order(
        self,
        *,
        symbol: str,
        side,
        quantity: int,
    ) -> Optional[dict]:
        try:
            if isinstance(side, int):
                side = "buy" if side > 0 else "sell"
            elif isinstance(side, str):
                side = side.lower().strip()
            else:
                raise ValueError(f"Invalid side type: {side}")

            if side not in ("buy", "sell"):
                raise ValueError(f"Invalid side: {side}")

            qty = int(quantity)
            if qty <= 0:
                raise ValueError(f"Invalid quantity: {qty}")

            alpaca_side = OrderSide.BUY if side == "buy" else OrderSide.SELL

            order = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=alpaca_side,
                time_in_force=TimeInForce.DAY,
            )

            result = self.client.submit_order(order)

            logger.info(f"Submitted {side.upper()} order: {symbol} qty={qty}")

            return {
                "order_id": str(result.id),
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "submitted_at": str(result.submitted_at),
            }

        except Exception as e:
            logger.error(f"Order submit failed for {symbol}: {e}")
            return None

    # ============================================================
    # POSITIONS
    # ============================================================

    def close_position(self, symbol: str) -> Optional[dict]:
        try:
            result = self.client.close_position(symbol)
            logger.info(f"Closed broker position: {symbol}")
            return {
                "order_id": str(result.id),
                "symbol": symbol,
                "submitted_at": str(result.submitted_at),
            }
        except Exception as e:
            logger.error(f"Close position failed for {symbol}: {e}")
            return None

    def get_live_broker_symbols(self) -> Set[str]:
        try:
            positions = self.client.get_all_positions()
            return {p.symbol for p in positions}
        except Exception as e:
            logger.warning(f"Failed to fetch broker positions: {e}")
            return set()

    # ============================================================
    # MAINTENANCE
    # ============================================================

    def check_and_update_orders(self):
        """
        Lightweight maintenance pass each loop.
        """
        self.reconcile_positions()

    def reconcile_positions(self):
        """
        Broker truth should win.

        1) If DB has open trades for symbols no longer live at broker, close them in DB.
        2) If broker has live symbols missing from DB, warn loudly so drift is visible.
        """
        try:
            broker_positions = self.client.get_all_positions()
            live_symbols = {p.symbol for p in broker_positions}

            db_open_positions = self.db.get_open_positions()
            db_open_symbols = {p.get("symbol") for p in db_open_positions if p.get("symbol")}

            stale_count = 0
            for pos in db_open_positions:
                symbol = pos.get("symbol")
                trade_id = pos.get("id")

                if not symbol or trade_id is None:
                    continue

                if symbol not in live_symbols:
                    entry_price = float(pos.get("entry_price", 0) or 0)
                    cluster_id = pos.get("cluster_id")

                    self.db.close_trade(
                        trade_id=trade_id,
                        exit_price=entry_price,
                        pnl=0.0,
                        cluster_id=cluster_id,
                    )
                    stale_count += 1
                    logger.warning(
                        f"Reconcile closed stale DB trade: id={trade_id} symbol={symbol}"
                    )

            broker_only_symbols = sorted(live_symbols - db_open_symbols)
            if broker_only_symbols:
                logger.warning(
                    f"Broker-only live positions not present in DB: {broker_only_symbols}"
                )

            db_only_symbols = sorted(db_open_symbols - live_symbols)
            if db_only_symbols:
                logger.warning(
                    f"DB-only open trades not present at broker before cleanup: {db_only_symbols}"
                )

            logger.info(
                f"Reconciled {len(broker_positions)} broker positions | "
                f"{len(db_open_positions)} DB open trades checked | "
                f"{stale_count} stale DB trades closed | "
                f"broker_symbols={sorted(live_symbols)} | "
                f"db_symbols={sorted(db_open_symbols)}"
            )

        except Exception as e:
            logger.warning(f"Reconcile failed: {e}")
