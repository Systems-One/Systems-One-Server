import thresholds as th

ROWS = [
  {"customer": "DCB", "machine_name": "DIM1", "location": "DUR", "metric": "good_read_pct", "direction": "low", "warn_value": 55.8, "bad_value": 21.7, "baseline_mean": 65.7, "baseline_stddev": 27.6, "baseline_p10": 25.6, "baseline_p90": 98.1, "baseline_samples": 163},
  {"customer": "DCB", "machine_name": None, "location": None, "metric": "no_dim_pct", "direction": "high", "warn_value": 4.0, "bad_value": 8.0, "baseline_mean": None, "baseline_stddev": None, "baseline_p10": None, "baseline_p90": None, "baseline_samples": None},
]
CFG = {"good_read_warn_pct": 95, "good_read_bad_pct": 90, "no_dim_warn_pct": 5, "no_dim_bad_pct": 10, "hand_scan_warn_pct": 15, "no_weight_warn_pct": 5}

def test_device_row_wins():
    r = th.lookup(ROWS, CFG, "DCB", "DIM1", "DUR", "good_read_pct")
    assert r["warn"] == 55.8 and r["bad"] == 21.7 and r["source"] == "device baseline" and r["baseline_samples"] == 163

def test_customer_row_then_config():
    assert th.lookup(ROWS, CFG, "DCB", "DIM1", "DUR", "no_dim_pct")["source"] == "customer baseline"
    r = th.lookup(ROWS, CFG, "DCB", "DIM1", "CPT", "good_read_pct")
    assert (r["warn"], r["bad"], r["source"], r["direction"]) == (95, 90, "customer default", "low")

def test_hand_scan_has_no_bad():
    r = th.lookup(ROWS, CFG, "BEX", "DIM1", "CPT", "hand_scan_pct")
    assert r["warn"] == 15 and r["bad"] is None and r["direction"] == "high"

def test_all_for_device_keys():
    assert set(th.all_for_device(ROWS, CFG, "DCB", "DIM1", "DUR")) == {"good_read_pct", "no_dim_pct", "hand_scan_pct", "no_weight_pct"}
