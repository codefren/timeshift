import logging
import traceback
from typing import List, Dict, Any
from datetime import datetime, time
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel
from sqlmodel import desc, asc
from dependencies import SessionDep, get_current_user, PaginationDep, ShiftsFiltersDep, require_permission, \
    require_any_permission
from SQLModels import (
    Users,
    Shifts,
)
from shifts.models import SingleShiftCreateRequest, ShiftUpdateRequest, ShiftResponse
from shifts.service import ShiftsService

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/shifts",
    tags=["Shifts"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}},
)

@router.post("/", response_model=Shifts | List[Shifts])
def create_single_shift(
        req: SingleShiftCreateRequest | List[SingleShiftCreateRequest],
        db: SessionDep = SessionDep,
        current_user: Users = Depends(require_any_permission(["create:Shifts", "create:OwnShifts"]))
):
    """
    Create a single or multiple shifts for one or multiple users.
    """
    cu_create_shifts_perm = current_user.has_permission("create:Shifts")
    if isinstance(req, list):
        res = []
        if not req:
            raise HTTPException(status_code=400, detail="Empty list of shifts provided")
        for shift in req:
            if not cu_create_shifts_perm and shift.user_id and shift.user_id != current_user.UserID:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"message":"No tienes permiso para crear turnos para otros usuarios"}
                )
            shift.user_id = current_user.UserID if not shift.user_id else shift.user_id
            res.append(shift.create_shift(db).model_dump(mode='python'))
            log.debug(f"Created shift {res[-1]}")
        return res

    # Check if the user has permission to create shifts for other users
    if not cu_create_shifts_perm and req.user_id and req.user_id != current_user.UserID:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message":"No tienes permiso para crear turnos para otros usuarios"}
        )
    req.user_id = current_user.UserID if not req.user_id else req.user_id
    return req.create_shift(db)


@router.get("/", response_model=Dict[str, Any])
def get_shifts(
        db: SessionDep,
        filters: ShiftsFiltersDep,
        pagination: PaginationDep,
        current_user: Users = Depends(require_permission("read:Shifts"))
):
    """
    Retrieve shifts based on filters with pagination.
    
    Filters include:
    - user_id: Filter by user ID
    - department_id: Filter by department ID
    - location_id: Filter by location ID
    - status: Filter by shift status (Planned, Confirmed, Canceled, Completed, Approved, Rejected)
    - is_published: Filter by published status
    
    Date Filtering (MUTUALLY EXCLUSIVE - only one type can be used):
    - date_from/date_to: Filter by date range
    - week_number/year_number: Filter by specific week and year
    - start_week/end_week with start_year/end_year: Filter by week range
    
    Note: You cannot combine different types of date filtering in a single request.
    """
    shifts, total_count = ShiftsService.get_shifts(db, filters, pagination, current_user)
    
    # Convert to response format
    shift_responses = [ShiftResponse.from_shift(shift) for shift in shifts]
    
    return {
        "shifts": shift_responses,
        "total_count": total_count,
        "page": pagination.page,
        "size": pagination.size,
        "total_pages": (total_count + pagination.size - 1) // pagination.size
    }


@router.put("/{shift_id}", response_model=ShiftResponse)
def update_shift(
        shift_id: int,
        update_data: ShiftUpdateRequest,
        db: SessionDep,
        current_user: Users = Depends(require_permission("update:Shifts"))
):
    """
    Update a shift by ID.
    
    Can update:
    - department_id: Will recalculate location_id if changed
    - location_id: Explicit location assignment
    - start_time: New start time
    - end_time: New end time
    - break_time: Break duration in hours
    - status: Shift status
    - is_published: Publication status
    """
    # Check if shift exists
    existing_shift = ShiftsService.get_shift_by_id(db, shift_id)
    if not existing_shift:
        raise ValueError(f"Shift with ID {shift_id} not found")

    if existing_shift.worklogs:
        raise ValueError("No se puede actualizar un turno que ya tiene registros de trabajo asociados")
    
    if isinstance(update_data.start_time, time):
        update_data.start_time = datetime.combine(existing_shift.Date, update_data.start_time)
    
    if isinstance(update_data.end_time, time):
        update_data.end_time = datetime.combine(existing_shift.Date, update_data.end_time)
    
    # Prepare update data
    update_dict = {}
    
    if update_data.department_id is not None:
        update_dict['DepartmentID'] = update_data.department_id
    
    if update_data.location_id is not None:
        update_dict['LocationID'] = update_data.location_id
    
    if update_data.start_time is not None:
        if isinstance(update_data.start_time, str):
            start_dt = datetime.fromisoformat(update_data.start_time)
        else:
            start_dt = update_data.start_time
        update_dict['Date'] = start_dt.date()
        update_dict['StartTime'] = start_dt.time()
    
    if update_data.end_time is not None:
        if isinstance(update_data.end_time, str):
            end_dt = datetime.fromisoformat(update_data.end_time)
        else:
            end_dt = update_data.end_time
        update_dict['EndTime'] = end_dt.time()
    
    if update_data.break_time is not None:
        update_dict['BreakTime'] = update_data.break_time
    
    if update_data.status is not None:
        update_dict['Status'] = update_data.status
    
    if update_data.is_published is not None:
        update_dict['IsPublished'] = update_data.is_published
    
    # Update the shift
    updated_shift = ShiftsService.update_shift(db, shift_id, current_user, **update_dict)
    
    if not updated_shift:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message":"Error al actualizar el turno"}
        )
    
    return ShiftResponse.from_shift(updated_shift)


def parse_comma_separated_ids(
    shift_ids: str = Query(
        ...,
        alias="shift_ids",
        description="IDs de turno separados por comas"
    )
) -> List[int]:
    try:
        return [int(s) for s in shift_ids.split(",") if s.strip()]
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message":"Los identificadores de turno deben ser enteros separados por comas"}
        )

@router.delete("/batch", response_model=List[ShiftResponse])
def cancel_shifts_batch(
        shift_ids: List[int] = Depends(parse_comma_separated_ids),
        db: SessionDep = SessionDep,
        current_user: Users = Depends(require_permission("delete:Shifts"))
):
    """
    Cancel multiple shifts by setting their status to 'Canceled' (soft delete).

    Provide a list of shift IDs to cancel.
    """
    if not shift_ids:
        raise HTTPException(status_code=400, detail={"message":"No se proporcionaron IDs de turno para cancelar"})

    canceled_shifts = ShiftsService.cancel_shifts_batch(db, shift_ids, current_user)

    if not canceled_shifts:
        log.error(f"Failed to cancel shifts, traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel shifts"
        )

    return [ShiftResponse.from_shift(shift) for shift in canceled_shifts]


@router.delete("/{shift_id}", response_model=ShiftResponse)
def cancel_shift(
        shift_id: int,
        db: SessionDep,
        current_user: Users = Depends(require_permission("delete:Shifts"))
):
    """
    Cancel a shift by setting its status to 'Canceled' (soft delete).
    """
    # Check if shift exists
    existing_shift = ShiftsService.get_shift_by_id(db, shift_id)
    if not existing_shift:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message":"Turno no encontrado"}
        )
    
    # Cancel the shift
    canceled_shift = ShiftsService.cancel_shift(db, shift_id, current_user)
    
    if not canceled_shift:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message":"Error al cancelar el turno"}
        )
    
    return ShiftResponse.from_shift(canceled_shift)


class DuplicateShiftsRequest(BaseModel):
    """
    Request model for duplicating shifts from source week to target week
    """
    source_week: int = Field(..., description="Número de semana origen", ge=1, le=53)
    source_year: int = Field(..., description="Año origen")
    target_week: int = Field(..., description="Número de semana destino", ge=1, le=53)
    target_year: int = Field(..., description="Año destino")
    department_id: int = Field(..., description="ID del departamento cuyos turnos serán duplicados")


@router.post("/duplicate-week", response_model=Dict[str, Any])
def duplicate_shifts_by_week(
    request: DuplicateShiftsRequest,
    db: SessionDep,
    current_user: Users = Depends(require_permission("create:Shifts"))
):
    """
    Duplica los turnos de una semana origen a una semana destino para un departamento específico.
    
    - Requiere los números de semana y año tanto de origen como de destino
    - Requiere el ID del departamento cuyos turnos se duplicarán
    - Solo duplica los turnos que no estén cancelados
    - Los turnos se crean con estado 'Planned' y sin publicar
    - No duplica turnos si hay conflictos con turnos existentes
    """
    
    # Verificar que los años son válidos (no se aceptan años pasados)
    current_year = datetime.now().year
    if request.source_year < current_year or request.target_year < current_year:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message":f"Los años deben ser iguales o superiores al año actual ({current_year})"}
        )
    
    # Verificar que el departamento existe
    # Esta validación dependería de cómo manejas los departamentos en tu aplicación
    
    try:
        # Duplicar los turnos
        new_shifts = ShiftsService.duplicate_shifts_by_week(
            db=db,
            department_id=request.department_id,
            source_week=request.source_week,
            source_year=request.source_year,
            target_week=request.target_week,
            target_year=request.target_year,
            current_user=current_user
        )
        
        # Convertir los nuevos turnos al formato de respuesta
        shift_responses = [ShiftResponse.from_shift(shift) for shift in new_shifts]
        
        return {
            "message": f"Se han duplicado {len(new_shifts)} turnos de la semana {request.source_week} a la semana {request.target_week}",
            "duplicated_shifts": shift_responses,
            "count": len(new_shifts)
        }
        
    except Exception as e:
        log.error(f"Error duplicando turnos: {str(e)}")
        log.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message":f"Error al duplicar turnos: {str(e)}"}
        )
