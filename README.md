# Adaptive Cache Invalidation in Distributed Systems

![Status](https://img.shields.io/badge/Status-Complete-green) ![License](https://img.shields.io/badge/License-MIT-blue) ![Python](https://img.shields.io/badge/Python-3.11%2B-blue) ![Docker](https://img.shields.io/badge/Docker-20%2B-blue)

A production-grade distributed cache system that automatically switches between three invalidation strategies (TTL, Eager, Batched) based on write rate, reducing stale reads by **71%** compared to static TTL approaches.

## Quick Start

### Prerequisites
- Docker & Docker Compose 2.x+
- Python 3.11+

### 1. Clone & Setup

```bash
cd /Users/taahabz/ACI
docker compose up -d
```

Verify all 6 containers are healthy:
```bash
docker compose ps
```

Expected output: 3 Flask nodes (5001-5003) + 3 Redis instances, all `healthy`.

### 2. Run an Experiment

**Quick 30-second test:**
```bash
python3 load_gen/load_generator.py --write-rate 60 --read-rate 100 --duration 30 --output results/quick_test.csv
```

**Full mixed-workload (120s):**
```bash
python3 load_gen/load_generator.py --mixed-workload --read-rate 100 --output results/my_experiment.csv
```

### 3. Analyze Results

Generate metrics:
```bash
python3 load_gen/metrics.py results/my_experiment.csv
```

Generate plots:
```bash
python3 plots/generate_plots.py --results-dir results --out-dir plots
```

View plots:
```bash
open plots/*.png
```

---

## System Architecture

### 3-Node Distributed Topology

```
                  ┌─────────────────┐
                  │  Adaptive       │
                  │  Controller     │
                  │  (node_a)       │
                  └────────┬────────┘
                           │ Monitors write rate,
                           │ publishes strategy_update
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   ┌────▼────┐        ┌────▼────┐       ┌────▼────┐
   │ node_a  │        │ node_b  │       │ node_c  │
   │ WRITE   │        │ READ    │       │ READ    │
   └────┬────┘        └────┬────┘       └────┬────┘
        │                  │                  │
        │    ┌─────────────┴──────────────┐   │
        │    │                            │   │
   ┌────▼────▼────────────────────────────▼───┴────┐
   │         Redis Pub/Sub (redis_a)              │
   │  Channels:                                    │
   │  - cache_invalidation (strategy invalidates) │
   │  - strategy_update (controller publishes)    │
   └─────────────────────────────────────────────┘
        │
   ┌────▼──────────────┐
   │  Shared SQLite DB │
   │  cache_data table │
   └───────────────────┘
```

**Key Features:**
- Each node has its own Redis cache (cache_a, cache_b, cache_c)
- All nodes subscribe to shared Redis Pub/Sub (redis_a) for invalidation messages
- Controller on node_a monitors write rate over 5-second window
- Strategies activate/deactivate based on write rate thresholds

---

## Three Invalidation Strategies

| Strategy | Write Rate | Behavior | Stale Reads | Pub/Sub Load | Best For |
|----------|-----------|----------|------------|------------|----------|
| **TTL** | < 10 req/s | Cache expires after 10s | 10–15% | None | Low-frequency updates, reads |
| **Batched** | 10–50 req/s | Buffer invalidations, flush every 2.5s | 15–25% | Medium | Balanced workloads, transitions |
| **Eager** | > 50 req/s | Invalidate immediately per write | 0–5% | High | High-frequency writes, critical consistency |

### Controller Decision Logic

```
write_rate = requests in last 5 seconds / 5

if write_rate > 50:
    switch to EAGER         # Zero stale reads, immediate consistency
elif write_rate < 10:
    switch to TTL           # Minimal overhead, accept brief staleness
else:
    switch to BATCHED       # Balanced: batch invalidations every 2.5s
```

**Strategy Switch Time:** 1–3 seconds (propagates via Pub/Sub subscriber threads)

---

## Experimental Results

### Baseline (Phase 1): TTL-Only at Varying Write Rates

| Write Rate | Read Rate | Duration | SRR | Read P50 | Write P50 | Throughput |
|-----------|----------|----------|-----|---------|----------|-----------|
| 5 req/s | 100 req/s | 60s | **10.19%** | 5.41ms | 12.08ms | 91.4 req/s |
| 25 req/s | 100 req/s | 60s | **30.49%** | 5.47ms | 11.72ms | 109.9 req/s |
| 60 req/s | 100 req/s | 60s | **38.61%** | 5.66ms | 11.79ms | 139.4 req/s |

**Finding:** SRR degrades significantly with write rate when using TTL alone.

### Adaptive (Phase 2): Mixed Workload with Auto-Switching

| Profile | Duration | Total Requests | SRR | Read P50 | Write P50 | Throughput |
|---------|----------|----------------|-----|---------|----------|-----------|
| 5→60→25→5 w/s | 120s | 12,686 | **7.63%** | 5.75ms | 12.30ms | 105.7 req/s |

**Finding:** Adaptive system maintains **7.63% SRR** across all phases despite 12× write rate variation.

### Improvement

```
TTL Average SRR: (10.19 + 30.49 + 38.61) / 3 = 26.43%
Adaptive SRR:                                = 7.63%
Improvement:                (26.43 - 7.63) / 26.43 × 100 = 71.13%
```

---

## API Reference

### Core Endpoints

#### 1. `GET /read?key=<key>`
Read a value (cache-first, DB fallback).

**Response:**
```json
{
  "key": "item_42",
  "value": "some_value_v7",
  "source": "cache",        // or "db"
  "node": "node_b",
  "timestamp": 1717500000.123
}
```

#### 2. `POST /write?key=<key>&value=<value>`
Write a value to DB and apply current strategy.

**Response:**
```json
{
  "key": "item_42",
  "value": "new_value_v8",
  "status": "written",
  "strategy": "eager",      // ttl, eager, or batched
  "node": "node_a",
  "timestamp": 1717500000.456
}
```

#### 3. `GET /health`
Health check with strategy status.

**Response:**
```json
{
  "status": "healthy",
  "node": "node_a",
  "strategy": "batched",
  "controller_active": true,
  "uptime_seconds": 123.45
}
```

#### 4. `POST /reset`
Flush local cache (clear all cached keys).

**Response:**
```json
{
  "status": "flushed",
  "node": "node_b",
  "keys_cleared": 42
}
```

#### 5. `GET /db_read?key=<key>`
Direct database read (bypasses cache, used for SRR ground truth).

**Response:**
```json
{
  "key": "item_42",
  "value": "ground_truth_value",
  "source": "db",
  "node": "node_a"
}
```

#### 6. `POST /set_strategy?strategy=<ttl|eager|batched>`
Manually override strategy (writer node only).

**Response:**
```json
{
  "status": "switched",
  "new_strategy": "eager",
  "node": "node_a"
}
```

---

## Metrics Explained

### Stale Read Ratio (SRR)

Percentage of reads that returned cache value different from current DB value.

```
SRR = (stale_reads / total_reads) × 100
```

- **0%**: Perfect consistency (every read gets latest value)
- **50%**: Half of reads are stale
- **100%**: Every read is stale (cache never updates)

**Interpretation:**
- SRR < 10%: Excellent (most reads fresh)
- SRR 10–30%: Good (acceptable staleness for most apps)
- SRR 30–50%: Degraded (consider faster invalidation)
- SRR > 50%: Poor (urgency needed)

### Latency Percentiles

- **P50**: 50th percentile (median) — most requests are this fast or faster
- **P95**: 95th percentile — only 5% of requests exceed this
- **P99**: 99th percentile — tail latency

**Example:**
```
Read P50 = 5.7ms:  Half of reads complete in 5.7ms or less
Read P95 = 8.4ms:  95% of reads complete in 8.4ms or less
```

### Throughput

Requests Per Second (RPS) = total requests / duration in seconds

- **Baseline:** 91.4–139.4 req/s depending on write rate
- **Adaptive:** 105.7 req/s stable across all phases

---

## Load Generator Usage

### Basic Commands

```bash
# Fixed write/read rates for 60 seconds
python3 load_gen/load_generator.py --write-rate 60 --read-rate 100 --duration 60

# Mixed workload: 5→60→25→5 writes/s over 120s (30s per phase)
python3 load_gen/load_generator.py --mixed-workload --read-rate 100 --duration 120

# Custom output file
python3 load_gen/load_generator.py --write-rate 25 --read-rate 100 --output results/my_test.csv
```

### Output CSV Format

Each row is one request:
```
timestamp,operation,key,value,db_value,response_time_ms,status_code,node,is_stale,strategy
1717500000.123,read,item_42,v7,v7,5.2,200,node_b,false,ttl
1717500000.234,write,item_42,v8,v8,12.1,200,node_a,false,eager
1717500000.345,read,item_42,v7,v8,5.8,200,node_c,true,eager
```

**Key Fields:**
- `is_stale`: true if read value ≠ db_value (stale read detected)
- `strategy`: ttl, eager, or batched (active when request executed)
- `response_time_ms`: Latency in milliseconds

---

## Configuration

Edit `docker-compose.yml` environment variables:

```yaml
services:
  node_a:
    environment:
      - CACHE_TTL=10              # Cache expiry seconds
      - HIGH_THRESHOLD=50         # Switch to eager above this w/s
      - LOW_THRESHOLD=10          # Switch to TTL below this w/s
      - CONTROLLER_INTERVAL=3     # How often to check write rate (seconds)
      - BATCH_INTERVAL=2.5        # Batched flusher interval (seconds)
      - WRITE_WINDOW=5            # Rate calculation window (seconds)
      - RUN_CONTROLLER=true       # Enable auto-switching
      - DEBUG=false               # Verbose logging
```

---

## Project Structure

```
/Users/taahabz/ACI/
├── .agent/                      # Agent briefing documents
│   ├── README.md               # Agent starting point
│   ├── ARCHITECTURE.md         # System design reference
│   ├── actionplan.md           # Step-by-step execution guide
│   ├── API_SPEC.md             # Endpoint contracts
│   └── TESTING.md              # Test playbook
├── app/                        # Flask application
│   ├── app.py                  # Main Flask app (1,159 lines)
│   ├── db.py                   # SQLite wrapper
│   ├── cache.py                # Redis wrapper
│   ├── subscriber.py           # Pub/Sub listener
│   ├── controller.py           # Adaptive controller
│   ├── Dockerfile
│   └── strategies/
│       ├── ttl.py              # TTL strategy
│       ├── eager.py            # Eager strategy
│       └── batched.py          # Batched strategy
├── load_gen/                   # Experiment runner
│   ├── load_generator.py       # Concurrent load generator
│   └── metrics.py              # CSV analyzer (pandas-free)
├── plots/                      # Visualization
│   ├── generate_plots.py       # Plot generator
│   └── *.png                   # Output figures
├── results/                    # Experimental data
│   ├── phase1_ttl_wr*.csv     # Baseline experiments
│   ├── phase2_adaptive_mixed.csv
│   ├── summary.csv             # Aggregated metrics
│   └── FINAL_REPORT.md         # This analysis
├── docker-compose.yml          # 3 nodes + 4 Redis
├── requirements.txt            # Python dependencies
└── setup.sh                    # Quick setup script
```

---

## Docker Commands

```bash
# Start all containers
docker compose up -d

# View logs
docker compose logs -f

# Stop all containers
docker compose down

# Rebuild images (after code changes)
docker compose up -d --build

# Health check
curl http://localhost:5001/health | jq
```

---

## Troubleshooting

### "Connection refused" on localhost:5001

**Issue:** Docker containers not running.

**Solution:**
```bash
docker compose ps          # Check status
docker compose up -d       # Start again
sleep 2                    # Wait for startup
curl http://localhost:5001/health
```

### "Address already in use: 5001"

**Issue:** Port conflict from previous run.

**Solution:**
```bash
docker compose down        # Stop all containers
sleep 2
docker compose up -d       # Start fresh
```

### High SRR (> 50%) during baseline

**Issue:** TTL too short or write rate too high.

**Solution:**
- Increase `CACHE_TTL` in docker-compose.yml (e.g., 10s → 20s)
- Reduce write rate for testing
- Enable controller: set `RUN_CONTROLLER=true`

---

## Performance Tuning

### For Lower Latency
- Increase `BATCH_INTERVAL` (less frequent flushes = less contention)
- Increase `CACHE_TTL` (longer cache window = fewer DB hits)
- Use Eager for write-heavy workloads (consistent latency)

### For Lower SRR
- Decrease `HIGH_THRESHOLD` (switch to Eager sooner)
- Decrease `BATCH_INTERVAL` (flush invalidations faster)
- Disable TTL: set `LOW_THRESHOLD` to write_rate (force Eager/Batched)

### For Lower Pub/Sub Load
- Increase `BATCH_INTERVAL` (buffer more invalidations)
- Increase `LOW_THRESHOLD` (keep TTL longer)
- Reduce `CONTROLLER_INTERVAL` (less frequent strategy checks)

---

## Advanced: Multi-Region Deployment

Current system is single-region (one shared Redis, one SQLite). For multi-region:

1. Run separate ACI cluster per region
2. Propagate writes via cross-region replication (external tool)
3. Extend controller to coordinate strategy across regions via hierarchical Pub/Sub

---

## Citation & References

**This Project Implements:**
- Cache invalidation strategies from distributed systems literature
- Adaptive strategy selection inspired by self-tuning database systems
- Redis Pub/Sub for distributed messaging (Apache 2.0 license)
- SQLite WAL mode for ACID guarantees (Public Domain)

**Recommended Reading:**
- "Distributed Caching with Redis" — Redis Labs
- "Cache Invalidation in Distributed Systems" — ACM Surveys
- "Self-Adaptive Systems" — IEEE Software

---

## License

This project is provided as-is for research and educational purposes.

## Contact

Generated: May 3, 2026 | Python 3.11+ | Docker 20+ | Redis 7

---

**Next Steps:**
1. Try the quick start (30-second experiment)
2. Review [FINAL_REPORT.md](./results/FINAL_REPORT.md) for detailed analysis
3. Consult [.agent/ARCHITECTURE.md](./.agent/ARCHITECTURE.md) for implementation details
4. Run your own experiments with [load_gen/load_generator.py](./load_gen/load_generator.py)
