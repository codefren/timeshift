-- ============================================================================
-- Limpieza del seed de desarrollo del calendario (seed_calendar_demo.sql)
-- Borra los turnos y worklogs de prueba de la semana 2026-07-13 .. 2026-07-19
-- para los usuarios 23, 24, 25, 26.
-- Motor: SQL Server (T-SQL). Base de datos: ShiftZone.
-- ============================================================================
SET NOCOUNT ON;

DELETE wt FROM WorkLogTotals wt JOIN WorkLogs w ON w.WorkLogID = wt.WorkLogID
  WHERE w.UserID IN (23,24,25,26) AND w.LogDate BETWEEN '2026-07-13' AND '2026-07-19';
DELETE wl FROM WorkLogLines wl JOIN WorkLogs w ON w.WorkLogID = wl.WorkLogID
  WHERE w.UserID IN (23,24,25,26) AND w.LogDate BETWEEN '2026-07-13' AND '2026-07-19';
DELETE FROM WorkLogs WHERE UserID IN (23,24,25,26) AND LogDate BETWEEN '2026-07-13' AND '2026-07-19';
DELETE FROM Shifts   WHERE UserID IN (23,24,25,26) AND Date    BETWEEN '2026-07-13' AND '2026-07-19';

PRINT 'Seed de calendario de desarrollo eliminado.';
GO
