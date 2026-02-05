"""Persistent storage layer for AI Broker."""
import sqlite3
import threading
from typing import Dict, Optional, List
from datetime import datetime
import logging

logger = logging.getLogger("ai_broker.persistence")


class Database:
    def __init__(self, db_path: str = "ai_broker.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._initialize_schema()

    # ============================================================
    # SCHEMA
    # ============================================================

    def _initialize_schema(self):
        with self._lock:
            cur = self.conn.cursor()

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    pnl REAL,
                    cluster_id INTEGER,
                    exploratory INTEGER DEFAULT 0
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS symbol_stats (
                    symbol TEXT PRIMARY KEY,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    total_trades INTEGER DEFAULT 0,
                    consecutive_losses INTEGER DEFAULT 0
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS cluster_stats (
                    cluster_id INTEGER PRIMARY KEY,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    total_trades INTEGER DEFAULT 0,
                    avg_win REAL DEFAULT 0.0,
                    avg_loss REAL DEFAULT 0.0,
                    expectancy REAL DEFAULT 0.0
                )
                """
            )

            self.conn.commit()

    # ============================================================
    # DAILY / RISK SUPPORT
    # ============================================================

    def get_daily_pnl(self) -> float:
        today = datetime.utcnow().date().isoformat()
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                """
                SELECT COALESCE(SUM(pnl), 0.0)
                FROM trades
                WHERE pnl IS NOT NULL
                  AND DATE(timestamp) = ?
                """,
                (today,),
            )
            return float(cur.fetchone()[0])

    def get_trades_today(self) -> int:
        today = datetime.utcnow().date().isoformat()
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                """
                SELECT COUNT(*)
                FROM trades
                WHERE DATE(timestamp) = ?
                """,
                (today,),
            )
            return int(cur.fetchone()[0])

    def get_open_positions(self) -> List[Dict]:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                """
                SELECT *
                FROM trades
                WHERE exit_price IS NULL
                """
            )
            return [dict(row) for row in cur.fetchall()]

    def get_position_by_symbol(self, symbol: str) -> Optional[Dict]:
        """Return open position for symbol, or None."""
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                """
                SELECT *
                FROM trades
                WHERE symbol = ?
                  AND exit_price IS NULL
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (symbol,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    # ============================================================
    # CLUSTER STATS
    # ============================================================

    def get_cluster_stats(self, cluster_id: int) -> Dict:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT * FROM cluster_stats WHERE cluster_id = ?",
                (cluster_id,),
            )
            row = cur.fetchone()

            if row:
                return dict(row)

            return {
                "cluster_id": cluster_id,
                "wins": 0,
                "losses": 0,
                "total_trades": 0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "expectancy": 0.0,
            }

    def update_cluster_stats(self, cluster_id: int, pnl: float):
        with self._lock:
            cur = self.conn.cursor()
            stats = self.get_cluster_stats(cluster_id)

            wins = stats["wins"]
            losses = stats["losses"]
            avg_win = stats["avg_win"]
            avg_loss = stats["avg_loss"]

            if pnl > 0:
                wins += 1
                avg_win = (avg_win * stats["wins"] + pnl) / max(wins, 1)
            else:
                losses += 1
                avg_loss = (avg_loss * stats["losses"] + abs(pnl)) / max(losses, 1)

            total = wins + losses
            expectancy = (
                (wins / total) * avg_win - (losses / total) * avg_loss
                if total > 0
                else 0.0
            )

            cur.execute(
                """
                INSERT INTO cluster_stats (
                    cluster_id, wins, losses, total_trades,
                    avg_win, avg_loss, expectancy
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cluster_id) DO UPDATE SET
                    wins = excluded.wins,
                    losses = excluded.losses,
                    total_trades = excluded.total_trades,
                    avg_win = excluded.avg_win,
                    avg_loss = excluded.avg_loss,
                    expectancy = excluded.expectancy
                """,
                (cluster_id, wins, losses, total, avg_win, avg_loss, expectancy),
            )

            self.conn.commit()

    # ============================================================
    # EXPLORATORY SUPPORT
    # ============================================================

    def get_cluster_exploratory_count(self, cluster_id: int) -> int:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                """
                SELECT COUNT(*)
                FROM trades
                WHERE cluster_id = ?
                  AND exploratory = 1
                """,
                (cluster_id,),
            )
            return int(cur.fetchone()[0])

    # ============================================================
    # TRADES
    # ============================================================

    def insert_trade(
        self,
        symbol: str,
        side: str,
        qty: float,
        entry_price: float,
        cluster_id: Optional[int],
        exploratory: bool = False,
    ):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                """
                INSERT INTO trades (
                    timestamp, symbol, side, qty,
                    entry_price, cluster_id, exploratory
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.utcnow().isoformat(),
                    symbol,
                    side,
                    qty,
                    entry_price,
                    cluster_id,
                    1 if exploratory else 0,
                ),
            )
            self.conn.commit()

    def close_trade(
        self,
        trade_id: int,
        exit_price: float,
        pnl: float,
        cluster_id: Optional[int],
    ):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                """
                UPDATE trades
                SET exit_price = ?, pnl = ?
                WHERE id = ?
                """,
                (exit_price, pnl, trade_id),
            )

            if cluster_id is not None:
                self.update_cluster_stats(cluster_id, pnl)

            self.conn.commit()

    # ============================================================
    # SYMBOL STATS
    # ============================================================

    def get_symbol_stats(self, symbol: str) -> Optional[Dict]:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT * FROM symbol_stats WHERE symbol = ?",
                (symbol,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def update_symbol_stats(self, symbol: str, pnl: float):
        with self._lock:
            cur = self.conn.cursor()
            stats = self.get_symbol_stats(symbol)
            win = pnl > 0

            if not stats:
                cur.execute(
                    """
                    INSERT INTO symbol_stats (
                        symbol, wins, losses, total_trades, consecutive_losses
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (symbol, 1 if win else 0, 0 if win else 1, 1, 0 if win else 1),
                )
            else:
                wins = stats["wins"] + (1 if win else 0)
                losses = stats["losses"] + (0 if win else 1)
                total = stats["total_trades"] + 1
                consecutive = 0 if win else stats["consecutive_losses"] + 1

                cur.execute(
                    """
                    UPDATE symbol_stats
                    SET wins=?, losses=?, total_trades=?, consecutive_losses=?
                    WHERE symbol=?
                    """,
                    (wins, losses, total, consecutive, symbol),
                )

            self.conn.commit()

    # ============================================================
    # SHUTDOWN
    # ============================================================

    def close(self):
        with self._lock:
            self.conn.close()
