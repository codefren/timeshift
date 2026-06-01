from typing import List, Optional, Iterable
import datetime
from pydantic import BaseModel, field_validator, Field, model_validator, NaiveDatetime
from SQLModels import WorkLogLines, WorkLogs, WorkLogTotals, Shifts
from users.objects import UserWorkedHoursResponse

class WorkLogResponse(BaseModel):
    worklog: WorkLogs
    lines: List[WorkLogLines] = None
    totals: Optional[WorkLogTotals] = None
    shift: Optional[Shifts] = None

class WorkLogDeletedResponse(BaseModel):
    deleted_worklog : int

class WorkLogListResponse(BaseModel):
    worklogs: Iterable[WorkLogResponse | WorkLogs]
    aggregated: Optional[UserWorkedHoursResponse] = None
    total: int
    pages: int

    @field_validator('worklogs', mode='before')
    def convert_worklogs(cls, v: Iterable[WorkLogResponse | WorkLogs]) -> List[WorkLogResponse]:
        """Convert worklogs to WorkLogResponse objects."""
        if v and isinstance(v[0], WorkLogResponse):
            return v
        return [WorkLogResponse(worklog=wl, lines=wl.lines, totals=wl.totals) for wl in v]

class PauseRequest(BaseModel):
    """Request model for pause periods"""
    start_time: datetime.time
    end_time: datetime.time
    absence_type: int

class WorkLogUpdateRequest(BaseModel):
    """Request model for updating worklogs"""
    start_datetime: NaiveDatetime
    end_datetime: NaiveDatetime
    dept_id: Optional[int] = None
    pauses: List[PauseRequest] = Field(default_factory=list)
    reason: str = Field(description="Reason for the modification")

    @model_validator(mode='after')
    def validate_time_range(self):
        """Validate that start_datetime is before end_datetime"""
        if self.start_datetime >= self.end_datetime:
            raise ValueError("start_datetime must be before end_datetime")
        if self.pauses:
            self.pauses.sort(key=lambda x: x.start_time)
            last_end = self.start_datetime.time()
            for pause in self.pauses:
                if pause.start_time >= pause.end_time:
                    raise ValueError("pause start_time must be before end_time")
                if pause.start_time >= self.end_datetime.time() or pause.start_time <= last_end or pause.end_time > self.end_datetime.time():
                    raise ValueError("pause times must be within worklog time range and pauses must not overlap")
                last_end = pause.end_time


        return self

class WorkLogAuditResponse(BaseModel):
    """Response model for worklog audit trail"""
    worklog_id: int
    total_modifications: int
    modifications: List[dict]