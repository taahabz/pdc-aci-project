# README — Agent Briefing Document

> **You are an AI agent tasked with building the "Adaptive Cache Invalidation in Distributed Systems" project from scratch. This README is your starting point. Read it fully before touching any code.**

---

## WHAT YOU ARE BUILDING

A distributed system with 3 Flask nodes, each with its own Redis cache, sharing one SQLite database. Writes happen on Node A. Reads happen on all nodes. The problem: when Node A writes a new value, Nodes B and C still serve the old cached value (stale reads). The solution: an Adaptive Controller that monitors write rate and automatically picks the best invalidation strategy (EAGER, BATCHED, or TTL) to minimize stale reads without wasting messages.

You will build this, test it, run experiments, generate plots, and produce a results analysis.

---

## YOUR DOCUMENTS

You have 4 markdown files. Each has a specific job. Here is what they are, when to use them, and the rule for each.

### 1. `actionplan.md` — THE MASTER PLAN (Start Here)

**What it is:** Your step-by-step execution guide. Every task you need to do is listed in order with numbered steps grouped into 3 phases and gated by 5 checkpoints.

**When to use it:** This is your primary working document. Follow it top to bottom. Every step has an action (what to build), a validation (how to verify it works), and a pass/fail gate (whether you can move on).

**Rule:** Never skip a step. Never proceed past a checkpoint until every check in that checkpoint is green. If a validation fails, fix it before moving on.

**Structure at a glance:**
- Step 2.x — Environment & directory setup
- **Checkpoint 0** — Environment ready
- Step 3.1–3.8 — Build Docker, Flask, SQLite, Redis, TTL strategy
- **Checkpoint 1** — Baseline nodes running
- Step 3.9–3.10 — Build load generator & metrics analyzer
- **Checkpoint 2** — Load generator working
- Step 3.11 — Run Phase 1 experiments (TTL-only baseline)
- **Checkpoint 3** — Phase 1 complete
- Step 4.1–4.7 — Build Eager, Batched, Subscriber, Controller
- **Checkpoint 4** — Adaptive system complete
- Step 5.1–5.5 — Run all experiments, generate plots, analyze results
- **Checkpoint 5** — Project complete

---

### 2. `ARCHITECTURE.md` — THE REFERENCE MANUAL

**What it is:** Deep technical documentation of how every component connects, communicates, and fails. Includes ASCII diagrams of the topology, all 5 data flows, the controller state machine, the thread model, and SQLite concurrency rules.

**When to use it:** Consult this BEFORE writing any component. When `actionplan.md` tells you to build something (e.g., "Write `subscriber.py`"), open `ARCHITECTURE.md` and read the relevant section first. It will tell you things that aren't obvious — like the fact that there are TWO separate Redis connections per node (one for local cache, one for shared Pub/Sub), or that the batch flusher must release its lock BEFORE doing network I/O.

**Rule:** If you are unsure how two components interact, the answer is in this document. Do not guess. Do not infer from the code alone. Read the architecture doc.

**Critical sections you must read before writing any code:**
- **Section 2: The Two Redis Distinction** — This is the #1 source of bugs. Every node connects to its OWN Redis for caching but to a SHARED Redis (redis_a) for Pub/Sub. Get this wrong and invalidation messages never arrive.
- **Section 5: Thread Model** — Each node runs up to 4 threads. Understand which threads access which shared variables and what locks protect them.
- **Section 6: SQLite Concurrency** — Always use `timeout=10` and WAL mode. Always open/close connections per request.

---

### 3. `API_SPEC.md` — THE CONTRACT

**What it is:** The exact request and response format for every HTTP endpoint and every Pub/Sub message. Includes method, path, parameters, response JSON with every field typed, status codes, side effects, error cases, and implementation pseudocode.

**When to use it:** Open this side-by-side when implementing any endpoint in `app.py`. The response shapes are contracts — the load generator parses these exact JSON fields. If you return `{"src": "cache"}` instead of `{"source": "cache"}`, the load generator breaks.

**Rule:** Implement endpoints exactly as specified. Field names, field types, status codes, and side effects must match. The load generator and metrics scripts depend on these contracts.

**Endpoints defined:**
| # | Endpoint | Purpose |
|---|----------|---------|
| 1 | `GET /read` | Read from cache → DB fallback |
| 2 | `POST /write` | Write to DB + apply strategy |
| 3 | `GET /health` | Health check + strategy status |
| 4 | `POST /reset` | Flush local Redis cache |
| 5 | `GET /db_read` | Direct DB read (SRR ground truth) |
| 6 | `POST /set_strategy` | Manual strategy override |

Also defines Pub/Sub message formats for `cache_invalidation` and `strategy_update` channels, and the load generator CLI interface.

---

### 4. `TESTING.md` — THE QUALITY GATE

**What it is:** Complete test playbook with actual pytest code for every component. 18 tests organized into unit tests (no Docker needed), integration tests (Docker required), end-to-end tests, and experiment validation tests.

**When to use it:** After building each component, go to the corresponding test section, copy the test code into `tests/`, and run it. If the test fails, the component is not done.

**Rule:** A component is not "done" until its tests pass. Do not move to the next step in `actionplan.md` until the corresponding tests in `TESTING.md` are green.

**Test categories:**
| Category | What it tests | Docker needed? | When to run |
|----------|--------------|----------------|-------------|
| `test_db.py` | SQLite helper CRUD + concurrency | No | After writing `db.py` |
| `test_cache.py` | Redis wrapper get/set/delete/TTL | Redis only | After writing `cache.py` |
| `test_strategies.py` | TTL/Eager/Batched logic in isolation | Redis only | After each strategy file |
| `test_controller.py` | Controller threshold decisions | No | After writing `controller.py` |
| `test_integration.py` | Cross-node reads, stale detection, invalidation | Full Docker | After each checkpoint |
| `test_e2e.py` | Controller auto-switching, switch latency | Full Docker | After Phase 2 |
| CSV validation | Experiment output correctness | Full Docker | After each experiment |
| Regression suite | Quick 30-second sanity check | Full Docker | After ANY code change |

---

## HOW THE DOCUMENTS RELATE

```
┌─────────────────────────────────────────────┐
│              README.md (this file)           │
│         "What am I doing? Start here."      │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│            actionplan.md                     │
│       "What do I do next? Step N."           │
│                                              │
│   Step says "Build subscriber.py"            │
│       │                  │                   │
│       ▼                  ▼                   │
│  ┌──────────┐    ┌─────────────┐             │
│  │ARCH.md   │    │API_SPEC.md  │             │
│  │"How does │    │"What exact   │             │
│  │it connect│    │JSON does it  │             │
│  │to other  │    │return?"      │             │
│  │parts?"   │    │              │             │
│  └──────────┘    └─────────────┘             │
│       │                                      │
│       ▼                                      │
│   Step says "Validate"                       │
│       │                                      │
│       ▼                                      │
│  ┌──────────┐                                │
│  │TESTING.md│                                │
│  │"Run this │                                │
│  │pytest.   │                                │
│  │Green?    │                                │
│  │Move on." │                                │
│  └──────────┘                                │
│       │                                      │
│       ▼                                      │
│   Next step...                               │
└─────────────────────────────────────────────┘
```

**The loop for every step is:**

1. Read the step in `actionplan.md`
2. Check `ARCHITECTURE.md` for how this component fits into the system
3. Check `API_SPEC.md` for exact contracts (if the step involves an endpoint or message)
4. Build it
5. Run the test from `TESTING.md`
6. Green? → next step. Red? → fix and re-test.

---

## EXECUTION PROTOCOL

### Before you write any code:

1. Read this README fully (you're doing that now).
2. Read `actionplan.md` Sections 1 and 2 (project summary + prerequisites).
3. Read `ARCHITECTURE.md` Sections 1, 2, and 5 (topology, two-Redis distinction, thread model).
4. Read `API_SPEC.md` top section (base URLs and endpoint list).
5. Now start executing `actionplan.md` Step 2.1.

### While building:

- Follow `actionplan.md` step by step.
- Look up details in `ARCHITECTURE.md` and `API_SPEC.md` as needed.
- Run tests from `TESTING.md` at every validation point.
- Never skip a checkpoint.

### When something breaks:

1. Check `ARCHITECTURE.md` Section 7.5 (Troubleshooting Guide in actionplan).
2. Check if the Two Redis distinction is correct (Section 2 of ARCHITECTURE.md).
3. Run the regression suite from `TESTING.md` to isolate what broke.
4. Fix, re-test, continue.

### When you're done:

- Every checkpoint in `actionplan.md` is green.
- Every test in `TESTING.md` Section 7 checklist is ticked.
- All 16 deliverables in `actionplan.md` Section 7.6 exist.
- 6 plot PNGs are generated.
- Summary results table is computed.
- H1 hypothesis is evaluated (confirmed or rejected with evidence).

---

## FILE MANIFEST

| File | Lines | Purpose |
|------|-------|---------|
| `README.md` | ~180 | This file. Entry point. Read first. |
| `actionplan.md` | ~1460 | Step-by-step execution plan with checkpoints |
| `ARCHITECTURE.md` | ~530 | Component reference, data flows, thread model |
| `API_SPEC.md` | ~550 | Exact endpoint and message contracts |
| `TESTING.md` | ~1070 | Full test playbook with pytest code |
| **Total** | **~3800** | **Complete project bible** |

---

## QUICK REFERENCE — THE 5 CHECKPOINTS

| # | Name | Key Gate |
|---|------|----------|
| 0 | Environment Ready | Docker, Python, dirs exist |
| 1 | Baseline Nodes Running | 3 nodes + 3 Redis up, read/write works, stale reads observable |
| 2 | Load Generator Working | CSV output with correct schema, SRR computed |
| 3 | Phase 1 Complete | 3 baseline experiment CSVs collected |
| 4 | Adaptive System Complete | All 3 strategies + controller auto-switching |
| 5 | Experiments Complete | All CSVs, all plots, results table, H1 evaluated |

---

**You now have everything you need. Open `actionplan.md` and start at Step 2.1.**
