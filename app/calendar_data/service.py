import datetime
import logging
from typing import Optional

from sqlmodel import Session, select
from sqlalchemy.orm import selectinload

from SQLModels import (
    Users, UserDepartments, WorkLogs, Shifts, ShiftStatus,
    AbsenceRequests, AbsenceStatus,
)
from users.models import UserDepartmentAssignment
from shifts.models import ShiftResponse
from work_logs.models import WorkLogResponse
from absences.models import AbsenceRequestResponse
from holidays.models import HolidayResponse
from holidays.service import HolidaysService
from calendar_data.models import CalendarEmployee, CalendarDataResponse

log = logging.getLogger(__name__)


def _is_dept_active(d: UserDepartments, today: datetime.date) -> bool:
    """Asignación de departamento vigente a día de hoy."""
    return d.AssignedDate <= today and (d.DeAssignedDate is None or d.DeAssignedDate > today)


class CalendarService:

    @staticmethod
    def get_calendar_data(
        db: Session,
        current_user: Users,
        date_from: datetime.date,
        date_to: datetime.date,
        department_id: Optional[int] = None,
    ) -> CalendarDataResponse:
        today = datetime.date.today()

        # 1) Empleados visibles según permisos (excluye al propio usuario, como el
        #    endpoint de subordinados que usaba el calendario antes).
        viewable_ids = set(current_user.get_viewable_users_ids(db))
        viewable_ids.discard(current_user.UserID)
        if not viewable_ids:
            return CalendarDataResponse(employees=[], shifts=[], worklogs=[], absences=[], holidays=[])

        emps = db.exec(
            select(Users)
            .where(Users.UserID.in_(viewable_ids), Users.IsInactive == False)  # noqa: E712
            .options(selectinload(Users.departments), selectinload(Users.details))
        ).all()

        # 2) Si se filtra por tienda, quedarnos con los empleados con asignación
        #    vigente a ese departamento. "Todos" => sin filtro.
        if department_id is not None:
            emps = [
                e for e in emps
                if any(d.DeptID == department_id and _is_dept_active(d, today) for d in e.departments)
            ]

        emp_ids = [e.UserID for e in emps]
        if not emp_ids:
            return CalendarDataResponse(employees=[], shifts=[], worklogs=[], absences=[], holidays=[])

        employees = [
            CalendarEmployee(
                UserID=e.UserID,
                FirstName=e.details.FirstName if e.details else "",
                LastName1=e.details.LastName1 if e.details else "",
                LastName2=e.details.LastName2 if e.details else None,
                Role=e.details.JobTitle if e.details else None,
                IsInactive=e.IsInactive,
                Depts=[UserDepartmentAssignment.from_user_department(d) for d in e.departments],
            )
            for e in emps
        ]

        # 3) Turnos publicados (no cancelados) del rango para esos empleados.
        shift_q = (
            select(Shifts)
            .where(
                Shifts.UserID.in_(emp_ids),
                Shifts.Date >= date_from,
                Shifts.Date <= date_to,
                Shifts.IsPublished == True,  # noqa: E712
                Shifts.Status != ShiftStatus.Canceled,
            )
        )
        if department_id is not None:
            shift_q = shift_q.where(Shifts.DepartmentID == department_id)
        shifts = [ShiftResponse.from_shift(s) for s in db.exec(shift_q).all()]

        # 4) Fichajes reales del rango — SIN tope de 250 y con lines/totals/shift
        #    cargados de una vez (eager). Incluye los que siguen en curso
        #    (IsFinished=0): es justo lo que el calendario debe mostrar.
        worklogs_rows = db.exec(
            select(WorkLogs)
            .where(
                WorkLogs.UserID.in_(emp_ids),
                WorkLogs.LogDate >= date_from,
                WorkLogs.LogDate <= date_to,
            )
            .options(
                selectinload(WorkLogs.lines),
                selectinload(WorkLogs.totals),
                selectinload(WorkLogs.shift),
            )
        ).all()
        worklogs = [
            WorkLogResponse(worklog=w, lines=w.lines, totals=w.totals, shift=w.shift)
            for w in worklogs_rows
        ]

        # 5) Ausencias aprobadas que solapen el rango visible.
        from_dt = datetime.datetime.combine(date_from, datetime.time.min)
        to_dt = datetime.datetime.combine(date_to, datetime.time.max)
        absences_rows = db.exec(
            select(AbsenceRequests)
            .where(
                AbsenceRequests.UserID.in_(emp_ids),
                AbsenceRequests.Status == AbsenceStatus.APPROVED,
                AbsenceRequests.StartTime <= to_dt,
                AbsenceRequests.EndTime >= from_dt,
            )
            .options(
                selectinload(AbsenceRequests.user).selectinload(Users.details),
                selectinload(AbsenceRequests.absence_type),
                selectinload(AbsenceRequests.review),
            )
        ).all()
        absences = [AbsenceRequestResponse.from_request(r) for r in absences_rows]

        # 6) Festivos del rango (reutiliza el servicio existente).
        holidays = [HolidayResponse.from_holiday(h) for h in HolidaysService.list_holidays(db, date_from, date_to)]

        return CalendarDataResponse(
            employees=employees,
            shifts=shifts,
            worklogs=worklogs,
            absences=absences,
            holidays=holidays,
        )
