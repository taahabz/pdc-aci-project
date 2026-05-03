"""
Redis Cache Interface
Wrapper around Redis operations for per-node local caching.
"""

import redis
import os
import logging

logger = logging.getLogger(__name__)

REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))

try:
    redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_keepalive=True
    )
    # Test connection
    redis_client.ping()
    logger.info(f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
except Exception as e:
    logger.warning(f"Redis connection failed at startup: {e}")
    redis_client = None


def cache_get(key):
    """
    Get a value from the cache.
    
    Args:
        key: The key to look up
        
    Returns:
        The cached value (string) if found, None otherwise
    """
    try:
        if redis_client is None:
            return None
        value = redis_client.get(key)
        return value
    except redis.ConnectionError as e:
        logger.warning(f"Cache get failed for key '{key}': {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in cache_get: {e}")
        return None


def cache_set(key, value, ttl=10):
    """
    Set a value in the cache with TTL.
    
    Args:
        key: The key to set
        value: The value to store
        ttl: Time to live in seconds (default: 10)
    """
    try:
        if redis_client is None:
            return
        redis_client.setex(key, ttl, value)
    except redis.ConnectionError as e:
        logger.warning(f"Cache set failed for key '{key}': {e}")
    except Exception as e:
        logger.error(f"Unexpected error in cache_set: {e}")


def cache_delete(key):
    """
    Delete a key from the cache.
    
    Args:
        key: The key to delete
    """
    try:
        if redis_client is None:
            return
        redis_client.delete(key)
    except redis.ConnectionError as e:
        logger.warning(f"Cache delete failed for key '{key}': {e}")
    except Exception as e:
        logger.error(f"Unexpected error in cache_delete: {e}")


def cache_flush():
    """Flush all keys from the local cache (for experiment resets)."""
    try:
        if redis_client is None:
            return
        redis_client.flushdb()
        logger.info("Cache flushed")
    except redis.ConnectionError as e:
        logger.warning(f"Cache flush failed: {e}")
    except Exception as e:
        logger.error(f"Unexpected error in cache_flush: {e}")


def is_redis_connected():
    """Check if Redis is currently connected."""
    try:
        if redis_client is None:
            return False
        redis_client.ping()
        return True
    except Exception:
        return False
