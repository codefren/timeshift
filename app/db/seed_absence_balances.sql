-- ============================================================================
-- Sembrado de saldos anuales de ausencias (AbsenceBalance)
-- ----------------------------------------------------------------------------
-- Crea el saldo anual para cada empleado ACTIVO usando el cupo por defecto
-- (DefaultAnnualDays) de cada tipo 'leave' con cupo (RequiresBalance = 1).
-- Hoy solo aplica a "Vacaciones" (31 días).
--
-- Idempotente: no duplica los saldos que ya existen (NOT EXISTS).
-- Toma el cupo del propio tipo, así que si cambias DefaultAnnualDays no hay
-- que tocar este script.
--
-- Motor: SQL Server (T-SQL). Base de datos: ShiftZone.
-- Equivalente en código: AbsencesService.seed_balances_for_active_users()
-- ============================================================================

DECLARE @Year INT = YEAR(GETDATE());   -- cambia a 2026, 2027, ... para otro año

INSERT INTO AbsenceBalance (UserID, AbsenceTypeID, Year, AccruedDays, UsedDays, PendingDays, UpdatedAt)
SELECT
    u.UserID,
    at.AbsenceTypeID,
    @Year,
    at.DefaultAnnualDays,   -- cupo configurado en el tipo (31 para Vacaciones)
    0,                      -- UsedDays
    0,                      -- PendingDays
    GETDATE()
FROM Users u
CROSS JOIN AbsenceTypes at
WHERE u.IsInactive = 0                         -- solo empleados activos
  AND at.Category = 'leave'
  AND at.RequiresBalance = 1                   -- solo tipos con cupo (Vacaciones)
  AND at.DefaultAnnualDays IS NOT NULL
  AND NOT EXISTS (                             -- evita duplicados (idempotente)
        SELECT 1 FROM AbsenceBalance b
        WHERE b.UserID = u.UserID
          AND b.AbsenceTypeID = at.AbsenceTypeID
          AND b.Year = @Year
  );

-- Para incluir también a los empleados inactivos, elimina la línea:
--   AND u.IsInactive = 0
