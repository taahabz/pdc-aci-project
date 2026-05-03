# ARCHITECTURE.md — Component Reference & Data Flow

> **Purpose:** This is the agent's reference document for HOW the system is wired. Consult this when implementing any component. If something in `actionplan.md` is ambiguous, this document is authoritative.

---

## 1. SYSTEM TOPOLOGY

```
┌─────────────────────────────────────────────────────────────────┐
│                        HOST MACHINE                             │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              Docker Bridge Network: cache_net             │   │
│  │                                                           │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │   │
│  │  │   node_a     │  │   node_b     │  │   node_c     │     │   │
│  │  │  Flask:5001  │  │  Flask:5002  │  │  Flask:5003  │     │   │
│  │  │  IS_WRITER=T │  │  IS_WRITER=F │  │  IS_WRITER=F │     │   │
│  │  │  CONTROLLER=T│  │  CONTROLLER=F│  │  CONTROLLER=F│     │   │
│  │  │      │       │  │      │       │  │      │       │     │   │
│  │  │      │       │  │      │       │  │      │       │     │   │
│  │  │  ┌───▼───┐   │  │  ┌───▼───┐   │  │  ┌───▼───┐   │   │   │
│  │  │  │redis_a│   │  │  │redis_b│   │  │  │redis_c│   │   │   │
│  │  │  │LOCAL  │   │  │  │LOCAL  │   │  │  │LOCAL  │   │   │   │
│  │  │  │CACHE  │   │  │  │CACHE  │   │  │  │CACHE  │   │   │   │
│  │  │  └───────┘   │  │  └───────┘   │  │  └───────┘   │   │   │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │   │
│  │         │                 │                 │            │   │
│  │         │     ┌───────────┴─────────────┐   │            │   │
│  │         │     │                         │   │            │   │
│  │         ▼     ▼                         ▼   ▼            │   │
│  │  ┌──────────────────────────────────────────────┐        │   │
│  │  │           redis_a (SHARED PUB/SUB)           │        │   │
│  │  │  Channel: cache_invalidation                 │        │   │
│  │  │  Channel: strategy_update                    │        │   │
│  │  │  ALL nodes connect HERE for messaging        │        │   │
│  │  └──────────────────────────────────────────────┘        │   │
│  │                                                           │   │
│  │  ┌──────────────────────────────────────────────┐        │   │
│  │  │         SHARED SQLITE (Docker volume)        │        │   │
│  │  │         /data/cache.db                       │        │   │
│  │  │         Mounted into ALL node containers     │        │   │
│  │  └──────────────────────────────────────────────┘        │   │
│  │                                                           │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              LOAD GENERATOR (runs on host)                │   │
│  │         Sends HTTP requests to localhost:5001/5002/5003   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. THE TWO REDIS DISTINCTION (CRITICAL)

This is the single most important architectural detail. Get this wrong and nothing works.

### Each node has TWO Redis connections:

| Connection        | Purpose               | Host Variable        | What It Connects To        |
|-------------------|-----------------------|----------------------|----------------------------|
| **Local Cache**   | get/set/delete keys   | `REDIS_HOST`         | Node's OWN Redis instance  |
| **Pub/Sub Bus**   | publish/subscribe     | `PUBSUB_REDIS_HOST`  | SHARED Redis (always redis_a) |

### Why two connections?

- **Local Cache** must be per-node. If all nodes shared one Redis for caching, there would be no "distributed cache" to invalidate — it would be a single shared cache, which defeats the entire project.
- **Pub/Sub Bus** must be shared. All nodes need to hear the same messages. Redis Pub/Sub only delivers to subscribers connected to the SAME Redis instance.

### Connection Map:

```
node_a:
  cache.py    → redis_a:6379  (local cache)
  subscriber  → redis_a:6379  (pub/sub — same instance, different connection)

node_b:
  cache.py    → redis_b:6379  (local cache)
  subscriber  → redis_a:6379  (pub/sub — connects to redis_a!)

node_c:
  cache.py    → redis_c:6379  (local cache)
  subscriber  → redis_a:6379  (pub/sub — connects to redis_a!)
```

### Code pattern:

```python
# cache.py — uses LOCAL Redis
import redis, os
local_redis = redis.Redis(
    host=os.environ.get('REDIS_HOST', 'localhost'),
    port=int(os.environ.get('REDIS_PORT', 6379)),
    decode_responses=True
)

# subscriber.py — uses SHARED Pub/Sub Redis
pubsub_redis = redis.Redis(
    host=os.environ.get('PUBSUB_REDIS_HOST', 'redis_a'),
    port=int(os.environ.get('PUBSUB_REDIS_PORT', 6379)),
    decode_responses=True
)
```

**NEVER cross these. NEVER use `REDIS_HOST` for Pub/Sub. NEVER use `PUBSUB_REDIS_HOST` for cache operations.**

---

## 3. DATA FLOWS

### 3.1 Read Flow (All Nodes)

```
Client GET /read?key=X
        │
        ▼
┌─ cache_get(X) ─────────────────┐
│  Redis local cache              │
│                                 │
│  HIT?  ─── YES ──▶ Return value from cache
│    │                {"source": "cache"}
│    NO
│    │
│    ▼
│  db_read(X) ───────────────────┐
│  SQLite shared DB               │
│                                 │
│  FOUND? ─── YES ──▶ cache_set(X, value, TTL=10)
│    │                 Return value from DB
│    │                 {"source": "db"}
│    NO
│    │
│    ▼
│  Return null
│  {"value": null, "source": "db"}
└─────────────────────────────────┘
```

### 3.2 Write Flow (Node A Only)

```
Client POST /write {key: X, value: V}
        │
        ▼
┌─ db_write(X, V) ───────────────┐
│  Write to SQLite                │
│  (INSERT OR REPLACE)            │
│                                 │
│  SUCCESS?                       │
│    │                            │
│    ▼                            │
│  Append time.time() to          │
│  write_timestamps list          │
│  (for controller to read)      │
│                                 │
│    │                            │
│    ▼                            │
│  current_strategy.on_write(X,V) │
│    │                            │
│    ├── TTL:     do nothing      │
│    ├── EAGER:   publish immediately │
│    └── BATCHED: append to buffer│
│                                 │
│    ▼                            │
│  Return {"status": "ok"}        │
└─────────────────────────────────┘
```

### 3.3 Invalidation Flow (Eager)

```
Node A                     redis_a (Pub/Sub)           Node B / Node C
  │                              │                          │
  │  publish(                    │                          │
  │    "cache_invalidation",     │                          │
  │    {"action":"invalidate",   │                          │
  │     "keys":["X"]}           │                          │
  │  )                           │                          │
  │ ─────────────────────────▶  │                          │
  │                              │  deliver to subscribers  │
  │                              │ ─────────────────────▶  │
  │                              │                          │
  │                              │                    subscriber thread:
  │                              │                    cache_delete("X")
  │                              │                    on LOCAL redis_b / redis_c
  │                              │                          │
  │                              │                    Next /read for X:
  │                              │                    cache MISS → DB read
  │                              │                    → gets fresh value
```

### 3.4 Invalidation Flow (Batched)

```
Node A                     redis_a (Pub/Sub)           Node B / Node C
  │                              │                          │
  │  on_write("X"): buffer.append("X")                     │
  │  on_write("Y"): buffer.append("Y")                     │
  │  on_write("Z"): buffer.append("Z")                     │
  │                              │                          │
  │  ... 2-3 seconds pass ...    │                          │
  │                              │                          │
  │  _flush():                   │                          │
  │  publish(                    │                          │
  │    "cache_invalidation",     │                          │
  │    {"action":"invalidate",   │                          │
  │     "keys":["X","Y","Z"]}   │                          │
  │  )                           │                          │
  │ ─────────────────────────▶  │                          │
  │                              │ ─────────────────────▶  │
  │                              │                    cache_delete("X")
  │                              │                    cache_delete("Y")
  │                              │                    cache_delete("Z")
```

### 3.5 Strategy Switch Flow

```
Controller (Node A)        redis_a (Pub/Sub)           All Nodes
  │                              │                          │
  │  calculate write_rate        │                          │
  │  = 65 w/s                    │                          │
  │  65 > HIGH_THRESHOLD(50)     │                          │
  │  → switch to EAGER           │                          │
  │                              │                          │
  │  publish(                    │                          │
  │    "strategy_update",        │                          │
  │    {"strategy":"eager"}      │                          │
  │  )                           │                          │
  │ ─────────────────────────▶  │                          │
  │                              │ ─────────────────────▶  │
  │                              │                    subscriber thread:
  │                              │                    current_strategy = eager
  │                              │                    log("Strategy → eager")
```

---

## 4. ADAPTIVE CONTROLLER STATE MACHINE

```
                    ┌──────────────────────────────┐
                    │                              │
                    │  Controller wakes up every   │
                    │  CONTROLLER_INTERVAL (3s)    │
                    │                              │
                    │  Counts writes in last       │
                    │  WRITE_WINDOW (5s)           │
                    │                              │
                    │  write_rate = count / 5.0    │
                    │                              │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │    write_rate > 50 ?          │
                    └──┬───────────────────────┬───┘
                     YES                       NO
                      │                         │
              ┌───────▼───────┐     ┌──────────▼───────────┐
              │               │     │    write_rate < 10 ?  │
              │    EAGER      │     └──┬────────────────┬──┘
              │               │      YES                NO
              │  Immediate    │       │                  │
              │  invalidation │  ┌────▼─────┐   ┌───────▼──────┐
              │  per write    │  │          │   │              │
              │               │  │   TTL    │   │   BATCHED    │
              │  SRR: ~0%     │  │          │   │              │
              │  Msgs: HIGH   │  │  Passive │   │  2-3s flush  │
              └───────────────┘  │  expiry  │   │  window      │
                                 │          │   │              │
                                 │  SRR:var │   │  SRR: low    │
                                 │  Msgs: 0 │   │  Msgs: MED   │
                                 └──────────┘   └──────────────┘
```

### Threshold Boundaries:

```
Write Rate (w/s):  0 ─────── 10 ──────────── 50 ───────── ∞
                   │          │               │            │
Strategy:         TTL      BATCHED          EAGER        EAGER
                   │          │               │            │
SRR:            varies    low (2-3s)      ~0% (instant)   │
Msg overhead:     0        medium           high          │
```

### Hysteresis Note:
The current design does NOT include hysteresis (dead band). If write rate oscillates around a threshold (e.g., 49-51 w/s), the strategy will flip back and forth. This is acceptable for this project. If it causes issues in experiments, add a ±5 dead band:
```python
# Optional hysteresis (implement only if needed)
if current_strategy == "eager" and write_rate < HIGH_THRESHOLD - 5:  # 45
    new_strategy = "batched"
elif current_strategy == "ttl" and write_rate > LOW_THRESHOLD + 5:  # 15
    new_strategy = "batched"
```

---

## 5. THREAD MODEL PER NODE

Each node runs multiple threads. Understanding this prevents race conditions.

```
┌─────────────────────────────────────────────────────────────┐
│                     Flask Node Process                       │
│                                                              │
│  ┌──────────────────────────────────────────────────┐       │
│  │  MAIN THREAD                                      │       │
│  │  Flask server (threaded=True)                     │       │
│  │  Handles: /read, /write, /health, /reset          │       │
│  │                                                    │       │
│  │  Shared state:                                     │       │
│  │    - current_strategy (string)                     │       │
│  │    - write_timestamps (list) [Node A only]         │       │
│  └──────────────────────────────────────────────────┘       │
│                                                              │
│  ┌──────────────────────────────────────────────────┐       │
│  │  THREAD 1: Pub/Sub Subscriber (daemon)            │       │
│  │  Blocking loop: pubsub.listen()                   │       │
│  │  Reads: cache_invalidation, strategy_update       │       │
│  │  Writes: current_strategy (on strategy_update)    │       │
│  │  Calls: cache_delete(key) (on invalidation)       │       │
│  └──────────────────────────────────────────────────┘       │
│                                                              │
│  ┌──────────────────────────────────────────────────┐       │
│  │  THREAD 2: Adaptive Controller (daemon)           │       │
│  │  [NODE A ONLY — gated by RUN_CONTROLLER=true]     │       │
│  │  Runs every CONTROLLER_INTERVAL seconds           │       │
│  │  Reads: write_timestamps                          │       │
│  │  Writes: current_strategy                         │       │
│  │  Publishes: strategy_update channel               │       │
│  └──────────────────────────────────────────────────┘       │
│                                                              │
│  ┌──────────────────────────────────────────────────┐       │
│  │  THREAD 3: Batch Flusher (daemon)                 │       │
│  │  [ACTIVE ONLY WHEN strategy == "batched"]         │       │
│  │  Runs every BATCH_INTERVAL seconds                │       │
│  │  Reads: _buffer (list of keys)                    │       │
│  │  Writes: _buffer (clears it after flush)          │       │
│  │  Publishes: cache_invalidation channel            │       │
│  │  PROTECTED BY: threading.Lock()                   │       │
│  └──────────────────────────────────────────────────┘       │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### Thread Safety Rules:

| Shared Variable       | Accessed By                          | Protection Needed          |
|------------------------|--------------------------------------|----------------------------|
| `current_strategy`     | Flask threads, Subscriber, Controller | Use a simple global string. Python's GIL makes single-word assignments atomic. No lock needed. |
| `write_timestamps`     | Flask /write handler, Controller     | Use `threading.Lock()`. Flask threads append; Controller reads + trims. |
| `_buffer` (batched)    | Flask /write handler, Batch Flusher  | Use `threading.Lock()`. Flask appends; Flusher reads + clears. |

### Critical: Lock Granularity for `_buffer`

```python
# CORRECT — lock only during buffer manipulation
def on_write(key, value):
    with _lock:
        _buffer.append(key)

def _flush():
    with _lock:
        if not _buffer:
            return
        keys = list(_buffer)
        _buffer.clear()
    # Publish OUTSIDE the lock — network I/O should not hold the lock
    pubsub_redis.publish('cache_invalidation', json.dumps({
        "action": "invalidate",
        "keys": keys
    }))
```

```python
# WRONG — holding lock during network I/O
def _flush():
    with _lock:
        keys = list(_buffer)
        _buffer.clear()
        pubsub_redis.publish(...)  # DON'T — this blocks other writes
```

---

## 6. SQLITE CONCURRENCY MODEL

SQLite uses file-level locking. Only ONE writer at a time across ALL processes.

```
node_a ──write──▶ ┌────────────┐
                   │  SQLite    │  ◀── File lock: only one write at a time
node_b ──read───▶ │  cache.db  │  ◀── Multiple concurrent reads OK
node_c ──read───▶ │            │
                   └────────────┘
```

### Rules:
1. **Always use `timeout=10`** in `sqlite3.connect()`. Without this, concurrent write attempts raise `OperationalError: database is locked` immediately instead of waiting.
2. **Open and close connections per-request.** Do NOT share a single connection across threads — `sqlite3.Connection` objects are not thread-safe by default.
3. **Use WAL mode** for better concurrent read/write performance:
   ```python
   conn = sqlite3.connect(DB_PATH, timeout=10)
   conn.execute("PRAGMA journal_mode=WAL")
   ```
   WAL (Write-Ahead Logging) allows readers to proceed while a writer is active. Without WAL, readers are blocked during writes.
4. **Our write rates (5-60 w/s) are well within SQLite's capacity** (~1000-5000 writes/s on SSD). The bottleneck is the single-writer constraint, not raw throughput.

---

## 7. DOCKER NETWORKING

### Port Mapping:

```
HOST                          CONTAINER
localhost:5001  ────────────▶  node_a:5001
localhost:5002  ────────────▶  node_b:5002
localhost:5003  ────────────▶  node_c:5003
localhost:6379  ────────────▶  redis_a:6379
localhost:6380  ────────────▶  redis_b:6379  (note: internal port is always 6379)
localhost:6381  ────────────▶  redis_c:6379
```

### Inter-Container DNS:

Inside the `cache_net` bridge network, containers resolve each other by service name:
- `node_a` can reach `redis_a` at hostname `redis_a`, port `6379`
- `node_b` can reach `redis_a` at hostname `redis_a`, port `6379` (for Pub/Sub)
- `node_b` can reach `redis_b` at hostname `redis_b`, port `6379` (for local cache)

**NEVER use `localhost` inside a container to refer to another container.** `localhost` inside `node_b` means `node_b` itself, not the host machine.

### Volume Mount:

```yaml
volumes:
  shared_db:  # Named volume — Docker manages the storage location

services:
  node_a:
    volumes:
      - shared_db:/data    # SQLite file lives at /data/cache.db inside container
  node_b:
    volumes:
      - shared_db:/data    # Same volume — same file
  node_c:
    volumes:
      - shared_db:/data    # Same volume — same file
```

---

## 8. METRICS COLLECTION ARCHITECTURE

### How SRR Is Measured:

```
Load Generator
    │
    │  1. POST /write to Node A: key=X, value=V3
    │
    │  2. GET /read from Node B: key=X
    │     Response: value=V2 (stale — cache hasn't been invalidated yet)
    │
    │  3. GET /db_read from Node A: key=X
    │     Response: value=V3 (ground truth from SQLite)
    │
    │  4. Compare: V2 != V3 → is_stale = 1
    │
    │  5. Log to CSV:
    │     timestamp, read, X, V2, V3, 4.2ms, 200, node_b, 1, ttl
```

### Why This Design Works:

- Step 2 and 3 happen back-to-back (milliseconds apart).
- Step 3 reads directly from SQLite (bypasses cache) via the `/db_read` endpoint.
- The small time gap between step 2 and 3 could theoretically cause a false positive (a write happens between the two reads). At our write rates (5-60 w/s), this is unlikely for any single request. Over thousands of requests, the error is negligible.
- This is the same approach used in academic distributed systems benchmarks.

### What Gets Logged:

```
Per-Request CSV Row:
┌───────────┬───────────┬─────┬───────┬──────────┬──────────────┬───────────┬──────┬──────────┬──────────┐
│ timestamp │ operation │ key │ value │ db_value │ response_ms  │ status    │ node │ is_stale │ strategy │
├───────────┼───────────┼─────┼───────┼──────────┼──────────────┼───────────┼──────┼──────────┼──────────┤
│ 1717..123 │ read      │ k_5 │ v_42  │ v_47     │ 3.8          │ 200       │ b    │ 1        │ ttl      │
│ 1717..124 │ write     │ k_5 │ v_48  │          │ 5.1          │ 200       │ a    │          │ ttl      │
└───────────┴───────────┴─────┴───────┴──────────┴──────────────┴───────────┴──────┴──────────┴──────────┘
```

---

## 9. FAILURE MODES REFERENCE

| Scenario                  | What Happens                                    | System Behavior                    | Recovery                              |
|---------------------------|-------------------------------------------------|------------------------------------|---------------------------------------|
| Redis local cache dies    | `cache_get()` raises `ConnectionError`           | All reads fall through to SQLite   | Automatic — catch exception, return None |
| Redis Pub/Sub dies        | Subscriber thread loses connection               | No invalidation messages delivered  | Subscriber retries every 2s           |
| Node goes offline         | Docker container stops                           | Other nodes unaffected             | Missed messages → stale data until TTL |
| SQLite locked             | `db_write()` blocks up to 10s                   | Write is slow but succeeds         | `timeout=10` handles this             |
| Controller thread crashes | Unhandled exception kills thread                | Strategy freezes at last value      | Flask continues serving; log the error |
| Batch flusher crashes     | Buffered keys never flushed                     | Stale data until TTL expires       | Log error; TTL is the safety net      |

---

## 10. KEY DESIGN DECISIONS LOG

| #  | Decision                                    | Rationale                                                        | Alternative Considered              |
|----|---------------------------------------------|------------------------------------------------------------------|-------------------------------------|
| 1  | Single codebase, ENV-driven node behavior  | Avoids code duplication; easier to maintain                      | Separate code per node              |
| 2  | redis_a is both Node A's local cache AND the Pub/Sub bus | Simplifies Docker setup; Node A's cache invalidation is a local delete anyway | Dedicated 4th Redis for Pub/Sub  |
| 3  | `/db_read` endpoint for SRR verification   | Clean HTTP-based approach; load gen doesn't need direct DB access | Load gen connects to SQLite directly |
| 4  | `threading.Lock` over `asyncio`            | Flask is synchronous; threading is simpler to reason about       | asyncio + aiohttp                   |
| 5  | JSON messages on Pub/Sub                   | Human-readable; easy to debug; negligible overhead at our scale  | MessagePack / Protobuf              |
| 6  | WAL mode for SQLite                        | Allows concurrent reads during writes                            | Default journal mode                |
| 7  | No hysteresis on controller thresholds     | Simplicity; oscillation is acceptable for this project           | ±5 dead band                        |
| 8  | Fire-and-forget Pub/Sub (no replay)        | Intentional limitation; tested in Phase 3 fault experiment       | Redis Streams with consumer groups  |

---

**END OF ARCHITECTURE.md**
