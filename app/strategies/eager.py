"""Eager invalidation strategy.

Publishes an invalidation message immediately on every write.
"""

from __future__ import annotations

import json
import logging
import os
import time

import redis

logger = logging.getLogger(__name__)

PUBSUB_REDIS_HOST = os.environ.get("PUBSUB_REDIS_HOST", "redis_a")
PUBSUB_REDIS_PORT = int(os.environ.get("PUBSUB_REDIS_PORT", 6379))
NODE_NAME = os.environ.get("NODE_NAME", "node_a")

_def_client = None


def _client() -> redis.Redis:
    global _def_client
    if _def_client is None:
        _def_client = redis.Redis(
            host=PUBSUB_REDIS_HOST,
            port=PUBSUB_REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=3,
        )
    return _def_client


def on_write(key: str, value: str) -> None:
    payload = {
        "action": "invalidate",
        "keys": [key],
        "timestamp": time.time(),
        "source": NODE_NAME,
        "strategy": "eager",
    }
    try:
        _client().publish("cache_invalidation", json.dumps(payload))
        logger.info("[EAGER] Published invalidation for key=%s", key)
    except redis.ConnectionError as exc:
        logger.warning("[EAGER] Publish failed (Redis unavailable): %s", exc)


def on_strategy_switch() -> None:
    logger.info("[EAGER] Strategy activated")


def on_strategy_leave() -> None:
    logger.info("[EAGER] Strategy deactivated")
