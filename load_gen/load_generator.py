"""Load generator for Adaptive Cache Invalidation experiments.

Generates concurrent write/read workload against the 3-node cluster,
verifies stale reads via /db_read, and writes per-request CSV output.
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import threading
import time
from dataclasses import dataclass, field
from itertools import cycle
from typing import Dict, List, Optional

import requests


@dataclass
class Counters:
    writes: int = 0
    reads: int = 0
    stale_reads: int = 0
    errors: int = 0
    latency_sum_ms: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add_latency(self, ms: float) -> None:
        with self.lock:
            self.latency_sum_ms += ms


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Distributed cache load generator")
    parser.add_argument("--write-rate", type=int, default=10, help="Target writes per second")
    parser.add_argument("--read-rate", type=int, default=100, help="Target reads per second")
    parser.add_argument("--duration", type=int, default=60, help="Test duration in seconds")
    parser.add_argument("--write-node", type=str, default="http://localhost:5001", help="Write node base URL")
    parser.add_argument(
        "--read-nodes",
        type=str,
        default="http://localhost:5001,http://localhost:5002,http://localhost:5003",
        help="Comma-separated read node base URLs",
    )
    parser.add_argument("--output", type=str, default="results/experiment.csv", help="Output CSV path")
    parser.add_argument("--key-space", type=int, default=100, help="Unique keys: item_0..item_N-1")
    parser.add_argument("--mixed-workload", action="store_true", help="Enable 120s mixed write workload")
    return parser.parse_args()


def get_current_write_rate(base_rate: int, elapsed_s: float, mixed_workload: bool) -> int:
    if not mixed_workload:
        return base_rate

    # 120s profile, 30s segments: 5 -> 60 -> 25 -> 5
    if elapsed_s < 30:
        return 5
    if elapsed_s < 60:
        return 60
    if elapsed_s < 90:
        return 25
    return 5


def safe_json_value(resp: requests.Response, key: str, default=None):
    try:
        payload = resp.json()
        return payload.get(key, default)
    except Exception:
        return default


def writer_thread(
    stop_event: threading.Event,
    args: argparse.Namespace,
    counters: Counters,
    csv_writer: csv.writer,
    csv_lock: threading.Lock,
    start_time: float,
) -> None:
    write_seq = 0
    next_tick = time.perf_counter()

    while not stop_event.is_set():
        elapsed = time.time() - start_time
        if elapsed >= args.duration:
            break

        current_rate = get_current_write_rate(args.write_rate, elapsed, args.mixed_workload)
        if current_rate <= 0:
            time.sleep(0.1)
            continue

        key = f"item_{random.randint(0, args.key_space - 1)}"
        write_seq += 1
        value = f"{key}_v{write_seq}"

        started = time.perf_counter()
        status_code = 0
        node = "unknown"
        strategy = "unknown"

        try:
            resp = requests.post(
                f"{args.write_node.rstrip('/')}/write",
                json={"key": key, "value": value},
                timeout=3,
            )
            status_code = resp.status_code
            node = safe_json_value(resp, "node", "unknown")
            strategy = safe_json_value(resp, "strategy", "unknown")
            if status_code >= 400:
                with counters.lock:
                    counters.errors += 1
        except Exception:
            with counters.lock:
                counters.errors += 1

        latency_ms = (time.perf_counter() - started) * 1000
        counters.add_latency(latency_ms)

        with counters.lock:
            counters.writes += 1

        with csv_lock:
            csv_writer.writerow(
                [
                    time.time(),
                    "write",
                    key,
                    value,
                    "",
                    round(latency_ms, 3),
                    status_code,
                    node,
                    "",
                    strategy,
                ]
            )

        interval = 1.0 / max(current_rate, 1)
        next_tick += interval
        sleep_s = next_tick - time.perf_counter()
        if sleep_s > 0:
            time.sleep(sleep_s)
        else:
            # If we fell behind, reset schedule to now to avoid runaway lag.
            next_tick = time.perf_counter()


def reader_thread(
    stop_event: threading.Event,
    args: argparse.Namespace,
    counters: Counters,
    csv_writer: csv.writer,
    csv_lock: threading.Lock,
    start_time: float,
) -> None:
    read_nodes: List[str] = [n.strip().rstrip("/") for n in args.read_nodes.split(",") if n.strip()]
    rr = cycle(read_nodes)
    next_tick = time.perf_counter()

    while not stop_event.is_set():
        elapsed = time.time() - start_time
        if elapsed >= args.duration:
            break

        key = f"item_{random.randint(0, args.key_space - 1)}"
        target = next(rr)

        started = time.perf_counter()
        status_code = 0
        node = "unknown"
        read_value = None
        strategy = "unknown"

        try:
            resp = requests.get(f"{target}/read", params={"key": key}, timeout=3)
            status_code = resp.status_code
            node = safe_json_value(resp, "node", target)
            read_value = safe_json_value(resp, "value", None)
            strategy = safe_json_value(resp, "strategy", "unknown")
            if status_code >= 400:
                with counters.lock:
                    counters.errors += 1
        except Exception:
            with counters.lock:
                counters.errors += 1

        latency_ms = (time.perf_counter() - started) * 1000
        counters.add_latency(latency_ms)

        # Ground truth from DB-direct endpoint on write node
        db_value = None
        is_stale = ""
        try:
            db_resp = requests.get(
                f"{args.write_node.rstrip('/')}/db_read",
                params={"key": key},
                timeout=3,
            )
            db_value = safe_json_value(db_resp, "value", None)
            if status_code == 200 and db_resp.status_code == 200:
                is_stale = 1 if read_value != db_value else 0
                if is_stale == 1:
                    with counters.lock:
                        counters.stale_reads += 1
        except Exception:
            pass

        with counters.lock:
            counters.reads += 1

        with csv_lock:
            csv_writer.writerow(
                [
                    time.time(),
                    "read",
                    key,
                    read_value,
                    db_value,
                    round(latency_ms, 3),
                    status_code,
                    node,
                    is_stale,
                    strategy,
                ]
            )

        interval = 1.0 / max(args.read_rate, 1)
        next_tick += interval
        sleep_s = next_tick - time.perf_counter()
        if sleep_s > 0:
            time.sleep(sleep_s)
        else:
            next_tick = time.perf_counter()


def main() -> None:
    args = parse_args()

    if args.mixed_workload:
        args.duration = 120

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    counters = Counters()
    stop_event = threading.Event()
    csv_lock = threading.Lock()

    start_time = time.time()

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "timestamp",
                "operation",
                "key",
                "value",
                "db_value",
                "response_time_ms",
                "status_code",
                "node",
                "is_stale",
                "strategy",
            ]
        )

        wt = threading.Thread(
            target=writer_thread,
            args=(stop_event, args, counters, writer, csv_lock, start_time),
            daemon=True,
        )
        rt = threading.Thread(
            target=reader_thread,
            args=(stop_event, args, counters, writer, csv_lock, start_time),
            daemon=True,
        )

        wt.start()
        rt.start()

        # progress every 5s
        while True:
            elapsed = time.time() - start_time
            if elapsed >= args.duration:
                break
            time.sleep(5)
            with counters.lock:
                total = counters.reads + counters.writes
                stale_pct = (counters.stale_reads / counters.reads * 100.0) if counters.reads else 0.0
                avg_lat = (counters.latency_sum_ms / total) if total else 0.0
                print(
                    f"[{int(elapsed):>3}s] writes: {counters.writes} | reads: {counters.reads} | "
                    f"stale: {counters.stale_reads} ({stale_pct:.1f}%) | avg_latency: {avg_lat:.1f}ms"
                )

        stop_event.set()
        wt.join(timeout=3)
        rt.join(timeout=3)

    total_elapsed = max(time.time() - start_time, 1e-6)
    with counters.lock:
        total = counters.reads + counters.writes
        stale_pct = (counters.stale_reads / counters.reads * 100.0) if counters.reads else 0.0
        avg_lat = (counters.latency_sum_ms / total) if total else 0.0

    print(
        f"[DONE] Total: {total} requests in {total_elapsed:.1f}s | "
        f"SRR: {stale_pct:.1f}% | Avg latency: {avg_lat:.1f}ms"
    )


if __name__ == "__main__":
    main()
