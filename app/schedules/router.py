import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException, Path
from sqlmodel import Session

from dependencies import SessionDep, get_current_user, require_permission
from SQLModels import Users
from SQLModels.Schedules import ScheduleTypes
from .models import (
    ScheduleCreateRequest,
    ScheduleUpdateRequest,
    ScheduleCompleteResponse,
    ScheduleListResponse,
    ScheduleService
)

router = APIRouter(
    prefix="/api/schedules",
    tags=["Schedules"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}},
)

logger = logging.getLogger(__name__)


@router.post("/", response_model=ScheduleCompleteResponse)
def create_schedule(
    db: SessionDep,
    schedule_request: ScheduleCreateRequest,
    current_user: Users = Depends(require_permission("manage:Schedules")),
):
    """
    Create a new schedule with lines and totals.
    
    Requires 'manage:Schedules' permission.
    """
    logger.info(f"User {current_user.UserID} creating schedule: {schedule_request.ScheduleName}")
    return schedule_request.create_schedule(db, current_user.UserID)


@router.get("/", response_model=ScheduleListResponse)
def get_schedules(
    db: SessionDep,
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(50, ge=1, le=100, description="Page size"),
    schedule_type: Optional[ScheduleTypes] = Query(None, description="Filter by schedule type"),
    created_by: Optional[int] = Query(None, description="Filter by creator user ID"),
    current_user: Users = Depends(require_permission("view:Schedules")),
):
    """
    Get list of schedules with optional filtering and pagination.
    
    Filters:
    - schedule_type: Filter by Fixed or Variable schedules
    - created_by: Filter by creator user ID
    """
    logger.debug(f"User {current_user.UserID} requesting schedules list")
    return ScheduleService.list_schedules(db, page, size, schedule_type, created_by)


@router.get("/{schedule_id}/", response_model=ScheduleCompleteResponse)
def get_schedule_by_id(
    schedule_id: int = Path(..., description="Schedule ID"),
    db: SessionDep = SessionDep,
    current_user: Users = Depends(require_permission("view:Schedules")),
):
    """
    Get a specific schedule by ID with all related data (lines, totals, creator).
    """
    logger.debug(f"User {current_user.UserID} requesting schedule {schedule_id}")
    return ScheduleService.get_schedule_by_id(db, schedule_id)


@router.get("/by-name/{schedule_name}/", response_model=ScheduleCompleteResponse)
def get_schedule_by_name(
    schedule_name: str = Path(..., description="Schedule name"),
    db: SessionDep = SessionDep,
    current_user: Users = Depends(require_permission("view:Schedules")),
):
    """
    Get a specific schedule by name with all related data (lines, totals, creator).
    """
    logger.debug(f"User {current_user.UserID} requesting schedule by name: {schedule_name}")
    return ScheduleService.get_schedule_by_name(db, schedule_name)


@router.put("/{schedule_id}/", response_model=ScheduleCompleteResponse)
def update_schedule(
    schedule_id: int = Path(..., description="Schedule ID"),
    schedule_request: ScheduleUpdateRequest = ...,
    db: SessionDep = SessionDep,
    current_user: Users = Depends(require_permission("manage:Schedules")),
):
    """
    Update an existing schedule.
    
    Can update:
    - Basic schedule information (name, type, dates)
    - Schedule lines (replaces all existing lines)
    - Automatically recalculates totals when lines are updated
    
    Requires 'manage:Schedules' permission.
    """
    logger.info(f"User {current_user.UserID} updating schedule {schedule_id}")
    return schedule_request.update_schedule(db, schedule_id)


@router.delete("/{schedule_id}/")
def delete_schedule(
    schedule_id: int = Path(..., description="Schedule ID"),
    db: SessionDep = SessionDep,
    current_user: Users = Depends(require_permission("manage:Schedules")),
):
    """
    Delete a schedule and all related data (lines, totals).
    
    Will fail if the schedule is currently being used by any shifts.
    
    Requires 'manage:Schedules' permission.
    """
    logger.info(f"User {current_user.UserID} deleting schedule {schedule_id}")
    ScheduleService.delete_schedule(db, schedule_id)
    return {"message": f"Schedule {schedule_id} deleted successfully"}


@router.get("/{schedule_id}/hours/{target_date}/")
def get_schedule_hours_for_date(
    schedule_id: int = Path(..., description="Schedule ID"),
    target_date: str = Path(..., description="Target date (YYYY-MM-DD)"),
    db: SessionDep = SessionDep,
    current_user: Users = Depends(require_permission("view:Schedules")),
):
    """
    Get the scheduled work hours for a specific date.
    
    Returns the hours based on the day of the week and schedule lines.
    """
    try:
        from datetime import datetime
        parsed_date = datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    logger.debug(f"User {current_user.UserID} requesting hours for schedule {schedule_id} on {target_date}")
    hours = ScheduleService.get_schedule_hours_for_date(db, schedule_id, parsed_date)
    
    return {
        "schedule_id": schedule_id,
        "date": target_date,
        "scheduled_hours": hours
    }


@router.get("/types/")
def get_schedule_types(current_user: Users = Depends(get_current_user)):
    """
    Get available schedule types.
    """
    return {
        "schedule_types": [
            {"value": schedule_type.value, "name": schedule_type.name}
            for schedule_type in ScheduleTypes
        ]
    }


@router.get("/weekdays/")
def get_weekdays(current_user: Users = Depends(get_current_user)):
    """
    Get available weekdays for schedule lines.
    """
    from SQLModels.Schedules import WeekDay
    return {
        "weekdays": [
            {"value": weekday.value, "name": weekday.name}
            for weekday in WeekDay
        ]
    }
