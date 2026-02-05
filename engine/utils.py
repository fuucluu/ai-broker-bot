import os
import yaml
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")


def load_config(path: str = "config/settings.yaml") -> dict:
    """Load YAML configuration file."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_symbols(path: str) -> list:
    """Load symbols from text file."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Symbols file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        return [line.strip().upper() for line in f if line.strip()]


def setup_logging(config: dict | None = None):
    """Setup logging configuration."""
    config = config or {}

    log_level = getattr(logging, config.get("level", "INFO").upper(), logging.INFO)
    log_dir = config.get("dir", "storage/logs")
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "ai_broker.log")

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def kill_switch_active() -> bool:
    """Check for STOP_TRADING file."""
    return os.path.exists("STOP_TRADING")


def check_paper_mode_safety(config: dict):
    """Ensure system cannot run in live mode."""
    mode = str(config.get("mode", "paper")).lower()
    if mode != "paper":
        raise RuntimeError("Refusing to run: mode is not PAPER")

    if os.environ.get("ALLOW_LIVE", "").lower() in ("1", "true", "yes"):
        raise RuntimeError("Refusing to run: ALLOW_LIVE is set")


def print_banner():
    print(
        "\n"
        "============================================================\n"
        "    AI BROKER - PAPER TRADING SYSTEM\n"
        "    ⚠️  PAPER MODE ONLY - NO REAL MONEY ⚠️\n"
        "============================================================\n"
    )


def now_et():
    return datetime.now(NY_TZ)
