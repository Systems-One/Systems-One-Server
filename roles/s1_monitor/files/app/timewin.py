"""Range presets and SAST time helpers. All inputs and outputs are naive UTC datetimes unless named local."""
import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    name: str
    bucket_seconds: int
    daily: bool
    hours: int | None
    days: int | None
    style: str  # "bars" | "line"


PRESETS = {
    "24h": Preset("24h", 1800, False, 24, None, "bars"),
    "48h": Preset("48h", 3600, False, 48, None, "bars"),
    "7d": Preset("7d", 86400, True, None, 7, "line"),
    "30d": Preset("30d", 86400, True, None, 30, "line"),
    "90d": Preset("90d", 86400, True, None, 90, "line"),
}


def to_local(d: dt.datetime, offset_hours: int) -> dt.datetime:
    return d + dt.timedelta(hours=offset_hours)


def to_utc(d_local: dt.datetime, offset_hours: int) -> dt.datetime:
    return d_local - dt.timedelta(hours=offset_hours)


def local_midnight(now_utc: dt.datetime, offset_hours: int) -> dt.datetime:
    local = to_local(now_utc, offset_hours)
    return to_utc(local.replace(hour=0, minute=0, second=0, microsecond=0), offset_hours)


def window(preset: Preset, now_utc: dt.datetime, offset_hours: int) -> tuple[dt.datetime, dt.datetime]:
    if preset.daily:
        start_today = local_midnight(now_utc, offset_hours)
        return start_today - dt.timedelta(days=preset.days - 1), start_today + dt.timedelta(days=1)
    b = preset.bucket_seconds
    epoch = int(now_utc.replace(microsecond=0, tzinfo=dt.timezone.utc).timestamp())
    to = dt.datetime.fromtimestamp((epoch // b) * b, dt.timezone.utc).replace(tzinfo=None)
    frm = to - dt.timedelta(hours=preset.hours) + dt.timedelta(seconds=b)
    return frm, to


def bucket_starts(from_utc: dt.datetime, to_utc: dt.datetime, bucket_seconds: int) -> list[dt.datetime]:
    out, cur = [], from_utc
    while cur < to_utc:
        out.append(cur)
        cur += dt.timedelta(seconds=bucket_seconds)
    return out


def week_monday(local_date: dt.date) -> dt.date:
    return local_date - dt.timedelta(days=local_date.weekday())


def min_items_for(preset: Preset, s) -> int:
    if preset.daily:
        return s.min_items_day
    return s.min_items_hour if preset.bucket_seconds >= 3600 else s.min_items_half_hour
