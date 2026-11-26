-- C: drive warn limit moves from 80% to 85% (bad stays at 90%).
-- Runs once: the named default is the marker, so a customer later set back to 80 on purpose is left alone.
IF NOT EXISTS (SELECT 1 FROM sys.default_constraints
               WHERE parent_object_id = OBJECT_ID(N'dbo.customer_config')
                 AND name = N'DF_customer_config_storage_warn_pct')
BEGIN
    DECLARE @old sysname = (
        SELECT dc.name
        FROM sys.default_constraints dc
        JOIN sys.columns c ON c.object_id = dc.parent_object_id AND c.column_id = dc.parent_column_id
        WHERE dc.parent_object_id = OBJECT_ID(N'dbo.customer_config') AND c.name = N'storage_warn_pct');
    IF @old IS NOT NULL
    BEGIN
        DECLARE @drop NVARCHAR(400) = N'ALTER TABLE dbo.customer_config DROP CONSTRAINT ' + QUOTENAME(@old);
        EXEC sp_executesql @drop;
    END

    ALTER TABLE dbo.customer_config
        ADD CONSTRAINT DF_customer_config_storage_warn_pct DEFAULT 85.0 FOR storage_warn_pct;

    UPDATE dbo.customer_config
    SET storage_warn_pct = 85.0, updated_at = SYSUTCDATETIME()
    WHERE storage_warn_pct = 80.0;
END
GO
