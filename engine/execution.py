"""Order execution engine (PAPER MODE ONLY)."""
import logging
from typing import Optional

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
    # ORDERS (KEYWORD-ONLY, IMMUTABLE API)
    # ============================================================

    def submit_order(
        self,
        *,
        symbol: str,
        side,
        quantity: int,
    ) -> Optional[dict]:
        """
        Submit a market order in PAPER MODE.

        Keyword-only args prevent ordering bugs forever.
        """
        try:
            # Normalize side
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
                "order_id": result.id,
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
            logger.info(f"Closed position: {symbol}")
            return {
                "order_id": result.id,
                "symbol": symbol,
                "submitted_at": str(result.submitted_at),
            }
        except Exception as e:
            logger.error(f"Close position failed for {symbol}: {e}")
            return None

    def check_and_update_orders(self):
        return

    def reconcile_positions(self):
        try:
            positions = self.client.get_all_positions()
            logger.info(f"Reconciled {len(positions)} broker positions")
        except Exception as e:
            logger.warning(f"Reconcile failed: {e}")
