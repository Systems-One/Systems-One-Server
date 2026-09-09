"""Job orchestration. Everything with side effects (DB, Teams, chart rendering) is injected."""
from datetime import datetime, timezone

from . import (anomalies, cards, chart_store, charts, customers, liveness, queries,
               status_sync, teams, thresholds, timewin, upload)
from .state import AlertState


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _dev_key(d):
    return f"{d['machine_name']}@{d['location']}"


class Runner:
    def __init__(self, settings, db, now_utc=None, post=None, render=None):
        self.s = settings
        self.db = db
        self.now = now_utc or _utcnow()
        self.post = post or teams.post_to_teams
        self.render = render or {
            "volume": charts.chart_daily_volume,
            "goodread": charts.chart_goodread_trend,
            "hourly": charts.chart_hourly_volume,
        }

    # ── shared ────────────────────────────────────────────────────────────────
    def _states(self):
        devices = liveness.fetch_devices(self.db.query)
        return liveness.classify(devices, self.now, self.s.offline_threshold_minutes, self.s.stale_days)

    def _send(self, card) -> bool:
        return bool(self.post(self.s.teams_webhook_url, card))

    # ── sync-status ───────────────────────────────────────────────────────────
    def sync_status(self):
        online, offline = status_sync.sync(self.db.executemany, self._states())
        print(f"device_status synced: {online} online, {offline} offline")
        return online, offline

    # ── check-alerts ──────────────────────────────────────────────────────────
    def check_alerts(self) -> bool:
        states = self._states()
        ok = self._offline_alerts(states)
        ok &= self._upload_alerts()
        return ok

    def _offline_alerts(self, states) -> bool:
        current = {}
        for st in liveness.alertable_offline(states, self.now):
            current[liveness.key(st)] = {
                "machine_name": st.device.machine_name, "location": st.device.location,
                "customer": st.device.customer, "last_seen": st.last_seen, "minutes_ago": st.minutes_ago,
            }
        state = AlertState(self.s.offline_state_file)
        d = state.diff(current, self.now)
        # A device that aged past STALE_DAYS (or was disabled/muted) leaves the state
        # silently: it did not recover, it stopped being alertable.
        silent = {liveness.key(st) for st in states if st.state == "stale"}
        silent |= {liveness.key(st) for st in states
                   if st.device.muted_until and st.device.muted_until > self.now}
        enabled = {liveness.key(st) for st in states}
        recovered = [x for x in d.recovered if _dev_key(x) not in silent and _dev_key(x) in enabled]
        dropped = [_dev_key(x) for x in d.recovered if x not in recovered]
        if dropped:
            print(f"left offline state without recovery (stale/muted/disabled): {dropped}")
        sent = True
        if d.new:
            sent &= self._send(cards.build_offline_alert_card(d.new))
            print(f"offline alert: {[_dev_key(x) for x in d.new]}")
        if recovered:
            sent &= self._send(cards.build_recovery_card(recovered))
            print(f"recovery: {[_dev_key(x) for x in recovered]}")
        if d.unchanged:
            print(f"still offline (no re-alert): {[_dev_key(x) for x in d.unchanged]}")
        if not (d.new or d.recovered or d.unchanged):
            print("all devices reporting normally")
        if sent:
            state.commit(d.pending)
        else:
            print("offline state NOT committed: a Teams post failed")
        return sent

    def _upload_alerts(self) -> bool:
        failing = upload.detect_upload_failures(
            upload.fetch_recent_packets(self.db.query, self.s.upload_lookback_packets),
            self.s.upload_alert_consecutive)
        current = {_dev_key(f): f for f in failing}
        state = AlertState(self.s.upload_state_file)
        d = state.diff(current, self.now)
        sent = True
        if d.new:
            sent &= self._send(cards.build_upload_alert_card(d.new))
            print(f"upload alert: {[_dev_key(x) for x in d.new]}")
        if d.recovered:
            sent &= self._send(cards.build_upload_recovery_card(d.recovered))
            print(f"upload recovery: {[_dev_key(x) for x in d.recovered]}")
        if d.unchanged:
            print(f"still failing upload (no re-alert): {[_dev_key(x) for x in d.unchanged]}")
        if not (d.new or d.recovered or d.unchanged):
            print("all devices uploading normally")
        if sent:
            state.commit(d.pending)
        else:
            print("upload state NOT committed: a Teams post failed")
        return sent

    # ── daily / monthly ───────────────────────────────────────────────────────
    def _save(self, png, label):
        try:
            return chart_store.save_chart(png, self.s.chart_dir, self.s.chart_public_base_url)
        except OSError as e:
            print(f"chart '{label}' could not be saved: {e}")
            return None

    def _customer_card(self, customer, start, end, cfg, thr, states, monthly_label=None):
        q, off = self.db.query, self.s.tz_offset_hours
        trend = queries.daily_trend(q, customer, start, end, off)
        summary = queries.device_summary(q, customer, start, end, off)
        if not summary:
            return None
        hourly = queries.hourly_pattern(q, customer, start, end, off)
        storage = queries.storage(q, customer)
        offline = [st for st in liveness.alertable_offline(states, self.now) if st.device.customer == customer]

        day_rows = trend if monthly_label else [r for r in trend if r["report_date"] == end]
        found = anomalies.detect(day_rows, storage, offline, cfg, thr)

        warn_by_device = {
            (r["machine_name"], r["location"]):
            thresholds.lookup(thr, cfg, customer, r["machine_name"], r["location"], "good_read_pct")[0]
            for r in summary
        }
        days = (end - start).days + 1
        label = monthly_label or f"Last {days} Days"
        chart_urls = {
            "volume": self._save(self.render["volume"](trend, f"Daily Volume — {customer} — {label}"), "volume"),
            "goodread": self._save(self.render["goodread"](trend, f"Good Read % — {customer} — {label}", warn_by_device), "goodread"),
            "hourly": self._save(self.render["hourly"](hourly, f"Hourly Pattern — {customer} — {label}"), "hourly"),
        }

        headers = ["Device", "Location", "Items", "Good Read %", "No Reads"]
        if cfg.has_dimension:
            headers.append("No Dims")
        if cfg.has_hand_scan:
            headers.append("Hand Scanned")
        if cfg.has_weight:
            headers.append("No Weight")

        def _row(r, trailing):
            cells = [r["machine_name"], r["location"], f"{(r['total_items'] or 0):,}",
                     f"{float(r['good_read_pct']):.1f}%" if r.get("good_read_pct") is not None else "—",
                     f"{r['no_reads'] or 0:,}"]
            if cfg.has_dimension:
                cells.append(f"{r['no_dimensions'] or 0:,}")
            if cfg.has_hand_scan:
                cells.append(f"{r['hand_scanned'] or 0:,}")
            if cfg.has_weight:
                cells.append(f"{r['no_weight'] or 0:,}")
            return cells + trailing

        storage_table = {"headers": ["Device", "Location", "Usage", "%"],
                         "rows": [[s["machine_name"], s["location"],
                                   f"{float(s['used_gb']):.1f} / {float(s['total_gb']):.1f} GB",
                                   f"{float(s['usage_percent']):.0f}%"] for s in storage]}

        if monthly_label is None:
            yesterday = queries.device_summary(q, customer, end, end, off)
            today_table = {"headers": headers + ["Not Sent"],
                           "rows": [_row(r, [f"{r['not_sent'] or 0:,}"]) for r in yesterday]}
            week_table = {"headers": headers, "rows": [_row(r, []) for r in summary]}
            card = cards.build_customer_section_card(
                customer=customer, days=days, anomalies=anomalies.format_lines(found),
                today_table=today_table, week_table=week_table, storage_table=storage_table, chart_urls=chart_urls)
            # cards.py labels the first table "Today's Scan Summary"; rename for complete-day semantics.
            for el in card["body"]:
                if el.get("type") == "TextBlock" and "Today" in el.get("text", ""):
                    el["text"] = "📦 Yesterday's Scan Summary"
            return card

        total_items = sum(int(r["total_items"] or 0) for r in summary)
        avg_good = sum(float(r["good_read_pct"] or 0) for r in summary) / max(len(summary), 1)
        kpis = {"total_items": total_items, "avg_good_read_pct": avg_good, "active_devices": len(summary)}
        month_rows = [_row(r, [f"{int(r['not_sent'] or 0):,}",
                               "▲ Strong" if float(r["good_read_pct"] or 0) >= 99 else "▼ Monitor"]) for r in summary]
        return cards.build_customer_section_card(
            customer=customer, days=days, anomalies=anomalies.format_lines(found),
            today_table={"headers": [], "rows": []},
            week_table={"headers": headers + ["Not Sent", "Trend"], "rows": month_rows},
            storage_table=storage_table, chart_urls=chart_urls, kpis=kpis)

    def _report(self, start, end, monthly_label=None) -> bool:
        chart_store.cleanup_old_charts(self.s.chart_dir, self.s.chart_retention_days)
        cfgs = customers.load_customer_configs(self.db.query)
        thr = thresholds.load_thresholds(self.db.query)
        states = self._states()
        ok = True
        sent = 0
        for customer in queries.customers_with_reports(self.db.query):
            card = self._customer_card(customer, start, end, customers.config_for(cfgs, customer), thr, states, monthly_label)
            if card is None:
                print(f"skip {customer}: no data in window")
                continue
            ok &= self._send(card)
            sent += 1
        print(f"{'monthly' if monthly_label else 'daily'} report {start}..{end}: {sent} card(s), ok={ok}")
        return ok

    def daily(self) -> bool:
        start, end = timewin.daily_window(self.now, self.s.tz_offset_hours, days=7)
        return self._report(start, end)

    def monthly(self) -> bool:
        start, end = timewin.previous_month(self.now, self.s.tz_offset_hours)
        return self._report(start, end, monthly_label=start.strftime("%B %Y"))

    # ── stale-digest ──────────────────────────────────────────────────────────
    def stale_digest(self) -> bool:
        stale = liveness.stale_devices(self._states())
        if not stale:
            print("no stale devices")
            return True
        items = [{"machine_name": st.device.machine_name, "location": st.device.location,
                  "customer": st.device.customer, "last_seen": st.last_seen,
                  "days_silent": st.minutes_ago // 1440} for st in stale]
        print(f"stale digest: {[_dev_key(i) for i in items]}")
        return self._send(cards.build_stale_digest_card(items))
