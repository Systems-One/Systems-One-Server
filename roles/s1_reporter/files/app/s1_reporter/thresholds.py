"""Per-device alert thresholds from dbo.alert_thresholds with a customer-config fallback."""

_SQL = ("SELECT customer, machine_name, location, metric, warn_value, bad_value "
        "FROM dbo.alert_thresholds")


def _f(v):
    return float(v) if v is not None else None


def load_thresholds(query) -> dict:
    return {
        (r["customer"], r["machine_name"], r["location"], r["metric"]): (_f(r["warn_value"]), _f(r["bad_value"]))
        for r in query(_SQL, None)
    }


def lookup(thresholds, cfg, customer, machine_name, location, metric):
    """Device row, then customer-wide row, then the customer_config fallback columns."""
    for key in ((customer, machine_name, location, metric), (customer, None, None, metric)):
        val = thresholds.get(key)
        if val and val[0] is not None:
            return val
    if metric == "good_read_pct":
        return cfg.good_read_warn_pct, cfg.good_read_bad_pct
    if metric == "no_dim_pct":
        return cfg.no_dim_warn_pct, cfg.no_dim_bad_pct
    raise KeyError(metric)
