"""Environment configuration. Every value has a default that matches the role defaults."""
import os
from dataclasses import dataclass


def _bool(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    db_host: str = os.getenv("DB_HOST", "mssql")
    db_port: int = int(os.getenv("DB_PORT", "1433"))
    db_name: str = os.getenv("DB_NAME", "S1_Remote_Monitoring")
    db_user: str = os.getenv("DB_USER", "admin")
    db_pass: str = os.getenv("DB_PASS", "")
    tz_offset_hours: int = int(os.getenv("TZ_OFFSET_HOURS", "2"))
    min_items_day: int = int(os.getenv("MIN_ITEMS_DAY", "100"))
    min_items_hour: int = int(os.getenv("MIN_ITEMS_HOUR", "30"))
    min_items_half_hour: int = int(os.getenv("MIN_ITEMS_HALF_HOUR", "15"))
    offline_gap_minutes: int = int(os.getenv("OFFLINE_GAP_MINUTES", "11"))
    stale_days: int = int(os.getenv("STALE_DAYS", "14"))
    snapshot_enabled: bool = _bool(os.getenv("SNAPSHOT_ENABLED", "true"))
    snapshot_interval_minutes: int = int(os.getenv("SNAPSHOT_INTERVAL_MINUTES", "15"))
    snapshot_retention_days: int = int(os.getenv("SNAPSHOT_RETENTION_DAYS", "400"))
    cache_ttl_live: int = int(os.getenv("CACHE_TTL_LIVE_SECONDS", "30"))
    cache_ttl_history: int = int(os.getenv("CACHE_TTL_HISTORY_SECONDS", "300"))
    query_timeout: int = int(os.getenv("QUERY_TIMEOUT_SECONDS", "20"))

    @property
    def conn_str(self) -> str:
        return (
            "DRIVER={ODBC Driver 18 for SQL Server};"
            f"SERVER={self.db_host},{self.db_port};DATABASE={self.db_name};"
            f"UID={self.db_user};PWD={self.db_pass};"
            "Encrypt=optional;TrustServerCertificate=yes;Connection Timeout=5;"
        )


settings = Settings()
