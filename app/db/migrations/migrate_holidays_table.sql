-- ============================================================================
-- Migración: crear la tabla Holidays
-- ----------------------------------------------------------------------------
-- Normalmente la crea init_db() / create_all, pero en entornos con la base
-- restaurada desde backup (SKIP_DB_INIT=true) create_all no se ejecuta y la
-- tabla nunca llega a crearse. Este script la crea si falta.
--
-- Esquema equivalente al SQLModel app/SQLModels/Absences.py::Holidays.
-- Idempotente: se puede ejecutar varias veces sin efectos secundarios.
-- Motor: SQL Server (T-SQL). Base de datos: ShiftZone.
-- ============================================================================

IF OBJECT_ID('dbo.Holidays', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.Holidays (
        HolidayID   INT IDENTITY(1,1) NOT NULL,
        Name        NVARCHAR(100) NOT NULL,
        Date        DATE          NOT NULL,
        CompanyID   INT           NULL,
        LocationID  INT           NULL,
        IsRecurring BIT           NOT NULL DEFAULT 0,
        CreatedBy   INT           NOT NULL,
        CreatedAt   DATETIME      NOT NULL DEFAULT GETDATE(),
        UpdatedAt   DATETIME      NOT NULL DEFAULT GETDATE(),
        CONSTRAINT PK_Holidays PRIMARY KEY (HolidayID),
        CONSTRAINT FK_Holidays_Companies
            FOREIGN KEY (CompanyID) REFERENCES dbo.Companies (CompanyID),
        CONSTRAINT FK_Holidays_Locations
            FOREIGN KEY (LocationID) REFERENCES dbo.Locations (LocationID),
        CONSTRAINT FK_Holidays_Users
            FOREIGN KEY (CreatedBy) REFERENCES dbo.Users (UserID)
    );
END
GO
