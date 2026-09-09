"""Settings from environment variables. Compose is the only configuration source."""
from dataclasses import dataclass
from typing import Mapping

_REQUIRED = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASS", "TEAMS_WEBHOOK_URL")


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_pass: str
    teams_webhook_url: str
    chart_dir: str = "/data/charts"
    chart_public_base_url: str = ""
    chart_retention_days: int = 14
    offline_threshold_minutes: int = 30
    stale_days: int = 14
    tz_offset_hours: int = 2
    upload_alert_consecutive: int = 3
    upload_lookback_packets: int = 6
    offline_state_file: str = "/data/offline_state.json"
    upload_state_file: str = "/data/upload_state.json"


def load_settings(env: Mapping[str, str]) -> Settings:
    missing = [k for k in _REQUIRED if not env.get(k)]
    if missing:
        raise SystemExit(f"Missing required environment variable(s): {', '.join(missing)}")

    def _int(name, default):
        return int(env.get(name, default))

    return Settings(
        db_host=env["DB_HOST"],
        db_port=int(env["DB_PORT"]),
        db_name=env["DB_NAME"],
        db_user=env["DB_USER"],
        db_pass=env["DB_PASS"],
        teams_webhook_url=env["TEAMS_WEBHOOK_URL"],
        chart_dir=env.get("CHART_DIR", "/data/charts"),
        chart_public_base_url=env.get("CHART_PUBLIC_BASE_URL", ""),
        chart_retention_days=_int("CHART_RETENTION_DAYS", 14),
        offline_threshold_minutes=_int("OFFLINE_THRESHOLD_MINUTES", 30),
        stale_days=_int("STALE_DAYS", 14),
        tz_offset_hours=_int("REPORT_TZ_OFFSET_HOURS", 2),
        upload_alert_consecutive=_int("UPLOAD_ALERT_CONSECUTIVE", 3),
        upload_lookback_packets=_int("UPLOAD_LOOKBACK_PACKETS", 6),
        offline_state_file=env.get("OFFLINE_STATE_FILE", "/data/offline_state.json"),
        upload_state_file=env.get("UPLOAD_STATE_FILE", "/data/upload_state.json"),
    )
