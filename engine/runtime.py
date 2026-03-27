"""Main runtime engine for AI Broker."""
import os
import time
import logging
from typing import Dict, List, Optional
from datetime import datetime

from reporter import send_report

from engine.utils import (
    load_config, load_symbols, setup_logging,
    kill_switch_active, check_paper_mode_safety, print_banner
)
from engine.persistence import Database
from engine.market_hours import is_market_open, should_trade, get_market_status, time_until_open
from engine.data_feed import DataFeed
from engine.features import extract_features
from engine.patterns import PatternRecognizer
from engine.scorer import Scorer
from engine.execution import ExecutionEngine
from engine.portfolio import PortfolioManager
from engine.risk import RiskGovernor
from engine.news import NewsIntelligence

logger = logging.getLogger("ai_broker.runtime")


class TradingEngine:
    def __init__(self, config_path: str = "config/settings.yaml"):
        self.config = load_config(config_path)
        self.symbols = load_symbols(self.config.get("symbols_file", "config/symbols.txt"))

        setup_logging(self.config.get("logging", {}))

        check_paper_mode_safety(self.config)

        db_path = self.config.get("database", {}).get("path", "ai_broker.db")
        self.db = Database(db_path)

        api_key = os.environ.get("ALPACA_API_KEY", "")
        api_secret = os.environ.get("ALPACA_API_SECRET", "")
        if not api_key or not api_secret:
            raise RuntimeError("ALPACA_API_KEY and ALPACA_API_SECRET must be set")

        feed = self.config.get("market_data", {}).get("feed", "iex")

        self.data_feed = DataFeed(api_key, api_secret, feed=feed)
        self.execution = ExecutionEngine(api_key, api_secret, self.db)
        self.portfolio = PortfolioManager(self.db, self.execution, self.data_feed)

        account = self.execution.get_account()
        account_value = float(account["equity"]) if account and "equity" in account else 100000.0
        self.risk = RiskGovernor(self.db, self.config, account_value)

        clustering_cfg = self.config.get("clustering", {})
        self.patterns = PatternRecognizer(
            self.db,
            n_clusters=clustering_cfg.get("n_clusters", 12),
            min_samples=clustering_cfg.get("min_samples", 100),
        )

        self.scorer = Scorer(self.db, self.patterns, self.config)
        self.news = NewsIntelligence(self.config, self.db)

        try:
            self.execution.reconcile_positions()
        except Exception as e:
            logger.warning(f"Reconcile failed at startup: {e}")

        self.running = True
        self._last_report_date = None

        logger.info(f"TradingEngine initialized with {len(self.symbols)} symbols")

    def run(self):
        print_banner()

        polling_seconds = int(self.config.get("trading", {}).get("polling_seconds", 30))
        timeframe = self.config.get("trading", {}).get("timeframe", "5Min")

        logger.info("Starting main loop...")

        try:
            while self.running:
                loop_start = time.time()

                # ✅ DAILY EMAIL REPORT (PRODUCTION SAFE)
                now = datetime.utcnow()

                if now.hour == 21 and now.minute < 5:
                    today = now.date()

                    if self._last_report_date != today:
                        try:
                            acct = self.execution.get_account() or {}
                            model_stats = self.patterns.get_model_stats()
                            risk_stats = self.risk.get_risk_status()

                            state = {
                                "equity": acct.get("equity", 0),
                                "cash": acct.get("cash", 0),
                                "daily_pnl": risk_stats.get("daily_pnl", 0),
                                "samples": model_stats.get("samples", 0),
                                "clusters": model_stats.get("n_clusters", 0),
                                "last_train": model_stats.get("last_train", "N/A"),
                                "trades_today": risk_stats.get("trades_today", 0),
                                "max_trades": risk_stats.get("max_trades", 0),
                                "open_positions": risk_stats.get("open_positions", 0),
                                "loss_pct_used": risk_stats.get("loss_pct_used", 0),
                            }

                            send_report(state)
                            logger.info("Daily email report sent")

                            self._last_report_date = today

                        except Exception as e:
                            logger.error(f"Email report failed: {e}")

                # Kill switch
                if kill_switch_active():
                    logger.warning("Kill switch active - STOP_TRADING file detected (no new trades)")
                    self._print_dashboard()
                    time.sleep(min(polling_seconds, 60))
                    continue

                if not is_market_open():
                    logger.info(f"Market closed. Status: {get_market_status()} (opens in {time_until_open()})")
                    time.sleep(60)
                    continue

                try:
                    acct = self.execution.get_account()
                    if acct and "equity" in acct:
                        self.risk.update_account_value(float(acct["equity"]))
                except Exception:
                    pass

                if should_trade():
                    self._trading_cycle(timeframe)

                try:
                    self.execution.check_and_update_orders()
                except Exception as e:
                    logger.warning(f"Order update error: {e}")

                elapsed = time.time() - loop_start
                time.sleep(max(0.0, polling_seconds - elapsed))

        except KeyboardInterrupt:
            logger.info("Shutdown requested (Ctrl+C)")
        finally:
            try:
                self.db.close()
            except Exception:
                pass
