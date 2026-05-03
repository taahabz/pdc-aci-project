"""Adaptive strategy controller.

Runs on Node A. Periodically computes write rate and switches strategy:
- rate > HIGH_THRESHOLD  -> eager
- rate < LOW_THRESHOLD   -> ttl
- otherwise              -> batched
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Callable, List

import redis

logger = logging.getLogger(__name__)

PUBSUB_REDIS_HOST = os.environ.get("PUBSUB_REDIS_HOST", "redis_a")
PUBSUB_REDIS_PORT = int(os.environ.get("PUBSUB_REDIS_PORT", 6379))
HIGH_THRESHOLD = float(os.environ.get("HIGH_THRESHOLD", 50))
LOW_THRESHOLD = float(os.environ.get("LOW_THRESHOLD", 10))
CONTROLLER_INTERVAL = float(os.environ.get("CONTROLLER_INTERVAL", 3))
WRITE_WINDOW = float(os.environ.get("WRITE_WINDOW", 5))

SwitchCallback = Callable[[str, float], None]
GetStrategyCallback = Callable[[], str]


def _select_strategy(write_rate: float) -> str:
    if write_rate > HIGH_THRESHOLD:
        return "eager"
    if write_rate < LOW_THRESHOLD:
        return "ttl"
    return "batched"


def _publish_strategy_update(strategy: str, write_rate: float) -> None:
    payload = {
        "strategy": strategy,
        "write_rate": write_rate,
        "timestamp": time.time(),
        "source": "controller",
    }
    try:
        client = redis.Redis(
            host=PUBSUB_REDIS_HOST,
            port=PUBSUB_REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=3,
        )
        client.publish("strategy_update", json.dumps(payload))
    except redis.ConnectionError as exc:
        logger.warning("[CONTROLLER] Failed to publish strategy update: %s", exc)


def _loop(
    write_timestamps: List[float],
    write_timestamps_lock: threading.Lock,
    get_strategy: GetStrategyCallback,
    switch_strategy: SwitchCallback,
) -> None:
    while True:
        now = time.time()
        cutoff = now - WRITE_WINDOW

        with write_timestamps_lock:
            while write_timestamps and write_timestamps[0] < cutoff:
                write_timestamps.pop(0)
            writes_in_window = len(write_timestamps)

        write_rate = writes_in_window / WRITE_WINDOW
        desired = _select_strategy(write_rate)
        current = get_strategy()

        if desired != current:
            logger.info(
                "[CONTROLLER] write_rate=%.2f w/s, switching %s -> %s",
                write_rate,
                current,
                desired,
            )
            switch_strategy(desired, write_rate)
            _publish_strategy_update(desired, write_rate)

        time.sleep(CONTROLLER_INTERVAL)


def start_controller(
    write_timestamps: List[float],
    write_timestamps_lock: threading.Lock,
    get_strategy: GetStrategyCallback,
    switch_strategy: SwitchCallback,
) -> threading.Thread:
    thread = threading.Thread(
        target=_loop,
        args=(write_timestamps, write_timestamps_lock, get_strategy, switch_strategy),
        name="adaptive-controller",
        daemon=True,
    )
    thread.start()
    return thread
