import logging
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Self, Dict, Any
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlmodel import Session, select, and_, func
from fastapi import HTTPException

from SQLModels import Schedules, ScheduleLines, ScheduleTotals, Users
from SQLModels.Schedules import WeekDay, ScheduleTypes


class ScheduleLineRequest(BaseModel):
    """Request model for creating/updating schedule lines"""
    WeekDay: WeekDay
    StartTime: time
    EndTime: time
    DurationHours: Optional[float] = None

    @model_validator(mode='after')
    def validate_duration_hours(self) -> Self:
        """Calculate duration hours if not provided, validate if provided"""
        if self.DurationHours is not None:
            if self.DurationHours <= 0:
                raise ValueError("Duration hours must be positive")
            return self
        
        # Calculate from start and end time if not provided
        start_time = self.StartTime
        end_time = self.EndTime
        
        if start_time and end_time:
            # Convert times to datetime for calculation
            start_dt = datetime.combine(date.today(), start_time)
            end_dt = datetime.combine(date.today(), end_time)
            
            # Handle overnight shifts
            if end_dt <= start_dt:
                end_dt = datetime.combine(date.today() + timedelta(days=1), end_time)
            
            duration = (end_dt - start_dt).total_seconds() / 3600
            self.DurationHours = round(duration, 2)
        
        return self

    @model_validator(mode='after')
    def validate_time_range(self) -> Self:
        """Validate that start time is before end time (same day)"""
        if self.StartTime >= self.EndTime:
            '''# Allow overnight shifts but log a warning
            logging.getLogger(__name__).warning(
                f"Overnight shift detected: {self.StartTime} to {self.EndTime}"
            )'''
            raise ValueError("Start time must be before end time")
        return self


class ScheduleLineResponse(BaseModel):
    """Response model for schedule lines"""
    ScheduleLineID: int
    ScheduleID: int
    WeekDay: WeekDay
    StartTime: time
    EndTime: time
    DurationHours: float

    @classmethod
    def from_schedule_line(cls, schedule_line: ScheduleLines) -> Self:
        return cls(
            ScheduleLineID=schedule_line.ScheduleLineID,
            ScheduleID=schedule_line.ScheduleID,
            WeekDay=schedule_line.WeekDay,
            StartTime=schedule_line.StartTime,
            EndTime=schedule_line.EndTime,
            DurationHours=schedule_line.DurationHours
        )


class ScheduleTotalsResponse(BaseModel):
    """Response model for schedule totals"""
    ScheduleID: int
    TotalWeekWorkDays: int
    TotalWeekWorkHours: float

    @classmethod
    def from_schedule_totals(cls, schedule_totals: ScheduleTotals) -> Self:
        return cls(
            ScheduleID=schedule_totals.ScheduleID,
            TotalWeekWorkDays=schedule_totals.TotalWeekWorkDays,
            TotalWeekWorkHours=schedule_totals.TotalWeekWorkHours
        )


class ScheduleCreateRequest(BaseModel):
    """Request model for creating schedules"""
    ScheduleName: str = Field(max_length=50)
    ScheduleType: ScheduleTypes = Field(default=ScheduleTypes.FIXED)
    StartDate: date = Field(default_factory=lambda: datetime.now().date())
    EndDate: date = Field(default_factory=lambda: datetime.now().date() + timedelta(days=365*20))
    lines: List[ScheduleLineRequest] = Field(min_length=1)

    @field_validator('ScheduleName')
    @classmethod
    def validate_schedule_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Schedule name cannot be empty")
        return v.strip()

    @model_validator(mode='after')
    def validate_dates(self) -> Self:
        """Validate date range"""
        if self.EndDate < self.StartDate:
            raise ValueError("End date must be after or equal to start date")
        return self

    def create_schedule(self, db: Session, created_by: int) -> 'ScheduleCompleteResponse':
        """Create schedule with all related data"""
        log = logging.getLogger(__name__)
        
        # Check if schedule name already exists
        if Schedules.exists(db, self.ScheduleName):
            raise HTTPException(status_code=400, detail=f"Schedule '{self.ScheduleName}' already exists")
        
        # Create main schedule
        schedule = Schedules(
            ScheduleName=self.ScheduleName,
            ScheduleType=self.ScheduleType.value,
            StartDate=self.StartDate,
            EndDate=self.EndDate,
            CreatedBy=created_by,
            CreatedAt=datetime.now()
        )
        schedule._create(db)
        log.info(f"Created schedule {schedule.ScheduleID}: {self.ScheduleName}")

        # Create schedule lines
        schedule_lines = []
        total_hours = 0.0
        total_days = len(self.lines)

        for i, line_req in enumerate(self.lines):
            line = ScheduleLines(
                ScheduleLineID=i+1,
                ScheduleID=schedule.ScheduleID,
                WeekDay=line_req.WeekDay.value,
                StartTime=line_req.StartTime,
                EndTime=line_req.EndTime,
                DurationHours=line_req.DurationHours
            )
            line._create(db)
            schedule_lines.append(line)
            total_hours += line_req.DurationHours
            log.debug(f"Created schedule line for {line_req.WeekDay}: {line_req.StartTime}-{line_req.EndTime}")

        # Create schedule totals
        totals = ScheduleTotals(
            ScheduleID=schedule.ScheduleID,
            TotalWeekWorkDays=total_days,
            TotalWeekWorkHours=total_hours
        )
        totals._create(db)
        log.info(f"Created schedule totals: {total_days} days, {total_hours} hours")

        return ScheduleCompleteResponse.from_schedule(db, schedule)


class ScheduleUpdateRequest(BaseModel):
    """Request model for updating schedules"""
    ScheduleName: Optional[str] = Field(None, max_length=50)
    ScheduleType: Optional[ScheduleTypes] = None
    StartDate: Optional[date] = None
    EndDate: Optional[date] = None
    lines: Optional[List[ScheduleLineRequest]] = Field(None, min_length=1)

    @property
    def NormalizedScheduleName(self) -> Optional[str]:
        return self.normalize_schedule_name(self.ScheduleName)

    @classmethod
    def normalize_schedule_name(cls, name: str) -> Optional[str]:
        return name.strip().replace(' ', '').lower() if name else None

    @field_validator('ScheduleName')
    @classmethod
    def validate_schedule_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Schedule name cannot be empty")
        return v.strip() if v else None

    @model_validator(mode='after')
    def validate_dates(self) -> Self:
        """Validate date range if both dates are provided"""
        if self.StartDate and self.EndDate and self.EndDate < self.StartDate:
            raise ValueError("End date must be after or equal to start date")
        return self

    def update_schedule(self, db: Session, schedule_id: int) -> 'ScheduleCompleteResponse':
        """Update schedule with provided data"""
        log = logging.getLogger(__name__)
        
        # Get existing schedule
        schedule = Schedules.get(db, schedule_id)
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")

        # Check if new name conflicts with existing schedules
        if self.ScheduleName and self.NormalizedScheduleName != self.normalize_schedule_name(schedule.ScheduleName):
            if Schedules.exists(db, self.ScheduleName):
                raise HTTPException(status_code=400, detail=f"Schedule '{self.ScheduleName}' already exists")

        # Update schedule fields
        update_data = {}
        if self.ScheduleName:
            update_data['ScheduleName'] = self.ScheduleName
        if self.ScheduleType:
            update_data['ScheduleType'] = self.ScheduleType.value
        if self.StartDate:
            update_data['StartDate'] = self.StartDate
        if self.EndDate:
            update_data['EndDate'] = self.EndDate

        if update_data:
            update_data['UpdatedAt'] = datetime.now()
            schedule.update(db, **update_data)
            log.info(f"Updated schedule {schedule_id} with: {update_data}")

        # Update lines if provided
        if self.lines is not None:
            # Delete existing lines
            existing_lines = ScheduleLines.get_lines(db, schedule_id)
            for line in existing_lines:
                line.delete(db)
            log.debug(f"Deleted {len(existing_lines)} existing schedule lines")

            # Create new lines and calculate totals
            total_hours = 0.0
            total_days = len(self.lines)

            for i,line_req in enumerate(self.lines):
                line = ScheduleLines(
                    ScheduleLineID=i+1,
                    ScheduleID=schedule_id,
                    WeekDay=line_req.WeekDay.value,
                    StartTime=line_req.StartTime,
                    EndTime=line_req.EndTime,
                    DurationHours=line_req.DurationHours
                )
                line._create(db)
                total_hours += line_req.DurationHours
                log.debug(f"Created new schedule line for {line_req.WeekDay}")

            # Update totals
            totals = ScheduleTotals.get(db, schedule_id)
            if totals:
                totals.update(db, TotalWeekWorkDays=total_days, TotalWeekWorkHours=total_hours)
            else:
                totals = ScheduleTotals(
                    ScheduleID=schedule_id,
                    TotalWeekWorkDays=total_days,
                    TotalWeekWorkHours=total_hours
                )
                totals._create(db)
            log.info(f"Updated schedule totals: {total_days} days, {total_hours} hours")

        return ScheduleCompleteResponse.from_schedule(db, schedule)


class ScheduleResponse(BaseModel):
    """Basic schedule response model"""
    ScheduleID: int
    ScheduleName: str
    ScheduleType: ScheduleTypes
    StartDate: date
    EndDate: date
    CreatedBy: int
    CreatedAt: datetime

    @classmethod
    def from_schedule(cls, schedule: Schedules) -> Self:
        return cls(
            ScheduleID=schedule.ScheduleID,
            ScheduleName=schedule.ScheduleName,
            ScheduleType=schedule.ScheduleType,
            StartDate=schedule.StartDate,
            EndDate=schedule.EndDate,
            CreatedBy=schedule.CreatedBy,
            CreatedAt=schedule.CreatedAt
        )


class ScheduleCompleteResponse(BaseModel):
    """Complete schedule response with all related data"""
    schedule: ScheduleResponse
    lines: List[ScheduleLineResponse]
    totals: Optional[ScheduleTotalsResponse] = None
    creator: Optional[str] = None  # Creator name

    @classmethod
    def from_schedule(cls, db: Session, schedule: Schedules) -> Self:
        # Get schedule lines
        lines = ScheduleLines.get_lines(db, schedule.ScheduleID)
        line_responses = [ScheduleLineResponse.from_schedule_line(line) for line in lines]

        # Get schedule totals
        totals = ScheduleTotals.get(db, schedule.ScheduleID)
        totals_response = ScheduleTotalsResponse.from_schedule_totals(totals) if totals else None

        # Get creator name
        creator = Users.get(db, schedule.CreatedBy)
        creator_name = f"{creator.details.FirstName} {creator.details.LastName1}" if creator and creator.details else None

        return cls(
            schedule=ScheduleResponse.from_schedule(schedule),
            lines=line_responses,
            totals=totals_response,
            creator=creator_name
        )


class ScheduleListResponse(BaseModel):
    """Response model for schedule list with pagination"""
    schedules: List[ScheduleCompleteResponse]
    total: int
    pages: int
    current_page: int

    @classmethod
    def from_schedules(cls, db: Session, schedules: List[Schedules], total: int, pages: int, current_page: int) -> Self:
        schedule_responses = [ScheduleCompleteResponse.from_schedule(db, schedule) for schedule in schedules]
        return cls(
            schedules=schedule_responses,
            total=total,
            pages=pages,
            current_page=current_page
        )


class ScheduleService:
    """Service class for schedule business logic"""
    
    @staticmethod
    def get_schedule_by_id(db: Session, schedule_id: int) -> ScheduleCompleteResponse:
        """Get schedule by ID with all related data"""
        schedule = Schedules.get(db, schedule_id)
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        return ScheduleCompleteResponse.from_schedule(db, schedule)

    @staticmethod
    def get_schedule_by_name(db: Session, schedule_name: str) -> ScheduleCompleteResponse:
        """Get schedule by name with all related data"""
        schedule = Schedules.get_by_name(db, schedule_name)
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        return ScheduleCompleteResponse.from_schedule(db, schedule)

    @staticmethod
    def list_schedules(db: Session, page: int = 1, size: int = 50, 
                      schedule_type: Optional[ScheduleTypes] = None,
                      created_by: Optional[int] = None) -> ScheduleListResponse:
        """List schedules with optional filtering and pagination"""
        
        # Build query
        query = select(Schedules)
        
        # Apply filters
        if schedule_type:
            query = query.where(Schedules.ScheduleType == schedule_type.value)
        if created_by:
            query = query.where(Schedules.CreatedBy == created_by)
        
        # Get total count
        total_query = select(func.count(Schedules.ScheduleID))
        if schedule_type:
            total_query = total_query.where(Schedules.ScheduleType == schedule_type.value)
        if created_by:
            total_query = total_query.where(Schedules.CreatedBy == created_by)
        
        total = db.exec(total_query).first()
        pages = (total + size - 1) // size  # Ceiling division
        
        # Apply pagination
        offset = (page - 1) * size
        query = query.offset(offset).limit(size)
        query = query.order_by(Schedules.CreatedAt.desc())
        
        schedules = db.exec(query).all()
        
        return ScheduleListResponse.from_schedules(db, schedules, total, pages, page)

    @staticmethod
    def delete_schedule(db: Session, schedule_id: int) -> bool:
        """Delete schedule and all related data"""
        log = logging.getLogger(__name__)
        
        schedule = Schedules.get(db, schedule_id)
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")

        # Check if schedule is being used by any shifts
        if schedule.shifts:
            schedule.update(db, EndDate=datetime.now().date())
            log.info(f"Schedule {schedule_id} is in use, set EndDate to today")
            return True

        # Delete related data
        lines = ScheduleLines.get_lines(db, schedule_id)
        for line in lines:
            line.delete(db)
        
        totals = ScheduleTotals.get(db, schedule_id)
        if totals:
            totals.delete(db)
        
        # Delete schedule
        schedule.delete(db)
        
        log.info(f"Deleted schedule {schedule_id}: {schedule.ScheduleName}")
        return True

    @staticmethod
    def get_schedule_hours_for_date(db: Session, schedule_id: int, target_date: date) -> float:
        """Get scheduled hours for a specific date"""
        schedule = Schedules.get(db, schedule_id)
        if not schedule:
            return 0.0
        
        return schedule.get_worklog_hours(target_date)
