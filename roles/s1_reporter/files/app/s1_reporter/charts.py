"""Chart rendering. Pure helpers at the top are unit-tested; matplotlib is imported lazily below."""
import io

PALETTE = ["#2563eb", "#7c3aed", "#059669", "#d97706", "#db2777",
           "#0891b2", "#16a34a", "#dc2626", "#9333ea", "#0284c7"]
CHART_STYLE = {
    "figure.facecolor": "none", "axes.facecolor": "none", "axes.edgecolor": "#d1d5db",
    "axes.labelcolor": "#374151", "xtick.color": "#6b7280", "ytick.color": "#6b7280",
    "text.color": "#1f2937", "grid.color": "#e5e7eb", "grid.linestyle": "--", "grid.alpha": 0.8,
}


# ── Pure helpers ───────────────────────────────────────────────────────────────
def goodread_axis_bounds(points, warn_lines):
    values = [float(v) for v in list(points) + list(warn_lines) if v is not None]
    if not values:
        return 85.0, 101.0
    return max(min(values) - 5.0, 0.0), 101.0


def series_by_device(rows):
    out = {}
    for r in rows:
        if (r.get("daily_items") or 0) > 0 and r.get("good_read_pct") is not None:
            out.setdefault((r["machine_name"], r["location"]), []).append((r["report_date"], float(r["good_read_pct"])))
    for pts in out.values():
        pts.sort()
    return out


def devices_with_data(rows):
    seen = []
    for r in rows:
        k = (r["machine_name"], r["location"])
        if (r.get("daily_items") or 0) > 0 and k not in seen:
            seen.append(k)
    return sorted(seen)


# ── Rendering ──────────────────────────────────────────────────────────────────
def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _fig_to_png(plt, fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=130, transparent=True)
    plt.close(fig)
    return buf.getvalue()


def chart_daily_volume(rows, title):
    plt = _plt()
    import numpy as np
    with plt.rc_context(CHART_STYLE):
        devices = devices_with_data(rows)
        dates = sorted({r["report_date"] for r in rows})
        fig, ax = plt.subplots(figsize=(12, 5))
        x = np.arange(len(dates))
        w = min(0.8 / max(len(devices), 1), 0.15)
        for i, (m, loc) in enumerate(devices):
            vals = [next((r["daily_items"] for r in rows
                          if r["machine_name"] == m and r["location"] == loc and r["report_date"] == d), 0)
                    for d in dates]
            ax.bar(x + i * w - (len(devices) * w / 2) + w / 2, vals, w * 0.85,
                   label=f"{m}@{loc}", color=PALETTE[i % len(PALETTE)], alpha=0.9)
        ax.set_xticks(x)
        ax.set_xticklabels([str(d) for d in dates], rotation=25, ha="right", fontsize=9)
        ax.set_ylabel("Items Scanned", fontsize=10)
        ax.set_title(title, fontsize=13, pad=12, fontweight="bold")
        if devices:
            ax.legend(fontsize=8, ncol=3, loc="upper left", framealpha=0.3)
        ax.grid(axis="y", alpha=0.4)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v):,}"))
        fig.tight_layout()
        return _fig_to_png(plt, fig)


def chart_goodread_trend(rows, title, warn_by_device):
    plt = _plt()
    with plt.rc_context(CHART_STYLE):
        series = series_by_device(rows)
        fig, ax = plt.subplots(figsize=(13, 6))
        all_points = []
        for i, (key, pts) in enumerate(sorted(series.items())):
            xs, ys = zip(*pts)
            all_points.extend(ys)
            color = PALETTE[i % len(PALETTE)]
            ax.plot(xs, ys, marker="o", markersize=5, label=f"{key[0]}@{key[1]}", color=color, linewidth=2, zorder=3)
            warn = warn_by_device.get(key)
            for x, y in pts:
                if warn is not None and y < warn:
                    ax.annotate(f"{y:.1f}%", (x, y), textcoords="offset points", xytext=(0, -14),
                                fontsize=7.5, ha="center", color=color, fontweight="bold")
        lo, hi = goodread_axis_bounds(all_points, [v for v in warn_by_device.values() if v is not None])
        ax.set_ylim(lo, hi)
        ax.set_ylabel("Good Read %", fontsize=10)
        ax.set_title(title, fontsize=13, pad=12, fontweight="bold")
        if series:
            ax.legend(fontsize=8, ncol=3, loc="lower left", framealpha=0.3)
        ax.grid(True, alpha=0.4)
        plt.xticks(rotation=25, ha="right", fontsize=9)
        fig.tight_layout()
        return _fig_to_png(plt, fig)


def chart_hourly_volume(rows, title):
    plt = _plt()
    with plt.rc_context(CHART_STYLE):
        fig, ax = plt.subplots(figsize=(12, 4))
        hours = [r["hour_of_day"] for r in rows]
        items = [r["total_items"] for r in rows]
        bars = ax.bar(hours, items, color="#38bdf8", alpha=0.85, width=0.7)
        if items:
            peak = max(items)
            for bar, val in zip(bars, items):
                if val == peak:
                    bar.set_color("#a78bfa")
        ax.set_xlabel("Hour of Day (24h, local)", fontsize=10)
        ax.set_ylabel("Total Items", fontsize=10)
        ax.set_title(title, fontsize=13, pad=12, fontweight="bold")
        ax.set_xticks(range(0, 24))
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v):,}"))
        ax.grid(axis="y", alpha=0.4)
        fig.tight_layout()
        return _fig_to_png(plt, fig)
