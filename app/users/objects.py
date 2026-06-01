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
