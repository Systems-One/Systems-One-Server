-- Per-customer capabilities and alert limits, replacing CUSTOMER_CAPS in code.
IF OBJECT_ID(N'dbo.customer_config', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.customer_config (
        customer            NVARCHAR(100) NOT NULL PRIMARY KEY,
        has_dimension       BIT NOT NULL DEFAULT 1,
        has_weight          BIT NOT NULL DEFAULT 0,
        has_hand_scan       BIT NOT NULL DEFAULT 0,
        hand_scan_warn_pct  DECIMAL(5,2) NOT NULL DEFAULT 15.0,
        no_weight_warn_pct  DECIMAL(5,2) NOT NULL DEFAULT 5.0,
        storage_warn_pct    DECIMAL(5,2) NOT NULL DEFAULT 80.0,
        storage_bad_pct     DECIMAL(5,2) NOT NULL DEFAULT 90.0,
        good_read_warn_pct  DECIMAL(5,2) NOT NULL DEFAULT 95.0,
        good_read_bad_pct   DECIMAL(5,2) NOT NULL DEFAULT 90.0,
        no_dim_warn_pct     DECIMAL(5,2) NOT NULL DEFAULT 5.0,
        no_dim_bad_pct      DECIMAL(5,2) NOT NULL DEFAULT 10.0,
        reports_enabled     BIT NOT NULL DEFAULT 1,
        updated_at          DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

-- Seed the four customers that had explicit capabilities in the old code.
MERGE dbo.customer_config AS t
USING (VALUES
    (N'PEPKOR',   1, 0, 0),
    (N'MADIBANA', 1, 1, 1),
    (N'PEP',      0, 0, 0),
    (N'SNOWSOFT', 0, 0, 0)
) AS s (customer, has_dimension, has_weight, has_hand_scan)
ON t.customer = s.customer
WHEN NOT MATCHED THEN
    INSERT (customer, has_dimension, has_weight, has_hand_scan)
    VALUES (s.customer, s.has_dimension, s.has_weight, s.has_hand_scan);
GO

-- Every other customer known to devices gets a defaults row.
INSERT INTO dbo.customer_config (customer)
SELECT DISTINCT d.customer
FROM dbo.devices d
WHERE NOT EXISTS (SELECT 1 FROM dbo.customer_config c WHERE c.customer = d.customer);
GO
