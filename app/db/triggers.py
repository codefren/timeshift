from sqlalchemy import Engine, text
import logging


def init_worklogs_triggers(engine: Engine):
    log = logging.getLogger(__name__)
    check_trigger_sql = """
    SELECT COUNT(*)
    FROM sys.triggers
    WHERE name = 'trg_UpdateUserHoursBalance'
    """
    trg = """
    CREATE TRIGGER [dbo].[trg_UpdateUserHoursBalance]
    ON [dbo].[WorkLogTotals]
    AFTER INSERT, UPDATE, DELETE
    AS
    BEGIN
        SET NOCOUNT ON;

        -- Delta = nuevos (inserted) - anteriores (deleted)
        -- INSERT: inserted tiene datos, deleted vacío  → delta = +nuevo
        -- UPDATE: inserted nuevos,      deleted viejos → delta = nuevo - viejo
        -- DELETE: inserted vacío,       deleted datos  → delta = -viejo

        ;WITH CTE_Delta AS (
            SELECT
                wl.UserID,
                DATEPART(ISO_WEEK, COALESCE(i.StartTime, d.StartTime)) AS WeekNumber,
                DATEPART(YEAR,     COALESCE(i.StartTime, d.StartTime)) AS YearNumber,
                SUM(COALESCE(i.TotalWorkedHours,         0) - COALESCE(d.TotalWorkedHours,         0)) AS DeltaWorked,
                SUM(COALESCE(i.TotalPauseCountedHours,   0) - COALESCE(d.TotalPauseCountedHours,   0)) AS DeltaPauseCounted,
                SUM(COALESCE(i.TotalPauseUncountedHours, 0) - COALESCE(d.TotalPauseUncountedHours, 0)) AS DeltaPauseUncounted,
                SUM(COALESCE(i.BalanceScheduleHours,     0) - COALESCE(d.BalanceScheduleHours,     0)) AS DeltaBalance
            FROM (SELECT WorkLogID FROM inserted UNION SELECT WorkLogID FROM deleted) AS combined(WorkLogID)
            LEFT JOIN inserted  i ON i.WorkLogID = combined.WorkLogID
            LEFT JOIN deleted   d ON d.WorkLogID = combined.WorkLogID
            JOIN WorkLogs wl       ON wl.WorkLogID = combined.WorkLogID
            GROUP BY
                wl.UserID,
                DATEPART(ISO_WEEK, COALESCE(i.StartTime, d.StartTime)),
                DATEPART(YEAR,     COALESCE(i.StartTime, d.StartTime))
        )
        MERGE INTO UserWeekHoursBalance AS target
        USING CTE_Delta AS source
          ON  target.UserID     = source.UserID
          AND target.WeekNumber = source.WeekNumber
          AND target.Year       = source.YearNumber
        WHEN MATCHED THEN
            UPDATE SET
                WorkedHours          = target.WorkedHours          + source.DeltaWorked,
                PausedCountedHours   = target.PausedCountedHours   + source.DeltaPauseCounted,
                PausedUncountedHours = target.PausedUncountedHours + source.DeltaPauseUncounted,
                BalanceHours         = target.BalanceHours         + source.DeltaBalance,
                UpdatedAt            = GETDATE()
        WHEN NOT MATCHED AND source.DeltaWorked <> 0 THEN
            INSERT (UserID, WeekNumber, Year,
                    WorkedHours, PausedCountedHours, PausedUncountedHours, BalanceHours, UpdatedAt)
            VALUES (source.UserID, source.WeekNumber, source.YearNumber,
                    source.DeltaWorked, source.DeltaPauseCounted,
                    source.DeltaPauseUncounted, source.DeltaBalance, GETDATE())
        ;

        ;WITH CTE_TotalDelta AS (
            SELECT
                wl.UserID,
                SUM(COALESCE(i.TotalWorkedHours,         0) - COALESCE(d.TotalWorkedHours,         0)) AS DeltaWorked,
                SUM(COALESCE(i.TotalPauseCountedHours,   0) - COALESCE(d.TotalPauseCountedHours,   0)) AS DeltaPauseCounted,
                SUM(COALESCE(i.TotalPauseUncountedHours, 0) - COALESCE(d.TotalPauseUncountedHours, 0)) AS DeltaPauseUncounted,
                SUM(COALESCE(i.BalanceScheduleHours,     0) - COALESCE(d.BalanceScheduleHours,     0)) AS DeltaBalance
            FROM (SELECT WorkLogID FROM inserted UNION SELECT WorkLogID FROM deleted) AS combined(WorkLogID)
            LEFT JOIN inserted  i ON i.WorkLogID = combined.WorkLogID
            LEFT JOIN deleted   d ON d.WorkLogID = combined.WorkLogID
            JOIN WorkLogs wl       ON wl.WorkLogID = combined.WorkLogID
            GROUP BY wl.UserID
        )
        MERGE INTO UserTotalHoursBalance AS target
        USING CTE_TotalDelta AS source
          ON target.UserID = source.UserID
        WHEN MATCHED THEN
            UPDATE SET
                TotalHours                = target.TotalHours                + source.DeltaWorked,
                TotalPausedCountedHours   = target.TotalPausedCountedHours   + source.DeltaPauseCounted,
                TotalPausedUncountedHours = target.TotalPausedUncountedHours + source.DeltaPauseUncounted,
                BalanceHours              = target.BalanceHours              + source.DeltaBalance,
                UpdatedAt                 = GETDATE()
        WHEN NOT MATCHED AND source.DeltaWorked <> 0 THEN
            INSERT (UserID, TotalHours, TotalPausedCountedHours, TotalPausedUncountedHours, BalanceHours, UpdatedAt)
            VALUES (source.UserID, source.DeltaWorked, source.DeltaPauseCounted,
                    source.DeltaPauseUncounted, source.DeltaBalance, GETDATE())
        ;
    END;
    ALTER TABLE [dbo].[WorkLogTotals] ENABLE TRIGGER [trg_UpdateUserHoursBalance];
    """
    with engine.connect() as connection:
        result = connection.execute(text(check_trigger_sql))
        trigger_exists = result.scalar() > 0  # Verificar si el trigger ya existe

        if not trigger_exists:
            connection.execute(text(trg))
            connection.commit()
            log.debug("Trigger calculate work hours balance creado exitosamente.")
        else:
            log.debug("Trigger work hours balance ya existente. No se creó de nuevo.")

def init_triggers(engine: Engine):
    init_worklogs_triggers(engine)
