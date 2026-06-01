from datetime import datetime, time, date
from typing import List, Optional, Iterable
from calendar import monthrange

from fastapi import HTTPException, Query
from pydantic import BaseModel, field_validator, Field, model_validator
from pydantic.types import datetime as datetype
from sqlmodel import Session

from SQLModels import Shifts, ShiftStatus, WorkLogs, Departments


class SingleShiftCreateRequest(BaseModel):
    """Esquema para la creación de un solo turno"""
    start_time: str | datetime = Field(default_factory=datetime.now().isoformat)
    end_time: str | datetime
    user_id: Optional[int] = Field(default=None)
    department_id: int
    publish: bool = Field(default=True)
    status: ShiftStatus = Field(default=ShiftStatus.Planned)
    related_worklog_id: Optional[int] = Field(default=None)
    location_id: Optional[int] = Field(default=None)
    schedule_id: Optional[int] = Field(default=None)
    break_time: Optional[int] = Field(default=0)
    created_by: Optional[int] = Field(default=None)

    @field_validator('start_time', 'end_time')
    def validate_time_format(cls, v):
        """Valida el formato de la hora"""
        try:
            return datetime.fromisoformat(v) if isinstance(v, str) else v
        except ValueError:
            raise ValueError("El formato de la hora debe ser ISO")

    def create_shift(self, db:Session) -> Shifts:
        if not self.user_id:
            raise HTTPException(
                status_code=400,
                detail="El ID de usuario no ha sido encontrado"
            )
        self.status = ShiftStatus.Confirmed if self.related_worklog_id else ShiftStatus.Planned
        work_log = WorkLogs.get(db, self.related_worklog_id) if self.related_worklog_id else None
        if not work_log and self.related_worklog_id:
            raise HTTPException(
                status_code=400,
                detail="El ID de registro de trabajo no ha sido encontrado"
            )
        if work_log and work_log.ShiftID:
            return Shifts.get(db, work_log.ShiftID)[0]

        if not self.location_id:
            self.location_id = Departments.get(db, self.department_id)
            if not self.location_id:
                raise HTTPException(
                    status_code=400,
                    detail="El ID de departamento no ha sido encontrado"
                )
            self.location_id = self.location_id.LocationID

        shift = Shifts.create(db,
                      UserID=self.user_id,
                      DepartmentID=self.department_id,
                      LocationID=self.location_id,
                      ScheduleID=self.schedule_id,
                      Date=self.start_time.date(),
                      StartTime=self.start_time.time(),
                      EndTime=self.end_time.time(),
                      BreakTime=self.break_time,
                      IsPublished=self.publish,
                      Status=self.status,
                      CreatedBy=self.created_by or self.user_id,
                      )

        work_log.update(db, ShiftID=shift.ShiftID) if self.related_worklog_id else None

        return shift


class ShiftUpdateRequest(BaseModel):
    """Schema for updating a shift"""
    department_id: Optional[int] = None
    location_id: Optional[int] = None
    start_time: Optional[str | datetime | time] = None
    end_time: Optional[str | datetime | time] = None
    break_time: Optional[float] = Field(None, ge=0)
    status: Optional[ShiftStatus] = None
    is_published: Optional[bool] = None
    
    @field_validator('start_time', 'end_time')
    def validate_time_format(cls, v):
        """Validate time format"""
        if v is None:
            return v
        try:
            return datetime.fromisoformat(v) if isinstance(v, str) and len(v) > 5 else time.fromisoformat(v) if isinstance(v, str) and len(v) == 5 else v
        except ValueError:
            raise ValueError("Time format must be ISO")
    
    @model_validator(mode='after')
    def validate_time_range(self):
        """Validate that start_time is before end_time"""
        if self.start_time and self.end_time:
            start = self.start_time if isinstance(self.start_time, datetime) or isinstance(self.start_time, time) else datetime.fromisoformat(self.start_time)
            end = self.end_time if isinstance(self.end_time, datetime) or isinstance(self.end_time, time) else datetime.fromisoformat(self.end_time)
            
            if start >= end:
                raise ValueError("start_time must be before end_time")
        
        return self


class ShiftResponse(BaseModel):
    """Response schema for shift data"""
    shift_id: int
    user_id: int
    department_id: int
    location_id: Optional[int]
    schedule_id: Optional[int]
    date: date
    start_time: time
    end_time: time
    break_time: float
    is_published: bool
    status: ShiftStatus
    created_by: int
    created_at: datetime
    updated_at: datetime
    total_hours: float
    
    @classmethod
    def from_shift(cls, shift: Shifts) -> 'ShiftResponse':
        """Create response from Shifts model"""
        return cls(
            shift_id=shift.ShiftID,
            user_id=shift.UserID,
            department_id=shift.DepartmentID,
            location_id=shift.LocationID,
            schedule_id=shift.ScheduleID,
            date=shift.Date,
            start_time=shift.StartTime,
            end_time=shift.EndTime,
            break_time=shift.BreakTime,
            is_published=shift.IsPublished,
            status=shift.Status,
            created_by=shift.CreatedBy,
            created_at=shift.CreatedAt,
            updated_at=shift.UpdatedAt,
            total_hours=shift.total_hours()
        )