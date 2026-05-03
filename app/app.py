"""
Adaptive Cache Invalidation System - Flask Application
Main entry point for each node in the distributed cache system.
"""

import os
import logging
import time
import threading
import json
import redis
from flask import Flask, request, jsonify

# Import local modules
from db import init_db, db_read, db_write
from cache import cache_get, cache_set, cache_flush
from subscriber import start_subscriber
from controller import start_controller
from strategies import ttl, eager, batched

# Configuration from environment
NODE_NAME = os.environ.get('NODE_NAME', 'node_a')
NODE_PORT = int(os.environ.get('NODE_PORT', 5001))
IS_WRITER = os.environ.get('IS_WRITER', 'false').lower() == 'true'
RUN_CONTROLLER = os.environ.get('RUN_CONTROLLER', 'false').lower() == 'true'
CACHE_TTL = int(os.environ.get('CACHE_TTL', 10))
PUBSUB_REDIS_HOST = os.environ.get('PUBSUB_REDIS_HOST', 'redis_a')
PUBSUB_REDIS_PORT = int(os.environ.get('PUBSUB_REDIS_PORT', 6379))

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger(NODE_NAME)

# Flask app
app = Flask(NODE_NAME)

# Global state
current_strategy_name = 'ttl'
current_strategy = ttl
strategy_map = {
    'ttl': ttl,
    'eager': eager,
    'batched': batched,
}
write_timestamps = []
write_timestamps_lock = threading.Lock()
strategy_lock = threading.Lock()
app_start_time = time.time()


def _publish_strategy_update(strategy: str, write_rate: float | None = None, source: str = 'manual') -> None:
    payload = {
        'strategy': strategy,
        'write_rate': write_rate,
        'timestamp': time.time(),
        'source': source,
    }
    try:
        client = redis.Redis(
            host=PUBSUB_REDIS_HOST,
            port=PUBSUB_REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=3,
        )
        client.publish('strategy_update', json.dumps(payload))
    except redis.ConnectionError as exc:
        logger.warning(f"Failed to publish strategy update: {exc}")


def _apply_strategy(strategy: str, write_rate: float | None = None, source: str = 'local') -> tuple[str, str]:
    global current_strategy_name, current_strategy

    strategy = strategy.lower().strip()
    if strategy not in strategy_map:
        raise ValueError(f"Invalid strategy: {strategy}")

    with strategy_lock:
        previous = current_strategy_name
        if previous == strategy:
            return previous, strategy

        try:
            if hasattr(current_strategy, 'on_strategy_leave'):
                current_strategy.on_strategy_leave()
        except Exception as exc:
            logger.warning(f"Strategy leave hook failed: {exc}")

        current_strategy = strategy_map[strategy]
        current_strategy_name = strategy

        try:
            if hasattr(current_strategy, 'on_strategy_switch'):
                current_strategy.on_strategy_switch()
        except Exception as exc:
            logger.warning(f"Strategy switch hook failed: {exc}")

    logger.info(f"Strategy changed: {previous} -> {strategy} (source={source}, write_rate={write_rate})")
    return previous, strategy


def _on_subscriber_strategy_update(strategy: str, write_rate: float | None = None) -> None:
    try:
        _apply_strategy(strategy, write_rate=write_rate, source='subscriber')
    except Exception as exc:
        logger.warning(f"Subscriber strategy update failed: {exc}")


def _get_current_strategy() -> str:
    return current_strategy_name


def _controller_switch_strategy(strategy: str, write_rate: float) -> None:
    _apply_strategy(strategy, write_rate=write_rate, source='controller')


# ============================================================================
# ENDPOINTS
# ============================================================================

@app.route('/read', methods=['GET'])
def read():
    """
    Read a value by key. Checks cache first, falls back to database.
    """
    key = request.args.get('key')
    if not key:
        return jsonify({"error": "Missing required parameter: key"}), 400

    # Try cache first
    try:
        cached = cache_get(key)
        if cached is not None:
            return jsonify({
                "key": key,
                "value": cached,
                "source": "cache",
                "node": NODE_NAME,
                "timestamp": time.time()
            })
    except Exception as e:
        logger.warning(f"Cache get error: {e}")

    # Cache miss or error - read from database
    value = db_read(key)

    # Cache the result if found and Redis is up
    if value is not None:
        try:
            cache_set(key, value, ttl=CACHE_TTL)
        except Exception as e:
            logger.warning(f"Cache set error: {e}")

    return jsonify({
        "key": key,
        "value": value,
        "source": "db",
        "node": NODE_NAME,
        "timestamp": time.time()
    })


@app.route('/write', methods=['POST'])
def write():
    """
    Write a key-value pair to the database.
    Only writable on the designated writer node.
    """
    data = request.get_json()
    if not data or 'key' not in data or 'value' not in data:
        return jsonify({"error": "Missing required fields: key, value"}), 400

    key = data['key']
    value = data['value']

    try:
        # Write to database
        db_write(key, value)
    except Exception as e:
        return jsonify({
            "error": "Database write failed",
            "detail": str(e)
        }), 500

    # Track write timestamp for controller
    with write_timestamps_lock:
        write_timestamps.append(time.time())

    # Update local cache on write node
    try:
        cache_set(key, value, ttl=CACHE_TTL)
    except Exception as e:
        logger.warning(f"Cache set after write failed: {e}")

    # Apply current invalidation strategy
    try:
        current_strategy.on_write(key, value)
    except Exception as e:
        logger.error(f"Strategy on_write failed: {e}")

    return jsonify({
        "status": "ok",
        "key": key,
        "value": value,
        "strategy": current_strategy_name,
        "node": NODE_NAME,
        "timestamp": time.time()
    })


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    uptime = time.time() - app_start_time
    return jsonify({
        "status": "healthy",
        "node": NODE_NAME,
        "strategy": current_strategy_name,
        "is_writer": IS_WRITER,
        "controller_active": RUN_CONTROLLER,
        "uptime_seconds": uptime,
        "timestamp": time.time()
    })


@app.route('/reset', methods=['POST'])
def reset():
    """Reset the local cache."""
    try:
        cache_flush()
    except Exception as e:
        logger.error(f"Cache flush failed: {e}")

    return jsonify({
        "status": "reset",
        "node": NODE_NAME,
        "timestamp": time.time()
    })


@app.route('/db_read', methods=['GET'])
def db_read_endpoint():
    """
    Direct database read (bypasses cache entirely).
    Used by load generator to get ground truth for SRR calculation.
    """
    key = request.args.get('key')
    if not key:
        return jsonify({"error": "Missing required parameter: key"}), 400

    value = db_read(key)
    return jsonify({
        "key": key,
        "value": value,
        "source": "db_direct",
        "timestamp": time.time()
    })


@app.route('/set_strategy', methods=['POST'])
def set_strategy():
    """
    Manually override the active strategy.
    Primarily for testing - in production the controller manages this.
    """
    if not IS_WRITER:
        return jsonify({"error": "set_strategy is only available on writer node"}), 403

    strategy = request.args.get('strategy', '').lower()
    valid_strategies = ['ttl', 'eager', 'batched']

    if strategy not in valid_strategies:
        return jsonify({
            "error": f"Invalid strategy. Must be one of: {', '.join(valid_strategies)}"
        }), 400

    try:
        previous, new = _apply_strategy(strategy, source='manual')
        _publish_strategy_update(new, source='manual')
    except Exception as e:
        logger.error(f"Failed to set strategy '{strategy}': {e}")
        return jsonify({
            "error": f"Strategy '{strategy}' not available"
        }), 500

    return jsonify({
        "status": "ok",
        "previous_strategy": previous,
        "new_strategy": new,
        "node": NODE_NAME,
        "timestamp": time.time()
    })


# ============================================================================
# INITIALIZATION
# ============================================================================

def init_app():
    """Initialize the application on startup."""
    logger.info(f"Initializing {NODE_NAME}...")
    logger.info(f"  Port: {NODE_PORT}")
    logger.info(f"  Is Writer: {IS_WRITER}")
    logger.info(f"  Run Controller: {RUN_CONTROLLER}")
    logger.info(f"  Initial Strategy: {current_strategy_name}")

    # Initialize database
    try:
        init_db()
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

    # Start subscriber thread on all nodes
    start_subscriber(_on_subscriber_strategy_update)

    # Start controller only on writer node when enabled
    if IS_WRITER and RUN_CONTROLLER:
        start_controller(
            write_timestamps=write_timestamps,
            write_timestamps_lock=write_timestamps_lock,
            get_strategy=_get_current_strategy,
            switch_strategy=_controller_switch_strategy,
        )
        logger.info("Adaptive controller started")

    logger.info("Initialization complete")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    init_app()
    app.run(host='0.0.0.0', port=NODE_PORT, threaded=True, debug=False)
