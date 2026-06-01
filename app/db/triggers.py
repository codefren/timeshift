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

    CREATE   TRIGGER [dbo].[trg_UpdateUserHoursBalance]
    ON [dbo].[WorkLogTotals]
    AFTER INSERT, UPDATE
    AS
    BEGIN
        SET NOCOUNT ON;
    
        ----------------------------------------
        -- 1) Agregar/actualizar UserWeekHoursBalance
        ----------------------------------------
        ;WITH CTE_UserWeek AS (
            SELECT
                wl.UserID,
                DATEPART(ISO_WEEK, i.StartTime) AS WeekNumber,
                DATEPART(YEAR,      i.StartTime) AS YearNumber,
                SUM(i.TotalWorkedHours)         AS SumWorkedHours,
                SUM(i.TotalPauseCountedHours)   AS SumPausedCountedHours,
                SUM(i.TotalPauseUncountedHours) AS SumPausedUncountedHours,
                SUM(i.BalanceScheduleHours)     AS SumBalanceHours
            FROM inserted AS i
            JOIN WorkLogs AS wl
              ON wl.WorkLogID = i.WorkLogID
            GROUP BY
                wl.UserID,
                DATEPART(ISO_WEEK, i.StartTime),
                DATEPART(YEAR,      i.StartTime)
        )
        MERGE INTO UserWeekHoursBalance AS target
        USING CTE_UserWeek AS source
          ON target.UserID     = source.UserID
         AND target.WeekNumber = source.WeekNumber
         AND target.Year = source.YearNumber
        WHEN MATCHED THEN
            UPDATE
               SET WorkedHours          = target.WorkedHours          + source.SumWorkedHours,
                   PausedCountedHours   = target.PausedCountedHours   + source.SumPausedCountedHours,
                   PausedUncountedHours = target.PausedUncountedHours + source.SumPausedUncountedHours,
                   BalanceHours         = target.BalanceHours         + source.SumBalanceHours,
                   UpdatedAt            = GETDATE()
        WHEN NOT MATCHED THEN
            INSERT (UserID, WeekNumber, Year,
                    WorkedHours, PausedCountedHours, PausedUncountedHours, BalanceHours, UpdatedAt)
            VALUES (source.UserID, source.WeekNumber, source.YearNumber,
                    source.SumWorkedHours, source.SumPausedCountedHours,
                    source.SumPausedUncountedHours, source.SumBalanceHours, GETDATE())
        ;
    
        ----------------------------------------
        -- 2) Agregar/actualizar UserTotalHoursBalance
        ----------------------------------------
        ;WITH CTE_UserTotal AS (
            SELECT
                wl.UserID,
                SUM(i.TotalWorkedHours)         AS SumWorkedHours,
                SUM(i.TotalPauseCountedHours)   AS SumPausedCountedHours,
                SUM(i.TotalPauseUncountedHours) AS SumPausedUncountedHours,
                SUM(i.BalanceScheduleHours)     AS SumBalanceHours
            FROM inserted AS i
            JOIN WorkLogs AS wl
              ON wl.WorkLogID = i.WorkLogID
            GROUP BY wl.UserID
        )
        MERGE INTO UserTotalHoursBalance AS target
        USING CTE_UserTotal AS source
          ON target.UserID = source.UserID
        WHEN MATCHED THEN
            UPDATE
               SET TotalHours               = target.TotalHours               + source.SumWorkedHours,
                   TotalPausedCountedHours  = target.TotalPausedCountedHours  + source.SumPausedCountedHours,
                   TotalPausedUncountedHours= target.TotalPausedUncountedHours+ source.SumPausedUncountedHours,
                   BalanceHours             = target.BalanceHours             + source.SumBalanceHours,
                   UpdatedAt                = GETDATE()
        WHEN NOT MATCHED THEN
            INSERT (UserID, TotalHours, TotalPausedCountedHours, TotalPausedUncountedHours, BalanceHours, UpdatedAt)
            VALUES (source.UserID, source.SumWorkedHours, source.SumPausedCountedHours,
                    source.SumPausedUncountedHours, source.SumBalanceHours, GETDATE())
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
