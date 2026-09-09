-- dbo.alert_thresholds: per-device warn/bad limits computed by s1_baselines.
-- Column set matches the table that already exists on production (2026-09-09).
IF OBJECT_ID(N'dbo.alert_thresholds', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.alert_thresholds (
        id               INT IDENTITY(1,1) PRIMARY KEY,
        customer         NVARCHAR(100) NOT NULL,
        machine_name     NVARCHAR(100) NULL,
        location         NVARCHAR(100) NULL,
        metric           NVARCHAR(50)  NOT NULL,
        direction        NVARCHAR(10)  NOT NULL,
        warn_value       DECIMAL(10,4) NULL,
        bad_value        DECIMAL(10,4) NULL,
        baseline_mean    DECIMAL(10,4) NULL,
        baseline_stddev  DECIMAL(10,4) NULL,
        baseline_p05     DECIMAL(10,4) NULL,
        baseline_p10     DECIMAL(10,4) NULL,
        baseline_p90     DECIMAL(10,4) NULL,
        baseline_p95     DECIMAL(10,4) NULL,
        baseline_samples INT NULL,
        lookback_days    INT NULL,
        last_computed    DATETIME NULL,
        is_override      BIT NOT NULL DEFAULT 0,
        updated_at       DATETIME NULL
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_alert_thresholds_key' AND object_id = OBJECT_ID(N'dbo.alert_thresholds'))
BEGIN
    CREATE INDEX IX_alert_thresholds_key
    ON dbo.alert_thresholds (customer, machine_name, location, metric);
END
GO
