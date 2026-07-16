-- ============================================================================
-- Migración: crear la tabla AbsenceBalance
-- ----------------------------------------------------------------------------
-- Normalmente la crea init_db() / create_all, pero en entornos con la base
-- restaurada desde backup (SKIP_DB_INIT=true) create_all no se ejecuta y la
-- tabla nunca llega a crearse. Este script la crea si falta.
--
-- Esquema equivalente al SQLModel app/SQLModels/Absences.py::AbsenceBalance
-- (PK compuesta UserID + AbsenceTypeID + Year).
--
-- Idempotente: se puede ejecutar varias veces sin efectos secundarios.
-- Motor: SQL Server (T-SQL). Base de datos: ShiftZone.
-- ============================================================================

IF OBJECT_ID('dbo.AbsenceBalance', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.AbsenceBalance (
        UserID        INT      NOT NULL,
        AbsenceTypeID INT      NOT NULL,
        Year          INT      NOT NULL,
        AccruedDays   FLOAT    NOT NULL DEFAULT 0,
        UsedDays      FLOAT    NOT NULL DEFAULT 0,
        PendingDays   FLOAT    NOT NULL DEFAULT 0,
        UpdatedAt     DATETIME NOT NULL DEFAULT GETDATE(),
        CONSTRAINT PK_AbsenceBalance PRIMARY KEY (UserID, AbsenceTypeID, Year),
        CONSTRAINT FK_AbsenceBalance_Users
            FOREIGN KEY (UserID) REFERENCES dbo.Users (UserID),
        CONSTRAINT FK_AbsenceBalance_AbsenceTypes
            FOREIGN KEY (AbsenceTypeID) REFERENCES dbo.AbsenceTypes (AbsenceTypeID)
    );
END
GO
