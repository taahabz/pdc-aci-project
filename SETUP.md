# Adaptive Cache Invalidation System — Project Structure

This is a distributed cache invalidation system with adaptive strategy selection.

## Quick Start

### 1. Initialize Environment
```bash
bash setup.sh
source venv/bin/activate
```

### 2. Start Docker Containers
```bash
docker compose up -d
```

### 3. Verify System
```bash
curl http://localhost:5001/health
curl http://localhost:5002/health
curl http://localhost:5003/health
```

### 4. Run Experiments
```bash
python3 load_gen/load_generator.py --write-rate 10 --duration 60
python3 load_gen/metrics.py results/experiment.csv
```

## Environment Configuration

- **`.env.example`** — Template configuration file
- **`.env`** — Your local configuration (created by `setup.sh`, not in git)
- **`venv/`** — Python virtual environment (local, not in git)

## Project Structure

```
.
├── setup.sh                 # Initialization script
├── .env.example             # Configuration template
├── requirements.txt         # Python dependencies (for requirements file)
├── docker-compose.yml       # Docker orchestration
│
├── app/                     # Flask application (shared codebase)
│   ├── Dockerfile
│   ├── app.py              # Main Flask server
│   ├── cache.py            # Redis cache wrapper
│   ├── db.py               # SQLite database interface
│   ├── controller.py        # Adaptive controller
│   ├── subscriber.py        # Pub/Sub listener
│   └── strategies/          # Invalidation strategies
│       ├── ttl.py
│       ├── eager.py
│       └── batched.py
│
├── load_gen/                # Load generator and metrics
│   ├── load_generator.py   # Workload generation
│   └── metrics.py          # Results analysis
│
├── plots/                   # Plotting and visualization
│   └── generate_plots.py
│
├── shared_db/               # SQLite shared volume
│   └── cache.db (created at runtime)
│
├── results/                 # Experiment output
│   └── *.csv (created by load generator)
│
├── logs/                    # Application logs
│   └── *.log (created at runtime)
│
└── tests/                   # Test suite
    ├── test_db.py
    ├── test_cache.py
    ├── test_strategies.py
    ├── test_integration.py
    └── test_e2e.py
```

## Portability Features

✓ **Python venv** — Isolated dependencies, works across machines
✓ **Environment variables** — Configuration via `.env` (customize without code changes)
✓ **Docker volumes** — Persistent data in `shared_db/`, `results/`, `logs/`
✓ **Relative paths** — All paths relative to project root
✓ **Self-documenting** — `.env.example` shows all available settings
✓ **One-command setup** — `bash setup.sh` creates everything

## Typical Workflow

### Development
```bash
source venv/bin/activate          # Activate environment
docker compose up -d               # Start containers
docker compose logs -f             # Watch logs
curl http://localhost:5001/health  # Manual testing
docker compose down                # Stop containers
```

### Running Experiments
```bash
source venv/bin/activate
docker compose up -d
./run_experiment.sh <write_rate>   # (script not yet created)
docker compose down
```

### Troubleshooting
```bash
# Check environment
cat .env

# View container logs
docker compose logs node_a
docker compose logs redis_a

# Reset containers
docker compose down -v
docker compose up -d

# Clean Python cache
find . -type d -name __pycache__ -exec rm -r {} +
find . -type f -name "*.pyc" -delete
```

## Deployment on Another Machine

1. Clone or copy the project
2. `bash setup.sh` — Creates venv and directories
3. Adjust `.env` for your environment (ports, paths, thresholds)
4. `docker compose up -d`
5. Run tests/experiments

All state is in volumes (`shared_db/`, `results/`, `logs/`) — easily backed up or transferred.
