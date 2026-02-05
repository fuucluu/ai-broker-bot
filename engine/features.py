"""Feature engineering for pattern recognition."""
import numpy as np
import pandas as pd
from typing import Dict, Optional, List
import logging

logger = logging.getLogger("ai_broker.features")

def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI indicator."""
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    
    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()
    
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)

def calculate_ema(prices: pd.Series, period: int) -> pd.Series:
    """Calculate EMA."""
    return prices.ewm(span=period, adjust=False).mean()

def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, 
                  period: int = 14) -> pd.Series:
    """Calculate Average True Range."""
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

def calculate_volume_zscore(volume: pd.Series, period: int = 20) -> pd.Series:
    """Calculate volume z-score."""
    mean = volume.rolling(period).mean()
    std = volume.rolling(period).std()
    return ((volume - mean) / std.replace(0, 1)).fillna(0)

def calculate_returns(close: pd.Series, periods: List[int]) -> Dict[str, pd.Series]:
    """Calculate returns over multiple periods."""
    returns = {}
    for p in periods:
        returns[f'ret_{p}bar'] = close.pct_change(p).fillna(0) * 100
    return returns

def extract_features(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Extract all features from OHLCV data."""
    if df is None or len(df) < 30:
        return None
    
    try:
        features = pd.DataFrame(index=df.index)
        
        # RSI
        features['rsi14'] = calculate_rsi(df['close'], 14)
        
        # EMAs
        features['ema9'] = calculate_ema(df['close'], 9)
        features['ema21'] = calculate_ema(df['close'], 21)
        
        # EMA spread (normalized)
        features['ema_spread'] = ((features['ema9'] - features['ema21']) / 
                                   df['close']) * 100
        
        # ATR
        features['atr14'] = calculate_atr(df['high'], df['low'], df['close'], 14)
        features['atr_pct'] = (features['atr14'] / df['close']) * 100
        
        # Volume z-score
        features['volume_zscore'] = calculate_volume_zscore(df['volume'], 20)
        
        # Returns
        returns = calculate_returns(df['close'], [1, 3, 6])
        for name, series in returns.items():
            features[name] = series
        
        # Add close price for reference
        features['close'] = df['close']
        
        # Drop NaN rows (need enough history)
        features = features.dropna()
        
        return features
        
    except Exception as e:
        logger.error(f"Error extracting features: {e}")
        return None

def get_feature_vector(features: pd.DataFrame) -> Optional[np.ndarray]:
    """Get latest feature vector for clustering."""
    if features is None or len(features) < 1:
        return None
    
    feature_cols = ['rsi14', 'ema_spread', 'atr_pct', 'volume_zscore',
                    'ret_1bar', 'ret_3bar', 'ret_6bar']
    
    try:
        row = features.iloc[-1]
        vector = np.array([row[col] for col in feature_cols if col in row.index])
        
        # Normalize RSI to 0-1 range
        if 'rsi14' in row.index:
            vector[0] = row['rsi14'] / 100
        
        # Clip extreme values
        vector = np.clip(vector, -10, 10)
        
        return vector
        
    except Exception as e:
        logger.error(f"Error getting feature vector: {e}")
        return None

def normalize_features(vectors: np.ndarray) -> np.ndarray:
    """Normalize feature vectors for clustering."""
    if len(vectors) == 0:
        return vectors
    
    # Z-score normalization
    mean = np.mean(vectors, axis=0)
    std = np.std(vectors, axis=0)
    std[std == 0] = 1  # Avoid division by zero
    
    normalized = (vectors - mean) / std
    return np.clip(normalized, -5, 5)

def get_market_regime(spy_features: pd.DataFrame) -> str:
    """Determine current market regime from SPY features."""
    if spy_features is None or len(spy_features) < 1:
        return "unknown"
    
    row = spy_features.iloc[-1]
    
    rsi = row.get('rsi14', 50)
    ema_spread = row.get('ema_spread', 0)
    atr_pct = row.get('atr_pct', 1)
    
    # High volatility
    if atr_pct > 2.0:
        return "high_volatility"
    
    # Trending up
    if ema_spread > 0.5 and rsi > 50:
        return "uptrend"
    
    # Trending down
    if ema_spread < -0.5 and rsi < 50:
        return "downtrend"
    
    # Overbought
    if rsi > 70:
        return "overbought"
    
    # Oversold
    if rsi < 30:
        return "oversold"
    
    return "neutral"
