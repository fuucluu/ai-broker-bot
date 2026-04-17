"""Utility helpers for AI Broker."""
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

import yaml


def load_config(config_path: str = "config/settings.yaml") -> Dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    return config


def load_symbols(symbols_path: str = "config/symbols.txt") -> List[str]:
    path = Path(symbols_path)
    if not path.exists():
        raise FileNotFoundError(f"Symbols file not found: {symbols_path}")

    symbols: List[str] = []
    with path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip().upper()
            if not line:
                continue
            if line.startswith("#"):
                continue
            symbols.append(line)

    # Deduplicate while preserving order
    seen = set()
    unique_symbols: List[str] = []
    for sym in symbols:
        if sym not in seen:
            seen.add(sym)
            unique_symbols.append(sym)

    return unique_symbols


def setup_logging(config: dict):
    level_name = str(config.get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    log_file = config.get("file", "ai_broker.log")

    # Make sure log directory exists if a relative/absolute path includes folders
    log_path = Path(log_file)
    if log_path.parent and str(log_path.parent) not in ("", "."):
        log_path.parent.mkdir(parents=True, exist_ok=True)

    # Clear existing handlers so re-runs do not duplicate logs
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    root_logger.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)

    # Quiet noisy third-party loggers a bit
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("alpaca").setLevel(logging.INFO)

    root_logger.info(f"Logging initialized -> level={level_name}, file={log_path}")


def kill_switch_active(stop_file: str = "STOP_TRADING") -> bool:
    return Path(stop_file).exists()


def check_paper_mode_safety(config: Dict[str, Any]) -> None:
    if os.environ.get("ALLOW_LIVE", "").strip().lower() in ("1", "true", "yes"):
        raise RuntimeError("ALLOW_LIVE detected. This system is PAPER-ONLY.")

    alpaca_base_url = os.environ.get("ALPACA_BASE_URL", "").strip().lower()
    if alpaca_base_url and "paper" not in alpaca_base_url:
        raise RuntimeError(
            f"Unsafe ALPACA_BASE_URL detected: {alpaca_base_url}. "
            "This system must use Alpaca paper trading only."
        )

    broker_cfg = config.get("broker", {})
    mode = str(broker_cfg.get("mode", "paper")).strip().lower()
    if mode not in ("paper", ""):
        raise RuntimeError(f"Unsafe broker mode in config: {mode}")


def print_banner() -> None:
    print("\n" + "=" * 60)
    print("    AI BROKER - PAPER TRADING SYSTEM")
    print("    ⚠️  PAPER MODE ONLY - NO REAL MONEY ⚠️")
    print("=" * 60 + "\n")
