"""Generate experiment plots from results CSV files."""

from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict
from statistics import mean

import matplotlib.pyplot as plt


def read_csv(path: str):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def to_float(v, default=0.0):
    try:
        if v in (None, ""):
            return default
        return float(v)
    except Exception:
        return default


def to_int(v, default=0):
    try:
        if v in (None, ""):
            return default
        return int(float(v))
    except Exception:
        return default


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def plot_ttl_baseline(results_dir: str, out_dir: str):
    targets = [
        (5, os.path.join(results_dir, "phase1_ttl_wr5.csv")),
        (25, os.path.join(results_dir, "phase1_ttl_wr25.csv")),
        (60, os.path.join(results_dir, "phase1_ttl_wr60.csv")),
    ]

    wr = []
    srr = []
    p95_read = []
    total_rps = []

    for write_rate, path in targets:
        if not os.path.exists(path):
            continue
        rows = read_csv(path)
        reads = [r for r in rows if r.get("operation") == "read"]
        stale = sum(1 for r in reads if to_int(r.get("is_stale")) == 1)
        srr_pct = (stale / len(reads) * 100.0) if reads else 0.0

        read_lat = sorted(to_float(r.get("response_time_ms")) for r in reads)
        if read_lat:
            idx = int(0.95 * (len(read_lat) - 1))
            p95 = read_lat[idx]
        else:
            p95 = 0.0

        ts = [to_float(r.get("timestamp")) for r in rows]
        duration = max(max(ts) - min(ts), 0.001) if ts else 0.001

        wr.append(write_rate)
        srr.append(srr_pct)
        p95_read.append(p95)
        total_rps.append(len(rows) / duration)

    if not wr:
        return

    # SRR vs write rate
    plt.figure(figsize=(8, 5))
    plt.plot(wr, srr, marker="o")
    plt.title("TTL Baseline: SRR vs Write Rate")
    plt.xlabel("Write Rate (w/s)")
    plt.ylabel("SRR (%)")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "ttl_srr_vs_write_rate.png"), dpi=140)
    plt.close()

    # Read p95 latency vs write rate
    plt.figure(figsize=(8, 5))
    plt.plot(wr, p95_read, marker="o", color="orange")
    plt.title("TTL Baseline: Read P95 Latency vs Write Rate")
    plt.xlabel("Write Rate (w/s)")
    plt.ylabel("Read P95 Latency (ms)")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "ttl_read_p95_vs_write_rate.png"), dpi=140)
    plt.close()

    # Throughput vs write rate
    plt.figure(figsize=(8, 5))
    plt.plot(wr, total_rps, marker="o", color="green")
    plt.title("TTL Baseline: Total Throughput vs Write Rate")
    plt.xlabel("Write Rate (w/s)")
    plt.ylabel("Total Throughput (req/s)")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "ttl_throughput_vs_write_rate.png"), dpi=140)
    plt.close()


def plot_mixed_adaptive(results_dir: str, out_dir: str):
    mixed = os.path.join(results_dir, "phase2_adaptive_mixed.csv")
    if not os.path.exists(mixed):
        return

    rows = read_csv(mixed)
    if not rows:
        return

    min_ts = min(to_float(r.get("timestamp")) for r in rows)

    # 5-second window SRR timeline
    buckets = defaultdict(lambda: {"reads": 0, "stale": 0})
    for r in rows:
        if r.get("operation") != "read":
            continue
        sec = int((to_float(r.get("timestamp")) - min_ts) // 5)
        buckets[sec]["reads"] += 1
        buckets[sec]["stale"] += 1 if to_int(r.get("is_stale")) == 1 else 0

    x = sorted(buckets.keys())
    srr = [
        (buckets[i]["stale"] / buckets[i]["reads"] * 100.0) if buckets[i]["reads"] else 0.0
        for i in x
    ]

    plt.figure(figsize=(10, 5))
    plt.plot([i * 5 for i in x], srr, marker=".")
    plt.title("Adaptive Mixed Workload: SRR Timeline (5s windows)")
    plt.xlabel("Elapsed Time (s)")
    plt.ylabel("SRR (%)")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "adaptive_mixed_srr_timeline.png"), dpi=140)
    plt.close()

    # Strategy usage from write rows
    strategy_counts = defaultdict(int)
    for r in rows:
        if r.get("operation") == "write":
            strategy_counts[(r.get("strategy") or "unknown").lower()] += 1

    if strategy_counts:
        labels = list(strategy_counts.keys())
        values = [strategy_counts[k] for k in labels]
        plt.figure(figsize=(8, 5))
        plt.bar(labels, values)
        plt.title("Adaptive Mixed Workload: Write Count by Strategy")
        plt.xlabel("Strategy")
        plt.ylabel("Write Requests")
        plt.tight_layout()
        plt.savefig(os.path.join(out_dir, "adaptive_strategy_usage.png"), dpi=140)
        plt.close()


def plot_comparison(results_dir: str, out_dir: str):
    ttl_paths = [
        os.path.join(results_dir, "phase1_ttl_wr5.csv"),
        os.path.join(results_dir, "phase1_ttl_wr25.csv"),
        os.path.join(results_dir, "phase1_ttl_wr60.csv"),
    ]
    adaptive_path = os.path.join(results_dir, "phase2_adaptive_mixed.csv")

    ttl_srr = []
    for p in ttl_paths:
        if not os.path.exists(p):
            continue
        rows = read_csv(p)
        reads = [r for r in rows if r.get("operation") == "read"]
        stale = sum(1 for r in reads if to_int(r.get("is_stale")) == 1)
        ttl_srr.append((stale / len(reads) * 100.0) if reads else 0.0)

    adaptive_srr = None
    if os.path.exists(adaptive_path):
        rows = read_csv(adaptive_path)
        reads = [r for r in rows if r.get("operation") == "read"]
        stale = sum(1 for r in reads if to_int(r.get("is_stale")) == 1)
        adaptive_srr = (stale / len(reads) * 100.0) if reads else 0.0

    if ttl_srr and adaptive_srr is not None:
        ttl_avg = mean(ttl_srr)
        plt.figure(figsize=(7, 5))
        plt.bar(["TTL Avg (Phase1)", "Adaptive Mixed"], [ttl_avg, adaptive_srr])
        plt.title("SRR Comparison")
        plt.ylabel("SRR (%)")
        plt.tight_layout()
        plt.savefig(os.path.join(out_dir, "srr_comparison_ttl_vs_adaptive.png"), dpi=140)
        plt.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", default="results")
    parser.add_argument("--out-dir", default="plots")
    args = parser.parse_args()

    ensure_dir(args.out_dir)

    plot_ttl_baseline(args.results_dir, args.out_dir)
    plot_mixed_adaptive(args.results_dir, args.out_dir)
    plot_comparison(args.results_dir, args.out_dir)

    print(f"Plots generated in: {args.out_dir}")


if __name__ == "__main__":
    main()
