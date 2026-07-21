import datetime
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from dependencies import SessionDep, get_current_user, require_permission
from SQLModels import Users
from calendar_data.models import CalendarDataResponse
from calendar_data.service import CalendarService

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/calendar",
    tags=["Calendar"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}},
)


@router.get("/", response_model=CalendarDataResponse)
def get_calendar_data(
    db: SessionDep,
    date_from: datetime.date = Query(..., description="Primer día visible (YYYY-MM-DD)"),
    date_to: datetime.date = Query(..., description="Último día visible (YYYY-MM-DD)"),
    department_id: Optional[int] = Query(None, description="Filtra a una tienda; omitir = todas"),
    current_user: Users = Depends(require_permission("read:Shifts")),
) -> CalendarDataResponse:
    """Carga única del calendario: empleados visibles + turnos + fichajes reales
    + ausencias aprobadas + festivos, todo acotado al rango de fechas y, si se
    indica, al departamento. Sustituye a las 4 llamadas separadas y elimina el
    tope de 250 fichajes de `/api/worklogs/`.
    """
    return CalendarService.get_calendar_data(db, current_user, date_from, date_to, department_id)
