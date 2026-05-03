"""Pub/Sub subscriber for cache invalidation and strategy updates."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Callable, Optional

import redis

from cache import cache_delete

logger = logging.getLogger(__name__)

PUBSUB_REDIS_HOST = os.environ.get("PUBSUB_REDIS_HOST", "redis_a")
PUBSUB_REDIS_PORT = int(os.environ.get("PUBSUB_REDIS_PORT", 6379))
NODE_NAME = os.environ.get("NODE_NAME", "node_a")

StrategyUpdateCallback = Callable[[str, Optional[float]], None]


def _listen_loop(on_strategy_update: StrategyUpdateCallback) -> None:
    while True:
        try:
            client = redis.Redis(
                host=PUBSUB_REDIS_HOST,
                port=PUBSUB_REDIS_PORT,
                decode_responses=True,
                socket_connect_timeout=3,
            )
            pubsub = client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe("cache_invalidation", "strategy_update")

            logger.info("[%s] Subscriber connected to %s:%s", NODE_NAME, PUBSUB_REDIS_HOST, PUBSUB_REDIS_PORT)

            for message in pubsub.listen():
                if not message:
                    continue

                channel = message.get("channel")
                raw_data = message.get("data")
                if not raw_data:
                    continue

                try:
                    payload = json.loads(raw_data)
                except Exception:
                    logger.warning("[%s] Invalid Pub/Sub payload: %s", NODE_NAME, raw_data)
                    continue

                if channel == "cache_invalidation":
                    keys = payload.get("keys", [])
                    if isinstance(keys, list):
                        for key in keys:
                            cache_delete(str(key))
                        logger.info("[%s] Invalidated keys: %s", NODE_NAME, keys)

                elif channel == "strategy_update":
                    strategy = str(payload.get("strategy", "")).lower().strip()
                    write_rate = payload.get("write_rate")
                    if strategy:
                        on_strategy_update(strategy, float(write_rate) if write_rate is not None else None)
                        logger.info("[%s] Strategy switched to: %s", NODE_NAME, strategy)

        except redis.ConnectionError as exc:
            logger.warning("[%s] Pub/Sub disconnected: %s. Retrying in 2s...", NODE_NAME, exc)
            time.sleep(2)
        except Exception as exc:
            logger.exception("[%s] Subscriber error: %s. Retrying in 2s...", NODE_NAME, exc)
            time.sleep(2)


def start_subscriber(on_strategy_update: StrategyUpdateCallback) -> threading.Thread:
    thread = threading.Thread(
        target=_listen_loop,
        args=(on_strategy_update,),
        name="pubsub-subscriber",
        daemon=True,
    )
    thread.start()
    return thread
