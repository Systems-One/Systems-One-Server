"""Threshold lookup in the reporter's order: device row, customer-wide row, customer_config."""
DEFAULT_CFG = {"has_dimension": True, "has_weight": False, "has_hand_scan": False,
               "hand_scan_warn_pct": 15.0, "no_weight_warn_pct": 5.0, "storage_warn_pct": 80.0, "storage_bad_pct": 90.0,
               "good_read_warn_pct": 95.0, "good_read_bad_pct": 90.0, "no_dim_warn_pct": 5.0, "no_dim_bad_pct": 10.0}
_CFG_FALLBACK = {
    "good_read_pct": ("good_read_warn_pct", "good_read_bad_pct", "low"),
    "no_dim_pct": ("no_dim_warn_pct", "no_dim_bad_pct", "high"),
    "hand_scan_pct": ("hand_scan_warn_pct", None, "high"),
    "no_weight_pct": ("no_weight_warn_pct", None, "high"),
}
METRICS = tuple(_CFG_FALLBACK)


def _from_row(r, source):
    return {"warn": r.get("warn_value"), "bad": r.get("bad_value"), "direction": r.get("direction") or "low",
            "baseline_mean": r.get("baseline_mean"), "baseline_stddev": r.get("baseline_stddev"),
            "baseline_p10": r.get("baseline_p10"), "baseline_p90": r.get("baseline_p90"),
            "baseline_samples": r.get("baseline_samples"), "source": source}


def lookup(rows, cfg, customer, machine, location, metric):
    for r in rows:
        if r["customer"] == customer and r["metric"] == metric and r.get("machine_name") == machine and r.get("location") == location:
            return _from_row(r, "device baseline")
    for r in rows:
        if r["customer"] == customer and r["metric"] == metric and r.get("machine_name") is None and r.get("location") is None:
            return _from_row(r, "customer baseline")
    if metric in _CFG_FALLBACK:
        wk, bk, d = _CFG_FALLBACK[metric]
        cfg = cfg or DEFAULT_CFG
        return {"warn": cfg.get(wk, DEFAULT_CFG[wk]), "bad": cfg.get(bk, DEFAULT_CFG[bk]) if bk else None, "direction": d,
                "baseline_mean": None, "baseline_stddev": None, "baseline_p10": None, "baseline_p90": None,
                "baseline_samples": None, "source": "customer default"}
    return {"warn": None, "bad": None, "direction": "high", "baseline_mean": None, "baseline_stddev": None,
            "baseline_p10": None, "baseline_p90": None, "baseline_samples": None, "source": "none"}


def all_for_device(rows, cfg, customer, machine, location):
    return {m: lookup(rows, cfg, customer, machine, location, m) for m in METRICS}
