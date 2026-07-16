-- ============================================================================
-- Migración: añadir columna UpdatedAt a Schedules
-- ----------------------------------------------------------------------------
-- create_all NO añade columnas a tablas ya existentes. En la base restaurada
-- desde backup, Schedules existe pero sin la columna UpdatedAt que el modelo
-- app/SQLModels/Schedules.py::Schedules ya define, lo que provoca un 500
-- (Invalid column name 'UpdatedAt') al consultar horarios.
--
-- Idempotente. Motor: SQL Server (T-SQL). Base de datos: ShiftZone.
-- ============================================================================

IF COL_LENGTH('dbo.Schedules', 'UpdatedAt') IS NULL
    ALTER TABLE dbo.Schedules ADD UpdatedAt DATETIME NOT NULL DEFAULT GETDATE();
GO
