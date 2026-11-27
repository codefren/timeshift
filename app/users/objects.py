from enum import Enum
from pydantic import BaseModel, Field, field_validator
from pydantic.types import PastDate
from typing import Optional, Union, List, Self
import pandas as pd


class UsersWorkedHoursArgs(BaseModel):
    start_date: PastDate
    end_date: PastDate
    user_id: Optional[Union[int, str, List[int | str]]]

    @field_validator('user_id', mode='before')
    @classmethod
    def validate_user_id(cls, v: Optional[Union[int, str, List[int | str]]]) -> Optional[List[int] | int]:
        if v is None:
            return None
        if isinstance(v, str):
            return [int(x) for x in eval(v)] if v.startswith('[') else int(v)
        return v

class WorkedHoursPeriods(str, Enum):
    day = "day"
    week = "week"
    month = "month"

class UsersWorkedHoursDetailedArgs(UsersWorkedHoursArgs):
    period: WorkedHoursPeriods = Field(WorkedHoursPeriods.day)

class WorkedHoursElements(BaseModel):
    WorkedHours: float = Field(default=0.0)
    PausedCountedHours: float = Field(default=0.0)
    PausedUncountedHours: float = Field(default=0.0)
    # Horas/días de vacaciones del periodo. Las horas YA están incluidas en
    # PausedCountedHours; se exponen aparte para que los informes las muestren.
    VacationHours: float = Field(default=0.0)
    VacationDays: int = Field(default=0)

    @classmethod
    def from_df(cls, df: pd.DataFrame) -> Self:
        return cls(WorkedHours=df.WorkedHours.sum(),
                   PausedCountedHours=df.PausedCountedHours.sum(),
                   PausedUncountedHours=df.PausedUncountedHours.sum())

class WorkedHoursElementsPeriod(WorkedHoursElements):
    Period: str | PastDate

    @classmethod
    def from_df(cls, df: pd.DataFrame) -> List[Self]:
        return [
            cls(Period=row.Period, WorkedHours=row.WorkedHours,
                PausedCountedHours=row.PausedCountedHours,
                PausedUncountedHours=row.PausedUncountedHours)
            for _, row in df.iterrows()
        ]

class UserWorkedHoursResponse(WorkedHoursElements):
    UserID: int

    @classmethod
    def from_df(cls, df: pd.DataFrame) -> List[Self]:
        return [cls(UserID=index if not 'UserID' in df.columns else row.UserID, WorkedHours=row.WorkedHours, PausedCountedHours=row.PausedCountedHours, PausedUncountedHours=row.PausedUncountedHours) for index, row in df.iterrows()]


class UserWorkedHoursDetailedResponse(UserWorkedHoursResponse):
    Period: WorkedHoursPeriods = Field(default=WorkedHoursPeriods.day)
    WorkedHoursDetailed: List[WorkedHoursElementsPeriod]

    @classmethod
    def from_df(cls, df: pd.DataFrame, period: WorkedHoursPeriods = WorkedHoursPeriods.day) -> List[Self]:
        grouped = df.groupby(['UserID']).agg({
            'WorkedHours': 'sum',
            'PausedCountedHours': 'sum',
            'PausedUncountedHours': 'sum'
        }).reset_index()

        return [cls(UserID=row.UserID, Period=period, WorkedHours=row.WorkedHours, PausedCountedHours=row.PausedCountedHours, PausedUncountedHours=row.PausedUncountedHours,
                    WorkedHoursDetailed=WorkedHoursElementsPeriod.from_df(df[df['UserID'] == row.UserID]))
                for _, row in grouped.iterrows()]


def vacation_period_key(day, period: WorkedHoursPeriods):
    """Clave de periodo con el mismo formato que usa cada informe detallado."""
    if period == WorkedHoursPeriods.week:
        iso = day.isocalendar()
        return f"{iso.year}-{iso.week}"
    if period == WorkedHoursPeriods.month:
        return f"{day.year}-{day.month:02d}"
    return day


def apply_vacations(responses: list, vac_df: pd.DataFrame, period: WorkedHoursPeriods | None = None) -> list:
    """Rellena VacationHours/VacationDays en las respuestas de horas trabajadas.

    vac_df: salida de WorkLogs.get_daily_vacation_hours (UserID, Day, VacationHours).
    period: None para el informe estándar (solo totales por usuario).
    """
    if vac_df is None or vac_df.empty:
        return responses
    for r in responses:
        user_rows = vac_df[vac_df['UserID'] == r.UserID]
        if user_rows.empty:
            continue
        r.VacationHours = float(user_rows['VacationHours'].sum())
        r.VacationDays = int(user_rows['Day'].nunique())
        if period is None or not hasattr(r, 'WorkedHoursDetailed'):
            continue
        by_key: dict = {}
        for _, row in user_rows.iterrows():
            key = vacation_period_key(row.Day, period)
            hours, days = by_key.get(key, (0.0, 0))
            by_key[key] = (hours + float(row.VacationHours), days + 1)
        seen = set()
        for d in r.WorkedHoursDetailed:
            key = d.Period
            if period == WorkedHoursPeriods.week:
                y, w = str(d.Period).split('-')
                key = f"{int(y)}-{int(w)}"
            if key in by_key:
                d.VacationHours, d.VacationDays = by_key[key]
                seen.add(key)
        # Periodos que solo contienen vacaciones y no venían en el detalle
        # (semanas antiguas sin fila en UserWeekHoursBalance)
        missing = [k for k in by_key if k not in seen]
        for key in missing:
            hours, days = by_key[key]
            r.WorkedHoursDetailed.append(WorkedHoursElementsPeriod(
                Period=key, PausedCountedHours=hours, VacationHours=hours, VacationDays=days))
            if period == WorkedHoursPeriods.week:
                r.PausedCountedHours += hours
        if missing:
            def sort_key(d):
                if period == WorkedHoursPeriods.week:
                    y, w = str(d.Period).split('-')
                    return (int(y), int(w))
                return str(d.Period)
            r.WorkedHoursDetailed.sort(key=sort_key)
    return responses
