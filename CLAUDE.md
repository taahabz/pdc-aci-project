# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Adaptive Cache Invalidation (ACI) in Distributed Systems — a research project demonstrating that an adaptive cache invalidation controller reduces stale reads by 71% vs. static TTL. The system runs as 3 Flask nodes backed by 4 Redis instances and a shared SQLite database, all orchestrated via Docker Compose.

## Commands

### Start/Stop the System
```bash
docker compose up -d          # Start all 6 containers
docker compose up -d --build  # Rebuild after code changes
docker compose ps             # Check health
docker compose logs -f        # Stream logs
docker compose down           # Stop all containers
```

### Local Development (without Docker)
```bash
bash setup.sh                  # One-time setup (creates venv, installs deps)
source venv/bin/activate
pip install -r requirements.txt
```

### Load Generation & Analysis
```bash
# Run experiment (30s, 25 writes/s, 100 reads/s)
python3 load_gen/load_generator.py --write-rate 25 --read-rate 100 --duration 30

# Mixed-workload profile (120s, 5→60→25→5 writes/s per 30s phase)
python3 load_gen/load_generator.py --mixed-workload --duration 120

# Analyze results
python3 load_gen/metrics.py results/load_test_*.csv

# Generate plots
python3 plots/generate_plots.py --results-dir results --out-dir plots
```

### Testing
No automated test suite is implemented yet. `tests/` is a placeholder. The test playbook with 18 scenarios is in `.agent/TESTING.md`. Once tests exist:
```bash
pytest tests/test_db.py::TestDbBasic::test_write_and_read -v  # single test
pytest tests/ -v --cov=app                                     # all tests
```

## Architecture

### System Topology

Three Flask nodes share a single SQLite database (via Docker named volume) and communicate cache invalidations over a Redis Pub/Sub bus:

```
node_a (writer + controller)  →  redis_a (local cache + Pub/Sub bus)
node_b (reader)               →  redis_b (local cache)
node_c (reader)               →  redis_c (local cache)
```

All nodes subscribe to `redis_a` for Pub/Sub. This means `redis_a` serves dual duty as node_a's local cache AND the shared invalidation bus.

### Single Codebase, ENV-Driven Behavior

All three nodes run the same `app/app.py`. Node role is determined by environment variables:
- `IS_WRITER=true` — enables the `/write` endpoint (node_a only)
- `RUN_CONTROLLER=true` — starts the adaptive controller thread (node_a only)
- `REDIS_HOST` — points each node to its own local Redis
- `PUBSUB_REDIS_HOST` — always points to `redis_a` (the shared bus)

### Adaptive Controller (node_a only)

Runs every `CONTROLLER_INTERVAL` seconds (default: 3s), calculates `write_rate = writes in last WRITE_WINDOW seconds / WRITE_WINDOW`, then selects a strategy:

| Write Rate | Strategy | Behavior |
|---|---|---|
| > 50 req/s | **eager** | Publish invalidation immediately on every write |
| 10–50 req/s | **batched** | Buffer keys; flush every 2.5s via Pub/Sub |
| < 10 req/s | **ttl** | No invalidation; cache expires after `CACHE_TTL` seconds (default: 10s) |

Strategy changes are broadcast on the `strategy_update` Pub/Sub channel so all nodes switch simultaneously.

### Threading Model (per Flask process)

Each node runs up to 4 threads:
1. **Main thread** — Flask WSGI server (`threaded=True`)
2. **Subscriber thread** — blocking `pubsub.listen()` loop; handles `cache_invalidation` and `strategy_update` messages
3. **Controller thread** — node_a only; periodic write-rate check, strategy selection, Pub/Sub publish
4. **Batch flusher thread** — node_a only, active when strategy is `batched`; flushes `_buffer` every `BATCH_INTERVAL` seconds

`current_strategy` (a Python string) is safe to assign without a lock (GIL). `write_timestamps` and `_buffer` are lists shared across threads and are protected by `threading.Lock()`.

### Stale Read Rate (SRR) Measurement

`load_gen/load_generator.py` measures SRR by comparing `/read` responses against `/db_read` (which bypasses the cache and hits SQLite directly). A stale read is when `/read` returns a value that doesn't match the current ground truth from `/db_read`.

### Key Files

| File | Purpose |
|---|---|
| `app/app.py` | Flask app: all 6 HTTP endpoints, init sequence, thread startup |
| `app/controller.py` | Adaptive strategy selection logic |
| `app/subscriber.py` | Pub/Sub listener: applies invalidations and strategy updates |
| `app/strategies/` | One file per strategy (`ttl.py`, `eager.py`, `batched.py`) |
| `app/cache.py` | Redis cache interface (get/set/delete/flush) |
| `app/db.py` | SQLite wrapper with WAL mode and thread-safe operations |
| `load_gen/load_generator.py` | Concurrent load generator and SRR measurement |
| `load_gen/metrics.py` | CSV result analyzer (no pandas dependency) |
| `docker-compose.yml` | Full topology: 3 nodes + 4 Redis + shared SQLite volume |
| `.agent/ARCHITECTURE.md` | Detailed design reference including failure modes and design decisions |
| `.agent/API_SPEC.md` | Complete HTTP endpoint contracts with exact request/response shapes |
| `.agent/TESTING.md` | 18-scenario test playbook organized by component |
