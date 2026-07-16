from sqlalchemy import Engine
import logging


def init_worklogs_triggers(engine: Engine):
    log = logging.getLogger(__name__)
    # DROP + CREATE en lugar de CREATE OR ALTER (que es SQL Server 2016+), para
    # compatibilidad con SQL Server 2008 R2. El DROP condicional y el ENABLE van
    # en ejecuciones separadas porque CREATE TRIGGER debe ser la primera (y única)
    # sentencia de su batch.
    drop_trg = (
        "IF OBJECT_ID(N'dbo.trg_UpdateUserHoursBalance', N'TR') IS NOT NULL "
        "DROP TRIGGER dbo.trg_UpdateUserHoursBalance;"
    )
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
    """
    enable_trg = "ALTER TABLE [dbo].[WorkLogTotals] ENABLE TRIGGER [trg_UpdateUserHoursBalance];"
    # exec_driver_sql: ejecución cruda por el driver, sin que SQLAlchemy interprete
    # ':' como bind param ni el string como texto con parámetros. Cada llamada es su
    # propio batch, por eso DROP y CREATE van separados (CREATE TRIGGER debe ser la
    # primera sentencia de su batch). engine.begin() hace commit al terminar bien.
    with engine.begin() as conn:
        conn.exec_driver_sql(drop_trg)   # batch aparte
        conn.exec_driver_sql(trg)        # CREATE TRIGGER como 1ª sentencia del batch
        conn.exec_driver_sql(enable_trg)
        log.debug("Trigger work hours balance creado/actualizado (DROP+CREATE).")

def init_triggers(engine: Engine):
    init_worklogs_triggers(engine)
