"""
Data Cache - Simple SQLite-based caching for collected data
"""
import sqlite3
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
import os


class DataCache:
    """Simple SQLite cache for investment data"""
    
    def __init__(self, cache_path: Optional[str] = None):
        """Initialize cache
        
        Args:
            cache_path: Path to SQLite database. Defaults to ~/.investment-skill/cache.db
        """
        if cache_path is None:
            cache_dir = Path.home() / ".investment-skill"
            cache_dir.mkdir(exist_ok=True)
            cache_path = cache_dir / "cache.db"
        
        self.db_path = str(cache_path)
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    ttl INTEGER DEFAULT 3600
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp ON cache(timestamp)
            """)
            conn.commit()
    
    def get(self, key: str) -> Optional[Any]:
        """Get cached data
        
        Args:
            key: Cache key
            
        Returns:
            Cached data or None if expired/not found
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT data, timestamp, ttl FROM cache WHERE key = ?",
                (key,)
            )
            row = cursor.fetchone()
            
            if row is None:
                return None
            
            data, timestamp, ttl = row
            
            # Check if expired
            cached_time = datetime.fromisoformat(timestamp)
            if datetime.now() - cached_time > timedelta(seconds=ttl):
                # Delete expired entry
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                conn.commit()
                return None
            
            return json.loads(data)
    
    def set(self, key: str, data: Any, ttl: int = 3600):
        """Cache data
        
        Args:
            key: Cache key
            data: Data to cache (must be JSON serializable)
            ttl: Time to live in seconds (default 1 hour)
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO cache (key, data, ttl)
                   VALUES (?, ?, ?)""",
                (key, json.dumps(data, default=str), ttl)
            )
            conn.commit()
    
    def delete(self, key: str):
        """Delete cached entry"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            conn.commit()
    
    def clear_expired(self):
        """Clear all expired entries"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """DELETE FROM cache 
                   WHERE datetime(timestamp, '+' || ttl || ' seconds') < datetime('now')"""
            )
            conn.commit()
    
    def clear_all(self):
        """Clear all cached data"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM cache")
            conn.commit()
    
    def get_stats(self) -> dict:
        """Get cache statistics"""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            expired = conn.execute(
                """SELECT COUNT(*) FROM cache 
                   WHERE datetime(timestamp, '+' || ttl || ' seconds') < datetime('now')"""
            ).fetchone()[0]
            
            return {
                "total_entries": total,
                "expired_entries": expired,
                "valid_entries": total - expired
            }
    
    @staticmethod
    def make_key(*args) -> str:
        """Create cache key from arguments"""
        key_str = "|".join(str(arg) for arg in args)
        return hashlib.md5(key_str.encode()).hexdigest()


# Global cache instance
_cache_instance: Optional[DataCache] = None


def get_cache() -> DataCache:
    """Get global cache instance"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = DataCache()
    return _cache_instance


def cached(ttl: int = 3600):
    """Decorator to cache function results
    
    Args:
        ttl: Cache time-to-live in seconds
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            cache = get_cache()
            
            # Create cache key from function name and arguments
            key = cache.make_key(func.__name__, *args, **kwargs)
            
            # Try to get from cache
            result = cache.get(key)
            if result is not None:
                return result
            
            # Call function and cache result
            result = func(*args, **kwargs)
            cache.set(key, result, ttl)
            return result
        
        return wrapper
    return decorator
