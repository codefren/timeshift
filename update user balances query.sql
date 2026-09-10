-------------------------------------------------------------------
-- 1) Recalcular UserWeekHoursBalance
-------------------------------------------------------------------
;WITH WeeklyStats AS (
    SELECT 
        w.UserID,
        DATEPART(ISO_WEEK, wt.StartTime)   AS WeekNumber,
        YEAR(wt.StartTime)                 AS [Year],
        SUM(
          wt.TotalWorkedHours
        ) AS WorkedHours,
        SUM(
          wt.TotalPauseCountedHours
        ) AS PausedCountedHours,
        SUM(
          wt.TotalPauseUncountedHours
        ) AS PausedUncountedHours
    FROM WorkLogs w
	LEFT JOIN WorkLogTotals wt
	  ON wt.WorkLogID = w.WorkLogID
    WHERE w.IsFinished = 1
    GROUP BY 
      w.UserID,
      DATEPART(ISO_WEEK, wt.StartTime),
      YEAR(wt.StartTime)
), 
ScheduleStats AS (
    SELECT
        s.UserID,
        DATEPART(ISO_WEEK, s.Date)      AS WeekNumber,
        YEAR(s.Date)                    AS [Year],
        SUM(
          DATEDIFF(SECOND, s.StartTime, s.EndTime) / 3600.0
          - s.BreakTime
        ) AS ScheduledHours
    FROM Shifts s
    WHERE s.Status IN ('Confirmed','Completed','Approved')
    GROUP BY 
      s.UserID,
      DATEPART(ISO_WEEK, s.Date),
      YEAR(s.Date)
)
MERGE INTO UserWeekHoursBalance AS dest
USING (
    SELECT 
        ws.UserID,
        ws.WeekNumber,
        ws.[Year],
        ws.WorkedHours,
        ws.PausedCountedHours,
        ws.PausedUncountedHours,
        ws.WorkedHours
        + ws.PausedCountedHours
        - ISNULL(ss.ScheduledHours,0)   AS BalanceHours
    FROM WeeklyStats ws
    LEFT JOIN ScheduleStats ss
      ON ss.UserID     = ws.UserID
     AND ss.WeekNumber = ws.WeekNumber
     AND ss.[Year]     = ws.[Year]
) AS src
  ON dest.UserID      = src.UserID
 AND dest.WeekNumber  = src.WeekNumber
 AND dest.[Year]      = src.[Year]
WHEN MATCHED THEN
  UPDATE SET 
    WorkedHours          = src.WorkedHours,
    PausedCountedHours   = src.PausedCountedHours,
    PausedUncountedHours = src.PausedUncountedHours,
    BalanceHours         = src.BalanceHours,
    UpdatedAt            = GETDATE()
WHEN NOT MATCHED BY TARGET THEN
  INSERT (UserID, WeekNumber, [Year], WorkedHours, PausedCountedHours, PausedUncountedHours, BalanceHours, UpdatedAt)
  VALUES (src.UserID, src.WeekNumber, src.[Year], src.WorkedHours, src.PausedCountedHours, src.PausedUncountedHours, src.BalanceHours, GETDATE())
;
-------------------------------------------------------------------
-- 2) Recalcular UserTotalHoursBalance
-------------------------------------------------------------------
;WITH TotalStats AS (
    SELECT
        w.UserID,
        SUM(CASE WHEN wl.IsPause = 0 
                 THEN DATEDIFF(SECOND, 
                               CAST(wl.StartTime AS datetime), 
                               CAST(wl.EndTime   AS datetime)
                              ) / 3600.0 
                 ELSE 0 END)              AS TotalHours,
        SUM(CASE WHEN wl.IsPause = 1 
                  AND at.IsCounted = 1 
                 THEN DATEDIFF(SECOND, 
                               CAST(wl.StartTime AS datetime), 
                               CAST(wl.EndTime   AS datetime)
                              ) / 3600.0 
                 ELSE 0 END)              AS TotalPausedCountedHours,
        SUM(CASE WHEN wl.IsPause = 1 
                  AND (at.IsCounted = 0 OR at.IsCounted IS NULL) 
                 THEN DATEDIFF(SECOND, 
                               CAST(wl.StartTime AS datetime), 
                               CAST(wl.EndTime   AS datetime)
                              ) / 3600.0 
                 ELSE 0 END)              AS TotalPausedUncountedHours
    FROM WorkLogs w
    JOIN WorkLogLines wl
      ON wl.WorkLogID = w.WorkLogID
    LEFT JOIN AbsenceTypes at
      ON at.AbsenceTypeID = wl.AbsenceType
    WHERE w.IsFinished = 1
    GROUP BY w.UserID
),
ScheduledTotal AS (
    SELECT
        s.UserID,
        SUM(
          DATEDIFF(SECOND, 
                   CAST(s.StartTime AS datetime), 
                   CAST(s.EndTime   AS datetime)
                  ) / 3600.0
          - s.BreakTime
        )                           AS ScheduledTotalHours
    FROM Shifts s
    WHERE s.Status IN ('Confirmed','Completed','Approved')
    GROUP BY s.UserID
)
MERGE INTO UserTotalHoursBalance AS dest
USING (
    SELECT
        ts.UserID,
        ts.TotalHours,
        ts.TotalPausedCountedHours,
        ts.TotalPausedUncountedHours,
        ts.TotalHours
        + ts.TotalPausedCountedHours
        - ISNULL(st.ScheduledTotalHours,0) AS BalanceHours
    FROM TotalStats ts
    LEFT JOIN ScheduledTotal st
      ON st.UserID = ts.UserID
) AS src
ON dest.UserID = src.UserID
WHEN MATCHED THEN
  UPDATE SET
    dest.TotalHours             = src.TotalHours,
    dest.TotalPausedCountedHours= src.TotalPausedCountedHours,
    dest.TotalPausedUncountedHours= src.TotalPausedUncountedHours,
    dest.BalanceHours           = src.BalanceHours,
    dest.UpdatedAt              = GETDATE()
WHEN NOT MATCHED BY TARGET THEN
  INSERT (UserID, TotalHours, TotalPausedCountedHours, TotalPausedUncountedHours, BalanceHours, UpdatedAt)
  VALUES (src.UserID, src.TotalHours, src.TotalPausedCountedHours, src.TotalPausedUncountedHours, src.BalanceHours, GETDATE())
;
