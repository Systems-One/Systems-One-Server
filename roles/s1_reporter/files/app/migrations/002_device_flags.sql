-- Reporting flags on devices. mqtt_ingestor inserts with an explicit column list, unaffected.
IF COL_LENGTH(N'dbo.devices', N'reporting_enabled') IS NULL
BEGIN
    ALTER TABLE dbo.devices ADD reporting_enabled BIT NOT NULL CONSTRAINT DF_devices_reporting_enabled DEFAULT 1;
END
GO

IF COL_LENGTH(N'dbo.devices', N'muted_until') IS NULL
BEGIN
    ALTER TABLE dbo.devices ADD muted_until DATETIME2 NULL;
END
GO

-- The one standby line that was hard-coded as an exclusion in the old reporter.
UPDATE dbo.devices SET reporting_enabled = 0
WHERE machine_name = N'DIM2' AND location = N'JBH' AND reporting_enabled = 1;
GO
