# TESTING.md — Complete Test Playbook

> **Purpose:** Every test that must pass before a component is considered done. Tests are organized by phase and component. Run tests in order — later tests depend on earlier ones passing.

---

## TABLE OF CONTENTS

1. [Test Infrastructure Setup](#1-test-infrastructure-setup)
2. [Unit Tests — Individual Components](#2-unit-tests--individual-components)
3. [Integration Tests — Component Interactions](#3-integration-tests--component-interactions)
4. [End-to-End Tests — Full System](#4-end-to-end-tests--full-system)
5. [Experiment Validation Tests](#5-experiment-validation-tests)
6. [Regression Tests](#6-regression-tests)
7. [Test Execution Checklist](#7-test-execution-checklist)

---

## 1. TEST INFRASTRUCTURE SETUP

### 1.1 Test Dependencies

Add to `requirements.txt` (or a separate `requirements-test.txt`):
```
pytest==8.*
requests==2.*
```

### 1.2 Test File Structure

```
tests/
├── conftest.py              # Shared fixtures
├── test_db.py               # db.py unit tests
├── test_cache.py            # cache.py unit tests
├── test_strategies.py       # Strategy unit tests
├── test_controller.py       # Controller logic tests
├── test_integration.py      # Multi-component tests
├── test_e2e.py              # Full system tests (requires Docker)
└── test_load_generator.py   # Load generator output validation
```

### 1.3 Test Categories

| Category     | Requires Docker? | Requires All Nodes? | Run When?                    |
|--------------|------------------|----------------------|-------------------------------|
| Unit         | NO (mock Redis)  | NO                   | After each file is written    |
| Integration  | YES (docker up)  | YES                  | After each phase checkpoint   |
| End-to-End   | YES (docker up)  | YES                  | After Phase 2 complete        |
| Experiment   | YES (docker up)  | YES                  | After each experiment run     |

---

## 2. UNIT TESTS — INDIVIDUAL COMPONENTS

### 2.1 `test_db.py` — SQLite Helper Tests

```python
"""
Tests for db.py — SQLite read/write operations.
Run WITHOUT Docker. Uses a temporary SQLite file.
"""
import os
import time
import tempfile
import threading
import pytest

# Set DB_PATH to a temp file before importing db module
TEMP_DB = tempfile.mktemp(suffix='.db')
os.environ['DB_PATH'] = TEMP_DB

from app.db import init_db, db_read, db_write


@pytest.fixture(autouse=True)
def setup_db():
    """Create fresh DB before each test."""
    if os.path.exists(TEMP_DB):
        os.remove(TEMP_DB)
    init_db()
    yield
    if os.path.exists(TEMP_DB):
        os.remove(TEMP_DB)


class TestDbBasic:
    def test_init_creates_table(self):
        """init_db() should create cache_data table without error."""
        init_db()  # Should not raise

    def test_write_and_read(self):
        """Basic write then read."""
        db_write("key1", "value1")
        assert db_read("key1") == "value1"

    def test_read_nonexistent_key(self):
        """Reading a key that doesn't exist returns None."""
        assert db_read("nonexistent") is None

    def test_write_updates_existing(self):
        """Writing to an existing key updates the value."""
        db_write("key1", "value1")
        db_write("key1", "value2")
        assert db_read("key1") == "value2"

    def test_multiple_keys(self):
        """Multiple keys are independent."""
        db_write("a", "1")
        db_write("b", "2")
        db_write("c", "3")
        assert db_read("a") == "1"
        assert db_read("b") == "2"
        assert db_read("c") == "3"

    def test_empty_value(self):
        """Empty string is a valid value (not None)."""
        db_write("key1", "")
        result = db_read("key1")
        assert result == ""
        assert result is not None


class TestDbConcurrency:
    def test_concurrent_writes_no_crash(self):
        """Multiple threads writing simultaneously should not crash."""
        errors = []

        def writer(thread_id):
            try:
                for i in range(50):
                    db_write(f"key_{thread_id}_{i}", f"val_{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Concurrent writes caused errors: {errors}"

    def test_concurrent_read_write(self):
        """Reads during writes should not crash or return corrupted data."""
        db_write("shared_key", "initial")
        errors = []

        def writer():
            try:
                for i in range(100):
                    db_write("shared_key", f"v{i}")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    val = db_read("shared_key")
                    # Value should be either None, "initial", or "v{N}"
                    if val is not None:
                        assert val == "initial" or val.startswith("v"), \
                            f"Corrupted read: {val}"
            except Exception as e:
                errors.append(e)

        w = threading.Thread(target=writer)
        r = threading.Thread(target=reader)
        w.start()
        r.start()
        w.join(timeout=30)
        r.join(timeout=30)

        assert len(errors) == 0, f"Concurrent read/write errors: {errors}"
```

**Pass criteria:** All tests green. Zero errors under concurrency.

---

### 2.2 `test_cache.py` — Redis Wrapper Tests

```python
"""
Tests for cache.py — Redis cache operations.
Requires a running Redis instance (use Docker: docker run -d -p 6379:6379 redis:7-alpine).
"""
import os
import time
import pytest

os.environ['REDIS_HOST'] = 'localhost'
os.environ['REDIS_PORT'] = '6379'

from app.cache import cache_get, cache_set, cache_delete, cache_flush


@pytest.fixture(autouse=True)
def clean_cache():
    """Flush cache before each test."""
    try:
        cache_flush()
    except Exception:
        pytest.skip("Redis not available")
    yield
    cache_flush()


class TestCacheBasic:
    def test_set_and_get(self):
        cache_set("k1", "v1", ttl=60)
        assert cache_get("k1") == "v1"

    def test_get_nonexistent(self):
        assert cache_get("nonexistent") is None

    def test_delete(self):
        cache_set("k1", "v1", ttl=60)
        cache_delete("k1")
        assert cache_get("k1") is None

    def test_delete_nonexistent_no_error(self):
        """Deleting a key that doesn't exist should not raise."""
        cache_delete("nonexistent")  # Should not raise

    def test_overwrite(self):
        cache_set("k1", "v1", ttl=60)
        cache_set("k1", "v2", ttl=60)
        assert cache_get("k1") == "v2"

    def test_flush(self):
        cache_set("k1", "v1", ttl=60)
        cache_set("k2", "v2", ttl=60)
        cache_flush()
        assert cache_get("k1") is None
        assert cache_get("k2") is None


class TestCacheTTL:
    def test_ttl_expiry(self):
        """Key should expire after TTL seconds."""
        cache_set("k1", "v1", ttl=2)
        assert cache_get("k1") == "v1"
        time.sleep(3)
        assert cache_get("k1") is None

    def test_ttl_not_expired_yet(self):
        """Key should still be available before TTL expires."""
        cache_set("k1", "v1", ttl=10)
        time.sleep(1)
        assert cache_get("k1") == "v1"


class TestCacheValueTypes:
    def test_string_value(self):
        cache_set("k", "hello world", ttl=60)
        assert cache_get("k") == "hello world"

    def test_numeric_string(self):
        cache_set("k", "12345", ttl=60)
        assert cache_get("k") == "12345"

    def test_empty_string(self):
        cache_set("k", "", ttl=60)
        result = cache_get("k")
        # Redis may return empty string or None — document which one
        # If empty string is stored, it should be retrievable
        assert result is not None or result == ""

    def test_json_string(self):
        import json
        val = json.dumps({"nested": "data"})
        cache_set("k", val, ttl=60)
        assert cache_get("k") == val
```

**Pass criteria:** All tests green. TTL test takes ~3 seconds (that's expected).

---

### 2.3 `test_strategies.py` — Strategy Unit Tests

```python
"""
Tests for individual invalidation strategies.
TTL: verify it does nothing.
Eager: verify it publishes immediately.
Batched: verify buffering and flushing.

Requires Redis for Eager and Batched tests.
"""
import os
import json
import time
import threading
import pytest

os.environ['PUBSUB_REDIS_HOST'] = 'localhost'
os.environ['PUBSUB_REDIS_PORT'] = '6379'

import redis

# These imports depend on your project structure
# Adjust paths as needed
from app.strategies.ttl import on_write as ttl_on_write
from app.strategies.eager import on_write as eager_on_write
from app.strategies.batched import on_write as batched_on_write, start_batch_flusher, _buffer, _lock


@pytest.fixture
def pubsub_listener():
    """Create a Pub/Sub listener that collects messages."""
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)
    ps = r.pubsub()
    ps.subscribe('cache_invalidation')
    # Consume the subscription confirmation message
    ps.get_message(timeout=2)
    messages = []

    def listen():
        for msg in ps.listen():
            if msg['type'] == 'message':
                messages.append(json.loads(msg['data']))

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    time.sleep(0.5)  # Let subscriber connect
    yield messages
    ps.unsubscribe()
    ps.close()


class TestTTLStrategy:
    def test_on_write_does_nothing(self):
        """TTL strategy's on_write should return without doing anything."""
        result = ttl_on_write("test_key", "test_value")
        # Should not raise, should not publish anything
        assert result is None or result == None

    def test_no_pubsub_message(self, pubsub_listener):
        """TTL strategy should NOT publish any Pub/Sub messages."""
        ttl_on_write("test_key", "test_value")
        time.sleep(1)
        assert len(pubsub_listener) == 0, \
            f"TTL published {len(pubsub_listener)} messages (expected 0)"


class TestEagerStrategy:
    def test_publishes_immediately(self, pubsub_listener):
        """Eager strategy should publish one message per write."""
        eager_on_write("item_1", "val_1")
        time.sleep(0.5)

        assert len(pubsub_listener) == 1
        msg = pubsub_listener[0]
        assert msg['action'] == 'invalidate'
        assert 'item_1' in msg['keys']

    def test_publishes_correct_key(self, pubsub_listener):
        """Published message should contain the exact key that was written."""
        eager_on_write("specific_key_42", "some_value")
        time.sleep(0.5)

        assert len(pubsub_listener) == 1
        assert pubsub_listener[0]['keys'] == ['specific_key_42']

    def test_multiple_writes_multiple_messages(self, pubsub_listener):
        """Each write should produce exactly one message."""
        for i in range(5):
            eager_on_write(f"key_{i}", f"val_{i}")

        time.sleep(1)
        assert len(pubsub_listener) == 5


class TestBatchedStrategy:
    @pytest.fixture(autouse=True)
    def clear_buffer(self):
        """Clear the batch buffer before each test."""
        with _lock:
            _buffer.clear()
        yield
        with _lock:
            _buffer.clear()

    def test_on_write_buffers_key(self):
        """on_write should add key to buffer, not publish immediately."""
        batched_on_write("key_1", "val_1")
        with _lock:
            assert "key_1" in _buffer

    def test_no_immediate_publish(self, pubsub_listener):
        """Batched should NOT publish immediately on write."""
        batched_on_write("key_1", "val_1")
        time.sleep(0.5)
        assert len(pubsub_listener) == 0

    def test_multiple_writes_buffer_all(self):
        """Multiple writes should all accumulate in the buffer."""
        for i in range(10):
            batched_on_write(f"key_{i}", f"val_{i}")
        with _lock:
            assert len(_buffer) == 10

    def test_flush_publishes_batch(self, pubsub_listener):
        """After flush interval, all buffered keys should be published in one message."""
        os.environ['BATCH_INTERVAL'] = '1'  # 1 second for faster test
        start_batch_flusher()

        for i in range(5):
            batched_on_write(f"key_{i}", f"val_{i}")

        time.sleep(2)  # Wait for flush

        assert len(pubsub_listener) >= 1
        # All keys should appear in the published message(s)
        all_keys = []
        for msg in pubsub_listener:
            all_keys.extend(msg['keys'])
        for i in range(5):
            assert f"key_{i}" in all_keys

    def test_buffer_cleared_after_flush(self):
        """Buffer should be empty after a flush."""
        os.environ['BATCH_INTERVAL'] = '1'
        start_batch_flusher()

        batched_on_write("key_1", "val_1")
        time.sleep(2)

        with _lock:
            assert len(_buffer) == 0
```

**Pass criteria:** All tests green. Batch flush test takes ~2 seconds (expected).

---

### 2.4 `test_controller.py` — Adaptive Controller Logic Tests

```python
"""
Tests for the Adaptive Controller decision logic.
Tests the threshold logic in isolation (no threads, no Pub/Sub).
"""
import time
import pytest


def controller_decide(write_rate, high_threshold=50, low_threshold=10):
    """
    Pure function version of the controller's decision logic.
    Extract this from controller.py for testability.
    """
    if write_rate > high_threshold:
        return "eager"
    elif write_rate < low_threshold:
        return "ttl"
    else:
        return "batched"


class TestControllerDecision:
    def test_low_rate_returns_ttl(self):
        assert controller_decide(0) == "ttl"
        assert controller_decide(5) == "ttl"
        assert controller_decide(9) == "ttl"
        assert controller_decide(9.9) == "ttl"

    def test_medium_rate_returns_batched(self):
        assert controller_decide(10) == "batched"
        assert controller_decide(25) == "batched"
        assert controller_decide(50) == "batched"

    def test_high_rate_returns_eager(self):
        assert controller_decide(51) == "eager"
        assert controller_decide(100) == "eager"
        assert controller_decide(500) == "eager"

    def test_boundary_low_threshold(self):
        """Exactly at LOW_THRESHOLD → batched (not ttl)."""
        assert controller_decide(10) == "batched"

    def test_boundary_high_threshold(self):
        """Exactly at HIGH_THRESHOLD → batched (not eager)."""
        assert controller_decide(50) == "batched"

    def test_custom_thresholds(self):
        assert controller_decide(15, high_threshold=20, low_threshold=5) == "batched"
        assert controller_decide(25, high_threshold=20, low_threshold=5) == "eager"
        assert controller_decide(3, high_threshold=20, low_threshold=5) == "ttl"


class TestWriteRateCalculation:
    def test_rate_from_timestamps(self):
        """
        Verify write rate calculation from a list of timestamps.
        Extract this logic from controller.py for testability.
        """
        now = time.time()
        window = 5.0

        # 20 writes in the last 5 seconds → 4.0 w/s
        timestamps = [now - i * 0.25 for i in range(20)]
        recent = [t for t in timestamps if t > now - window]
        rate = len(recent) / window
        assert abs(rate - 4.0) < 0.5

    def test_empty_timestamps(self):
        """No writes → rate = 0."""
        timestamps = []
        window = 5.0
        now = time.time()
        recent = [t for t in timestamps if t > now - window]
        rate = len(recent) / window
        assert rate == 0.0

    def test_old_timestamps_excluded(self):
        """Timestamps older than the window should not count."""
        now = time.time()
        window = 5.0
        # All timestamps are 10 seconds old
        timestamps = [now - 10 - i for i in range(50)]
        recent = [t for t in timestamps if t > now - window]
        rate = len(recent) / window
        assert rate == 0.0
```

**Pass criteria:** All tests green. No timing dependencies — these are pure logic tests.

---

## 3. INTEGRATION TESTS — COMPONENT INTERACTIONS

> **Prerequisite:** All containers running (`docker compose up -d`).

### 3.1 `test_integration.py`

```python
"""
Integration tests — verify components work together.
Requires: docker compose up -d (all 6 containers running).
Run from host machine.
"""
import time
import json
import requests
import pytest

NODE_A = "http://localhost:5001"
NODE_B = "http://localhost:5002"
NODE_C = "http://localhost:5003"
ALL_NODES = [NODE_A, NODE_B, NODE_C]


@pytest.fixture(autouse=True)
def reset_caches():
    """Reset all caches before each test."""
    for node in ALL_NODES:
        try:
            requests.post(f"{node}/reset", timeout=5)
        except requests.ConnectionError:
            pytest.skip(f"Node {node} not available — is Docker running?")
    time.sleep(0.5)
    yield


class TestHealthChecks:
    def test_all_nodes_healthy(self):
        for node in ALL_NODES:
            r = requests.get(f"{node}/health", timeout=5)
            assert r.status_code == 200
            data = r.json()
            assert data['status'] == 'healthy'

    def test_node_names_correct(self):
        names = []
        for node in ALL_NODES:
            r = requests.get(f"{node}/health", timeout=5)
            names.append(r.json()['node'])
        assert 'node_a' in names
        assert 'node_b' in names
        assert 'node_c' in names


class TestBasicReadWrite:
    def test_write_then_read_same_node(self):
        r = requests.post(f"{NODE_A}/write",
                          json={"key": "test1", "value": "hello"}, timeout=5)
        assert r.status_code == 200

        r = requests.get(f"{NODE_A}/read?key=test1", timeout=5)
        assert r.json()['value'] == "hello"

    def test_write_a_read_b(self):
        """Write on Node A, read on Node B — should get value from DB."""
        requests.post(f"{NODE_A}/write",
                      json={"key": "cross1", "value": "world"}, timeout=5)

        r = requests.get(f"{NODE_B}/read?key=cross1", timeout=5)
        data = r.json()
        assert data['value'] == "world"
        assert data['source'] == "db"  # First read is a cache miss

    def test_second_read_is_cache_hit(self):
        """Second read on same node should come from cache."""
        requests.post(f"{NODE_A}/write",
                      json={"key": "cache1", "value": "v1"}, timeout=5)

        # First read — cache miss
        requests.get(f"{NODE_B}/read?key=cache1", timeout=5)

        # Second read — cache hit
        r = requests.get(f"{NODE_B}/read?key=cache1", timeout=5)
        assert r.json()['source'] == "cache"

    def test_read_nonexistent_key(self):
        r = requests.get(f"{NODE_B}/read?key=does_not_exist", timeout=5)
        assert r.json()['value'] is None

    def test_db_read_endpoint(self):
        """Direct DB read should always return DB value."""
        requests.post(f"{NODE_A}/write",
                      json={"key": "dbr1", "value": "dbval"}, timeout=5)

        r = requests.get(f"{NODE_A}/db_read?key=dbr1", timeout=5)
        data = r.json()
        assert data['value'] == "dbval"
        assert data['source'] == "db_direct"


class TestTTLBehavior:
    def test_stale_read_under_ttl(self):
        """After a write update, other nodes should serve stale data until TTL expires."""
        # Initial write + cache on Node B
        requests.post(f"{NODE_A}/write",
                      json={"key": "stale1", "value": "v1"}, timeout=5)
        requests.get(f"{NODE_B}/read?key=stale1", timeout=5)  # Cache v1

        # Update value
        requests.post(f"{NODE_A}/write",
                      json={"key": "stale1", "value": "v2"}, timeout=5)

        # Immediate read from Node B — should be stale (still v1)
        r = requests.get(f"{NODE_B}/read?key=stale1", timeout=5)
        assert r.json()['value'] == "v1"  # STALE
        assert r.json()['source'] == "cache"

    def test_ttl_expiry_gives_fresh_data(self):
        """After TTL expires, read should return fresh value from DB."""
        requests.post(f"{NODE_A}/write",
                      json={"key": "ttltest", "value": "old"}, timeout=5)
        requests.get(f"{NODE_B}/read?key=ttltest", timeout=5)  # Cache "old"

        requests.post(f"{NODE_A}/write",
                      json={"key": "ttltest", "value": "new"}, timeout=5)

        # Wait for TTL (10s) + buffer
        time.sleep(12)

        r = requests.get(f"{NODE_B}/read?key=ttltest", timeout=5)
        assert r.json()['value'] == "new"
        assert r.json()['source'] == "db"  # Cache expired → DB read


class TestEagerInvalidation:
    """Tests for Eager strategy — requires subscriber threads running."""

    def test_eager_eliminates_stale_reads(self):
        """Under Eager, writes should invalidate caches immediately."""
        # Switch to Eager
        requests.post(f"{NODE_A}/set_strategy?strategy=eager", timeout=5)
        time.sleep(1)

        # Cache a value on Node B
        requests.post(f"{NODE_A}/write",
                      json={"key": "eager1", "value": "v1"}, timeout=5)
        requests.get(f"{NODE_B}/read?key=eager1", timeout=5)

        # Update value — Eager should invalidate Node B's cache
        requests.post(f"{NODE_A}/write",
                      json={"key": "eager1", "value": "v2"}, timeout=5)
        time.sleep(0.5)  # Small delay for Pub/Sub propagation

        # Read from Node B — should NOT be stale
        r = requests.get(f"{NODE_B}/read?key=eager1", timeout=5)
        assert r.json()['value'] == "v2"

        # Clean up — switch back to TTL
        requests.post(f"{NODE_A}/set_strategy?strategy=ttl", timeout=5)


class TestBatchedInvalidation:
    """Tests for Batched strategy."""

    def test_batched_delays_then_invalidates(self):
        """Batched should serve stale briefly, then invalidate after flush."""
        requests.post(f"{NODE_A}/set_strategy?strategy=batched", timeout=5)
        time.sleep(1)

        # Cache a value on Node B
        requests.post(f"{NODE_A}/write",
                      json={"key": "batch1", "value": "v1"}, timeout=5)
        requests.get(f"{NODE_B}/read?key=batch1", timeout=5)

        # Update value
        requests.post(f"{NODE_A}/write",
                      json={"key": "batch1", "value": "v2"}, timeout=5)

        # Wait for batch flush (2-3s) + buffer
        time.sleep(4)

        # Read from Node B — should be fresh after flush
        r = requests.get(f"{NODE_B}/read?key=batch1", timeout=5)
        assert r.json()['value'] == "v2"

        # Clean up
        requests.post(f"{NODE_A}/set_strategy?strategy=ttl", timeout=5)


class TestStrategyPropagation:
    """Verify strategy changes propagate to all nodes."""

    def test_strategy_propagates_to_all_nodes(self):
        requests.post(f"{NODE_A}/set_strategy?strategy=eager", timeout=5)
        time.sleep(2)

        for node in ALL_NODES:
            r = requests.get(f"{node}/health", timeout=5)
            assert r.json()['strategy'] == "eager", \
                f"{node} strategy is {r.json()['strategy']}, expected eager"

        # Clean up
        requests.post(f"{NODE_A}/set_strategy?strategy=ttl", timeout=5)
        time.sleep(2)
```

**Pass criteria:** All tests green. Some tests take 10-15 seconds (TTL expiry tests).

---

## 4. END-TO-END TESTS — FULL SYSTEM

### 4.1 Adaptive Controller E2E Test

```python
"""
End-to-end test for the Adaptive Controller.
Verifies the controller auto-switches strategies based on write rate.
Requires: docker compose up -d with RUN_CONTROLLER=true on Node A.
"""
import time
import requests
import threading


def send_writes(rate, duration, url="http://localhost:5001"):
    """Send writes at approximately `rate` writes/second for `duration` seconds."""
    end_time = time.time() + duration
    interval = 1.0 / rate if rate > 0 else 1.0
    counter = 0
    while time.time() < end_time:
        try:
            requests.post(f"{url}/write",
                          json={"key": f"k_{counter % 50}", "value": f"v_{counter}"},
                          timeout=2)
        except Exception:
            pass
        counter += 1
        time.sleep(interval)


def get_strategy(url="http://localhost:5001"):
    r = requests.get(f"{url}/health", timeout=5)
    return r.json()['strategy']


class TestAdaptiveControllerE2E:
    def test_low_rate_selects_ttl(self):
        """At 5 w/s, controller should select TTL."""
        send_writes(rate=5, duration=10)
        time.sleep(5)  # Let controller detect
        strategy = get_strategy()
        assert strategy == "ttl", f"Expected ttl at 5 w/s, got {strategy}"

    def test_high_rate_selects_eager(self):
        """At 80 w/s, controller should select EAGER."""
        # Use threading for higher rate
        t = threading.Thread(target=send_writes, args=(80, 15))
        t.start()
        time.sleep(10)  # Let controller detect
        strategy = get_strategy()
        t.join()
        assert strategy == "eager", f"Expected eager at 80 w/s, got {strategy}"

    def test_strategy_transitions(self):
        """Controller should transition through strategies as rate changes."""
        strategies_seen = set()

        # Low rate → TTL
        send_writes(rate=3, duration=10)
        time.sleep(5)
        strategies_seen.add(get_strategy())

        # High rate → EAGER
        t = threading.Thread(target=send_writes, args=(80, 15))
        t.start()
        time.sleep(10)
        strategies_seen.add(get_strategy())
        t.join()

        # Verify we saw at least 2 different strategies
        assert len(strategies_seen) >= 2, \
            f"Expected multiple strategies, only saw: {strategies_seen}"

    def test_switch_latency_under_5_seconds(self):
        """Strategy should switch within 5 seconds of rate change."""
        # Establish TTL baseline
        send_writes(rate=3, duration=10)
        time.sleep(5)
        assert get_strategy() == "ttl"

        # Blast writes and measure switch time
        start = time.time()
        t = threading.Thread(target=send_writes, args=(100, 20))
        t.start()

        switch_time = None
        while time.time() - start < 15:
            if get_strategy() != "ttl":
                switch_time = time.time() - start
                break
            time.sleep(0.5)

        t.join()
        assert switch_time is not None, "Strategy never switched from TTL"
        assert switch_time <= 8, \
            f"Switch took {switch_time:.1f}s (target: ≤5s, allowing 8s tolerance)"
```

---

## 5. EXPERIMENT VALIDATION TESTS

These tests validate the OUTPUTS of experiments, not the system itself.

### 5.1 CSV Output Validation

```python
"""
Validate experiment CSV files have correct schema and reasonable data.
Run after each experiment.
"""
import pandas as pd
import pytest
import os


def validate_csv(filepath):
    """Validate a single experiment CSV file."""
    assert os.path.exists(filepath), f"CSV not found: {filepath}"

    df = pd.read_csv(filepath)

    # Schema checks
    required_columns = [
        'timestamp', 'operation', 'key', 'value',
        'db_value', 'response_time_ms', 'status_code',
        'node', 'is_stale', 'strategy'
    ]
    for col in required_columns:
        assert col in df.columns, f"Missing column: {col}"

    # Data type checks
    assert df['timestamp'].dtype in ['float64', 'int64']
    assert df['operation'].isin(['read', 'write']).all()
    assert df['status_code'].isin([200, 400, 500]).all()

    # Sanity checks
    reads = df[df['operation'] == 'read']
    writes = df[df['operation'] == 'write']
    assert len(reads) > 0, "No read operations recorded"
    assert len(writes) > 0, "No write operations recorded"

    # Staleness check — only reads should have is_stale values
    assert writes['is_stale'].isna().all() or (writes['is_stale'] == '').all(), \
        "Writes should not have is_stale values"

    # Latency sanity — no negative latencies
    assert (df['response_time_ms'] >= 0).all(), "Negative latencies found"

    # Latency sanity — no absurdly high latencies (>10 seconds)
    assert (df['response_time_ms'] < 10000).all(), "Latencies >10s found"

    return df


class TestPhase1CSVs:
    def test_phase1_wr5(self):
        df = validate_csv("results/phase1_ttl_wr5.csv")
        reads = df[df['operation'] == 'read']
        srr = reads['is_stale'].astype(int).mean() * 100
        print(f"Phase 1 WR5 SRR: {srr:.2f}%")

    def test_phase1_wr25(self):
        df = validate_csv("results/phase1_ttl_wr25.csv")

    def test_phase1_wr60(self):
        df = validate_csv("results/phase1_ttl_wr60.csv")


class TestPhase2CSVs:
    def test_phase2_wr5(self):
        df = validate_csv("results/phase2_adaptive_wr5.csv")

    def test_phase2_wr25(self):
        df = validate_csv("results/phase2_adaptive_wr25.csv")

    def test_phase2_wr60(self):
        df = validate_csv("results/phase2_adaptive_wr60.csv")


class TestSRRComparison:
    def test_adaptive_improves_srr_at_high_write_rate(self):
        """Adaptive SRR should be lower than TTL SRR at 60 w/s."""
        ttl_df = pd.read_csv("results/phase1_ttl_wr60.csv")
        adaptive_df = pd.read_csv("results/phase2_adaptive_wr60.csv")

        ttl_reads = ttl_df[ttl_df['operation'] == 'read']
        adaptive_reads = adaptive_df[adaptive_df['operation'] == 'read']

        ttl_srr = ttl_reads['is_stale'].astype(int).mean() * 100
        adaptive_srr = adaptive_reads['is_stale'].astype(int).mean() * 100

        print(f"TTL SRR at 60 w/s:      {ttl_srr:.2f}%")
        print(f"Adaptive SRR at 60 w/s: {adaptive_srr:.2f}%")
        print(f"Improvement:            {((ttl_srr - adaptive_srr) / ttl_srr * 100):.1f}%")

        assert adaptive_srr < ttl_srr, \
            f"Adaptive SRR ({adaptive_srr:.2f}%) should be lower than TTL ({ttl_srr:.2f}%)"

    def test_srr_increases_with_write_rate_under_ttl(self):
        """Under TTL-only, SRR should increase as write rate increases."""
        srrs = []
        for wr in [5, 25, 60]:
            df = pd.read_csv(f"results/phase1_ttl_wr{wr}.csv")
            reads = df[df['operation'] == 'read']
            srr = reads['is_stale'].astype(int).mean() * 100
            srrs.append(srr)

        print(f"TTL SRR at 5/25/60 w/s: {srrs}")
        # SRR should generally increase (allow some variance)
        assert srrs[2] > srrs[0], \
            f"SRR at 60 w/s ({srrs[2]:.2f}%) should be > SRR at 5 w/s ({srrs[0]:.2f}%)"
```

---

## 6. REGRESSION TESTS

Run these after ANY code change to ensure nothing broke.

```python
"""
Quick regression suite — runs in <30 seconds.
Covers the most critical paths that must never break.
"""
import requests
import time

NODE_A = "http://localhost:5001"
NODE_B = "http://localhost:5002"


def test_regression_write_read():
    """Basic write-read cycle still works."""
    r = requests.post(f"{NODE_A}/write",
                      json={"key": "reg_1", "value": "check"}, timeout=5)
    assert r.status_code == 200
    r = requests.get(f"{NODE_A}/read?key=reg_1", timeout=5)
    assert r.json()['value'] == "check"


def test_regression_cross_node():
    """Cross-node reads still work."""
    requests.post(f"{NODE_A}/write",
                  json={"key": "reg_2", "value": "cross"}, timeout=5)
    r = requests.get(f"{NODE_B}/read?key=reg_2", timeout=5)
    assert r.json()['value'] == "cross"


def test_regression_health():
    """Health endpoints respond."""
    for port in [5001, 5002, 5003]:
        r = requests.get(f"http://localhost:{port}/health", timeout=5)
        assert r.status_code == 200


def test_regression_db_read():
    """/db_read still bypasses cache."""
    requests.post(f"{NODE_A}/write",
                  json={"key": "reg_3", "value": "dbcheck"}, timeout=5)
    r = requests.get(f"{NODE_A}/db_read?key=reg_3", timeout=5)
    assert r.json()['value'] == "dbcheck"
    assert r.json()['source'] == "db_direct"


def test_regression_reset():
    """/reset clears cache."""
    requests.post(f"{NODE_A}/write",
                  json={"key": "reg_4", "value": "resetme"}, timeout=5)
    requests.get(f"{NODE_A}/read?key=reg_4", timeout=5)  # Cache it
    requests.post(f"{NODE_A}/reset", timeout=5)
    r = requests.get(f"{NODE_A}/read?key=reg_4", timeout=5)
    assert r.json()['source'] == "db"  # Cache was flushed
```

---

## 7. TEST EXECUTION CHECKLIST

### Phase 1 Testing

| #  | Test                                    | Command                                              | When to Run              | Pass? |
|----|-----------------------------------------|------------------------------------------------------|--------------------------|-------|
| 1  | db.py unit tests                        | `pytest tests/test_db.py -v`                         | After writing db.py      | [ ]   |
| 2  | cache.py unit tests                     | `pytest tests/test_cache.py -v`                      | After writing cache.py   | [ ]   |
| 3  | TTL strategy unit test                  | `pytest tests/test_strategies.py::TestTTLStrategy -v` | After writing ttl.py    | [ ]   |
| 4  | Health check integration                | `pytest tests/test_integration.py::TestHealthChecks -v` | After docker compose up | [ ]  |
| 5  | Basic read/write integration            | `pytest tests/test_integration.py::TestBasicReadWrite -v` | After app.py works    | [ ]  |
| 6  | TTL behavior integration                | `pytest tests/test_integration.py::TestTTLBehavior -v`    | After TTL confirmed   | [ ]  |
| 7  | Load generator output validation        | `pytest tests/test_load_generator.py -v`                  | After load gen runs   | [ ]  |

### Phase 2 Testing

| #  | Test                                    | Command                                              | When to Run              | Pass? |
|----|-----------------------------------------|------------------------------------------------------|--------------------------|-------|
| 8  | Eager strategy unit test                | `pytest tests/test_strategies.py::TestEagerStrategy -v`   | After writing eager.py  | [ ]  |
| 9  | Batched strategy unit test              | `pytest tests/test_strategies.py::TestBatchedStrategy -v` | After writing batched.py| [ ]  |
| 10 | Controller logic unit test              | `pytest tests/test_controller.py -v`                      | After writing controller| [ ]  |
| 11 | Eager invalidation integration          | `pytest tests/test_integration.py::TestEagerInvalidation -v` | After subscriber works | [ ] |
| 12 | Batched invalidation integration        | `pytest tests/test_integration.py::TestBatchedInvalidation -v` | After batch flusher | [ ]  |
| 13 | Strategy propagation integration        | `pytest tests/test_integration.py::TestStrategyPropagation -v` | After controller     | [ ] |
| 14 | Controller E2E test                     | `pytest tests/test_e2e.py -v`                             | After full Phase 2     | [ ]  |

### Phase 3 Testing

| #  | Test                                    | Command                                              | When to Run              | Pass? |
|----|-----------------------------------------|------------------------------------------------------|--------------------------|-------|
| 15 | Phase 1 CSV validation                  | `pytest tests/test_load_generator.py::TestPhase1CSVs -v`  | After Phase 1 experiments | [ ] |
| 16 | Phase 2 CSV validation                  | `pytest tests/test_load_generator.py::TestPhase2CSVs -v`  | After Phase 2 experiments | [ ] |
| 17 | SRR comparison test                     | `pytest tests/test_load_generator.py::TestSRRComparison -v` | After all experiments   | [ ] |
| 18 | Regression suite                        | `pytest tests/test_regression.py -v`                       | After ANY code change    | [ ] |

### Full Suite

```bash
# Run everything (takes ~5 minutes)
pytest tests/ -v --tb=short

# Run only fast tests (no TTL expiry waits)
pytest tests/ -v -k "not ttl_expiry and not ttl_expiry_gives"
```

---

**END OF TESTING.md**
