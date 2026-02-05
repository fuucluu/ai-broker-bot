"""Pattern recognition via KMeans clustering."""
import numpy as np
import pickle
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from engine.persistence import Database
from engine.features import normalize_features

logger = logging.getLogger("ai_broker.patterns")

class PatternRecognizer:
    def __init__(self, db: Database, n_clusters: int = 12, 
                 min_samples: int = 100, model_path: str = "model"):
        self.db = db
        self.n_clusters = n_clusters
        self.min_samples = min_samples
        self.model_path = Path(model_path)
        self.model_path.mkdir(exist_ok=True)
        
        self.kmeans: Optional[KMeans] = None
        self.scaler: Optional[StandardScaler] = None
        self.training_vectors: List[np.ndarray] = []
        self.last_train_time: Optional[datetime] = None
        
        self._load_model()
    
    def _model_file(self) -> Path:
        return self.model_path / "kmeans_model.pkl"
    
    def _load_model(self):
        """Load existing model if available."""
        model_file = self._model_file()
        if model_file.exists():
            try:
                with open(model_file, 'rb') as f:
                    data = pickle.load(f)
                    self.kmeans = data.get('kmeans')
                    self.scaler = data.get('scaler')
                    self.training_vectors = data.get('vectors', [])
                    self.last_train_time = data.get('last_train')
                    logger.info(f"Loaded model with {len(self.training_vectors)} samples")
            except Exception as e:
                logger.warning(f"Could not load model: {e}")
    
    def _save_model(self):
        """Save current model."""
        try:
            with open(self._model_file(), 'wb') as f:
                pickle.dump({
                    'kmeans': self.kmeans,
                    'scaler': self.scaler,
                    'vectors': self.training_vectors,
                    'last_train': self.last_train_time
                }, f)
        except Exception as e:
            logger.error(f"Could not save model: {e}")
    
    def add_sample(self, vector: np.ndarray):
        """Add a new feature vector sample."""
        if vector is not None and len(vector) > 0:
            self.training_vectors.append(vector)
            # Limit stored samples
            if len(self.training_vectors) > 10000:
                self.training_vectors = self.training_vectors[-5000:]
    
    def needs_retrain(self, interval_hours: int = 24) -> bool:
        """Check if model needs retraining."""
        if self.kmeans is None:
            return len(self.training_vectors) >= self.min_samples
        
        if self.last_train_time is None:
            return True
        
        elapsed = datetime.now() - self.last_train_time
        return elapsed > timedelta(hours=interval_hours)
    
    def train(self) -> bool:
        """Train or retrain the clustering model."""
        if len(self.training_vectors) < self.min_samples:
            logger.info(f"Not enough samples: {len(self.training_vectors)}/{self.min_samples}")
            return False
        
        try:
            X = np.array(self.training_vectors)
            
            # Fit scaler
            self.scaler = StandardScaler()
            X_scaled = self.scaler.fit_transform(X)
            
            # Train KMeans
            self.kmeans = KMeans(
                n_clusters=self.n_clusters,
                init='k-means++',
                n_init=10,
                max_iter=300,
                random_state=42
            )
            self.kmeans.fit(X_scaled)
            
            self.last_train_time = datetime.now()
            self._save_model()
            
            logger.info(f"Trained model on {len(X)} samples")
            return True
            
        except Exception as e:
            logger.error(f"Training failed: {e}")
            return False
    
    def predict_cluster(self, vector: np.ndarray) -> Optional[int]:
        """Predict cluster for a feature vector."""
        if self.kmeans is None or self.scaler is None:
            return None
        
        if vector is None or len(vector) == 0:
            return None
        
        try:
            X = vector.reshape(1, -1)
            X_scaled = self.scaler.transform(X)
            cluster = int(self.kmeans.predict(X_scaled)[0])
            return cluster
        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            return None
    
    def get_cluster_distance(self, vector: np.ndarray, cluster_id: int) -> float:
        """Get distance from vector to cluster center."""
        if self.kmeans is None or self.scaler is None:
            return float('inf')
        
        try:
            X = vector.reshape(1, -1)
            X_scaled = self.scaler.transform(X)
            center = self.kmeans.cluster_centers_[cluster_id]
            distance = np.linalg.norm(X_scaled[0] - center)
            return float(distance)
        except Exception:
            return float('inf')
    
    def get_cluster_quality(self, cluster_id: int) -> Dict:
        """Get quality metrics for a cluster from AI memory."""
        stats = self.db.get_cluster_stats(cluster_id)
        if stats is None:
            return {
                'trades': 0,
                'win_rate': 0.0,
                'expectancy': 0.0,
                'quality': 'unknown'
            }
        
        trades = stats['total_trades']
        win_rate = stats['wins'] / trades if trades > 0 else 0.0
        expectancy = stats['expectancy']
        
        # Determine quality level
        if trades < 10:
            quality = 'insufficient_data'
        elif expectancy > 0.02 and win_rate > 0.55:
            quality = 'excellent'
        elif expectancy > 0.01 and win_rate > 0.50:
            quality = 'good'
        elif expectancy > 0 and win_rate > 0.45:
            quality = 'marginal'
        else:
            quality = 'poor'
        
        return {
            'trades': trades,
            'win_rate': win_rate,
            'expectancy': expectancy,
            'avg_win': stats['avg_win'],
            'avg_loss': stats['avg_loss'],
            'quality': quality
        }
    
    def should_trade_cluster(self, cluster_id: int, min_trades: int = 30, 
                            min_expectancy: float = 0.001) -> Tuple[bool, str]:
        """Determine if we should trade based on cluster quality."""
        quality = self.get_cluster_quality(cluster_id)
        
        if quality['trades'] < min_trades:
            return False, f"Insufficient data ({quality['trades']}/{min_trades} trades)"
        
        if quality['expectancy'] < min_expectancy:
            return False, f"Negative expectancy ({quality['expectancy']:.4f})"
        
        if quality['quality'] == 'poor':
            return False, "Poor cluster quality"
        
        return True, f"OK ({quality['quality']}, EV={quality['expectancy']:.4f})"
    
    def get_best_clusters(self, top_n: int = 5) -> List[Dict]:
        """Get top performing clusters."""
        all_stats = self.db.get_all_cluster_stats()
        
        # Filter to clusters with enough trades
        valid = [s for s in all_stats if s['total_trades'] >= 20]
        
        # Sort by expectancy
        valid.sort(key=lambda x: x['expectancy'], reverse=True)
        
        return valid[:top_n]
    
    def get_model_stats(self) -> Dict:
        """Get current model statistics."""
        return {
            'trained': self.kmeans is not None,
            'n_clusters': self.n_clusters,
            'samples': len(self.training_vectors),
            'last_train': self.last_train_time.isoformat() if self.last_train_time else None
        }
