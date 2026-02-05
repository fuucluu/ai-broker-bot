"""Main runtime engine for AI Broker."""
import os
import time
import logging
from typing import Dict, List, Optional

from engine.utils import (
    load_config, load_symbols, setup_logging,
    kill_switch_active, check_paper_mode_safety, print_banner
)
from engine.persistence import Database
from engine.market_hours import is_market_open, should_trade, get_market_status, time_until_open
from engine.data_feed import DataFeed
from engine.features import extract_features
from engine.patterns import PatternRecognizer
from engine.scorer import Scorer  # ✅ correct class name
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

        # Paper-mode safety checks
        check_paper_mode_safety(self.config)

        # DB
        db_path = self.config.get("database", {}).get("path", "ai_broker.db")
        self.db = Database(db_path)

        # Alpaca creds
        api_key = os.environ.get("ALPACA_API_KEY", "")
        api_secret = os.environ.get("ALPACA_API_SECRET", "")
        if not api_key or not api_secret:
            raise RuntimeError("ALPACA_API_KEY and ALPACA_API_SECRET must be set")

        # Market data feed selection (defaults to IEX)
        feed = self.config.get("market_data", {}).get("feed", "iex")

        # Components
        self.data_feed = DataFeed(api_key, api_secret, feed=feed)
        self.execution = ExecutionEngine(api_key, api_secret, self.db)
        self.portfolio = PortfolioManager(self.db, self.execution, self.data_feed)

        # Risk setup (use account equity if available)
        account = self.execution.get_account()
        account_value = float(account["equity"]) if account and "equity" in account else 100000.0
        self.risk = RiskGovernor(self.db, self.config, account_value)

        # Pattern recognizer
        clustering_cfg = self.config.get("clustering", {})
        self.patterns = PatternRecognizer(
            self.db,
            n_clusters=clustering_cfg.get("n_clusters", 12),
            min_samples=clustering_cfg.get("min_samples", 100),
        )

        # ✅ Scorer (correct class)
        self.scorer = Scorer(self.db, self.patterns, self.config)

        # News intelligence (may be disabled by config)
        self.news = NewsIntelligence(self.config, self.db)

        # Optional: reconcile positions at startup
        try:
            self.execution.reconcile_positions()
        except Exception as e:
            logger.warning(f"Reconcile failed at startup: {e}")

        self.running = True
        logger.info(f"TradingEngine initialized with {len(self.symbols)} symbols")

    def run(self):
        print_banner()

        polling_seconds = int(self.config.get("trading", {}).get("polling_seconds", 30))
        timeframe = self.config.get("trading", {}).get("timeframe", "5Min")

        logger.info("Starting main loop...")

        try:
            while self.running:
                loop_start = time.time()

                # Kill switch
                if kill_switch_active():
                    logger.warning("Kill switch active - STOP_TRADING file detected (no new trades)")
                    self._print_dashboard()
                    time.sleep(min(polling_seconds, 60))
                    continue

                # Market hours
                if not is_market_open():
                    logger.info(f"Market closed. Status: {get_market_status()} (opens in {time_until_open()})")
                    time.sleep(60)
                    continue

                # Update account value for risk sizing
                try:
                    acct = self.execution.get_account()
                    if acct and "equity" in acct:
                        self.risk.update_account_value(float(acct["equity"]))
                except Exception:
                    pass

                # Main trading cycle
                if should_trade():
                    self._trading_cycle(timeframe)

                # Update pending orders
                try:
                    self.execution.check_and_update_orders()
                except Exception as e:
                    logger.warning(f"Order update error: {e}")

                # Sleep
                elapsed = time.time() - loop_start
                time.sleep(max(0.0, polling_seconds - elapsed))

        except KeyboardInterrupt:
            logger.info("Shutdown requested (Ctrl+C)")
        finally:
            try:
                self.db.close()
            except Exception:
                pass

    def _trading_cycle(self, timeframe: str):
        # News (optional)
        try:
            news_result = self.news.process_news(self.symbols)
            if news_result.get("should_pause"):
                logger.warning("News triggered trading pause")
                return
        except Exception:
            pass

        # Pull enough history so features can compute and training can start immediately
        bars_data = self.data_feed.get_multi_bars(self.symbols, timeframe, limit=300)

        # Build SPY features (regime proxy)
        spy_features = None
        if "SPY" in bars_data and bars_data["SPY"] is not None:
            spy_features = extract_features(bars_data["SPY"])

        # Always collect samples (scorer.add_sample happens inside evaluate_entry)
        signals = []

        for symbol in self.symbols:
            bars = bars_data.get(symbol)
            if bars is None or len(bars) == 0:
                continue

            features = extract_features(bars)
            if features is None or len(features) == 0:
                continue

            signal = self.scorer.evaluate_entry(symbol, features, spy_features)
            if signal:
                signals.append((signal, features, bars))

        # Train model when enough samples are collected
        try:
            if self.patterns.needs_retrain():
                trained = self.patterns.train()
                if trained:
                    logger.info("Pattern model trained/retrained")
        except Exception as e:
            logger.warning(f"Model train check failed: {e}")

        # Dashboard
        self._print_dashboard()

        # No signals yet (normal early)
        if not signals:
            return

        # Global risk gate
        can_trade, reason = self.risk.can_trade()
        if not can_trade:
            logger.info(f"Risk blocked trading: {reason}")
            return

        # Pick best signal
        signals.sort(key=lambda x: x[0].score, reverse=True)
        signal, features, bars = signals[0]

        # Per-symbol risk gate
        ok_sym, sym_reason = self.risk.can_trade_symbol(signal.symbol)
        if not ok_sym:
            logger.info(f"{signal.symbol} blocked: {sym_reason}")
            return

        # Position sizing (ATR-based)
        last_close = float(bars["close"].iloc[-1]) if "close" in bars.columns else None
        atr = float(features["atr14"].iloc[-1]) if "atr14" in features.columns else 0.0
        if last_close is None or last_close <= 0:
            return

        qty, stop_dist = self.risk.calculate_position_size(
            price=last_close,
            atr=atr,
            confidence=float(signal.confidence) if hasattr(signal, "confidence") else 0.5,
        )

        if qty <= 0:
            logger.info(f"{signal.symbol} size=0 (risk sizing blocked)")
            return

        # Open via PortfolioManager so DB stays consistent
        try:
            position_id = self.portfolio.open_position(
                symbol=signal.symbol,
                side=signal.side,
                qty=qty,
                price=last_close,
                cluster_id=getattr(signal, "cluster_id", None),
            )
            if position_id:
                logger.info(
                    f"OPEN {signal.symbol} {signal.side} qty={qty} score={signal.score:.2f} "
                    f"cluster={getattr(signal,'cluster_id',None)} reason={signal.reason}"
                )
                self.risk.record_trade(signal.symbol)
        except Exception as e:
            logger.error(f"Failed to open position: {e}")

    def _print_dashboard(self):
        # If your PortfolioManager already has a print_dashboard(), use it.
        if hasattr(self.portfolio, "print_dashboard"):
            try:
                self.portfolio.print_dashboard(self.patterns)
                return
            except Exception:
                pass

        # Fallback minimal dashboard
        try:
            acct = self.execution.get_account() or {}
            equity = acct.get("equity", "?")
            cash = acct.get("cash", "?")
            stats = self.patterns.get_model_stats()
            risk = self.risk.get_risk_status()
            print(f"\nAI BROKER | Equity={equity} Cash={cash} | Model={stats} | Risk={risk}\n")
        except Exception:
            pass
