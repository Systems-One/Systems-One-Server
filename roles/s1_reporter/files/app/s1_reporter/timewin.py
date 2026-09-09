"""Local-day windows. DB timestamps are UTC; reports are about SAST days (UTC+offset, no DST)."""
from datetime import date, datetime, timedelta


def local_date(now_utc: datetime, offset_hours: int) -> date:
    return (now_utc + timedelta(hours=offset_hours)).date()


def daily_window(now_utc: datetime, offset_hours: int, days: int = 7):
    """Inclusive local date range of `days` complete days ending yesterday."""
    end = local_date(now_utc, offset_hours) - timedelta(days=1)
    return end - timedelta(days=days - 1), end


def previous_month(now_utc: datetime, offset_hours: int):
    today = local_date(now_utc, offset_hours)
    end = today.replace(day=1) - timedelta(days=1)
    return end.replace(day=1), end


def utc_bounds(start_date: date, end_date: date, offset_hours: int):
    """[start, end) UTC datetimes covering the inclusive local date range."""
    off = timedelta(hours=offset_hours)
    start = datetime.combine(start_date, datetime.min.time()) - off
    end = datetime.combine(end_date + timedelta(days=1), datetime.min.time()) - off
    return start, end
