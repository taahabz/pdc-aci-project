"""
SQLite Database Interface
Thread-safe read/write operations with proper concurrency handling.
"""

import sqlite3
import time
import os
import logging

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get('DB_PATH', '/data/cache.db')


def init_db():
    """Initialize the database with required tables."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache_data (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at REAL
        )
    """)
    conn.commit()
    conn.close()
    logger.info(f"Database initialized at {DB_PATH}")


def db_read(key):
    """
    Read a value from the database by key.
    
    Args:
        key: The key to look up
    
    Returns:
        The value (string) if found, None otherwise
    """
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM cache_data WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"db_read error for key '{key}': {e}")
        return None


def db_write(key, value):
    """
    Write a key-value pair to the database.
    
    Args:
        key: The key to write
        value: The value to store
        
    Returns:
        True if successful, False otherwise
        
    Raises:
        Exception if database is unavailable
    """
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "INSERT OR REPLACE INTO cache_data (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, time.time())
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"db_write error for key '{key}': {e}")
        raise


def db_clear():
    """Clear all entries from the database (for testing)."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute("DELETE FROM cache_data")
        conn.commit()
        conn.close()
        logger.info("Database cleared")
    except Exception as e:
        logger.error(f"db_clear error: {e}")
