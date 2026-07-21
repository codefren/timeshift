from typing import List, Optional
from pydantic import BaseModel

from users.models import UserDepartmentAssignment
from shifts.models import ShiftResponse
from work_logs.models import WorkLogResponse
from absences.models import AbsenceRequestResponse
from holidays.models import HolidayResponse


class CalendarEmployee(BaseModel):
    """Empleado tal como lo consume el calendario: identidad + pertenencia a
    departamentos vigente (para pintar filas y, en cliente, agrupar por tienda)."""
    UserID: int
    FirstName: str
    LastName1: str
    LastName2: Optional[str] = None
    Role: Optional[str] = None
    IsInactive: bool = False
    Depts: List[UserDepartmentAssignment]


class CalendarDataResponse(BaseModel):
    """Payload único del calendario: reemplaza las 4 llamadas separadas
    (shifts / worklogs / absences / holidays) + la de empleados.

    Todo viene ya acotado en el servidor al rango de fechas, a los empleados
    visibles del usuario y, si se indica `department_id`, a esa tienda.
    """
    employees: List[CalendarEmployee]
    shifts: List[ShiftResponse]
    worklogs: List[WorkLogResponse]
    absences: List[AbsenceRequestResponse]
    holidays: List[HolidayResponse]
