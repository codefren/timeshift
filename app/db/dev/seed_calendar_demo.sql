-- ============================================================================
-- SEED DE DESARROLLO — datos de ejemplo para el calendario
-- ----------------------------------------------------------------------------
-- Inserta turnos (incluyendo TURNOS PARTIDOS) y worklogs para la semana
-- 2026-07-13 .. 2026-07-19, en usuarios que ya aparecen en el calendario
-- (23 Ana Caramelli, 24 Tania Fort, 25 Valeria Mattos, 26 Valentina Masafierro).
--
-- SOLO PARA ENTORNOS DE DESARROLLO / DEMO. No ejecutar en producción.
-- Idempotente: borra y re-crea sus propios datos. Limpieza total en
-- cleanup_calendar_demo.sql.
--
-- Motor: SQL Server (T-SQL). Base de datos: ShiftZone.
-- ============================================================================
SET NOCOUNT ON;

-- ── Limpieza previa (idempotencia) ──────────────────────────────────────────
DELETE wt FROM WorkLogTotals wt JOIN WorkLogs w ON w.WorkLogID = wt.WorkLogID
  WHERE w.UserID IN (23,24,25,26) AND w.LogDate BETWEEN '2026-07-13' AND '2026-07-19';
DELETE wl FROM WorkLogLines wl JOIN WorkLogs w ON w.WorkLogID = wl.WorkLogID
  WHERE w.UserID IN (23,24,25,26) AND w.LogDate BETWEEN '2026-07-13' AND '2026-07-19';
DELETE FROM WorkLogs WHERE UserID IN (23,24,25,26) AND LogDate BETWEEN '2026-07-13' AND '2026-07-19';
DELETE FROM Shifts   WHERE UserID IN (23,24,25,26) AND Date    BETWEEN '2026-07-13' AND '2026-07-19';

-- ── Turnos ──────────────────────────────────────────────────────────────────
INSERT INTO Shifts (UserID, DepartmentID, LocationID, ScheduleID, Date, StartTime, EndTime, BreakTime, IsPublished, Status, CreatedBy, CreatedAt, UpdatedAt)
VALUES
-- 23 — turno PARTIDO (martes 14): mañana + tarde
(23, 10, 10, NULL, '2026-07-14', '10:30', '14:30', 0, 1, 'Planned', 1, GETDATE(), GETDATE()),
(23, 10, 10, NULL, '2026-07-14', '16:00', '20:00', 0, 1, 'Planned', 1, GETDATE(), GETDATE()),
-- 24 — turno PARTIDO (miércoles 15)
(24,  2,  2, NULL, '2026-07-15', '09:00', '13:00', 0, 1, 'Planned', 1, GETDATE(), GETDATE()),
(24,  2,  2, NULL, '2026-07-15', '17:00', '21:00', 0, 1, 'Planned', 1, GETDATE(), GETDATE()),
-- 25 — turno SIMPLE (lunes 13)
(25,  2,  2, NULL, '2026-07-13', '10:00', '18:00', 0, 1, 'Planned', 1, GETDATE(), GETDATE()),
-- 26 — turno SIMPLE (martes 14)
(26,  2,  2, NULL, '2026-07-14', '09:00', '17:00', 0, 1, 'Planned', 1, GETDATE(), GETDATE());

-- ── Worklogs (fichajes reales) ──────────────────────────────────────────────
-- WorkLogLineID NO es IDENTITY → se asignan IDs explícitos calculados en runtime.
DECLARE @lineId INT = (SELECT ISNULL(MAX(WorkLogLineID), 0) FROM WorkLogLines);

-- Worklog TERMINADO (23, martes 14): entrada a tiempo (10:32 vs 10:30)
DECLARE @wl1 INT;
INSERT INTO WorkLogs (UserID, LogDate, ShiftID, IsFinished, IsApproved) VALUES (23, '2026-07-14', NULL, 1, 0);
SET @wl1 = SCOPE_IDENTITY();
INSERT INTO WorkLogLines (WorkLogLineID, WorkLogID, StartTime, EndTime, IsPause, LoggedHours) VALUES
  (@lineId + 1, @wl1, '10:32', '14:30', 0, 3.97),
  (@lineId + 2, @wl1, '16:03', '20:05', 0, 4.03);
SET @lineId = @lineId + 2;

-- Worklog EN CURSO (26, martes 14): entrada tardía (09:10 vs 09:00 → marca tardanza)
DECLARE @wl2 INT;
INSERT INTO WorkLogs (UserID, LogDate, ShiftID, IsFinished, IsApproved) VALUES (26, '2026-07-14', NULL, 0, 0);
SET @wl2 = SCOPE_IDENTITY();
INSERT INTO WorkLogLines (WorkLogLineID, WorkLogID, StartTime, EndTime, IsPause, LoggedHours) VALUES
  (@lineId + 1, @wl2, '09:10', NULL, 0, NULL);

-- Totales del worklog terminado. Se desactiva temporalmente un trigger de la
-- base restaurada (trg_UpdateUserHoursBalance) que referencia una columna
-- inexistente ('TotalPauseHours') y aborta el INSERT. Es un bug del backup;
-- aquí solo lo sorteamos para el seed de dev.
DECLARE @trgTbl SYSNAME = (SELECT OBJECT_NAME(parent_id) FROM sys.triggers WHERE name = 'trg_UpdateUserHoursBalance');
IF @trgTbl IS NOT NULL EXEC('DISABLE TRIGGER trg_UpdateUserHoursBalance ON dbo.' + @trgTbl);

INSERT INTO WorkLogTotals (WorkLogID, StartTime, EndTime, TotalWorkedHours, TotalPauseCountedHours, BalanceScheduleHours, TotalPauseUncountedHours)
VALUES (@wl1, '2026-07-14 10:32:00', '2026-07-14 20:05:00', 8.0, 0, 0, 1.53);

IF @trgTbl IS NOT NULL EXEC('ENABLE TRIGGER trg_UpdateUserHoursBalance ON dbo.' + @trgTbl);

-- ── Resumen ─────────────────────────────────────────────────────────────────
SELECT 'Shifts'   AS Tabla, COUNT(*) AS N FROM Shifts   WHERE UserID IN (23,24,25,26) AND Date    BETWEEN '2026-07-13' AND '2026-07-19'
UNION ALL
SELECT 'WorkLogs',          COUNT(*)      FROM WorkLogs WHERE UserID IN (23,24,25,26) AND LogDate BETWEEN '2026-07-13' AND '2026-07-19';
GO
