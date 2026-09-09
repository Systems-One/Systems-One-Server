"""Needs-attention rules. Mirrors s1_reporter's anomaly rules over today so far."""
import thresholds as th
from rates import rate, RATE_DEFS

_RANK = {"bad": 0, "warn": 1}


def _label(d):
    return f"{d['machine_name']} @ {d['location']}"


def _push(out, sev, d, rule, value, limit=None, since=None, over=0.0):
    out.append({
        "severity": sev,
        "device_id": d["id"],
        "label": _label(d),
        "customer": d["customer"],
        "rule": rule,
        "value": value,
        "limit": limit,
        "since": since.replace(microsecond=0).isoformat() + "Z" if since else None,
        "over": float(over)
    })


def _ago(now, then):
    m = max(0, int((now - then).total_seconds() // 60))
    return f"{m} min" if m < 60 else (f"{m // 60} h {m % 60} min" if m < 2880 else f"{m // 1440} d")


def attention(devices, cfg_by_customer, threshold_rows, recent_packets_by_device, now_utc, s):
    out = []
    for d in devices:
        if not d.get("reporting_enabled", True):
            continue
        if d.get("muted_until") and d["muted_until"] > now_utc:
            continue
        cfg = cfg_by_customer.get(d["customer"], th.DEFAULT_CFG)
        st = d.get("state")
        if st in ("offline", "never"):
            since = d.get("last_seen")
            _push(out, "bad", d, "No data", "silent for " + (_ago(now_utc, since) if since else "ever"), since=since,
                  over=(now_utc - since).total_seconds() / 60 if since else 1e9)
        if st == "stale":
            continue
        pk = (recent_packets_by_device.get(d["id"]) or [])[:3]
        if len(pk) == 3 and all((p.get("items") or 0) > 0 and (p.get("not_sent") or 0) > 0 for p in pk):
            _push(out, "bad", d, "Upload stuck", f"{sum(int(p['not_sent']) for p in pk)} items not sent in last 3 packets", over=999)
        items = int(d.get("items") or 0)
        if items >= s.min_items_day:
            for r in RATE_DEFS:
                if r["key"] == "not_sent_pct" or not (r["cap"] == "always" or cfg.get(r["cap"])):
                    continue
                t = th.lookup(threshold_rows, cfg, d["customer"], d["machine_name"], d["location"], r["key"])
                v = rate(d.get(r["part"]), items)
                if v is None or t["warn"] is None:
                    continue
                low = r["direction"] == "low"
                sev = None
                if t["bad"] is not None and ((low and v < t["bad"]) or (not low and v > t["bad"])):
                    sev = "bad"
                elif (low and v < t["warn"]) or (not low and v > t["warn"]):
                    sev = "warn"
                if sev:
                    lim = t["bad"] if sev == "bad" else t["warn"]
                    _push(out, sev, d, f"{r['name']} today", f"{v:.1f}%", ("below " if low else "above ") + f"{lim:.1f}%", over=abs(v - lim))
        cu = d.get("c_usage")
        if cu is not None:
            bad_pct = cfg.get("storage_bad_pct", th.DEFAULT_CFG["storage_bad_pct"])
            warn_pct = cfg.get("storage_warn_pct", th.DEFAULT_CFG["storage_warn_pct"])
            if cu > bad_pct:
                _push(out, "bad", d, "C: drive", f"{cu:.1f}%", f"above {bad_pct:.0f}%", over=cu - bad_pct)
            elif cu > warn_pct:
                _push(out, "warn", d, "C: drive", f"{cu:.1f}%", f"above {warn_pct:.0f}%", over=cu - warn_pct)
        if d.get("application_running") is False:
            _push(out, "bad", d, "App stopped", "since " + (d["stopped_since"].strftime("%a %d %b %H:%M") if d.get("stopped_since") else "unknown"),
                  since=d.get("stopped_since"), over=500)
    return sorted(out, key=lambda a: (_RANK[a["severity"]], -a["over"], a["label"]))
