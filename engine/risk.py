"""Risk management governor - NON-BYPASSABLE."""
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from engine.persistence import Database
from engine.utils import kill_switch_active

logger = logging.getLogger("ai_broker.risk")


@dataclass
class RiskLimits:
    risk_per_trade_pct: float = 1.0
    max_daily_loss_pct: float = 2.0
    max_trades_per_day: int = 5
    max_positions: int = 5
    max_exposure_pct: float = 50.0
    cooldown_after_trade_seconds: int = 60
    cooldown_after_loss_seconds: int = 300
    volatility_pause_atr_mult: float = 3.0


class RiskGovernor:
    """Non-bypassable risk management system."""

    def __init__(self, db: Database, config: Dict, account_value: float = 100000):
        self.db = db
        self.account_value = account_value
        self.limits = self._load_limits(config.get("risk", {}))

        self._last_trade_time: Optional[datetime] = None
        self._last_loss_time: Optional[datetime] = None
        self._paused_symbols: Dict[str, datetime] = {}
        self._volatility_pause_until: Optional[datetime] = None

        # Track per-symbol trade counts (future-proof)
        self._symbol_trade_counts: Dict[str, int] = {}

    # ============================================================
    # CONFIG
    # ============================================================

    def _load_limits(self, config: Dict) -> RiskLimits:
        return RiskLimits(
            risk_per_trade_pct=config.get("risk_per_trade_pct", 1.0),
            max_daily_loss_pct=config.get("max_daily_loss_pct", 2.0),
            max_trades_per_day=config.get("max_trades_per_day", 5),
            max_positions=config.get("max_positions", 5),
            max_exposure_pct=config.get("max_exposure_pct", 50.0),
            cooldown_after_trade_seconds=config.get("cooldown_after_trade_seconds", 60),
            cooldown_after_loss_seconds=config.get("cooldown_after_loss_seconds", 300),
            volatility_pause_atr_mult=config.get("volatility_pause_atr_mult", 3.0),
        )

    # ============================================================
    # STATE UPDATES
    # ============================================================

    def update_account_value(self, value: float):
        """Update current account value."""
        self.account_value = value

    # ============================================================
    # TRADE PERMISSION CHECKS
    # ============================================================

    def can_trade(self) -> Tuple[bool, str]:
        """Master check if trading is allowed."""
        if kill_switch_active():
            return False, "KILL SWITCH ACTIVE - STOP_TRADING file detected"

        daily_pnl = self.db.get_daily_pnl()
        max_daily_loss = self.account_value * (self.limits.max_daily_loss_pct / 100)
        if daily_pnl <= -max_daily_loss:
            return False, f"Daily loss limit reached: ${daily_pnl:.2f}"

        trades_today = self.db.get_trades_today()
        if trades_today >= self.limits.max_trades_per_day:
            return False, f"Daily trade limit reached: {trades_today}/{self.limits.max_trades_per_day}"

        open_positions = len(self.db.get_open_positions())
        if open_positions >= self.limits.max_positions:
            return False, f"Position limit reached: {open_positions}/{self.limits.max_positions}"

        if self._last_trade_time:
            elapsed = (datetime.now() - self._last_trade_time).total_seconds()
            if elapsed < self.limits.cooldown_after_trade_seconds:
                return False, f"Trade cooldown: {int(self.limits.cooldown_after_trade_seconds - elapsed)}s remaining"

        if self._last_loss_time:
            elapsed = (datetime.now() - self._last_loss_time).total_seconds()
            if elapsed < self.limits.cooldown_after_loss_seconds:
                return False, f"Loss cooldown: {int(self.limits.cooldown_after_loss_seconds - elapsed)}s remaining"

        if self._volatility_pause_until:
            if datetime.now() < self._volatility_pause_until:
                return False, "Volatility pause active"
            self._volatility_pause_until = None

        return True, "OK"

    def can_trade_symbol(self, symbol: str) -> Tuple[bool, str]:
        can, reason = self.can_trade()
        if not can:
            return False, reason

        if symbol in self._paused_symbols:
            if datetime.now() < self._paused_symbols[symbol]:
                return False, f"{symbol} temporarily paused"
            del self._paused_symbols[symbol]

        if self.db.get_position_by_symbol(symbol):
            return False, f"Already have position in {symbol}"

        stats = self.db.get_symbol_stats(symbol)
        if stats and stats.get("consecutive_losses", 0) >= 5:
            self.pause_symbol(symbol, minutes=60)
            return False, f"{symbol} has 5+ consecutive losses"

        return True, "OK"

    # ============================================================
    # POSITION SIZING
    # ============================================================

    def calculate_position_size(
        self, price: float, atr: float, confidence: float = 0.5
    ) -> Tuple[int, float]:
        risk_pct = self.limits.risk_per_trade_pct * confidence
        risk_amount = self.account_value * (risk_pct / 100)

        stop_distance = atr * 2 if atr > 0 else price * 0.02
        shares = int(risk_amount / stop_distance)

        max_value = (
            self.account_value
            * (self.limits.max_exposure_pct / 100)
            / self.limits.max_positions
        )
        max_shares = int(max_value / price)

        shares = max(1, min(shares, max_shares))
        return shares, shares * price

    # ============================================================
    # TRADE RECORDING  ✅ FIXED
    # ============================================================

    def record_trade(self, symbol: str):
        """Record that a trade was executed."""
        self._last_trade_time = datetime.now()
        self._symbol_trade_counts[symbol] = self._symbol_trade_counts.get(symbol, 0) + 1

    def record_loss(self):
        """Record that a loss occurred."""
        self._last_loss_time = datetime.now()

    # ============================================================
    # PAUSES
    # ============================================================

    def pause_symbol(self, symbol: str, minutes: int = 30):
        self._paused_symbols[symbol] = datetime.now() + timedelta(minutes=minutes)
        logger.info(f"Paused {symbol} for {minutes} minutes")

    def trigger_volatility_pause(self, minutes: int = 15):
        self._volatility_pause_until = datetime.now() + timedelta(minutes=minutes)
        logger.warning(f"Volatility pause triggered for {minutes} minutes")

    def check_volatility(self, spy_atr_pct: float, normal_atr_pct: float = 1.0) -> bool:
        if spy_atr_pct > normal_atr_pct * self.limits.volatility_pause_atr_mult:
            self.trigger_volatility_pause()
            return True
        return False

    # ============================================================
    # DASHBOARD
    # ============================================================

    def get_risk_status(self) -> Dict:
        daily_pnl = self.db.get_daily_pnl()
        trades_today = self.db.get_trades_today()
        open_positions = len(self.db.get_open_positions())

        max_daily_loss = self.account_value * (self.limits.max_daily_loss_pct / 100)
        loss_pct_used = (
            abs(min(0, daily_pnl)) / max_daily_loss * 100
            if max_daily_loss > 0
            else 0
        )

        can_trade, reason = self.can_trade()

        return {
            "can_trade": can_trade,
            "reason": reason,
            "daily_pnl": daily_pnl,
            "daily_loss_limit": -max_daily_loss,
            "loss_pct_used": loss_pct_used,
            "trades_today": trades_today,
            "max_trades": self.limits.max_trades_per_day,
            "open_positions": open_positions,
            "max_positions": self.limits.max_positions,
            "paused_symbols": list(self._paused_symbols.keys()),
            "kill_switch": kill_switch_active(),
        }

    # ============================================================
    # NEWS ADJUSTMENT
    # ============================================================

    def apply_news_risk_adjustment(self, base_size: int, reduction_pct: float) -> int:
        adjusted = int(base_size * (1 - reduction_pct / 100))
        return max(1, adjusted)
