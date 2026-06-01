import datetime
import os
from datetime import timedelta
import logging
from typing import List, Sequence, Optional, Union
from fastapi import APIRouter, Depends, Query, HTTPException, Response, status
from pydantic import BaseModel
from sqlmodel import desc, asc, select, or_
from dependencies import SessionDep, get_current_user, PaginationDep, WorkLogFiltersDep, require_permission
from SQLModels import (
    Users,
    WorkLogs,
    WorkLogLines, Departments,
    WorkLogTotals, AbsenceTypes, WorkLogsList, WorkLogOperations, OperationTypes, Shifts, ShiftStatus
)
from .models import WorkLogResponse, WorkLogListResponse, WorkLogDeletedResponse, WorkLogUpdateRequest, WorkLogAuditResponse
from services.worklog_audit_service import WorkLogAuditService
from users.objects import UserWorkedHoursResponse

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/worklogs",
    tags=["WorkLogs"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}},
)


@router.get("/status/", response_model=WorkLogResponse)
def get_actual_worklog(db: SessionDep, user: Users = Depends(get_current_user)) -> WorkLogResponse:
    work_log = WorkLogs.get_actual_worklog(db, user.UserID)
    if work_log is None:
        raise HTTPException(status_code=404, detail="No active worklog found")
    return WorkLogResponse(worklog=work_log, lines=work_log.lines)


@router.get("/", response_model=WorkLogListResponse)
def get_worklogs(db: SessionDep,
                 params: PaginationDep,
                 filters: WorkLogFiltersDep,
                 ) -> WorkLogListResponse:
    params.order = desc if params.order == "desc" else asc
    wls = WorkLogs.list(db, params, filters)
    agg = None

    if filters.show_aggregated:
        start_date = filters.log_after or filters.log_date
        end_date = filters.log_before or filters.log_date
        agg = WorkLogs.get_worked_hours(db, start_date, end_date, filters.user_id)
        logger.debug(f"Aggregated worked hours for {start_date} to {end_date}, with result: {len(agg)}")
        agg = UserWorkedHoursResponse.from_df(agg)[0] if not agg.empty else None

    return WorkLogListResponse(worklogs=[
        WorkLogResponse(worklog=w, lines=w.lines, totals=w.totals, shift=w.shift) for w in wls.worklogs],
        aggregated=agg,
        pages=wls.pages,
        total=wls.total)


@router.post("/start/", response_model=WorkLogResponse)
def start_worklog(db: SessionDep,
                  dept_id: Optional[int] = Query(None),
                  latitude: Optional[float] = Query(None),
                  longitude: Optional[float] = Query(None),
                  ip: Optional[str] = Query(None),
                  start_datetime: datetime.datetime = Query(default_factory=datetime.datetime.now,
                                                            alias="start_datetime"),
                  cancel_if_no_shift: bool = Query(False),
                  user: Users = Depends(get_current_user)) -> WorkLogResponse | Response:
    shift = Shifts.get_actual(db, user.UserID,
                              day=start_datetime.date(),
                              before=(start_datetime-timedelta(minutes=os.environ.get("SHIFT_BEFORE_MINUTES_MARGIN",15))).time())
    if shift is None and cancel_if_no_shift:
        return Response(status_code=status.HTTP_204_NO_CONTENT)


    dept = Departments.get(db, dept_id) if dept_id else None if shift is None else shift.department
    if dept and dept.ForceLocation and (not latitude or not longitude):
        raise HTTPException(status_code=400, detail="Se requiere la ubicación para este departamento y no ha sido proporcionada")
    elif dept and dept.ForceLocation and not dept.is_in_location(latitude, longitude):
        raise HTTPException(status_code=400, detail="No puedes fichar desde fuera de la ubicación del departamento, comprueba tu ubicación e inténtalo de nuevo")
    work_log = WorkLogs.create_worklog(db, user.UserID, log_date=start_datetime, shift_id=shift.ShiftID if shift else None,)
    if work_log is None:
        raise HTTPException(status_code=404, detail="Error creando el registro de trabajo, ¿tienes ya uno abierto?")
    if latitude is not None and longitude is not None and ip is not None:
        logger.debug(f"Creating START operation for worklog {work_log.WorkLogID}")
        operation = WorkLogOperations(WorkLogID=work_log.WorkLogID, Lat=latitude,
                                      Long=longitude, IpAddr=ip, Operation=OperationTypes.START)
        operation.create(db)
    if shift:
        shift.Status = ShiftStatus.Confirmed
        db.add(shift)
        db.commit()
    return WorkLogResponse(worklog=work_log, lines=work_log.lines)


@router.post("/{worklog_id}/pause/", response_model=WorkLogResponse)
def pause_worklog(db: SessionDep,
                  worklog_id: int,
                  current_user: Users = Depends(get_current_user),
                  pause_time: datetime.time = Query(default_factory=lambda: datetime.datetime.now().time(),
                                                    alias="pause_time"),
                  absence_type: int = Query(alias="absence_type"),
                  ) -> WorkLogResponse:
    if not AbsenceTypes.exists(db, absence_type):
        raise HTTPException(status_code=404, detail="Absence type not found")
    work_log = WorkLogs.pause_worklog(db, worklog_id, current_user.UserID, pause_time, absence_type)
    if work_log is None:
        raise HTTPException(status_code=404, detail="Worklog not found or already paused")

    return WorkLogResponse(worklog=work_log, lines=work_log.lines)


@router.post("/{worklog_id}/resume/", response_model=WorkLogResponse)
def resume_worklog(db: SessionDep,
                   worklog_id: int,
                   current_user: Users = Depends(get_current_user),
                   resume_time: datetime.time = Query(default_factory=lambda: datetime.datetime.now().time(),
                                                      alias="resume_time"),
                   ) -> WorkLogResponse:
    work_log = WorkLogs.resume_worklog(db, worklog_id, current_user.UserID, resume_time)
    if work_log is None:
        raise HTTPException(status_code=404, detail="Worklog not found or already resumed")
    return WorkLogResponse(worklog=work_log, lines=work_log.lines)


@router.post("/{worklog_id}/end/", response_model=Union[WorkLogDeletedResponse, WorkLogResponse])
def end_worklog(db: SessionDep,
                worklog_id: int,
                dept_id: Optional[int] = Query(None),
                latitude: Optional[float] = Query(None),
                longitude: Optional[float] = Query(None),
                ip: Optional[str] = Query(None),
                current_user: Users = Depends(get_current_user),
                end_time: datetime.time = Query(default_factory=lambda: datetime.datetime.now().time(),
                                                alias="end_time"),
                restore_to_shift_end: bool = Query(False, alias="restore_to_shift_end"),
                delete_if_less_than_minutes: int = Query(5, alias="delete_if_less_than_minutes")
                ) -> Union[WorkLogDeletedResponse, WorkLogResponse]:
    worklog = WorkLogs.get(db, worklog_id)
    if worklog is None:
        raise HTTPException(status_code=404, detail="Worklog not found")

    ddate = datetime.datetime.today().date()
    if worklog.lines and 0 < delete_if_less_than_minutes < 60:
        logger.debug(f"Checking if worklog {worklog_id} should be deleted due to short duration")
        dt1 = datetime.datetime.combine(worklog.LogDate, worklog.lines[0].StartTime)
        dt2 = datetime.datetime.combine(ddate, end_time)
        if (dt2 - dt1).total_seconds() < delete_if_less_than_minutes * 60:
            logger.debug(f"Deleting worklog {worklog_id} due to short duration")
            worklog.complete_removal(db)
            return WorkLogDeletedResponse(deleted_worklog=worklog_id)
        logger.debug(f"Worklog {worklog_id} duration is sufficient, not deleting")
    if worklog.shift is not None:
        theoric_start_time = datetime.datetime.combine(worklog.LogDate, worklog.shift.StartTime)
        delta = timedelta(hours=worklog.shift.EndTime.hour, minutes=worklog.shift.EndTime.minute,
                          seconds=worklog.shift.EndTime.second)
        theoric_end_time = theoric_start_time + delta
        real_end_time = datetime.datetime.combine(datetime.date.today(), end_time)
        if real_end_time > theoric_end_time and (
                (worklog.shift.department.ForceLocation and
                 not worklog.shift.is_in_location(latitude, longitude)
                ) or
                restore_to_shift_end
        ):
            end_time = theoric_end_time.time()
        if real_end_time > theoric_end_time and ddate > worklog.LogDate:
            end_time = None

    work_log = WorkLogs.finish_worklog(db, worklog_id, current_user.UserID, end_time)
    if work_log is None:
        raise HTTPException(status_code=404, detail="Worklog not found or already ended")
    if latitude is not None and longitude is not None and ip is not None:
        logger.debug(f"Creating END operation for worklog {work_log.WorkLogID}")
        operation = WorkLogOperations(WorkLogID=work_log.WorkLogID, Lat=latitude,
                                      Long=longitude, IpAddr=ip, Operation=OperationTypes.END)
        operation.create(db)
    return WorkLogResponse(worklog=work_log, lines=work_log.lines)

@router.put("/{worklog_id}/", response_model=WorkLogResponse)
def update_worklog(
    db: SessionDep,
    worklog_id: int,
    update_request: WorkLogUpdateRequest,
    current_user: Users = Depends(require_permission("manage:Shifts"))
) -> WorkLogResponse:
    """
    Update an existing worklog with comprehensive audit trail tracking.
    
    This endpoint allows modification of:
    - Start and end datetime
    - Department assignment
    - Pause periods with absence types
    
    All changes are tracked in the audit trail for compliance and history.
    """
    # Get the existing worklog
    worklog = WorkLogs.get(db, worklog_id)
    if not worklog:
        raise HTTPException(status_code=404, detail="Worklog no encontrado")

    if not worklog.IsFinished:
        raise HTTPException(status_code=400, detail="Solo se pueden modificar los registros de trabajo finalizados")

    if worklog.UserID == current_user.UserID:
        raise HTTPException(status_code=403, detail="No puedes modificar tus propios registros de trabajo")

    # Check if user can modify this worklog (must be a subordinate)
    manageable_user_ids = current_user.get_manageable_users_ids(db)
    if worklog.UserID not in manageable_user_ids:
        raise HTTPException(status_code=403, detail="Este registro de trabajo pertenece a un usuario que no gestionas")
    
    # Validate department exists
    department = Departments.get(db, update_request.dept_id) if update_request.dept_id else None
    if update_request.dept_id and not department:
        raise HTTPException(status_code=404, detail="Departamento no encontrado")
    
    # Validate absence types for pauses
    for pause in update_request.pauses:
        if not AbsenceTypes.exists(db, pause.absence_type):
            raise HTTPException(status_code=404, detail=f"Tipo de ausencia {pause.absence_type} no encontrado")
    
    # Store original state for audit trail
    original_lines = list(worklog.lines)
    original_totals = worklog.totals
    
    # Extract log date from start_datetime
    log_date = update_request.start_datetime.date()
    
    # edit the shift associated
    if worklog.shift and update_request.dept_id:
        shift = worklog.shift
        shift.update(db, DepartmentID=department.DeptID, LocationID=department.LocationID)
    else:
        shift = None



    # Capture worklog-level changes
    worklog_changes = {
        'log_date': log_date,
        'shift_id': shift.ShiftID if shift else None,
        'start_datetime': update_request.start_datetime,
        'end_datetime': update_request.end_datetime,
        'dept_id': update_request.dept_id,
        'pauses': update_request.pauses
    }
    
    # Create audit records for worklog changes
    WorkLogAuditService.capture_worklog_changes(
        db=db,
        worklog_id=worklog_id,
        modified_by_user_id=current_user.UserID,
        old_worklog=worklog,
        new_data=worklog_changes,
        reason=update_request.reason
    )
    
    # Apply worklog-level changes
    worklog.update(db, **{
        'LogDate': log_date,
        'ShiftID': shift.ShiftID if shift else None,
    })
    
    # Build new lines structure
    new_lines_data = []
    line_id = 1
    
    # Add main work period (start to first pause or end)
    current_time = update_request.start_datetime.time()
    
    # Sort pauses by start time
    sorted_pauses = sorted(update_request.pauses, key=lambda p: p.start_time)
    
    for pause in sorted_pauses:
        # Add work period before this pause
        if current_time < pause.start_time:
            new_lines_data.append({
                'WorkLogLineID': line_id,
                'start_time': current_time,
                'end_time': pause.start_time,
                'is_pause': False,
                'absence_type': None
            })
            line_id += 1
        
        # Add the pause period
        new_lines_data.append({
            'WorkLogLineID': line_id,
            'start_time': pause.start_time,
            'end_time': pause.end_time,
            'is_pause': True,
            'absence_type': pause.absence_type
        })
        line_id += 1
        current_time = pause.end_time
    
    # Add final work period (after last pause to end)
    if current_time < update_request.end_datetime.time():
        new_lines_data.append({
            'WorkLogLineID': line_id,
            'start_time': current_time,
            'end_time': update_request.end_datetime.time(),
            'is_pause': False,
            'absence_type': None
        })
    
    # Create audit records for line changes
    WorkLogAuditService.capture_line_changes(
        db=db,
        worklog_id=worklog_id,
        modified_by_user_id=current_user.UserID,
        old_lines=original_lines,
        new_lines_data=new_lines_data,
        reason=update_request.reason
    )
    
    # Apply line changes
    # Remove all existing lines
    for line in worklog.lines:
        line.delete(db)
    
    # Create new lines
    new_lines = []
    for line_data in new_lines_data:
        # Calculate logged hours
        start_dt = datetime.datetime.combine(log_date, line_data['start_time'])
        end_dt = datetime.datetime.combine(log_date, line_data['end_time'])
        logged_hours = (end_dt - start_dt).total_seconds() / 3600
        
        new_line = WorkLogLines(
            WorkLogID=worklog_id,
            WorkLogLineID=line_data['WorkLogLineID'],
            StartTime=line_data['start_time'],
            EndTime=line_data['end_time'],
            IsPause=line_data['is_pause'],
            AbsenceType=line_data['absence_type'],
            LoggedHours=logged_hours
        )
        new_line = new_line._create(db)
        new_lines.append(new_line)
    
    worklog.lines = new_lines
    
    # Mark worklog as finished and recalculate totals
    worklog.update(db, IsFinished=True)
    
    # Delete existing totals
    if worklog.totals:
        worklog.totals.delete(db)
    
    # Create new totals
    new_totals = worklog.create_totals(db)
    
    # Create audit record for totals recalculation
    WorkLogAuditService.capture_totals_recalculation(
        db=db,
        worklog_id=worklog_id,
        modified_by_user_id=current_user.UserID,
        old_totals=original_totals,
        new_totals=new_totals,
        reason=f"Totals recalculated due to worklog modifications. {update_request.reason}".strip()
    )
    
    # Refresh worklog to get updated relationships
    db.refresh(worklog)
    
    logger.info(f"Worklog {worklog_id} updated by user {current_user.UserID}. Reason: {update_request.reason}")
    
    return WorkLogResponse(worklog=worklog, lines=worklog.lines, totals=worklog.totals, shift=worklog.shift)


@router.get("/{worklog_id}/audit/", response_model=WorkLogAuditResponse)
def get_worklog_audit_trail(
    db: SessionDep,
    worklog_id: int,
    limit: int = Query(50, description="Maximum number of audit records to return"),
    current_user: Users = Depends(get_current_user)
) -> WorkLogAuditResponse:
    """
    Get the complete audit trail for a specific worklog.
    
    Returns all modifications made to the worklog and its lines,
    including who made the changes, when, and what was changed.
    """
    # Verify worklog exists
    worklog = WorkLogs.get(db, worklog_id)
    if not worklog:
        raise HTTPException(status_code=404, detail="Worklog not found")
    
    # Check if user has permission to view audit trail
    # For now, users can only view audit trails for their own worklogs
    if worklog.UserID != current_user.UserID:
        raise HTTPException(status_code=403, detail="You can only view audit trails for your own worklogs")
    
    # Get comprehensive modification summary
    audit_summary = WorkLogAuditService.get_worklog_modification_summary(
        db=db,
        worklog_id=worklog_id,
        limit=limit
    )
    
    return WorkLogAuditResponse(**audit_summary)


@router.get("/absence-types/", response_model=Optional[Sequence[AbsenceTypes]])
def get_absence_types(db: SessionDep) -> Sequence[AbsenceTypes] | None:
    return AbsenceTypes.get_all(db)


@router.delete("/date-range/", response_model=List[int])
def delete_worklogs_by_date_range(
    db: SessionDep,
    start_date: datetime.date = Query(..., description="Start date of the range to delete worklogs"),
    end_date: datetime.date = Query(..., description="End date of the range to delete worklogs"),
    only_current_user: bool = Query(True, description="If True, only delete worklogs for the current user"),
    current_user: Users = Depends(require_permission("delete:Worklogs"))
) -> List[int]:
    """
    Delete all worklogs within the specified date range.
    This endpoint will delete all worklog data and related entities (lines, operations, totals).
    """
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="Start date must be before or equal to end date")
    
    # Get all worklogs within the date range for the current user
    query = select(WorkLogs).where(
        WorkLogs.LogDate >= start_date,
        WorkLogs.LogDate <= end_date
    )
    if only_current_user:
        logger.debug(f"Filtering worklogs for user {current_user.UserID} in date range {start_date} to {end_date}")
        query = query.where(WorkLogs.UserID == current_user.UserID)

    worklogs = db.exec(query).all()
    
    if not worklogs:
        raise HTTPException(status_code=404, detail="No worklogs found in the specified date range")
    
    deleted_ids = []
    
    # Delete each worklog and its related entities
    for worklog in worklogs:
        worklog_id = worklog.WorkLogID
        worklog.complete_removal(db)
        deleted_ids.append(worklog_id)
    
    return deleted_ids
