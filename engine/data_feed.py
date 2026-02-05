"""Market data feed using Alpaca API (polling approach)."""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

# Feed enum (newer alpaca-py)
try:
    from alpaca.data.enums import DataFeed as AlpacaDataFeed
except Exception:
    AlpacaDataFeed = None

logger = logging.getLogger("ai_broker.data")
NY_TZ = ZoneInfo("America/New_York")


class DataFeed:
    def __init__(self, api_key: str, api_secret: str, feed: str = "iex"):
        self.client = StockHistoricalDataClient(api_key, api_secret)
        self._cache: Dict[str, pd.DataFrame] = {}
        self._last_fetch: Dict[str, datetime] = {}
        self.feed = (feed or "iex").strip().lower()

    def _get_timeframe(self, tf_str: str) -> TimeFrame:
        tf_map = {
            "1Min": TimeFrame(1, TimeFrameUnit.Minute),
            "5Min": TimeFrame(5, TimeFrameUnit.Minute),
            "15Min": TimeFrame(15, TimeFrameUnit.Minute),
            "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
            "1Day": TimeFrame(1, TimeFrameUnit.Day),
        }
        return tf_map.get(tf_str, TimeFrame(5, TimeFrameUnit.Minute))

    def _get_feed_enum(self):
        if AlpacaDataFeed is None:
            return None
        if self.feed == "sip":
            return AlpacaDataFeed.SIP
        if self.feed == "delayed_sip":
            return AlpacaDataFeed.DELAYED_SIP
        return AlpacaDataFeed.IEX  # default low-cost

    def _bars_df_for_symbol(self, bars, symbol: str) -> Optional[pd.DataFrame]:
        # alpaca-py returns a BarSet; correct access is bars.df
        df_all = getattr(bars, "df", None)
        if df_all is None or df_all.empty:
            return None

        # Typical: MultiIndex (symbol, timestamp)
        if isinstance(df_all.index, pd.MultiIndex):
            try:
                df = df_all.xs(symbol, level=0)
            except Exception:
                return None
        else:
            df = df_all

        if df is None or df.empty:
            return None

        df = df.copy()
        df.index.name = "timestamp"
        df = df.sort_index()

        # Ensure required columns
        for col in ("open", "high", "low", "close", "volume"):
            if col not in df.columns:
                return None

        if "vwap" not in df.columns:
            df["vwap"] = df["close"]

        df = df[["open", "high", "low", "close", "volume", "vwap"]].copy()

        # Defensive types
        df["open"] = df["open"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
        df["vwap"] = df["vwap"].astype(float)

        return df

    def get_bars(
        self,
        symbol: str,
        timeframe: str = "5Min",
        limit: int = 100,
        use_cache: bool = True,
    ) -> Optional[pd.DataFrame]:
        cache_key = f"{symbol}_{timeframe}"
        now = datetime.now(NY_TZ)

        # 30s cache
        if use_cache and cache_key in self._cache:
            last = self._last_fetch.get(cache_key)
            if last and (now - last).total_seconds() < 30:
                return self._cache[cache_key]

        try:
            end = now
            start = end - timedelta(days=10)

            feed_enum = self._get_feed_enum()

            if feed_enum is not None:
                request = StockBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=self._get_timeframe(timeframe),
                    start=start,
                    end=end,
                    limit=limit,
                    feed=feed_enum,
                )
            else:
                request = StockBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=self._get_timeframe(timeframe),
                    start=start,
                    end=end,
                    limit=limit,
                )

            bars = self.client.get_stock_bars(request)
            df = self._bars_df_for_symbol(bars, symbol)

            if df is None or df.empty:
                logger.warning(f"No data for {symbol}")
                return None

            if limit and len(df) > limit:
                df = df.iloc[-limit:]

            self._cache[cache_key] = df
            self._last_fetch[cache_key] = now
            return df

        except Exception as e:
            logger.error(f"Error fetching bars for {symbol}: {e}")
            return None

    def get_latest_price(self, symbol: str) -> Optional[float]:
        df = self.get_bars(symbol, limit=1, use_cache=False)
        if df is not None and len(df) > 0:
            return float(df["close"].iloc[-1])
        return None

    def get_multi_bars(
        self, symbols: List[str], timeframe: str = "5Min", limit: int = 100
    ) -> Dict[str, pd.DataFrame]:
        results: Dict[str, pd.DataFrame] = {}

        try:
            now = datetime.now(NY_TZ)
            start = now - timedelta(days=10)

            feed_enum = self._get_feed_enum()

            if feed_enum is not None:
                request = StockBarsRequest(
                    symbol_or_symbols=symbols,
                    timeframe=self._get_timeframe(timeframe),
                    start=start,
                    end=now,
                    limit=limit,
                    feed=feed_enum,
                )
            else:
                request = StockBarsRequest(
                    symbol_or_symbols=symbols,
                    timeframe=self._get_timeframe(timeframe),
                    start=start,
                    end=now,
                    limit=limit,
                )

            bars = self.client.get_stock_bars(request)
            df_all = getattr(bars, "df", None)

            if df_all is None or df_all.empty:
                logger.warning("No multi-bar data returned")
                return {}

            if isinstance(df_all.index, pd.MultiIndex):
                for sym in symbols:
                    try:
                        sdf = df_all.xs(sym, level=0).copy()
                    except Exception:
                        continue

                    if sdf is None or sdf.empty:
                        continue

                    sdf.index.name = "timestamp"
                    sdf = sdf.sort_index()

                    if "vwap" not in sdf.columns and "close" in sdf.columns:
                        sdf["vwap"] = sdf["close"]

                    # Ensure required
                    if not all(c in sdf.columns for c in ("open", "high", "low", "close", "volume")):
                        continue

                    cols = [c for c in ("open", "high", "low", "close", "volume", "vwap") if c in sdf.columns]
                    sdf = sdf[cols]

                    if limit and len(sdf) > limit:
                        sdf = sdf.iloc[-limit:]

                    results[sym] = sdf

                    cache_key = f"{sym}_{timeframe}"
                    self._cache[cache_key] = sdf
                    self._last_fetch[cache_key] = now

            else:
                if len(symbols) == 1:
                    sym = symbols[0]
                    df = df_all.copy()
                    df.index.name = "timestamp"
                    df = df.sort_index()
                    if "vwap" not in df.columns and "close" in df.columns:
                        df["vwap"] = df["close"]
                    results[sym] = df

        except Exception as e:
            logger.error(f"Error fetching multi bars: {e}")

        return results

    def get_latest_prices(self, symbols: List[str]) -> Dict[str, float]:
        prices: Dict[str, float] = {}
        bars = self.get_multi_bars(symbols, limit=1)
        for symbol, df in bars.items():
            if df is not None and len(df) > 0:
                prices[symbol] = float(df["close"].iloc[-1])
        return prices

    def clear_cache(self):
        self._cache.clear()
        self._last_fetch.clear()
