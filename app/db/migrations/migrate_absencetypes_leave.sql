-- ============================================================================
-- Migración: columnas nuevas de AbsenceTypes + tipos de ausencia 'leave'
-- ----------------------------------------------------------------------------
-- Necesaria porque el código añade columnas a AbsenceTypes (Category,
-- RequiresBalance, DefaultAnnualDays, IsActive) que create_all NO crea sobre
-- una tabla ya existente. Debe ejecutarse en cada entorno (incl. PRODUCCIÓN)
-- ANTES o justo DESPUÉS de desplegar el código de la feature de ausencias.
--
-- Idempotente: se puede ejecutar varias veces sin efectos secundarios.
-- Motor: SQL Server (T-SQL). Ejecutar conectado a la base de datos correcta
-- (p.ej. ShiftZone).
-- ============================================================================

-- 1) Añadir columnas si faltan
IF COL_LENGTH('dbo.AbsenceTypes','Category')          IS NULL ALTER TABLE dbo.AbsenceTypes ADD Category          varchar(10) NOT NULL DEFAULT 'pause';
IF COL_LENGTH('dbo.AbsenceTypes','RequiresBalance')   IS NULL ALTER TABLE dbo.AbsenceTypes ADD RequiresBalance   bit         NOT NULL DEFAULT 0;
IF COL_LENGTH('dbo.AbsenceTypes','DefaultAnnualDays') IS NULL ALTER TABLE dbo.AbsenceTypes ADD DefaultAnnualDays float       NULL;
IF COL_LENGTH('dbo.AbsenceTypes','IsActive')          IS NULL ALTER TABLE dbo.AbsenceTypes ADD IsActive          bit         NOT NULL DEFAULT 1;
GO

-- 2) Insertar los tipos solicitables ('leave') si no existen
MERGE dbo.AbsenceTypes AS t
USING (VALUES
  ('Vacaciones',      1, 'leave', 1, 31.0, 1),
  ('Médico',          1, 'leave', 0, NULL, 1),
  ('Permiso escolar', 1, 'leave', 0, NULL, 1)
) AS s(TypeName, IsCounted, Category, RequiresBalance, DefaultAnnualDays, IsActive)
ON t.TypeName = s.TypeName AND t.Category = 'leave'
WHEN NOT MATCHED THEN
  INSERT (TypeName, IsCounted, Category, RequiresBalance, DefaultAnnualDays, IsActive)
  VALUES (s.TypeName, s.IsCounted, s.Category, s.RequiresBalance, s.DefaultAnnualDays, s.IsActive);
GO

-- 3) (Opcional) Verificación
-- SELECT AbsenceTypeID, TypeName, Category, RequiresBalance, DefaultAnnualDays, IsActive
-- FROM dbo.AbsenceTypes ORDER BY Category, AbsenceTypeID;
