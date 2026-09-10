-- =============================================================
--  Integración Ausencias / Festivos — DDL de tablas nuevas
--  Crea Holidays y AbsenceBalance + columna TotalDays.
--  Idempotente: puede ejecutarse varias veces sin error.
--  Orden: ejecutar ANTES de seed_absences_permissions.sql.
--  Ajusta el nombre de la base en el USE si difiere.
-- =============================================================
USE [timeshift];
GO

SET NOCOUNT ON;

-- ── 1. Tabla Holidays ────────────────────────────────────────
IF OBJECT_ID(N'dbo.Holidays', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.Holidays (
        HolidayID   INT IDENTITY(1,1) NOT NULL,
        Name        NVARCHAR(100)     NOT NULL,
        [Date]      DATE              NOT NULL,
        CompanyID   INT               NULL,
        LocationID  INT               NULL,
        IsRecurring BIT               NOT NULL CONSTRAINT DF_Holidays_IsRecurring DEFAULT (0),
        CreatedBy   INT               NOT NULL,
        CreatedAt   DATETIME2         NOT NULL CONSTRAINT DF_Holidays_CreatedAt DEFAULT (SYSDATETIME()),
        UpdatedAt   DATETIME2         NOT NULL CONSTRAINT DF_Holidays_UpdatedAt DEFAULT (SYSDATETIME()),
        CONSTRAINT PK_Holidays PRIMARY KEY CLUSTERED (HolidayID),
        CONSTRAINT FK_Holidays_Companies FOREIGN KEY (CompanyID)  REFERENCES dbo.Companies (CompanyID),
        CONSTRAINT FK_Holidays_Locations FOREIGN KEY (LocationID) REFERENCES dbo.Locations (LocationID),
        CONSTRAINT FK_Holidays_Users     FOREIGN KEY (CreatedBy)  REFERENCES dbo.Users (UserID)
    );

    -- Índice para acelerar get_for_date / get_range (consultas por fecha)
    CREATE INDEX IX_Holidays_Date ON dbo.Holidays ([Date]);
END;
GO

-- ── 2. Tabla AbsenceBalance (PK compuesta) ───────────────────
IF OBJECT_ID(N'dbo.AbsenceBalance', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.AbsenceBalance (
        UserID        INT       NOT NULL,
        AbsenceTypeID INT       NOT NULL,
        [Year]        INT       NOT NULL,
        AccruedDays   FLOAT     NOT NULL CONSTRAINT DF_AbsenceBalance_Accrued DEFAULT (0),
        UsedDays      FLOAT     NOT NULL CONSTRAINT DF_AbsenceBalance_Used    DEFAULT (0),
        PendingDays   FLOAT     NOT NULL CONSTRAINT DF_AbsenceBalance_Pending DEFAULT (0),
        UpdatedAt     DATETIME2 NOT NULL CONSTRAINT DF_AbsenceBalance_Updated DEFAULT (SYSDATETIME()),
        CONSTRAINT PK_AbsenceBalance PRIMARY KEY CLUSTERED (UserID, AbsenceTypeID, [Year]),
        CONSTRAINT FK_AbsenceBalance_Users FOREIGN KEY (UserID)
            REFERENCES dbo.Users (UserID),
        CONSTRAINT FK_AbsenceBalance_Types FOREIGN KEY (AbsenceTypeID)
            REFERENCES dbo.AbsenceTypes (AbsenceTypeID)
    );
END;
GO

-- ── 3. Columna TotalDays en AbsenceRequests ──────────────────
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID(N'dbo.AbsenceRequests') AND name = 'TotalDays'
)
BEGIN
    ALTER TABLE dbo.AbsenceRequests
        ADD TotalDays FLOAT NOT NULL CONSTRAINT DF_AbsenceRequests_TotalDays DEFAULT (0);
END;
GO

-- ── 4. Verificación ──────────────────────────────────────────
SELECT t.name AS TableName, c.name AS ColumnName, ty.name AS DataType
FROM sys.tables t
JOIN sys.columns c ON c.object_id = t.object_id
JOIN sys.types  ty ON ty.user_type_id = c.user_type_id
WHERE t.name IN ('Holidays', 'AbsenceBalance', 'AbsenceRequests')
ORDER BY t.name, c.column_id;
GO
