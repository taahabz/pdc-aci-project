"""Adaptive Cache Invalidation — Demo Dashboard."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# Ensure dashboard/ utilities are importable
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from csv_tailer import (
    compute_latency_timeline,
    compute_srr_timeline,
    cumulative_stats,
    current_write_rate,
    read_csv_rows,
)
from live_poller import check_nodes_up, poll_health

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
RESULTS = ROOT / "results"
LOAD_GEN = ROOT / "load_gen" / "load_generator.py"
LIVE_CSV = str(RESULTS / "live_demo.csv")

STRATEGY_COLORS = {
    "ttl": "#2196F3",
    "batched": "#FF9800",
    "eager": "#F44336",
    "unknown": "#9E9E9E",
}
STRATEGY_LABELS = {"ttl": "TTL", "batched": "BATCHED", "eager": "EAGER", "unknown": "—"}
STRATEGY_EMOJIS = {"ttl": "⏱", "batched": "📦", "eager": "⚡", "unknown": "?"}

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Adaptive Cache Invalidation",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
.strategy-card {
    padding: 24px 20px;
    border-radius: 14px;
    text-align: center;
    margin-bottom: 10px;
    transition: background 0.3s;
}
.strategy-active-label {
    font-size: 11px;
    font-weight: 700;
    color: rgba(255,255,255,0.75);
    letter-spacing: 2px;
    text-transform: uppercase;
}
.strategy-name {
    font-size: 40px;
    font-weight: 900;
    color: #fff;
    line-height: 1.1;
    margin: 6px 0 2px;
}
.strategy-rate {
    font-size: 13px;
    color: rgba(255,255,255,0.65);
}
.hero-box {
    background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
    padding: 36px 28px;
    border-radius: 16px;
    text-align: center;
}
.hero-number { font-size: 80px; font-weight: 900; color: #00e5a0; line-height: 1; }
.hero-subtitle { font-size: 15px; color: #aaa; margin-top: 8px; }
.hero-detail  { font-size: 12px; color: #666; margin-top: 4px; }
</style>
""", unsafe_allow_html=True)


# ── Utilities ─────────────────────────────────────────────────────────────────

def _strategy_card(strategy: str, write_rate: Optional[float] = None) -> None:
    color = STRATEGY_COLORS.get(strategy, STRATEGY_COLORS["unknown"])
    name = STRATEGY_LABELS.get(strategy, strategy.upper())
    emoji = STRATEGY_EMOJIS.get(strategy, "?")
    rate_line = f'<div class="strategy-rate">{write_rate:.1f} writes/s</div>' if write_rate is not None else ""
    st.markdown(
        f"""<div class="strategy-card" style="background:{color}">
            <div class="strategy-active-label">Active Strategy</div>
            <div class="strategy-name">{emoji}&nbsp;{name}</div>
            {rate_line}
        </div>""",
        unsafe_allow_html=True,
    )


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, OSError):
        return False


def _start_demo() -> None:
    os.makedirs(RESULTS, exist_ok=True)
    proc = subprocess.Popen(
        [sys.executable, str(LOAD_GEN), "--mixed-workload", "--output", LIVE_CSV],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    st.session_state["demo_pid"] = proc.pid
    st.session_state["demo_running"] = True
    st.session_state["demo_start"] = time.time()
    st.session_state["switch_events"] = []
    st.session_state["last_strategy"] = None


def _stop_demo() -> None:
    pid = st.session_state.get("demo_pid")
    if pid:
        try:
            os.kill(pid, 15)
        except (ProcessLookupError, OSError):
            pass
    st.session_state["demo_running"] = False
    st.session_state.pop("demo_pid", None)


# ── Tab 1: Live Demo ──────────────────────────────────────────────────────────

def render_live_tab() -> None:
    # Check if previously started process has finished
    pid = st.session_state.get("demo_pid")
    if pid and not _is_alive(pid):
        st.session_state["demo_running"] = False
        st.session_state.pop("demo_pid", None)

    running = st.session_state.get("demo_running", False)

    # ── Header + controls ────────────────────────────────────────────────────
    col_btn, col_status = st.columns([2, 5])
    with col_btn:
        if not running:
            nodes_up = check_nodes_up()
            help_txt = None if nodes_up else "Start Docker stack first: docker compose up -d"
            if st.button(
                "▶ Run Mixed Workload",
                type="primary",
                use_container_width=True,
                disabled=not nodes_up,
                help=help_txt,
            ):
                _start_demo()
                st.rerun()
        else:
            if st.button("■ Stop Demo", use_container_width=True):
                _stop_demo()
                st.rerun()

    with col_status:
        if running:
            elapsed = time.time() - st.session_state.get("demo_start", time.time())
            pct = min(elapsed / 120.0, 1.0)
            if elapsed < 30:
                phase = "Phase 1/4 — 5 w/s   → expects TTL (blue)"
            elif elapsed < 60:
                phase = "Phase 2/4 — 60 w/s  → expects EAGER (red)"
            elif elapsed < 90:
                phase = "Phase 3/4 — 25 w/s  → expects BATCHED (orange)"
            else:
                phase = "Phase 4/4 — 5 w/s   → expects TTL (blue)"
            st.progress(pct, text=f"{phase}   [{int(elapsed)}s / 120s]")
        elif not running and os.path.exists(LIVE_CSV):
            st.info("Showing last demo run. Click ▶ Run to start a new one.", icon="ℹ️")
        else:
            st.caption("Start the Docker stack (`docker compose up -d`), then click ▶ Run Mixed Workload.")

    if not running and not os.path.exists(LIVE_CSV):
        return

    # ── Live metrics ─────────────────────────────────────────────────────────
    rows = read_csv_rows(LIVE_CSV)
    health = poll_health()

    col_card, col_kpis = st.columns([1, 3], gap="medium")

    with col_card:
        if health:
            strategy = health.get("strategy", "unknown")
            # detect and record strategy switches
            last = st.session_state.get("last_strategy")
            if last and last != strategy:
                elapsed_at_switch = time.time() - st.session_state.get("demo_start", time.time())
                st.session_state["switch_events"].append(
                    {"strategy": strategy, "t": elapsed_at_switch}
                )
            st.session_state["last_strategy"] = strategy

            wr = current_write_rate(rows)
            _strategy_card(strategy, wr)
        else:
            st.error("Node A unreachable", icon="🔴")

    with col_kpis:
        stats = cumulative_stats(rows)
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Requests", f"{stats['total']:,}")
        k2.metric("Reads", f"{stats['reads']:,}")
        k3.metric("Writes", f"{stats['writes']:,}")
        srr_delta = None
        if stats["srr"] > 0:
            srr_delta = f"target < 10%"
        k4.metric("Live SRR", f"{stats['srr']:.1f}%", delta=srr_delta, delta_color="inverse")

    # ── SRR chart ─────────────────────────────────────────────────────────────
    srr_data = compute_srr_timeline(rows, bucket_s=5.0)
    if srr_data:
        df_srr = pd.DataFrame(srr_data)
        fig = go.Figure()

        for strat in ["ttl", "batched", "eager", "unknown"]:
            sub = df_srr[df_srr["strategy"] == strat]
            if sub.empty:
                continue
            fig.add_trace(go.Scatter(
                x=sub["time_s"],
                y=sub["srr"],
                mode="lines+markers",
                name=STRATEGY_LABELS.get(strat, strat.upper()),
                line=dict(color=STRATEGY_COLORS.get(strat, "#999"), width=3),
                marker=dict(size=5),
                hovertemplate="t=%{x:.0f}s  SRR=%{y:.1f}%<extra></extra>",
            ))

        # Mark strategy switches as vertical lines
        for ev in st.session_state.get("switch_events", []):
            fig.add_vline(
                x=ev["t"],
                line_dash="dash",
                line_color=STRATEGY_COLORS.get(ev["strategy"], "#aaa"),
                annotation_text=STRATEGY_LABELS.get(ev["strategy"], ""),
                annotation_font_size=10,
                annotation_font_color=STRATEGY_COLORS.get(ev["strategy"], "#aaa"),
            )

        fig.update_layout(
            title="Stale Read Ratio (5-second buckets)",
            xaxis_title="Time (seconds)",
            yaxis_title="SRR (%)",
            yaxis_range=[0, 55],
            height=290,
            margin=dict(l=0, r=0, t=44, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Latency chart ─────────────────────────────────────────────────────────
    lat_data = compute_latency_timeline(rows, bucket_s=5.0)
    if lat_data:
        df_lat = pd.DataFrame(lat_data)
        fig_lat = px.line(
            df_lat,
            x="time_s",
            y="p50_ms",
            title="Read Latency P50 (5-second buckets)",
            labels={"time_s": "Time (seconds)", "p50_ms": "P50 (ms)"},
        )
        fig_lat.update_traces(line_color="#AB47BC", line_width=2.5)
        fig_lat.update_layout(
            height=230,
            margin=dict(l=0, r=0, t=44, b=0),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_lat, use_container_width=True)

    # ── Auto-refresh while running ────────────────────────────────────────────
    if running:
        time.sleep(2)
        st.rerun()


# ── Tab 2: Results Analysis ───────────────────────────────────────────────────

def render_analysis_tab() -> None:
    # Hero callout
    col_hero, col_explain = st.columns([1, 2], gap="large")
    with col_hero:
        st.markdown("""
<div class="hero-box">
  <div class="hero-number">71%</div>
  <div class="hero-subtitle">reduction in stale reads</div>
  <div class="hero-detail">Adaptive vs. static TTL · Mixed workload</div>
</div>
""", unsafe_allow_html=True)

    with col_explain:
        st.markdown("### Baseline vs Adaptive")
        st.markdown("""
With **static TTL**, stale read ratio balloons at high write rates:
- 5 w/s → 10.2% SRR *(acceptable)*
- 25 w/s → 30.5% SRR *(degraded)*
- 60 w/s → 38.6% SRR *(poor)*

**Average: 26.4% SRR**

With **adaptive switching** across a mixed 5→60→25→5 w/s workload:

**7.6% SRR — 71% improvement**

The controller switches to EAGER at high write rates (near-zero stale reads) and falls back to TTL at low rates (minimal overhead).
""")

    st.divider()

    summary_path = RESULTS / "summary.csv"
    phase2_path = RESULTS / "phase2_adaptive_mixed.csv"

    if not summary_path.exists():
        st.warning("No summary.csv found in results/. Run an experiment first.")
        return

    summary_df = pd.read_csv(summary_path)
    baseline = summary_df[summary_df["experiment_name"].str.contains("phase1", na=False)].copy()
    adaptive = summary_df[summary_df["experiment_name"].str.contains("phase2", na=False)].copy()

    # ── SRR comparison + latency side by side ─────────────────────────────────
    col1, col2 = st.columns(2, gap="medium")

    with col1:
        if not baseline.empty and not adaptive.empty:
            baseline["label"] = "TTL " + baseline["write_rate"].astype(str) + " w/s"
            adaptive_label = adaptive.copy()
            adaptive_label["label"] = "Adaptive (mixed)"
            compare = pd.concat([baseline[["label", "srr_pct"]], adaptive_label[["label", "srr_pct"]]])
            compare["color"] = compare["label"].apply(
                lambda l: "#00C853" if "Adaptive" in l else "#EF5350"
            )

            fig_srr = px.bar(
                compare,
                x="label",
                y="srr_pct",
                color="label",
                color_discrete_map={l: c for l, c in zip(compare["label"], compare["color"])},
                title="Stale Read Ratio: TTL Baseline vs Adaptive",
                labels={"srr_pct": "SRR (%)", "label": ""},
                text_auto=".1f",
            )
            fig_srr.update_layout(
                showlegend=False,
                height=370,
                yaxis_range=[0, 48],
                margin=dict(l=0, r=0, t=44, b=0),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )
            fig_srr.update_traces(textfont_size=12, textposition="outside")
            st.plotly_chart(fig_srr, use_container_width=True)

    with col2:
        if not baseline.empty:
            baseline["label"] = "TTL " + baseline["write_rate"].astype(str) + " w/s"
            lat_melt = baseline[["label", "read_p50_ms", "read_p95_ms"]].melt(
                id_vars="label", var_name="Percentile", value_name="Latency (ms)"
            )
            lat_melt["Percentile"] = lat_melt["Percentile"].map(
                {"read_p50_ms": "P50", "read_p95_ms": "P95"}
            )
            fig_lat = px.bar(
                lat_melt,
                x="label",
                y="Latency (ms)",
                color="Percentile",
                barmode="group",
                title="Read Latency Remains Stable Across Write Rates",
                labels={"label": ""},
                color_discrete_map={"P50": "#42A5F5", "P95": "#1565C0"},
            )
            fig_lat.update_layout(
                height=370,
                margin=dict(l=0, r=0, t=44, b=0),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_lat, use_container_width=True)

    # ── Phase 2 timeline ──────────────────────────────────────────────────────
    if phase2_path.exists():
        st.subheader("Phase 2: Adaptive System — SRR Timeline (120s)")
        df2 = pd.read_csv(phase2_path)
        df2_reads = df2[df2["operation"] == "read"].copy()
        df2_reads["time_s"] = df2_reads["timestamp"] - df2_reads["timestamp"].min()
        df2_reads["bucket"] = (df2_reads["time_s"] // 5) * 5

        bucket_stats = (
            df2_reads.groupby(["bucket", "strategy"])
            .agg(total=("is_stale", "count"), stale=("is_stale", "sum"))
            .reset_index()
        )
        bucket_stats["srr"] = bucket_stats["stale"] / bucket_stats["total"] * 100

        fig_timeline = go.Figure()
        for strat in ["ttl", "batched", "eager"]:
            sub = bucket_stats[bucket_stats["strategy"] == strat]
            if sub.empty:
                continue
            fig_timeline.add_trace(go.Scatter(
                x=sub["bucket"],
                y=sub["srr"],
                mode="lines+markers",
                name=STRATEGY_LABELS[strat],
                line=dict(color=STRATEGY_COLORS[strat], width=3),
                marker=dict(size=5),
                hovertemplate="t=%{x:.0f}s  SRR=%{y:.1f}%<extra></extra>",
            ))

        for t, label in [(30, "→ 60 w/s"), (60, "→ 25 w/s"), (90, "→ 5 w/s")]:
            fig_timeline.add_vline(
                x=t, line_dash="dot", line_color="#888",
                annotation_text=label, annotation_font_size=10, annotation_font_color="#888",
            )

        fig_timeline.update_layout(
            xaxis_title="Time (seconds)",
            yaxis_title="SRR (%)",
            yaxis_range=[0, 55],
            height=330,
            margin=dict(l=0, r=0, t=10, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_timeline, use_container_width=True)
        st.caption("Write rate phases: 5 → 60 → 25 → 5 writes/s (30 seconds each). "
                   "Strategy switches automatically — SRR tracks the optimal strategy in each phase.")


# ── Tab 3: How It Works ───────────────────────────────────────────────────────

def render_explainer_tab() -> None:
    col_left, col_right = st.columns([3, 2], gap="large")

    with col_left:
        st.subheader("Strategy Decision Zones")
        st.markdown(
            "Drag the sliders to see how threshold changes affect which strategy is active at a given write rate."
        )

        high = st.slider("HIGH_THRESHOLD — switch to Eager above this", 20, 100, 50, key="high_thresh")
        low = st.slider("LOW_THRESHOLD  — switch to TTL below this", 1, min(40, high - 1), 10, key="low_thresh")

        x = list(range(0, 101))
        labels = []
        for rate in x:
            if rate > high:
                labels.append("Eager")
            elif rate < low:
                labels.append("TTL")
            else:
                labels.append("Batched")

        fig_zone = go.Figure()
        for strat, label in [("ttl", "TTL"), ("batched", "Batched"), ("eager", "Eager")]:
            x_vals = [v for v, l in zip(x, labels) if l == label]
            if x_vals:
                fig_zone.add_trace(go.Bar(
                    x=x_vals,
                    y=[1.0] * len(x_vals),
                    name=label,
                    marker_color=STRATEGY_COLORS[strat],
                    hovertemplate=f"{label}<extra></extra>",
                    showlegend=True,
                ))

        fig_zone.add_vline(x=low, line_dash="dash", line_color="white",
                           annotation_text=f"LOW={low}", annotation_font_color="white", annotation_font_size=11)
        fig_zone.add_vline(x=high, line_dash="dash", line_color="white",
                           annotation_text=f"HIGH={high}", annotation_font_color="white", annotation_font_size=11)

        fig_zone.update_layout(
            barmode="stack",
            xaxis_title="Write Rate (writes/second)",
            yaxis_visible=False,
            height=160,
            margin=dict(l=0, r=0, t=8, b=30),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_zone, use_container_width=True)

        st.markdown("---")
        st.subheader("Strategy Characteristics")
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.markdown(
                f"""<div style="background:{STRATEGY_COLORS['ttl']};padding:14px;border-radius:10px;color:white">
                <b>⏱ TTL</b><br>
                Cache expires after N seconds. No Pub/Sub overhead. Accepts brief staleness.
                Best for low write rates.
                </div>""",
                unsafe_allow_html=True,
            )
        with col_b:
            st.markdown(
                f"""<div style="background:{STRATEGY_COLORS['batched']};padding:14px;border-radius:10px;color:white">
                <b>📦 BATCHED</b><br>
                Buffers invalidation messages, flushes every 2.5s. Balances consistency with throughput.
                Best for medium rates.
                </div>""",
                unsafe_allow_html=True,
            )
        with col_c:
            st.markdown(
                f"""<div style="background:{STRATEGY_COLORS['eager']};padding:14px;border-radius:10px;color:white">
                <b>⚡ EAGER</b><br>
                Invalidates cache immediately per write. Near-zero stale reads. Higher Pub/Sub load.
                Best for high rates.
                </div>""",
                unsafe_allow_html=True,
            )

    with col_right:
        st.subheader("System Architecture")
        st.markdown("""
```
    ┌─────────────────────┐
    │  Adaptive Controller │
    │  (node_a, 3s poll)  │
    │                     │
    │  write_rate > 50?   │
    │    → EAGER          │
    │  write_rate < 10?   │
    │    → TTL            │
    │  else → BATCHED     │
    └──────────┬──────────┘
               │ Redis Pub/Sub
               │ strategy_update
       ┌───────┼───────┐
       │       │       │
    node_a  node_b  node_c
    Redis   Redis   Redis
    cache   cache   cache
       └───────┼───────┘
               │
         SQLite DB
         (shared)
```
""")

        st.markdown("""
**How a strategy switch propagates:**
1. Controller detects write rate crossing threshold
2. Publishes new strategy to `strategy_update` Redis channel
3. All 3 nodes receive it via background subscriber thread
4. Nodes switch within **1–3 seconds**

**Stale read detection:**
```
read_value ≠ /db_read value
     → is_stale = 1
```
Ground truth from DB-direct endpoint, checked per request.
""")

        st.markdown("**Key config (docker-compose.yml):**")
        st.code(
            "CACHE_TTL=10          # TTL seconds\n"
            "HIGH_THRESHOLD=50     # → Eager above\n"
            "LOW_THRESHOLD=10      # → TTL below\n"
            "CONTROLLER_INTERVAL=3 # check every Ns\n"
            "BATCH_INTERVAL=2.5    # batched flush Ns",
            language="yaml",
        )


# ── Main layout ───────────────────────────────────────────────────────────────

st.title("⚡ Adaptive Cache Invalidation")
st.caption(
    "A distributed cache system that auto-selects its invalidation strategy based on write rate"
    " · **71% fewer stale reads** vs. static TTL"
)

tab_live, tab_analysis, tab_explainer = st.tabs(
    ["⚡ Live Demo", "📊 Results Analysis", "🔧 How It Works"]
)

with tab_live:
    render_live_tab()

with tab_analysis:
    render_analysis_tab()

with tab_explainer:
    render_explainer_tab()
