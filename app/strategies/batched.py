"""Batched invalidation strategy.

Collects written keys in a buffer and publishes invalidation in periodic batches.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import List

import redis

logger = logging.getLogger(__name__)

PUBSUB_REDIS_HOST = os.environ.get("PUBSUB_REDIS_HOST", "redis_a")
PUBSUB_REDIS_PORT = int(os.environ.get("PUBSUB_REDIS_PORT", 6379))
NODE_NAME = os.environ.get("NODE_NAME", "node_a")
BATCH_INTERVAL = float(os.environ.get("BATCH_INTERVAL", 2.5))

_buffer: List[str] = []
_lock = threading.Lock()
_running = False
_thread: threading.Thread | None = None
_client = None


def _redis_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis(
            host=PUBSUB_REDIS_HOST,
            port=PUBSUB_REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=3,
        )
    return _client


def on_write(key: str, value: str) -> None:
    with _lock:
        _buffer.append(key)


def _flush_once() -> None:
    with _lock:
        if not _buffer:
            return
        keys = list(dict.fromkeys(_buffer))
        _buffer.clear()

    payload = {
        "action": "invalidate",
        "keys": keys,
        "timestamp": time.time(),
        "source": NODE_NAME,
        "strategy": "batched",
    }

    try:
        _redis_client().publish("cache_invalidation", json.dumps(payload))
        logger.info("[BATCHED] Published invalidation for %d key(s)", len(keys))
    except redis.ConnectionError as exc:
        logger.warning("[BATCHED] Publish failed (Redis unavailable): %s", exc)


def _loop() -> None:
    while _running:
        time.sleep(BATCH_INTERVAL)
        _flush_once()


def start_flusher() -> None:
    global _running, _thread
    if _running:
        return
    _running = True
    _thread = threading.Thread(target=_loop, name="batched-flusher", daemon=True)
    _thread.start()
    logger.info("[BATCHED] Flusher started (interval=%.2fs)", BATCH_INTERVAL)


def stop_flusher() -> None:
    global _running
    _running = False


def on_strategy_switch() -> None:
    start_flusher()
    logger.info("[BATCHED] Strategy activated")


def on_strategy_leave() -> None:
    logger.info("[BATCHED] Strategy deactivated")
