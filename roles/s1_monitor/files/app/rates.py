"""Pure rate maths. A bucket is a dict; nothing here touches the database."""
PARTS = ("good_read", "no_read", "no_dimension", "no_weight", "hand_scanned", "not_sent", "more_than_1_item")

RATE_DEFS = [
    {"key": "good_read_pct", "name": "Good read", "part": "good_read", "cap": "always", "direction": "low"},
    {"key": "no_dim_pct", "name": "No dimension", "part": "no_dimension", "cap": "has_dimension", "direction": "high"},
    {"key": "hand_scan_pct", "name": "Hand scanned", "part": "hand_scanned", "cap": "has_hand_scan", "direction": "high"},
    {"key": "no_weight_pct", "name": "No weight", "part": "no_weight", "cap": "has_weight", "direction": "high"},
    {"key": "not_sent_pct", "name": "Not sent", "part": "not_sent", "cap": "always", "direction": "high"},
]
ALL_RATES = RATE_DEFS + [
    {"key": "no_read_pct", "name": "No read", "part": "no_read", "cap": "always", "direction": "high"},
    {"key": "multi_item_pct", "name": "More than 1 item", "part": "more_than_1_item", "cap": "has_dimension", "direction": "high"},
]


def rate(part, items):
    return round(100.0 * float(part or 0) / float(items), 2) if items and items > 0 else None


def _iso(d):
    return d.replace(microsecond=0).isoformat() + "Z"


def fill_buckets(rows, starts, min_items):
    by = {r["bucket_utc"]: r for r in rows}
    out = []
    for s in starts:
        r = by.get(s)
        if r is None:
            b = {"ts": _iso(s), "nodata": True, "items": 0, "rows": 0, "low_volume": True}
            b.update({p: 0 for p in PARTS})
            b["rates"] = {d["key"]: None for d in ALL_RATES}
        else:
            items = int(r.get("items") or 0)
            b = {"ts": _iso(s), "nodata": False, "items": items, "rows": int(r.get("rows") or 0), "low_volume": items < min_items}
            b.update({p: int(r.get(p) or 0) for p in PARTS})
            b["rates"] = {d["key"]: rate(b[d["part"]], items) for d in ALL_RATES}
        out.append(b)
    return out


def _stats(vals, nd=1):
    vals = [v for v in vals if v is not None]
    if not vals:
        return {"max": None, "min": None, "avg": None}
    return {"max": max(vals), "min": min(vals), "avg": round(sum(vals) / len(vals), nd)}


def summary(buckets, per_hour_values, per_unit_label):
    with_data = [b for b in buckets if not b["nodata"]]
    good = [b["rates"]["good_read_pct"] for b in with_data if not b["low_volume"] and b["items"] > 0]
    per = _stats(per_hour_values)
    per["label"] = per_unit_label
    return {"items": _stats([b["items"] for b in with_data]), "good_read_pct": _stats(good), "per_unit": per}


def totals(buckets):
    t = {"items": 0}
    t.update({p: 0 for p in PARTS})
    for b in buckets:
        if b["nodata"]:
            continue
        t["items"] += b["items"]
        for p in PARTS:
            t[p] += b[p]
    return t


def partition(t, has_hand_scan):
    good, noread = int(t.get("good_read") or 0), int(t.get("no_read") or 0)
    if not has_hand_scan:
        return [{"name": "Good read", "value": good}, {"name": "No read", "value": noread}]
    hand = min(int(t.get("hand_scanned") or 0), noread)
    return [{"name": "Good read", "value": good},
            {"name": "No read, recovered by hand scan", "value": hand},
            {"name": "No read, not recovered", "value": noread - hand}]


def applicable_rates(cfg):
    return [d for d in RATE_DEFS if d["cap"] == "always" or bool(cfg.get(d["cap"]))]
