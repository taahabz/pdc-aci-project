"""CSV reading and rolling metrics computation for the live dashboard."""
from __future__ import annotations

import csv
import io
import os
import time
from typing import Dict, List


def read_csv_rows(path: str) -> List[Dict]:
    """Read all complete rows from a growing CSV, safe against partial final lines."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", newline="", encoding="utf-8") as f:
            content = f.read()
        last_newline = content.rfind("\n")
        if last_newline <= 0:
            return []
        reader = csv.DictReader(io.StringIO(content[:last_newline]))
        return [r for r in reader if r.get("timestamp")]
    except Exception:
        return []


def compute_srr_timeline(rows: List[Dict], bucket_s: float = 5.0) -> List[Dict]:
    """Compute stale read ratio in rolling time buckets."""
    reads = [r for r in rows if r.get("operation") == "read" and r.get("is_stale") != ""]
    if not reads:
        return []

    try:
        min_ts = min(float(r["timestamp"]) for r in reads)
    except (ValueError, KeyError):
        return []

    buckets: Dict[int, Dict] = {}
    for r in reads:
        try:
            b = int((float(r["timestamp"]) - min_ts) / bucket_s)
            if b not in buckets:
                buckets[b] = {
                    "time_s": b * bucket_s,
                    "total": 0,
                    "stale": 0,
                    "strategy": r.get("strategy", "unknown"),
                }
            buckets[b]["total"] += 1
            if str(r.get("is_stale")) == "1":
                buckets[b]["stale"] += 1
        except (ValueError, KeyError):
            continue

    return [
        {
            "time_s": d["time_s"],
            "srr": round(d["stale"] / d["total"] * 100, 2) if d["total"] else 0.0,
            "reads": d["total"],
            "strategy": d["strategy"],
        }
        for d in (buckets[b] for b in sorted(buckets))
    ]


def compute_latency_timeline(rows: List[Dict], bucket_s: float = 5.0) -> List[Dict]:
    """Compute rolling P50 read latency per bucket."""
    reads = [r for r in rows if r.get("operation") == "read"]
    if not reads:
        return []

    try:
        min_ts = min(float(r["timestamp"]) for r in reads)
    except (ValueError, KeyError):
        return []

    buckets: Dict[int, List[float]] = {}
    for r in reads:
        try:
            b = int((float(r["timestamp"]) - min_ts) / bucket_s)
            buckets.setdefault(b, []).append(float(r["response_time_ms"]))
        except (ValueError, KeyError):
            continue

    return [
        {
            "time_s": b * bucket_s,
            "p50_ms": round(sorted(lats)[len(lats) // 2], 2),
            "count": len(lats),
        }
        for b, lats in sorted(buckets.items())
    ]


def cumulative_stats(rows: List[Dict]) -> Dict:
    reads = [r for r in rows if r.get("operation") == "read"]
    writes = [r for r in rows if r.get("operation") == "write"]
    stale = [r for r in reads if str(r.get("is_stale")) == "1"]
    srr = len(stale) / len(reads) * 100 if reads else 0.0
    return {
        "total": len(rows),
        "reads": len(reads),
        "writes": len(writes),
        "stale": len(stale),
        "srr": round(srr, 2),
    }


def current_write_rate(rows: List[Dict], window_s: float = 5.0) -> float:
    """Estimate current write rate from recent CSV rows (same formula as controller)."""
    now = time.time()
    recent = [r for r in rows if r.get("operation") == "write" and
              abs(float(r.get("timestamp", 0)) - now) <= window_s]
    return len(recent) / window_s
