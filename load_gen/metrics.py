"""Metrics analyzer for load generator CSV output."""

from __future__ import annotations

import argparse
import csv
import os
import re
from collections import Counter
from typing import Dict, List, Optional


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze experiment CSV metrics")
    parser.add_argument("input", help="Path to experiment CSV")
    parser.add_argument("--summary", default="results/summary.csv", help="Summary CSV output path")
    return parser.parse_args()


def to_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value: object, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def percentile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = q * (len(ordered) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    frac = idx - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def detect_rate_from_name(name: str, key: str) -> Optional[int]:
    # ex: phase1_ttl_wr25.csv -> wr25
    m = re.search(rf"{key}(\d+)", name)
    if not m:
        return None
    return int(m.group(1))


def main() -> None:
    args = parse_args()

    with open(args.input, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        raise SystemExit("Input CSV is empty")

    required = {
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
    }
    missing = required.difference(rows[0].keys())
    if missing:
        raise SystemExit(f"Missing required columns: {sorted(missing)}")

    reads = [r for r in rows if (r.get("operation") or "").lower() == "read"]
    writes = [r for r in rows if (r.get("operation") or "").lower() == "write"]

    timestamps = [to_float(r.get("timestamp"), 0.0) for r in rows]
    min_ts = min(timestamps) if timestamps else 0.0
    max_ts = max(timestamps) if timestamps else 0.0
    duration = max(max_ts - min_ts, 0.001)

    total_requests = len(rows)
    total_reads = len(reads)
    total_writes = len(writes)

    stale_reads = sum(1 for r in reads if to_int(r.get("is_stale"), 0) == 1)
    srr_pct = (stale_reads / total_reads * 100.0) if total_reads else 0.0

    read_lat = [to_float(r.get("response_time_ms"), 0.0) for r in reads]
    write_lat = [to_float(r.get("response_time_ms"), 0.0) for r in writes]

    read_p50 = percentile(read_lat, 0.50)
    read_p95 = percentile(read_lat, 0.95)
    read_p99 = percentile(read_lat, 0.99)

    write_p50 = percentile(write_lat, 0.50)
    write_p95 = percentile(write_lat, 0.95)
    write_p99 = percentile(write_lat, 0.99)

    read_rps = total_reads / duration
    write_rps = total_writes / duration
    total_rps = total_requests / duration

    errors = sum(1 for r in rows if to_int(r.get("status_code"), 0) >= 400)
    error_pct = (errors / total_requests * 100.0) if total_requests else 0.0

    print("=== Experiment Summary ===")
    print(f"Duration: {duration:.1f} seconds")
    print(f"Total Requests: {total_requests}")
    print(f"  Reads:  {total_reads}")
    print(f"  Writes: {total_writes}")
    print()
    print("--- Stale Read Ratio (SRR) ---")
    print(f"Total Reads:      {total_reads}")
    print(f"Stale Reads:      {stale_reads}")
    print(f"SRR:              {srr_pct:.2f}%")
    print()
    print("--- Latency (ms) ---")
    print(f"Read  P50:    {read_p50:.1f} ms")
    print(f"Read  P95:    {read_p95:.1f} ms")
    print(f"Read  P99:    {read_p99:.1f} ms")
    print(f"Write P50:    {write_p50:.1f} ms")
    print(f"Write P95:    {write_p95:.1f} ms")
    print(f"Write P99:    {write_p99:.1f} ms")
    print()
    print("--- Throughput ---")
    print(f"Read  RPS:    {read_rps:.1f} req/s")
    print(f"Write RPS:    {write_rps:.1f} req/s")
    print(f"Total RPS:    {total_rps:.1f} req/s")
    print()
    print("--- Errors ---")
    print(f"HTTP Errors:  {errors} ({error_pct:.2f}%)")

    exp_name = os.path.basename(args.input)
    strategy_values = [
        str(r.get("strategy", "")).strip().lower()
        for r in rows
        if str(r.get("strategy", "")).strip() not in {"", "unknown"}
    ]
    if strategy_values:
        strategy = Counter(strategy_values).most_common(1)[0][0]
    else:
        strategy = "unknown"

    write_rate = detect_rate_from_name(exp_name, "wr")
    read_rate = detect_rate_from_name(exp_name, "rr")

    os.makedirs(os.path.dirname(args.summary) or ".", exist_ok=True)
    summary_exists = os.path.exists(args.summary)

    row: Dict[str, object] = {
        "experiment_name": exp_name,
        "strategy": strategy,
        "write_rate": write_rate if write_rate is not None else "",
        "read_rate": read_rate if read_rate is not None else "",
        "duration": round(duration, 3),
        "total_reads": total_reads,
        "stale_reads": stale_reads,
        "srr_pct": round(srr_pct, 4),
        "read_p50_ms": round(read_p50, 4),
        "read_p95_ms": round(read_p95, 4),
        "write_p50_ms": round(write_p50, 4),
        "write_p95_ms": round(write_p95, 4),
        "total_rps": round(total_rps, 4),
        "errors": errors,
    }

    columns = [
        "experiment_name",
        "strategy",
        "write_rate",
        "read_rate",
        "duration",
        "total_reads",
        "stale_reads",
        "srr_pct",
        "read_p50_ms",
        "read_p95_ms",
        "write_p50_ms",
        "write_p95_ms",
        "total_rps",
        "errors",
    ]

    with open(args.summary, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        if not summary_exists:
            writer.writeheader()
        writer.writerow(row)

    print()
    print(f"Summary appended to: {args.summary}")


if __name__ == "__main__":
    main()
