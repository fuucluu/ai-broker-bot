"""Market hours handling for NYSE/NASDAQ."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")

# Regular market hours
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)

# Holidays 2024-2025 (major US market holidays)
HOLIDAYS = {
    "2024-01-01", "2024-01-15", "2024-02-19", "2024-03-29", "2024-05-27",
    "2024-06-19", "2024-07-04", "2024-09-02", "2024-11-28", "2024-12-25",
    "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26",
    "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
}

def now_ny() -> datetime:
    return datetime.now(NY_TZ)

def is_market_open() -> bool:
    now = now_ny()
    if now.weekday() >= 5:  # Weekend
        return False
    if now.strftime('%Y-%m-%d') in HOLIDAYS:
        return False
    current_time = now.time()
    return MARKET_OPEN <= current_time < MARKET_CLOSE

def time_until_open() -> timedelta:
    now = now_ny()
    today_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    
    if now.time() < MARKET_OPEN:
        return today_open - now
    
    # Find next trading day
    next_day = now + timedelta(days=1)
    while next_day.weekday() >= 5 or next_day.strftime('%Y-%m-%d') in HOLIDAYS:
        next_day += timedelta(days=1)
    
    next_open = next_day.replace(hour=9, minute=30, second=0, microsecond=0)
    return next_open - now

def time_until_close() -> timedelta:
    now = now_ny()
    today_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if now.time() < MARKET_CLOSE:
        return today_close - now
    return timedelta(0)

def minutes_until_close() -> int:
    return int(time_until_close().total_seconds() / 60)

def is_near_close(minutes: int = 15) -> bool:
    return 0 < minutes_until_close() <= minutes

def get_market_status() -> str:
    if is_market_open():
        mins = minutes_until_close()
        return f"OPEN ({mins} min to close)"
    else:
        td = time_until_open()
        hours = int(td.total_seconds() / 3600)
        mins = int((td.total_seconds() % 3600) / 60)
        return f"CLOSED (opens in {hours}h {mins}m)"

def should_trade() -> bool:
    """Check if we should be actively trading."""
    if not is_market_open():
        return False
    if is_near_close(minutes=5):  # Don't trade in last 5 minutes
        return False
    now = now_ny()
    if now.time() < time(9, 35):  # Skip first 5 minutes
        return False
    return True
