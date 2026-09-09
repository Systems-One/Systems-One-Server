"""Report SQL. All windows are inclusive local dates converted to UTC bounds; all values parameterised."""
from .timewin import utc_bounds

_ENABLED = "d.reporting_enabled = 1"


def daily_trend(query, customer, start_date, end_date, offset_hours):
    start_utc, end_utc = utc_bounds(start_date, end_date, offset_hours)
    return query(f"""
        SELECT d.machine_name, d.location, d.customer,
               CAST(DATEADD(hour, %s, ds.ts_datetime) AS DATE) AS report_date,
               SUM(ds.total_items)   AS daily_items,
               SUM(ds.good_read)     AS daily_good,
               SUM(ds.no_read)       AS daily_no_read,
               SUM(ds.no_dimension)  AS daily_no_dim,
               SUM(ds.hand_scanned)  AS daily_hand_scanned,
               SUM(ds.no_weight)     AS daily_no_weight,
               CAST(SUM(ds.good_read)*100.0/NULLIF(SUM(ds.total_items),0) AS DECIMAL(5,1)) AS good_read_pct
        FROM dbo.devices d
        JOIN dbo.device_statistics ds ON ds.device_id = d.id
        WHERE {_ENABLED} AND d.customer = %s
          AND ds.ts_datetime >= %s AND ds.ts_datetime < %s
        GROUP BY d.machine_name, d.location, d.customer, CAST(DATEADD(hour, %s, ds.ts_datetime) AS DATE)
        ORDER BY d.location, d.machine_name, report_date
    """, (offset_hours, customer, start_utc, end_utc, offset_hours))


def device_summary(query, customer, start_date, end_date, offset_hours):
    start_utc, end_utc = utc_bounds(start_date, end_date, offset_hours)
    return query(f"""
        SELECT d.machine_name, d.location, d.customer,
               SUM(ds.total_items)  AS total_items,
               SUM(ds.good_read)    AS good_reads,
               SUM(ds.no_read)      AS no_reads,
               SUM(ds.no_dimension) AS no_dimensions,
               SUM(ds.not_sent)     AS not_sent,
               SUM(ds.hand_scanned) AS hand_scanned,
               SUM(ds.no_weight)    AS no_weight,
               CAST(SUM(ds.good_read)*100.0/NULLIF(SUM(ds.total_items),0) AS DECIMAL(5,2)) AS good_read_pct
        FROM dbo.devices d
        JOIN dbo.device_statistics ds ON ds.device_id = d.id
        WHERE {_ENABLED} AND d.customer = %s
          AND ds.ts_datetime >= %s AND ds.ts_datetime < %s
        GROUP BY d.machine_name, d.location, d.customer
        ORDER BY total_items DESC
    """, (customer, start_utc, end_utc))


def hourly_pattern(query, customer, start_date, end_date, offset_hours):
    start_utc, end_utc = utc_bounds(start_date, end_date, offset_hours)
    return query(f"""
        SELECT DATEPART(HOUR, DATEADD(hour, %s, ds.ts_datetime)) AS hour_of_day,
               SUM(ds.total_items) AS total_items
        FROM dbo.devices d
        JOIN dbo.device_statistics ds ON ds.device_id = d.id
        WHERE {_ENABLED} AND d.customer = %s AND ds.total_items > 0
          AND ds.ts_datetime >= %s AND ds.ts_datetime < %s
        GROUP BY DATEPART(HOUR, DATEADD(hour, %s, ds.ts_datetime))
        ORDER BY hour_of_day
    """, (offset_hours, customer, start_utc, end_utc, offset_hours))


def storage(query, customer):
    return query(f"""
        SELECT d.machine_name, d.location, dss.drive, dss.total_gb, dss.used_gb, dss.usage_percent
        FROM dbo.devices d
        JOIN dbo.device_storage_status dss ON dss.device_id = d.id
        WHERE {_ENABLED} AND d.customer = %s AND dss.drive = 'C:'
        ORDER BY dss.usage_percent DESC
    """, (customer,))


def customers_with_reports(query):
    return [r["customer"] for r in query(
        "SELECT customer FROM dbo.customer_config WHERE reports_enabled = 1 ORDER BY customer", None)]
