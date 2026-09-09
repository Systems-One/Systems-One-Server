IF OBJECT_ID(N'dbo.device_health_history', N'U') IS NULL
BEGIN
CREATE TABLE dbo.device_health_history (
    id                  BIGINT IDENTITY(1,1) PRIMARY KEY,
    device_id           INT          NOT NULL,
    snapshot_utc        DATETIME2(0) NOT NULL,
    status              NVARCHAR(40) NULL,
    status_ts_utc       DATETIME2(0) NULL,
    application_running BIT          NULL,
    app_ts_utc          DATETIME2(0) NULL,
    uptime_seconds      DECIMAL(18,3) NULL,
    cpu_percent         DECIMAL(5,2) NULL,
    mem_usage_pct       DECIMAL(5,2) NULL,
    temp_celsius        DECIMAL(5,2) NULL,
    c_usage_percent     DECIMAL(5,2) NULL,
    max_usage_percent   DECIMAL(5,2) NULL,
    drives_json         NVARCHAR(MAX) NULL,
    last_stats_utc      DATETIME2(0) NULL
);
END
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_device_health_history_device_ts')
BEGIN
CREATE INDEX IX_device_health_history_device_ts
    ON dbo.device_health_history (device_id, snapshot_utc);
END
