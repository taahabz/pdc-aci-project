# API_SPEC.md — Complete Endpoint Reference

> **Purpose:** Exact request/response contracts for every HTTP endpoint. The agent must implement endpoints that match these specifications exactly. The load generator depends on these response shapes.

---

## BASE URLS

| Node   | Internal (container-to-container) | External (host machine)      |
|--------|-----------------------------------|-------------------------------|
| Node A | `http://node_a:5001`              | `http://localhost:5001`       |
| Node B | `http://node_b:5002`              | `http://localhost:5002`       |
| Node C | `http://node_c:5003`              | `http://localhost:5003`       |

---

## ENDPOINT 1: `GET /read`

### Description
Read a value by key. Checks local Redis cache first, falls back to shared SQLite database on cache miss.

### Request
```
GET /read?key=<key>
```

| Parameter | Location | Type   | Required | Description                |
|-----------|----------|--------|----------|----------------------------|
| `key`     | query    | string | YES      | The key to look up         |

### Response — Cache Hit
```json
HTTP/1.1 200 OK
Content-Type: application/json

{
    "key": "item_42",
    "value": "some_value_v7",
    "source": "cache",
    "node": "node_b",
    "timestamp": 1717500000.123
}
```

### Response — Cache Miss, DB Hit
```json
HTTP/1.1 200 OK
Content-Type: application/json

{
    "key": "item_42",
    "value": "some_value_v7",
    "source": "db",
    "node": "node_b",
    "timestamp": 1717500000.456
}
```
**Side effect:** The value is cached in local Redis with TTL on a cache miss + DB hit.

### Response — Cache Miss, DB Miss
```json
HTTP/1.1 200 OK
Content-Type: application/json

{
    "key": "item_42",
    "value": null,
    "source": "db",
    "node": "node_b",
    "timestamp": 1717500000.789
}
```
**Side effect:** Nothing is cached (don't cache null values).

### Response — Missing Key Parameter
```json
HTTP/1.1 400 Bad Request
Content-Type: application/json

{
    "error": "Missing required parameter: key"
}
```

### Response — Redis Down (Graceful Degradation)
```json
HTTP/1.1 200 OK
Content-Type: application/json

{
    "key": "item_42",
    "value": "some_value_v7",
    "source": "db",
    "node": "node_b",
    "timestamp": 1717500001.234
}
```
**Behavior:** If Redis is unreachable, skip cache entirely and read from DB. Do NOT return an error — the system degrades gracefully.

### Implementation Pseudocode
```python
@app.route('/read')
def read():
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
    except redis.ConnectionError:
        pass  # Cache down — fall through to DB

    # Cache miss — read from DB
    value = db_read(key)

    # Cache the result (if not null and Redis is up)
    if value is not None:
        try:
            cache_set(key, value, ttl=CACHE_TTL)
        except redis.ConnectionError:
            pass  # Cache down — skip caching

    return jsonify({
        "key": key,
        "value": value,
        "source": "db",
        "node": NODE_NAME,
        "timestamp": time.time()
    })
```

---

## ENDPOINT 2: `POST /write`

### Description
Write a key-value pair to the shared SQLite database. Applies the current invalidation strategy after writing. Only Node A should accept writes in normal operation (but all nodes CAN have the endpoint for flexibility).

### Request
```
POST /write
Content-Type: application/json

{
    "key": "item_42",
    "value": "new_value_v8"
}
```

| Field   | Type   | Required | Description               |
|---------|--------|----------|---------------------------|
| `key`   | string | YES      | The key to write          |
| `value` | string | YES      | The value to store        |

### Response — Success
```json
HTTP/1.1 200 OK
Content-Type: application/json

{
    "status": "ok",
    "key": "item_42",
    "value": "new_value_v8",
    "strategy": "eager",
    "node": "node_a",
    "timestamp": 1717500002.567
}
```

### Response — Missing Fields
```json
HTTP/1.1 400 Bad Request
Content-Type: application/json

{
    "error": "Missing required fields: key, value"
}
```

### Response — DB Write Failure
```json
HTTP/1.1 500 Internal Server Error
Content-Type: application/json

{
    "error": "Database write failed",
    "detail": "database is locked"
}
```

### Side Effects (in order)
1. Write to SQLite: `INSERT OR REPLACE INTO cache_data (key, value, updated_at) VALUES (?, ?, time.time())`
2. Append `time.time()` to `write_timestamps` list (for controller)
3. Also update local cache on the write node: `cache_set(key, value, ttl=CACHE_TTL)` — the write node should have the fresh value in its own cache
4. Call `current_strategy.on_write(key, value)`:
   - TTL: no-op
   - EAGER: publish invalidation immediately
   - BATCHED: append key to buffer

### Implementation Pseudocode
```python
@app.route('/write', methods=['POST'])
def write():
    data = request.get_json()
    if not data or 'key' not in data or 'value' not in data:
        return jsonify({"error": "Missing required fields: key, value"}), 400

    key = data['key']
    value = data['value']

    try:
        db_write(key, value)
    except Exception as e:
        return jsonify({"error": "Database write failed", "detail": str(e)}), 500

    # Track write timestamp for controller
    with write_timestamps_lock:
        write_timestamps.append(time.time())

    # Update local cache on write node
    try:
        cache_set(key, value, ttl=CACHE_TTL)
    except redis.ConnectionError:
        pass

    # Apply current invalidation strategy
    try:
        current_strategy_fn(key, value)
    except Exception as e:
        app.logger.error(f"Strategy on_write failed: {e}")

    return jsonify({
        "status": "ok",
        "key": key,
        "value": value,
        "strategy": current_strategy_name,
        "node": NODE_NAME,
        "timestamp": time.time()
    })
```

---

## ENDPOINT 3: `GET /health`

### Description
Health check endpoint. Returns node status and current active strategy.

### Request
```
GET /health
```

### Response
```json
HTTP/1.1 200 OK
Content-Type: application/json

{
    "status": "healthy",
    "node": "node_a",
    "strategy": "eager",
    "is_writer": true,
    "controller_active": true,
    "uptime_seconds": 342.5,
    "timestamp": 1717500003.890
}
```

| Field               | Type    | Description                                    |
|---------------------|---------|------------------------------------------------|
| `status`            | string  | Always `"healthy"` if responding               |
| `node`              | string  | Node identifier from `NODE_NAME` env var       |
| `strategy`          | string  | Current active strategy: `ttl`/`eager`/`batched` |
| `is_writer`         | boolean | Whether this node accepts writes               |
| `controller_active` | boolean | Whether the Adaptive Controller is running     |
| `uptime_seconds`    | float   | Seconds since Flask app started                |
| `timestamp`         | float   | Current `time.time()`                          |

---

## ENDPOINT 4: `POST /reset`

### Description
Flush the local Redis cache. Used between experiment runs to ensure clean state.

### Request
```
POST /reset
```

### Response
```json
HTTP/1.1 200 OK
Content-Type: application/json

{
    "status": "reset",
    "node": "node_b",
    "timestamp": 1717500004.123
}
```

### Side Effects
1. Call `cache_flush()` — executes `FLUSHDB` on local Redis.
2. Does NOT clear the SQLite database (data persists across resets).
3. Does NOT reset the strategy (stays at current strategy).

---

## ENDPOINT 5: `GET /db_read`

### Description
Read a value directly from SQLite, bypassing the Redis cache entirely. Used by the load generator to get ground truth for SRR calculation.

### Request
```
GET /db_read?key=<key>
```

| Parameter | Location | Type   | Required | Description           |
|-----------|----------|--------|----------|-----------------------|
| `key`     | query    | string | YES      | The key to look up    |

### Response — Key Exists
```json
HTTP/1.1 200 OK
Content-Type: application/json

{
    "key": "item_42",
    "value": "new_value_v8",
    "source": "db_direct",
    "timestamp": 1717500005.456
}
```

### Response — Key Does Not Exist
```json
HTTP/1.1 200 OK
Content-Type: application/json

{
    "key": "item_42",
    "value": null,
    "source": "db_direct",
    "timestamp": 1717500005.789
}
```

### Implementation
```python
@app.route('/db_read')
def direct_db_read():
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
```

**IMPORTANT:** This endpoint NEVER touches Redis. It reads ONLY from SQLite. This is the ground truth source for SRR measurement.

---

## ENDPOINT 6: `POST /set_strategy`

### Description
Manually override the active invalidation strategy. Used for testing individual strategies in isolation. In production (Phase 2+), the Adaptive Controller manages strategy selection automatically.

### Request
```
POST /set_strategy?strategy=<strategy_name>
```

| Parameter  | Location | Type   | Required | Valid Values                 |
|------------|----------|--------|----------|------------------------------|
| `strategy` | query    | string | YES      | `ttl`, `eager`, `batched`    |

### Response — Success
```json
HTTP/1.1 200 OK
Content-Type: application/json

{
    "status": "ok",
    "previous_strategy": "ttl",
    "new_strategy": "eager",
    "node": "node_a",
    "timestamp": 1717500006.123
}
```

### Response — Invalid Strategy
```json
HTTP/1.1 400 Bad Request
Content-Type: application/json

{
    "error": "Invalid strategy. Must be one of: ttl, eager, batched"
}
```

### Side Effects
1. Update local `current_strategy_name` and `current_strategy_fn`.
2. If switching to `batched`: ensure the batch flusher thread is started.
3. Publish to `strategy_update` channel so other nodes switch too:
   ```json
   {"strategy": "eager"}
   ```
4. This endpoint should ONLY be available on Node A (the writer node).

---

## PUB/SUB MESSAGE FORMATS

These are not HTTP endpoints but are equally critical contracts.

### Channel: `cache_invalidation`

**Published by:** Node A (via eager.py or batched.py)
**Subscribed by:** Node B, Node C (via subscriber.py)

```json
{
    "action": "invalidate",
    "keys": ["item_5", "item_12", "item_33"],
    "timestamp": 1717500007.890,
    "source": "node_a",
    "strategy": "batched"
}
```

| Field       | Type         | Description                                    |
|-------------|--------------|------------------------------------------------|
| `action`    | string       | Always `"invalidate"`                          |
| `keys`      | string[]     | List of keys to delete from local cache        |
| `timestamp` | float        | When the message was published                 |
| `source`    | string       | Which node published this                      |
| `strategy`  | string       | Which strategy triggered this message          |

**Eager:** sends one message per write with `keys: [single_key]`.
**Batched:** sends one message per flush with `keys: [all_buffered_keys]`.
**TTL:** never publishes to this channel.

### Channel: `strategy_update`

**Published by:** Adaptive Controller (on Node A)
**Subscribed by:** All nodes (via subscriber.py)

```json
{
    "strategy": "eager",
    "write_rate": 67.4,
    "timestamp": 1717500008.123,
    "source": "controller"
}
```

| Field        | Type   | Description                                 |
|--------------|--------|---------------------------------------------|
| `strategy`   | string | New active strategy: `ttl`/`eager`/`batched` |
| `write_rate` | float  | Current measured write rate (w/s)           |
| `timestamp`  | float  | When the decision was made                  |
| `source`     | string | Always `"controller"`                       |

---

## LOAD GENERATOR COMMAND-LINE INTERFACE

Not an HTTP endpoint, but the agent needs this spec to build `load_generator.py`.

### Usage
```bash
python3 load_gen/load_generator.py [OPTIONS]
```

### Arguments

| Argument           | Type   | Default                                                      | Description                              |
|--------------------|--------|--------------------------------------------------------------|------------------------------------------|
| `--write-rate`     | int    | `10`                                                         | Target writes per second                 |
| `--read-rate`      | int    | `100`                                                        | Target reads per second                  |
| `--duration`       | int    | `60`                                                         | Test duration in seconds                 |
| `--write-node`     | str    | `http://localhost:5001`                                      | URL of the write node                    |
| `--read-nodes`     | str    | `http://localhost:5001,http://localhost:5002,http://localhost:5003` | Comma-separated read node URLs     |
| `--output`         | str    | `results/experiment.csv`                                     | Output CSV file path                     |
| `--key-space`      | int    | `100`                                                        | Number of unique keys (item_0..item_N-1) |
| `--mixed-workload` | flag   | `false`                                                      | Enable mixed workload mode               |

### Output

**stdout:** Progress updates every 5 seconds:
```
[  5s] writes: 50 | reads: 500 | stale: 23 (4.6%) | avg_latency: 5.2ms
[ 10s] writes: 100 | reads: 1000 | stale: 41 (4.1%) | avg_latency: 4.8ms
...
[DONE] Total: 6500 requests in 60.0s | SRR: 4.3% | Avg latency: 5.0ms
```

**CSV file:** One row per request (see CSV schema in actionplan.md Section 7.4).

### Mixed Workload Mode (`--mixed-workload`)

When enabled, the write rate changes every 30 seconds:
```
0-30s:   write_rate = 5 w/s
30-60s:  write_rate = 60 w/s
60-90s:  write_rate = 25 w/s
90-120s: write_rate = 5 w/s
```
Duration is automatically set to 120 seconds.
Read rate stays constant at the `--read-rate` value.

---

## RESPONSE FIELD GLOSSARY

| Field         | Type    | Present In           | Description                                         |
|---------------|---------|----------------------|-----------------------------------------------------|
| `key`         | string  | /read, /write, /db_read | The cache key                                    |
| `value`       | string? | /read, /write, /db_read | The stored value (null if not found)             |
| `source`      | string  | /read, /db_read      | Where data came from: `cache`, `db`, `db_direct`    |
| `node`        | string  | all endpoints        | Which node served this response                     |
| `strategy`    | string  | /write, /health, /set_strategy | Current active invalidation strategy    |
| `status`      | string  | /write, /health, /reset, /set_strategy | `ok`, `healthy`, `reset`        |
| `timestamp`   | float   | all endpoints        | `time.time()` when response was generated            |
| `is_writer`   | boolean | /health              | Whether this node accepts writes                    |
| `controller_active` | boolean | /health         | Whether the Adaptive Controller thread is running    |
| `error`       | string  | error responses      | Human-readable error description                    |

---

**END OF API_SPEC.md**
