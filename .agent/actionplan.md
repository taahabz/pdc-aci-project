# ACTIONPLAN: Adaptive Cache Invalidation in Distributed Systems

## Agent Execution Guide — SRS + Gameplan

> **Purpose:** This document is a step-by-step, validation-gated execution plan for an AI agent (or developer) to build the entire project from scratch. Every step has a concrete deliverable, a validation check, and a pass/fail gate. Do NOT proceed to the next step until the current step's validation passes.

---

## TABLE OF CONTENTS

1. [Project Summary & Goals](#1-project-summary--goals)
2. [Prerequisites & Environment Setup](#2-prerequisites--environment-setup)
3. [Phase 1 — Baseline Infrastructure](#3-phase-1--baseline-infrastructure)
4. [Phase 2 — Adaptive System](#4-phase-2--adaptive-system)
5. [Phase 3 — Experiments & Analysis](#5-phase-3--experiments--analysis)
6. [Checkpoints & Milestones](#6-checkpoints--milestones)
7. [Appendix — Constants, Thresholds, File Manifest](#7-appendix--constants-thresholds-file-manifest)

---

## 1. PROJECT SUMMARY & GOALS

### 1.1 What We Are Building

A distributed cache invalidation system with 3 application nodes, each with its own Redis cache, connected via Redis Pub/Sub, backed by a shared SQLite database. An Adaptive Controller on Node A monitors the write rate and dynamically switches between three cache invalidation strategies: EAGER, BATCHED, and TTL.

### 1.2 Hypothesis to Test

**H1:** The adaptive cache invalidation system will reduce the Stale Read Ratio (SRR) by at least 40% compared to a static TTL-only approach under varying write rates, while keeping message overhead proportional to the write rate.

### 1.3 Target Metrics (Pass/Fail Criteria for the Project)

| Metric                 | Target                         |
|------------------------|--------------------------------|
| Stale Read Ratio (SRR) | < 5% under adaptive system     |
| Request Latency (P95)  | ≤ 100 ms on local Docker       |
| Throughput (RPS)        | ≥ 500 req/s on local sim       |
| Strategy Switch Time   | ≤ 5 seconds                    |

### 1.4 Technology Stack

| Component          | Technology              |
|--------------------|-------------------------|
| App Nodes          | Python 3.11 + Flask     |
| Cache              | Redis 7                 |
| Database           | SQLite3 (shared volume) |
| Message Bus        | Redis Pub/Sub           |
| Containerization   | Docker + Docker Compose |
| Load Generation    | Python threading + requests |
| Plotting           | matplotlib              |
| OS                 | Any with Docker support |

---

## 2. PREREQUISITES & ENVIRONMENT SETUP

### Step 2.1 — Verify Docker & Docker Compose

**Action:**
```bash
docker --version
docker compose version
```

**Validation:**
- Docker version ≥ 20.x prints to stdout.
- Docker Compose version ≥ 2.x prints to stdout.

**If fail:** Install Docker Desktop (Mac/Win) or Docker Engine + Compose plugin (Linux).

---

### Step 2.2 — Verify Python 3.11+

**Action:**
```bash
python3 --version
```

**Validation:**
- Python 3.11.x or higher.

**If fail:** Install Python 3.11 via pyenv or system package manager.

---

### Step 2.3 — Verify pip packages (for local load generator & plotting)

**Action:**
```bash
pip install requests matplotlib pandas
```

**Validation:**
```bash
python3 -c "import requests, matplotlib, pandas; print('OK')"
```
Output: `OK`

---

### Step 2.4 — Create Project Directory Structure

**Action:** Create the following exact folder/file tree:

```
adaptive-cache-invalidation/
├── docker-compose.yml
├── requirements.txt
├── shared_db/                    # SQLite volume mount point
│   └── .gitkeep
├── node_a/
│   ├── Dockerfile
│   ├── app.py
│   ├── cache.py
│   ├── db.py
│   ├── controller.py
│   ├── subscriber.py
│   └── strategies/
│       ├── __init__.py
│       ├── eager.py
│       ├── batched.py
│       └── ttl.py
├── node_b/
│   ├── Dockerfile
│   ├── app.py
│   ├── cache.py
│   ├── db.py
│   ├── subscriber.py
│   └── strategies/
│       ├── __init__.py
│       ├── eager.py
│       ├── batched.py
│       └── ttl.py
├── node_c/
│   ├── Dockerfile
│   ├── app.py
│   ├── cache.py
│   ├── db.py
│   ├── subscriber.py
│   └── strategies/
│       ├── __init__.py
│       ├── eager.py
│       ├── batched.py
│       └── ttl.py
├── load_gen/
│   ├── load_generator.py
│   └── metrics.py
├── plots/
│   └── generate_plots.py
└── results/                      # CSV output directory
    └── .gitkeep
```

**Validation:**
```bash
find adaptive-cache-invalidation -type f | sort
```
Confirm all files listed above exist (they can be empty stubs for now).

**IMPORTANT NOTE ON CODE REUSE:**
- `node_b/` and `node_c/` are structurally identical. They differ ONLY in:
  - Port number (environment variable, not hardcoded)
  - Node name (environment variable)
  - Node A additionally runs the Adaptive Controller
- Consider: You can use ONE shared codebase mounted into all 3 containers, with ENV vars controlling behavior. This is the RECOMMENDED approach. If you do this, the structure simplifies to:

```
adaptive-cache-invalidation/
├── docker-compose.yml
├── requirements.txt
├── shared_db/
│   └── .gitkeep
├── app/                          # Single codebase for all nodes
│   ├── Dockerfile
│   ├── app.py
│   ├── cache.py
│   ├── db.py
│   ├── controller.py
│   ├── subscriber.py
│   └── strategies/
│       ├── __init__.py
│       ├── eager.py
│       ├── batched.py
│       └── ttl.py
├── load_gen/
│   ├── load_generator.py
│   └── metrics.py
├── plots/
│   └── generate_plots.py
└── results/
    └── .gitkeep
```

**Decision Gate:** Choose one structure. Document the choice. Proceed.

---

### ✅ CHECKPOINT 0 — Environment Ready

| Check                           | Expected         |
|---------------------------------|------------------|
| Docker running                  | Yes              |
| Docker Compose available        | Yes              |
| Python 3.11+                    | Yes              |
| pip packages installed          | Yes              |
| Directory structure created     | Yes              |

**Gate:** ALL checks pass → proceed to Phase 1.

---

## 3. PHASE 1 — BASELINE INFRASTRUCTURE

> **Goal:** Get 3 nodes running with TTL-only caching, a functioning load generator, and metrics logging. At the end of Phase 1, you can run experiments with static TTL and record SRR/latency/throughput.

---

### Step 3.1 — Write `requirements.txt`

**Action:** Create `requirements.txt` with exact contents:

```
flask==3.0.*
redis==5.0.*
gunicorn==21.*
```

**Validation:** File exists and contains flask, redis, gunicorn.

---

### Step 3.2 — Write `Dockerfile`

**Action:** Create `app/Dockerfile` (or `node_a/Dockerfile` etc.):

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "app.py"]
```

**Validation:** File exists, uses python:3.11-slim, copies requirements first (layer caching).

---

### Step 3.3 — Write `db.py` (SQLite Helper)

**Purpose:** Provides thread-safe read/write to the shared SQLite database.

**Functional Requirements:**
1. `init_db()` — Creates the `cache_data` table if it doesn't exist.
   - Schema: `CREATE TABLE IF NOT EXISTS cache_data (key TEXT PRIMARY KEY, value TEXT, updated_at REAL)`
   - `updated_at` stores `time.time()` — needed for SRR measurement.
2. `db_read(key)` — Returns the current value for a key, or `None`.
   - SQL: `SELECT value FROM cache_data WHERE key = ?`
3. `db_write(key, value)` — Inserts or replaces a key-value pair.
   - SQL: `INSERT OR REPLACE INTO cache_data (key, value, updated_at) VALUES (?, ?, ?)`
   - Uses `time.time()` for `updated_at`.
4. All connections MUST use `timeout=10` to handle SQLite write locks.
5. Database path: read from `os.environ.get('DB_PATH', '/data/cache.db')`.
6. Each function opens and closes its own connection (no shared connection — SQLite is not thread-safe with shared connections).

**Validation Test:**
```python
# Run locally or inside container
from db import init_db, db_read, db_write
init_db()
db_write("test_key", "test_value")
assert db_read("test_key") == "test_value", "FAIL: db_read did not return written value"
db_write("test_key", "updated_value")
assert db_read("test_key") == "updated_value", "FAIL: db_write did not update"
assert db_read("nonexistent") is None, "FAIL: nonexistent key should return None"
print("db.py: ALL TESTS PASSED")
```

---

### Step 3.4 — Write `cache.py` (Redis Wrapper)

**Purpose:** Thin wrapper around Redis operations for each node's local cache.

**Functional Requirements:**
1. Initialize Redis connection using environment variables:
   - `REDIS_HOST` (default: `localhost`)
   - `REDIS_PORT` (default: `6379`)
2. `cache_get(key)` — Returns the cached value (string) or `None`.
   - Use `redis_client.get(key)` → decode to string if not None.
3. `cache_set(key, value, ttl=10)` — Sets a key with TTL in seconds.
   - Use `redis_client.setex(key, ttl, value)`.
4. `cache_delete(key)` — Deletes a key from cache.
   - Use `redis_client.delete(key)`.
5. `cache_flush()` — Flushes all keys (used for experiment resets).
   - Use `redis_client.flushdb()`.
6. Handle `redis.ConnectionError` gracefully — log the error and return None/pass (system degrades to DB-only reads on Redis failure).

**Validation Test:**
```python
# Requires a running Redis instance
from cache import cache_set, cache_get, cache_delete, cache_flush
cache_flush()
cache_set("k1", "v1", ttl=10)
assert cache_get("k1") == "v1", "FAIL: cache_get did not return set value"
cache_delete("k1")
assert cache_get("k1") is None, "FAIL: cache_delete did not remove key"
print("cache.py: ALL TESTS PASSED")
```

---

### Step 3.5 — Write `strategies/ttl.py` (TTL Strategy)

**Purpose:** The simplest strategy — on write, do nothing extra. Let Redis auto-expire entries after TTL seconds.

**Functional Requirements:**
1. `on_write(key, value)` — Does nothing. Returns immediately.
   - The cache already has a TTL set during `cache_set()`. When TTL expires, the next read will miss the cache and re-fetch from SQLite.
2. That's it. This is the baseline "do nothing" strategy.

**Validation:**
- File exists.
- `on_write("k", "v")` returns without error.
- No Pub/Sub messages are published (verify by subscribing to `cache_invalidation` channel and confirming silence).

---

### Step 3.6 — Write `app.py` (Flask Application — Phase 1 Version)

**Purpose:** The main application server. Runs on each node.

**Functional Requirements:**

**Endpoint: `GET /read?key=<key>`**
1. Check Redis cache first via `cache_get(key)`.
2. If cache HIT: return `{"key": key, "value": value, "source": "cache"}`.
3. If cache MISS: read from SQLite via `db_read(key)`.
   - If DB has value: `cache_set(key, value, ttl=CACHE_TTL)`, return `{"key": key, "value": value, "source": "db"}`.
   - If DB has no value: return `{"key": key, "value": null, "source": "db"}`.
4. Return HTTP 200 with JSON response.
5. Include a `timestamp` field in the response: `time.time()`.

**Endpoint: `POST /write`**
1. Accept JSON body: `{"key": "...", "value": "..."}`.
2. Write to SQLite via `db_write(key, value)`.
3. Apply the current active strategy's `on_write(key, value)`.
4. Increment the node's write counter (used by Adaptive Controller later).
5. Return `{"status": "ok", "key": key, "strategy": current_strategy_name}`.
6. Return HTTP 200.

**Endpoint: `GET /health`**
1. Return `{"status": "healthy", "node": NODE_NAME, "strategy": current_strategy_name}`.
2. Return HTTP 200.

**Endpoint: `POST /reset`**
1. Flush the Redis cache via `cache_flush()`.
2. Return `{"status": "reset"}`.
3. Used between experiment runs to clear state.

**Environment Variables Used:**
| Variable          | Default        | Description                         |
|-------------------|----------------|-------------------------------------|
| `NODE_NAME`       | `node_a`       | Identifier for this node            |
| `NODE_PORT`       | `5001`         | Flask listen port                   |
| `REDIS_HOST`      | `redis_a`      | Hostname of this node's Redis       |
| `REDIS_PORT`      | `6379`         | Port of this node's Redis           |
| `DB_PATH`         | `/data/cache.db` | Path to shared SQLite file        |
| `CACHE_TTL`       | `10`           | Default TTL in seconds              |
| `IS_WRITER`       | `false`        | Only Node A is `true`               |
| `RUN_CONTROLLER`  | `false`        | Only Node A is `true` (Phase 2)     |

**Startup Sequence:**
1. Call `init_db()` to ensure table exists.
2. Set initial strategy to TTL.
3. Start Flask server on `0.0.0.0:NODE_PORT` with `threaded=True`.

**Validation Test (manual, after Docker is running):**
```bash
# From host machine
# Write a value
curl -X POST http://localhost:5001/write \
  -H "Content-Type: application/json" \
  -d '{"key": "item_1", "value": "hello"}'
# Expected: {"status": "ok", "key": "item_1", "strategy": "ttl"}

# Read from the same node (should be cache miss first, then DB)
curl "http://localhost:5001/read?key=item_1"
# Expected: {"key": "item_1", "value": "hello", "source": "db", ...}

# Read again (should be cache hit now)
curl "http://localhost:5001/read?key=item_1"
# Expected: {"key": "item_1", "value": "hello", "source": "cache", ...}

# Read from a different node (should be cache miss — its own Redis is empty)
curl "http://localhost:5002/read?key=item_1"
# Expected: {"key": "item_1", "value": "hello", "source": "db", ...}

# Health check
curl http://localhost:5001/health
# Expected: {"status": "healthy", "node": "node_a", "strategy": "ttl"}
```

---

### Step 3.7 — Write `docker-compose.yml`

**Purpose:** Defines all containers, networking, and volumes.

**Functional Requirements:**

```yaml
version: "3.8"

networks:
  cache_net:
    driver: bridge

volumes:
  shared_db:

services:
  redis_a:
    image: redis:7-alpine
    networks:
      - cache_net
    ports:
      - "6379:6379"

  redis_b:
    image: redis:7-alpine
    networks:
      - cache_net
    ports:
      - "6380:6379"

  redis_c:
    image: redis:7-alpine
    networks:
      - cache_net
    ports:
      - "6381:6379"

  node_a:
    build: ./app
    networks:
      - cache_net
    ports:
      - "5001:5001"
    environment:
      - NODE_NAME=node_a
      - NODE_PORT=5001
      - REDIS_HOST=redis_a
      - REDIS_PORT=6379
      - DB_PATH=/data/cache.db
      - CACHE_TTL=10
      - IS_WRITER=true
      - RUN_CONTROLLER=false
      - PUBSUB_REDIS_HOST=redis_a
      - PUBSUB_REDIS_PORT=6379
      - HIGH_THRESHOLD=50
      - LOW_THRESHOLD=10
    volumes:
      - shared_db:/data
    depends_on:
      - redis_a

  node_b:
    build: ./app
    networks:
      - cache_net
    ports:
      - "5002:5002"
    environment:
      - NODE_NAME=node_b
      - NODE_PORT=5002
      - REDIS_HOST=redis_b
      - REDIS_PORT=6379
      - DB_PATH=/data/cache.db
      - CACHE_TTL=10
      - IS_WRITER=false
      - RUN_CONTROLLER=false
      - PUBSUB_REDIS_HOST=redis_a
      - PUBSUB_REDIS_PORT=6379
    volumes:
      - shared_db:/data
    depends_on:
      - redis_b

  node_c:
    build: ./app
    networks:
      - cache_net
    ports:
      - "5003:5003"
    environment:
      - NODE_NAME=node_c
      - NODE_PORT=5003
      - REDIS_HOST=redis_c
      - REDIS_PORT=6379
      - DB_PATH=/data/cache.db
      - CACHE_TTL=10
      - IS_WRITER=false
      - RUN_CONTROLLER=false
      - PUBSUB_REDIS_HOST=redis_a
      - PUBSUB_REDIS_PORT=6379
    volumes:
      - shared_db:/data
    depends_on:
      - redis_c
```

**CRITICAL DESIGN DECISIONS:**
- All nodes use `redis_a` for Pub/Sub (`PUBSUB_REDIS_HOST`). Each node uses its own Redis for local caching (`REDIS_HOST`).
- This separation is essential: Pub/Sub must be on a SHARED Redis instance so all nodes can communicate. Local cache is per-node.
- SQLite is on a shared Docker volume (`shared_db:/data`).

**Validation:**
```bash
docker compose config
# Should print the resolved YAML without errors

docker compose build
# Should build successfully — no pip install errors

docker compose up -d
# All 6 containers should start

docker compose ps
# All containers show status "Up" or "running"
```

---

### Step 3.8 — Smoke Test the Running System

**Action:** With all containers up, run these tests IN ORDER:

**Test 3.8.1 — Health checks:**
```bash
curl http://localhost:5001/health
curl http://localhost:5002/health
curl http://localhost:5003/health
```
**Pass:** All return `{"status": "healthy", ...}`.

**Test 3.8.2 — Write then read on same node:**
```bash
curl -X POST http://localhost:5001/write \
  -H "Content-Type: application/json" \
  -d '{"key": "smoke_1", "value": "abc"}'

curl "http://localhost:5001/read?key=smoke_1"
```
**Pass:** Write returns `"status": "ok"`. Read returns `"value": "abc"`.

**Test 3.8.3 — Cross-node read (DB fallback):**
```bash
curl "http://localhost:5002/read?key=smoke_1"
```
**Pass:** Returns `"value": "abc"`, `"source": "db"` (first time is a cache miss on Node B).

**Test 3.8.4 — Cross-node cache hit:**
```bash
curl "http://localhost:5002/read?key=smoke_1"
```
**Pass:** Returns `"value": "abc"`, `"source": "cache"` (now cached on Node B).

**Test 3.8.5 — TTL expiry (stale read scenario):**
```bash
# Write a new value to same key on Node A
curl -X POST http://localhost:5001/write \
  -H "Content-Type: application/json" \
  -d '{"key": "smoke_1", "value": "UPDATED"}'

# Immediately read from Node B (should still return OLD cached value)
curl "http://localhost:5002/read?key=smoke_1"
```
**Pass:** Node B returns `"value": "abc"` (stale!) because TTL hasn't expired yet. This is the expected behavior under TTL-only strategy.

**Test 3.8.6 — Wait for TTL then re-read:**
```bash
sleep 11
curl "http://localhost:5002/read?key=smoke_1"
```
**Pass:** Returns `"value": "UPDATED"`, `"source": "db"` (cache expired, re-fetched from DB).

---

### ✅ CHECKPOINT 1 — Baseline Nodes Running

| Check                                            | Expected          |
|--------------------------------------------------|--------------------|
| All 6 containers up (`docker compose ps`)        | 6 running          |
| Health endpoints responding on 5001, 5002, 5003  | All return healthy |
| Write on Node A readable from Node B/C via DB    | Yes                |
| Stale read observable under TTL-only             | Yes                |
| TTL expiry triggers fresh DB read                | Yes                |

**Gate:** ALL checks pass → proceed to Step 3.9.

---

### Step 3.9 — Write `load_gen/load_generator.py`

**Purpose:** Sends concurrent read/write HTTP requests to the cluster at configurable rates. Records every response for metrics analysis.

**Functional Requirements:**

**Command-line Arguments:**
| Argument           | Type  | Default | Description                                     |
|--------------------|-------|---------|-------------------------------------------------|
| `--write-rate`     | int   | 10      | Target writes per second                        |
| `--read-rate`      | int   | 100     | Target reads per second                         |
| `--duration`       | int   | 60      | Test duration in seconds                        |
| `--write-node`     | str   | `http://localhost:5001` | Node to send writes to           |
| `--read-nodes`     | str   | `http://localhost:5001,http://localhost:5002,http://localhost:5003` | Comma-separated read nodes (round-robin) |
| `--output`         | str   | `results/experiment.csv` | Output CSV file path            |
| `--key-space`      | int   | 100     | Number of unique keys (item_0 to item_99)       |

**Write Thread Logic:**
1. Target: `write_rate` writes per second.
2. Distribute writes evenly within each second using `time.sleep(1.0 / write_rate)`.
3. For each write:
   - Pick a random key from `item_0` to `item_{key_space - 1}`.
   - Generate a value: `f"{key}_v{counter}"` (monotonically increasing counter per key or globally).
   - POST to `write_node/write` with JSON `{"key": key, "value": value}`.
   - Record: `timestamp, operation=write, key, value_sent, response_time_ms, status_code, node`.

**Read Thread Logic:**
1. Target: `read_rate` reads per second.
2. Distribute reads evenly within each second.
3. For each read:
   - Pick a random key from the same key space.
   - GET from a read node (round-robin across `read_nodes`).
   - **IMMEDIATELY** after receiving the read response, make a **verification read** directly from SQLite (via a GET to the write node's `/read` endpoint with a special `?source=db` parameter, OR query the DB directly if running locally).
   - Record: `timestamp, operation=read, key, value_received, db_value_at_read_time, response_time_ms, status_code, node, is_stale`.
   - `is_stale = 1` if `value_received != db_value_at_read_time`, else `0`.

**SRR Verification Design (CRITICAL):**
The SRR measurement requires knowing the DB value at the exact moment of the read. Two approaches:

**Approach A (Recommended):** Add a `/db_read?key=<key>` endpoint to Node A that always reads directly from SQLite (bypasses cache). After each cached read from Node B/C, immediately call `/db_read?key=<key>` on Node A to get the ground truth.

**Approach B:** Have the load generator connect directly to the SQLite file (requires the `shared_db` volume to be mounted to the host or the load generator to run inside Docker).

**Choose Approach A** — it's simpler and doesn't require direct DB access from the host.

**Add to `app.py`:**
```python
@app.route('/db_read')
def direct_db_read():
    key = request.args.get('key')
    value = db_read(key)
    return jsonify({"key": key, "value": value, "source": "db_direct"})
```

**CSV Output Schema:**
```
timestamp,operation,key,value,db_value,response_time_ms,status_code,node,is_stale,strategy
```

**Validation Test:**
```bash
# Reset all caches first
curl -X POST http://localhost:5001/reset
curl -X POST http://localhost:5002/reset
curl -X POST http://localhost:5003/reset

# Run load generator for 10 seconds at low rate
python3 load_gen/load_generator.py \
  --write-rate 5 \
  --read-rate 20 \
  --duration 10 \
  --output results/test_run.csv

# Check output
head -5 results/test_run.csv
wc -l results/test_run.csv
```
**Pass:**
- CSV file created with header row.
- Approximately `(5 + 20) * 10 = 250` rows (±20% due to timing variance).
- `is_stale` column contains both `0` and `1` values (some stale reads expected under TTL).

---

### Step 3.10 — Write `load_gen/metrics.py`

**Purpose:** Reads the CSV output from load_generator.py and computes summary metrics.

**Functional Requirements:**

**Input:** Path to a CSV file (from load_generator.py).

**Output Metrics (print to stdout):**

```
=== Experiment Summary ===
Duration: 60.0 seconds
Total Requests: 6500
  Reads:  6000
  Writes: 500

--- Stale Read Ratio (SRR) ---
Total Reads:      6000
Stale Reads:      342
SRR:              5.70%

--- Latency (ms) ---
Read  P50:    3.2 ms
Read  P95:    12.4 ms
Read  P99:    45.1 ms
Write P50:    5.1 ms
Write P95:    18.3 ms
Write P99:    52.7 ms

--- Throughput ---
Read  RPS:    100.0 req/s
Write RPS:    8.3 req/s
Total RPS:    108.3 req/s

--- Errors ---
HTTP Errors:  0 (0.00%)
```

**Also write a summary row to a separate `results/summary.csv`:**
```
experiment_name,strategy,write_rate,read_rate,duration,total_reads,stale_reads,srr_pct,read_p50_ms,read_p95_ms,write_p50_ms,write_p95_ms,total_rps,errors
```

**Validation Test:**
```bash
python3 load_gen/metrics.py results/test_run.csv
```
**Pass:** Prints a table with all metrics. SRR is a number between 0-100. No exceptions.

---

### ✅ CHECKPOINT 2 — Load Generator & Metrics Working

| Check                                            | Expected               |
|--------------------------------------------------|------------------------|
| Load generator runs for specified duration        | Yes                    |
| CSV output has correct schema                     | Yes                    |
| is_stale correctly computed (0 or 1)              | Yes                    |
| metrics.py reads CSV and prints summary           | Yes                    |
| Under TTL-only at write_rate=5, SRR is low (<10%) | Approximately yes      |
| Under TTL-only at write_rate=60, SRR is high (>15%)| Approximately yes     |

**Gate:** ALL checks pass → proceed to Phase 1 Experiments (Step 3.11) then Phase 2.

---

### Step 3.11 — Run Phase 1 Experiments (TTL-Only Baseline)

**Purpose:** Collect baseline data under static TTL strategy at three write rates.

**Action:** Run three experiments, resetting between each:

**Experiment 1A: Low write rate (5 w/s)**
```bash
# Reset
curl -X POST http://localhost:5001/reset
curl -X POST http://localhost:5002/reset
curl -X POST http://localhost:5003/reset

python3 load_gen/load_generator.py \
  --write-rate 5 --read-rate 100 --duration 60 \
  --output results/phase1_ttl_wr5.csv

python3 load_gen/metrics.py results/phase1_ttl_wr5.csv
```

**Experiment 1B: Medium write rate (25 w/s)**
```bash
curl -X POST http://localhost:5001/reset
curl -X POST http://localhost:5002/reset
curl -X POST http://localhost:5003/reset

python3 load_gen/load_generator.py \
  --write-rate 25 --read-rate 100 --duration 60 \
  --output results/phase1_ttl_wr25.csv

python3 load_gen/metrics.py results/phase1_ttl_wr25.csv
```

**Experiment 1C: High write rate (60 w/s)**
```bash
curl -X POST http://localhost:5001/reset
curl -X POST http://localhost:5002/reset
curl -X POST http://localhost:5003/reset

python3 load_gen/load_generator.py \
  --write-rate 60 --read-rate 100 --duration 60 \
  --output results/phase1_ttl_wr60.csv

python3 load_gen/metrics.py results/phase1_ttl_wr60.csv
```

**Validation:**
- Three CSV files exist in `results/`.
- SRR increases as write rate increases (5 w/s should have lowest SRR, 60 w/s should have highest).
- Record exact SRR values — these are the baseline to compare against Phase 2.

**Expected Results (approximate):**
| Write Rate | Expected SRR (TTL-only) |
|------------|-------------------------|
| 5 w/s      | 5-15%                   |
| 25 w/s     | 15-30%                  |
| 60 w/s     | 25-45%                  |

---

### ✅ CHECKPOINT 3 — Phase 1 Complete

| Check                                            | Expected               |
|--------------------------------------------------|------------------------|
| Three baseline experiments completed              | Yes                    |
| SRR increases with write rate                     | Yes                    |
| All CSVs have correct data                        | Yes                    |
| Latency P95 ≤ 200ms (lenient for baseline)        | Yes                    |
| No container crashes during experiments            | Yes                    |

**Gate:** ALL checks pass → proceed to Phase 2.

---

## 4. PHASE 2 — ADAPTIVE SYSTEM

> **Goal:** Add Eager and Batched strategies, the Pub/Sub subscriber, and the Adaptive Controller. At the end of Phase 2, the system dynamically switches strategies based on write rate.

---

### Step 4.1 — Write `subscriber.py` (Pub/Sub Listener)

**Purpose:** Background thread on each node that subscribes to Redis Pub/Sub channels and acts on messages.

**Functional Requirements:**

1. Connect to the **shared** Pub/Sub Redis (`PUBSUB_REDIS_HOST:PUBSUB_REDIS_PORT`) — NOT the node's local cache Redis.
2. Subscribe to two channels: `cache_invalidation` and `strategy_update`.
3. Run in a daemon thread (so it dies when the main process exits).
4. On `cache_invalidation` message:
   - Parse JSON: `{"action": "invalidate", "keys": ["key1", "key2", ...]}` (batched format — Eager sends a list of 1, Batched sends a list of N).
   - For each key in the list: call `cache_delete(key)` on the LOCAL Redis cache.
   - Log: `f"[{NODE_NAME}] Invalidated keys: {keys}"`.
5. On `strategy_update` message:
   - Parse JSON: `{"strategy": "eager"|"batched"|"ttl"}`.
   - Update the global `current_strategy` variable in `app.py`.
   - Log: `f"[{NODE_NAME}] Strategy switched to: {strategy}"`.
6. Handle `redis.ConnectionError` — retry connection every 2 seconds with logging.

**Validation Test:**
```bash
# Terminal 1: Start subscriber on Node B
docker compose exec node_b python -c "
from subscriber import start_subscriber
import time
start_subscriber()
time.sleep(30)
"

# Terminal 2: Publish a test invalidation message
docker compose exec node_a python -c "
import redis, json
r = redis.Redis(host='redis_a', port=6379)
r.publish('cache_invalidation', json.dumps({'action': 'invalidate', 'keys': ['test_key']}))
print('Published')
"
```
**Pass:** Terminal 1 logs `Invalidated keys: ['test_key']`.

---

### Step 4.2 — Write `strategies/eager.py`

**Purpose:** On every write, immediately publish an invalidation message for that key.

**Functional Requirements:**
1. `on_write(key, value)`:
   - Connect to shared Pub/Sub Redis.
   - Publish to `cache_invalidation` channel: `{"action": "invalidate", "keys": [key]}`.
   - Log: `f"[EAGER] Published invalidation for key: {key}"`.
2. Message is published AFTER the DB write succeeds (never publish if DB write failed).

**Validation Test:**
```bash
# 1. Write a value and cache it on Node B
curl -X POST http://localhost:5001/write \
  -H "Content-Type: application/json" \
  -d '{"key": "eager_test", "value": "v1"}'
curl "http://localhost:5002/read?key=eager_test"  # Caches on Node B

# 2. Switch Node A to Eager strategy (manual override for testing)
# Add a /set_strategy endpoint for testing:
curl -X POST "http://localhost:5001/set_strategy?strategy=eager"

# 3. Write a new value
curl -X POST http://localhost:5001/write \
  -H "Content-Type: application/json" \
  -d '{"key": "eager_test", "value": "v2"}'

# 4. Read from Node B — should NOT be stale
curl "http://localhost:5002/read?key=eager_test"
```
**Pass:** Node B returns `"value": "v2"` (not stale `"v1"`), with `"source": "db"` (cache was invalidated, so it re-fetched from DB).

---

### Step 4.3 — Write `strategies/batched.py`

**Purpose:** Collect written keys in a buffer. A background timer flushes the buffer every N seconds via Pub/Sub.

**Functional Requirements:**
1. Module-level state:
   - `_buffer = []` — list of keys written since last flush.
   - `_lock = threading.Lock()` — protects `_buffer`.
   - `BATCH_INTERVAL` — read from `os.environ.get('BATCH_INTERVAL', '2')` seconds.
2. `on_write(key, value)`:
   - Acquire `_lock`.
   - Append `key` to `_buffer`.
   - Release `_lock`.
   - That's it — no Pub/Sub publish here.
3. `start_batch_flusher()`:
   - Start a daemon thread that runs `_flush()` every `BATCH_INTERVAL` seconds.
4. `_flush()`:
   - Acquire `_lock`.
   - If `_buffer` is empty: release and return.
   - Copy buffer contents, clear `_buffer`.
   - Release `_lock`.
   - Publish to `cache_invalidation`: `{"action": "invalidate", "keys": [list of all buffered keys]}`.
   - Log: `f"[BATCHED] Flushed {len(keys)} keys"`.

**Validation Test:**
```bash
# 1. Switch to Batched strategy
curl -X POST "http://localhost:5001/set_strategy?strategy=batched"

# 2. Cache a key on Node B
curl "http://localhost:5002/read?key=batch_test"

# 3. Write 5 values rapidly
for i in {1..5}; do
  curl -s -X POST http://localhost:5001/write \
    -H "Content-Type: application/json" \
    -d "{\"key\": \"batch_test\", \"value\": \"v$i\"}" &
done
wait

# 4. Immediately read from Node B — might still be stale (batch hasn't flushed)
curl "http://localhost:5002/read?key=batch_test"

# 5. Wait for batch flush (3 seconds to be safe)
sleep 3

# 6. Read from Node B again — should now be fresh
curl "http://localhost:5002/read?key=batch_test"
```
**Pass:**
- Step 4: May return stale value (this is correct — batch hasn't flushed yet).
- Step 6: Returns `"value": "v5"` (latest value), `"source": "db"`.

---

### Step 4.4 — Add `/set_strategy` Endpoint to `app.py` (Testing Utility)

**Purpose:** Allows manual strategy switching for testing. The Adaptive Controller will do this automatically later.

**Endpoint: `POST /set_strategy?strategy=<eager|batched|ttl>`**
1. Validate strategy name is one of: `eager`, `batched`, `ttl`.
2. Update the global `current_strategy` variable.
3. If switching TO `batched`: call `start_batch_flusher()` (if not already running).
4. Return `{"status": "ok", "strategy": strategy}`.

**Validation:** Already used in Steps 4.2 and 4.3 tests above.

---

### Step 4.5 — Integrate Subscriber into `app.py` Startup

**Action:** Modify `app.py` startup sequence to:
1. Call `init_db()`.
2. Start the Pub/Sub subscriber thread via `start_subscriber()`.
3. Set initial strategy to TTL.
4. Start Flask.

**Validation:**
```bash
docker compose down
docker compose up -d --build
sleep 5

# Verify subscriber is running (check logs)
docker compose logs node_b | grep -i "subscrib"
```
**Pass:** Logs show subscriber started and listening on channels.

---

### Step 4.6 — Write `controller.py` (Adaptive Controller)

**Purpose:** Background thread on Node A that monitors write rate and switches strategies.

**Functional Requirements:**

1. Runs ONLY on Node A (gated by `RUN_CONTROLLER=true` env var).
2. Runs as a daemon thread started from `app.py`.
3. **Write rate tracking:**
   - Maintain a rolling window of write timestamps (last 5 seconds).
   - Every `CONTROLLER_INTERVAL` seconds (default: 3), calculate: `write_rate = len(writes_in_last_5s) / 5.0`.
4. **Decision logic:**
   ```python
   if write_rate > HIGH_THRESHOLD:     # default 50
       new_strategy = "eager"
   elif write_rate < LOW_THRESHOLD:    # default 10
       new_strategy = "ttl"
   else:
       new_strategy = "batched"
   ```
5. **If strategy changed:**
   - Update local `current_strategy`.
   - Publish to `strategy_update` channel: `{"strategy": new_strategy}`.
   - Log: `f"[CONTROLLER] Write rate: {write_rate:.1f} w/s → Strategy: {new_strategy}"`.
6. **If strategy unchanged:** Log at debug level only, no publish.

**Environment Variables:**
| Variable             | Default | Description                        |
|----------------------|---------|------------------------------------|
| `RUN_CONTROLLER`     | `false` | Set to `true` on Node A only       |
| `CONTROLLER_INTERVAL`| `3`     | Seconds between controller checks  |
| `HIGH_THRESHOLD`     | `50`    | Write rate above this → EAGER      |
| `LOW_THRESHOLD`      | `10`    | Write rate below this → TTL        |
| `WRITE_WINDOW`       | `5`     | Rolling window size in seconds     |

**Write Counter Integration:**
The controller needs to know the write rate. Two approaches:
- **Approach A (Recommended):** `app.py`'s `/write` endpoint appends `time.time()` to a shared `write_timestamps` list. The controller reads this list.
- **Approach B:** Use Redis INCR with expiry to count writes.

**Choose Approach A** — it's simpler and avoids extra Redis calls.

**Validation Test:**
```bash
# 1. Enable controller on Node A
# In docker-compose.yml, set RUN_CONTROLLER=true for node_a
# Rebuild and restart
docker compose down
docker compose up -d --build
sleep 5

# 2. Send writes at different rates and watch the logs

# Low rate — should be TTL
for i in {1..10}; do
  curl -s -X POST http://localhost:5001/write \
    -H "Content-Type: application/json" \
    -d "{\"key\": \"ctrl_test\", \"value\": \"v$i\"}"
  sleep 0.5  # 2 writes/sec
done

# Check logs
docker compose logs node_a | grep CONTROLLER
# Expected: "Write rate: ~2.0 w/s → Strategy: ttl"

# High rate — should switch to EAGER
for i in {1..200}; do
  curl -s -X POST http://localhost:5001/write \
    -H "Content-Type: application/json" \
    -d "{\"key\": \"ctrl_test\", \"value\": \"v$i\"}" &
done
wait

sleep 5
docker compose logs node_a | grep CONTROLLER
# Expected: "Write rate: ~XX.X w/s → Strategy: eager" (or batched, depending on rate achieved)
```

**Pass:**
- Controller logs show write rate calculation.
- Strategy changes based on thresholds.
- Other nodes log receiving the strategy update.

---

### Step 4.7 — Integration Test: Full Adaptive System

**Purpose:** Verify the entire system works end-to-end with automatic strategy switching.

**Test Procedure:**

```bash
# 1. Clean start
docker compose down -v
docker compose up -d --build
sleep 10

# 2. Verify all nodes healthy and on TTL
curl http://localhost:5001/health  # strategy: ttl
curl http://localhost:5002/health  # strategy: ttl
curl http://localhost:5003/health  # strategy: ttl

# 3. Send low write rate — should stay TTL
python3 -c "
import requests, time
for i in range(30):
    requests.post('http://localhost:5001/write', json={'key': f'k{i%10}', 'value': f'v{i}'})
    time.sleep(0.5)  # 2 w/s
"

curl http://localhost:5001/health  # strategy: ttl ✓

# 4. Send high write rate — should switch to EAGER
python3 -c "
import requests, time, threading
def blast():
    for i in range(500):
        requests.post('http://localhost:5001/write', json={'key': f'k{i%10}', 'value': f'v{i}'})
        time.sleep(0.01)  # ~100 w/s
blast()
"

sleep 5
curl http://localhost:5001/health  # strategy: eager ✓

# 5. Stop writing — should decay back to TTL
sleep 20
curl http://localhost:5001/health  # strategy: ttl ✓
```

**Pass:** Strategy transitions: `ttl` → `eager` (or `batched`) → `ttl` based on write rate.

---

### ✅ CHECKPOINT 4 — Adaptive System Complete

| Check                                                  | Expected       |
|--------------------------------------------------------|----------------|
| Eager strategy invalidates caches immediately          | Yes            |
| Batched strategy flushes every 2-3 seconds             | Yes            |
| Subscriber thread running on all nodes                 | Yes            |
| Controller detects write rate changes                  | Yes            |
| Strategy auto-switches and propagates to all nodes     | Yes            |
| Strategy switches visible in logs                      | Yes            |
| No stale reads under Eager at any write rate           | ~0% SRR        |
| Stale reads under Batched limited to batch window      | 2-3s staleness |

**Gate:** ALL checks pass → proceed to Phase 3.

---

## 5. PHASE 3 — EXPERIMENTS & ANALYSIS

> **Goal:** Run all experiments with the adaptive system, compare to Phase 1 baselines, run fault tests, generate plots, and write the analysis.

---

### Step 5.1 — Run Phase 2 Experiments (Adaptive System)

**Experiment 2A: Low write rate (5 w/s) — Adaptive**
```bash
curl -X POST http://localhost:5001/reset
curl -X POST http://localhost:5002/reset
curl -X POST http://localhost:5003/reset

python3 load_gen/load_generator.py \
  --write-rate 5 --read-rate 100 --duration 60 \
  --output results/phase2_adaptive_wr5.csv

python3 load_gen/metrics.py results/phase2_adaptive_wr5.csv
```

**Experiment 2B: Medium write rate (25 w/s) — Adaptive**
```bash
# (same reset commands)
python3 load_gen/load_generator.py \
  --write-rate 25 --read-rate 100 --duration 60 \
  --output results/phase2_adaptive_wr25.csv
```

**Experiment 2C: High write rate (60 w/s) — Adaptive**
```bash
# (same reset commands)
python3 load_gen/load_generator.py \
  --write-rate 60 --read-rate 100 --duration 60 \
  --output results/phase2_adaptive_wr60.csv
```

**Validation:**
- SRR under adaptive should be LOWER than corresponding Phase 1 TTL-only experiment.
- Target: SRR < 5% under adaptive system.

---

### Step 5.2 — Mixed Workload Test

**Purpose:** Verify the controller switches strategy when write rate changes dynamically.

**Action:** Write a custom load generator script or modify the existing one:

```
Timeline:
  0-30s:   write_rate = 5 w/s   (expect TTL)
  30-60s:  write_rate = 60 w/s  (expect EAGER)
  60-90s:  write_rate = 25 w/s  (expect BATCHED)
  90-120s: write_rate = 5 w/s   (expect TTL)
```

```bash
python3 load_gen/load_generator.py \
  --mixed-workload \
  --duration 120 \
  --output results/phase3_mixed_workload.csv
```

**Validation:**
- CSV data shows strategy column changing over time.
- Strategy switch latency ≤ 5 seconds from the workload change.
- Log output from controller confirms strategy transitions at expected times.

---

### Step 5.3 — Node-Offline Fault Test

**Purpose:** Test the Redis Pub/Sub fire-and-forget limitation. Measure SRR spike when a node misses invalidation messages.

**Procedure:**
```bash
# 1. Start all nodes, begin writing at 60 w/s
python3 load_gen/load_generator.py \
  --write-rate 60 --read-rate 100 --duration 120 \
  --output results/phase3_fault_test.csv &
LOAD_PID=$!

# 2. After 30 seconds, stop Node B
sleep 30
docker compose stop node_b
echo "Node B stopped at $(date)"

# 3. Wait 30 seconds (Node B misses all invalidation messages)
sleep 30

# 4. Restart Node B
docker compose start node_b
echo "Node B restarted at $(date)"

# 5. Let the experiment continue for another 60 seconds
wait $LOAD_PID
```

**Validation:**
- Analyze the CSV to compute SRR specifically for Node B reads.
- SRR for Node B should spike after restart (serving stale cached data).
- SRR should recover over time as TTL expires stale entries.
- Document the spike magnitude and recovery time.

---

### Step 5.4 — Write `plots/generate_plots.py`

**Purpose:** Generate matplotlib plots from experiment CSVs.

**Required Plots:**

**Plot 1: SRR vs Write Rate — TTL vs Adaptive**
- X-axis: Write rate (5, 25, 60 w/s)
- Y-axis: SRR (%)
- Two lines: TTL-only (Phase 1), Adaptive (Phase 2)
- Bar chart or line chart
- Save as: `plots/srr_comparison.png`

**Plot 2: Latency Comparison (P95)**
- X-axis: Write rate
- Y-axis: P95 latency (ms)
- Two grouped bars: TTL-only vs Adaptive
- Save as: `plots/latency_comparison.png`

**Plot 3: Throughput Comparison**
- X-axis: Write rate
- Y-axis: Requests per second
- Save as: `plots/throughput_comparison.png`

**Plot 4: Mixed Workload Timeline**
- X-axis: Time (seconds)
- Y-axis (left): SRR (rolling 5-second window)
- Y-axis (right) or color-coded background: Active strategy
- Save as: `plots/mixed_workload_timeline.png`

**Plot 5: Node-Offline SRR Spike**
- X-axis: Time (seconds)
- Y-axis: SRR for Node B (rolling 5-second window)
- Vertical lines marking: node stop, node restart
- Save as: `plots/fault_test_srr_spike.png`

**Plot 6: Message Volume Comparison**
- Bar chart: Eager vs Batched vs TTL message counts
- Save as: `plots/message_volume.png`

**Validation:**
```bash
python3 plots/generate_plots.py
ls plots/*.png
```
**Pass:** All 6 PNG files exist and are non-zero size.

---

### Step 5.5 — Compute Final Results Table

**Action:** Use `metrics.py` to generate a summary table:

```
| Experiment      | Strategy | Write Rate | SRR (%) | Read P95 (ms) | Write P95 (ms) | RPS   |
|-----------------|----------|------------|---------|----------------|----------------|-------|
| Phase 1 - Low   | TTL      | 5 w/s      | ?.??%   | ?.? ms         | ?.? ms         | ???   |
| Phase 1 - Med   | TTL      | 25 w/s     | ?.??%   | ?.? ms         | ?.? ms         | ???   |
| Phase 1 - High  | TTL      | 60 w/s     | ?.??%   | ?.? ms         | ?.? ms         | ???   |
| Phase 2 - Low   | Adaptive | 5 w/s      | ?.??%   | ?.? ms         | ?.? ms         | ???   |
| Phase 2 - Med   | Adaptive | 25 w/s     | ?.??%   | ?.? ms         | ?.? ms         | ???   |
| Phase 2 - High  | Adaptive | 60 w/s     | ?.??%   | ?.? ms         | ?.? ms         | ???   |
```

**H1 Evaluation:**
- Calculate: `improvement = (TTL_SRR - Adaptive_SRR) / TTL_SRR * 100`
- If improvement ≥ 40% at the high write rate → **H1 CONFIRMED**.
- If improvement < 40% → **H1 REJECTED** (document why; this is still a valid result).

---

### ✅ CHECKPOINT 5 — Experiments Complete

| Check                                              | Expected              |
|----------------------------------------------------|-----------------------|
| Phase 1 experiments (3 CSVs)                       | Complete              |
| Phase 2 experiments (3 CSVs)                       | Complete              |
| Mixed workload experiment                          | Complete              |
| Node-offline fault test                            | Complete              |
| All 6 plots generated                              | Yes                   |
| Summary results table computed                     | Yes                   |
| H1 evaluation documented                           | Yes (confirmed/rejected) |
| SRR < 5% under adaptive system                    | Checked               |
| Latency P95 ≤ 100ms                               | Checked               |
| Strategy switch time ≤ 5s                          | Checked               |

**Gate:** ALL checks pass → project complete.

---

## 6. CHECKPOINTS & MILESTONES

| #  | Checkpoint                         | Depends On     | Key Deliverable                           |
|----|------------------------------------|----------------|-------------------------------------------|
| 0  | Environment Ready                  | Nothing        | Docker, Python, dirs created              |
| 1  | Baseline Nodes Running             | CP 0           | 3 nodes + 3 Redis containers up           |
| 2  | Load Generator & Metrics Working   | CP 1           | CSV output + metrics script               |
| 3  | Phase 1 Complete                   | CP 2           | 3 baseline experiment CSVs                |
| 4  | Adaptive System Complete           | CP 3           | Controller + all 3 strategies working     |
| 5  | Experiments Complete               | CP 4           | All CSVs, plots, results table, H1 eval   |

**Total estimated time: 30-50 hours of focused work.**

---

## 7. APPENDIX — CONSTANTS, THRESHOLDS, FILE MANIFEST

### 7.1 All Environment Variables (Complete List)

| Variable              | Used By        | Default          | Description                          |
|-----------------------|----------------|------------------|--------------------------------------|
| `NODE_NAME`           | app.py         | `node_a`         | Node identifier                      |
| `NODE_PORT`           | app.py         | `5001`           | Flask listen port                    |
| `REDIS_HOST`          | cache.py       | `localhost`      | Local cache Redis hostname           |
| `REDIS_PORT`          | cache.py       | `6379`           | Local cache Redis port               |
| `PUBSUB_REDIS_HOST`   | subscriber.py  | `redis_a`        | Shared Pub/Sub Redis hostname        |
| `PUBSUB_REDIS_PORT`   | subscriber.py  | `6379`           | Shared Pub/Sub Redis port            |
| `DB_PATH`             | db.py          | `/data/cache.db` | SQLite database file path            |
| `CACHE_TTL`           | cache.py       | `10`             | Default cache TTL in seconds         |
| `IS_WRITER`           | app.py         | `false`          | Whether this node accepts writes     |
| `RUN_CONTROLLER`      | app.py         | `false`          | Whether to start Adaptive Controller |
| `HIGH_THRESHOLD`      | controller.py  | `50`             | Write rate → EAGER threshold         |
| `LOW_THRESHOLD`       | controller.py  | `10`             | Write rate → TTL threshold           |
| `CONTROLLER_INTERVAL` | controller.py  | `3`              | Seconds between controller checks    |
| `WRITE_WINDOW`        | controller.py  | `5`              | Rolling window size in seconds       |
| `BATCH_INTERVAL`      | batched.py     | `2`              | Seconds between batch flushes        |

### 7.2 Redis Pub/Sub Channel Definitions

| Channel               | Message Format                                          | Publisher         | Subscribers   |
|------------------------|---------------------------------------------------------|-------------------|---------------|
| `cache_invalidation`  | `{"action": "invalidate", "keys": ["k1", "k2", ...]}`  | Node A strategies | Node B, C     |
| `strategy_update`     | `{"strategy": "eager"\|"batched"\|"ttl"}`               | Controller        | All nodes     |

### 7.3 API Endpoint Reference

| Method | Path                          | Node(s)  | Purpose                              |
|--------|-------------------------------|----------|---------------------------------------|
| GET    | `/read?key=<key>`             | All      | Read from cache or DB                 |
| POST   | `/write`                      | Node A   | Write to DB + apply strategy          |
| GET    | `/health`                     | All      | Health check + current strategy       |
| POST   | `/reset`                      | All      | Flush Redis cache                     |
| GET    | `/db_read?key=<key>`          | Node A   | Direct DB read (SRR verification)     |
| POST   | `/set_strategy?strategy=<s>`  | Node A   | Manual strategy override (testing)    |

### 7.4 CSV Schema Reference

**Experiment Data CSV:**
```
timestamp,operation,key,value,db_value,response_time_ms,status_code,node,is_stale,strategy
```

**Summary CSV:**
```
experiment_name,strategy,write_rate,read_rate,duration,total_reads,stale_reads,srr_pct,read_p50_ms,read_p95_ms,write_p50_ms,write_p95_ms,total_rps,errors
```

### 7.5 Troubleshooting Guide

| Problem                                    | Diagnosis Command                          | Fix                                              |
|--------------------------------------------|--------------------------------------------|---------------------------------------------------|
| Container won't start                      | `docker compose logs <service>`            | Check for Python syntax errors in app.py          |
| Node can't reach Redis                     | `docker compose exec node_a redis-cli -h redis_a ping` | Verify `depends_on` and network in compose file |
| SQLite "database is locked"                | Check write rate; lower it                 | Increase `timeout=10` in `sqlite3.connect()`      |
| Pub/Sub messages not received              | `docker compose exec node_a redis-cli -h redis_a subscribe cache_invalidation` | Verify PUBSUB_REDIS_HOST is same across all nodes |
| SRR always 0%                              | Check if writes are actually reaching DB   | Verify `/write` endpoint stores to SQLite         |
| SRR always 100%                            | Check if reads ever hit cache              | Verify `cache_set()` is called after DB read      |
| Strategy never switches                    | `docker compose logs node_a \| grep CONTROLLER` | Check thresholds vs actual write rate       |
| Load generator connection refused           | `curl http://localhost:5001/health`         | Ensure containers are up and ports are mapped     |
| Batch flusher never fires                  | Check `start_batch_flusher()` is called    | Ensure batch thread starts when strategy switches |

### 7.6 Final Deliverables Checklist

| #  | Deliverable                              | File/Location                        | Status |
|----|------------------------------------------|--------------------------------------|--------|
| 1  | Docker Compose file                      | `docker-compose.yml`                 | [ ]    |
| 2  | Application code (all nodes)             | `app/` directory                     | [ ]    |
| 3  | TTL strategy                             | `app/strategies/ttl.py`              | [ ]    |
| 4  | Eager strategy                           | `app/strategies/eager.py`            | [ ]    |
| 5  | Batched strategy                         | `app/strategies/batched.py`          | [ ]    |
| 6  | Adaptive Controller                      | `app/controller.py`                  | [ ]    |
| 7  | Pub/Sub subscriber                       | `app/subscriber.py`                  | [ ]    |
| 8  | Load generator                           | `load_gen/load_generator.py`         | [ ]    |
| 9  | Metrics analyzer                         | `load_gen/metrics.py`                | [ ]    |
| 10 | Phase 1 experiment CSVs (3 files)        | `results/phase1_*.csv`               | [ ]    |
| 11 | Phase 2 experiment CSVs (3 files)        | `results/phase2_*.csv`               | [ ]    |
| 12 | Mixed workload CSV                       | `results/phase3_mixed_workload.csv`  | [ ]    |
| 13 | Fault test CSV                           | `results/phase3_fault_test.csv`      | [ ]    |
| 14 | All plots (6 PNG files)                  | `plots/*.png`                        | [ ]    |
| 15 | Summary results table                    | `results/summary.csv`                | [ ]    |
| 16 | Plot generation script                   | `plots/generate_plots.py`            | [ ]    |

---

**END OF ACTION PLAN**

*This document is the single source of truth for the project. Follow it step by step. Do not skip validations. If a checkpoint fails, fix the failing check before proceeding.*
