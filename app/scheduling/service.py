"""Orquestación del auto-scheduler: carga datos → infiere demanda → resuelve →
construye la propuesta. No persiste nada (el manager revisa y publica)."""
from datetime import date, datetime, time, timedelta
from typing import List

from sqlmodel import Session, select

from SQLModels.Users import Users, UserDetail, UserDepartments
from SQLModels.WorkLogs import AbsenceRequests, AbsenceStatus
from SQLModels.Absences import Holidays

from .config import DEFAULT, SchedulerConfig
from .demand import infer_demand, DemandGrid
from .solver import EmployeeInput, solve, DAYS
from .schemas import (
    GenerateScheduleResponse, ProposedShiftOut, ScheduleReport, HoursByUser, DayCoverage,
)


def load_employees(db: Session, department_id: int, week_start: date, week_end: date,
                   grid: DemandGrid) -> List[EmployeeInput]:
    """Empleados vigentes en el departamento durante la semana, con su
    disponibilidad (fuera de ausencias aprobadas y festivos)."""
    memberships = db.exec(
        select(UserDepartments).where(
            UserDepartments.DeptID == department_id,
            UserDepartments.AssignedDate <= week_end,
        )
    ).all()

    employees: List[EmployeeInput] = []
    for mem in memberships:
        if mem.DeAssignedDate is not None and mem.DeAssignedDate <= week_start:
            continue
        user = Users.get(db, mem.UserID)
        if user is None or user.IsInactive:
            continue
        detail = UserDetail.get(db, mem.UserID)
        contract = float(detail.ContractWeeklyHours) if detail and detail.ContractWeeklyHours else 40.0
        name = f"{detail.FirstName} {detail.LastName1}" if detail else f"User {mem.UserID}"

        absences = db.exec(
            select(AbsenceRequests).where(
                AbsenceRequests.UserID == mem.UserID,
                AbsenceRequests.Status == AbsenceStatus.APPROVED,
                AbsenceRequests.StartTime <= datetime.combine(week_end, time(23, 59)),
                AbsenceRequests.EndTime >= datetime.combine(week_start, time(0, 0)),
            )
        ).all()
        absent_days = set()
        for ab in absences:
            cur = ab.StartTime.date()
            while cur <= ab.EndTime.date():
                absent_days.add(cur)
                cur += timedelta(days=1)

        avail = [[True] * grid.num_slots for _ in range(DAYS)]
        for d in range(DAYS):
            day_date = week_start + timedelta(days=d)
            if day_date in absent_days or Holidays.is_holiday(db, day_date):
                avail[d] = [False] * grid.num_slots
        employees.append(EmployeeInput(mem.UserID, name, contract, avail))
    return employees


def generate_proposal(db: Session, department_id: int, week_start: date,
                      cfg: SchedulerConfig = DEFAULT) -> GenerateScheduleResponse:
    # Normalizar al lunes
    if week_start.weekday() != 0:
        week_start = week_start - timedelta(days=week_start.weekday())
    week_end = week_start + timedelta(days=6)

    grid = infer_demand(db, department_id, week_start, cfg)
    employees = load_employees(db, department_id, week_start, week_end, grid)

    if not employees:
        return GenerateScheduleResponse(
            department_id=department_id, week_start=week_start, status="NO_EMPLOYEES",
            slot_minutes=grid.slot_minutes, shifts=[],
            report=ScheduleReport(coverage_pct=0.0, demand_slots=0, shortfall_slots=0,
                                  coverage_by_day=[], hours_by_user=[]),
        )

    result = solve(employees, grid, cfg)
    name_by_id = {e.user_id: e.name for e in employees}
    contract_by_id = {e.user_id: e.contract_hours for e in employees}

    shifts_out: List[ProposedShiftOut] = []
    for s in result.shifts:
        shift_date = week_start + timedelta(days=s.day_index)
        shifts_out.append(ProposedShiftOut(
            user_id=s.user_id,
            user_name=name_by_id.get(s.user_id, ""),
            date=shift_date,
            day_index=s.day_index,
            start_time=grid.slot_start_time(s.start_slot).strftime("%H:%M"),
            end_time=grid.slot_start_time(s.end_slot).strftime("%H:%M"),
        ))

    demand_slots = sum(grid.get(d, t) for d in range(DAYS) for t in range(grid.num_slots))
    covered = demand_slots - result.total_shortfall_slots
    coverage_pct = round(100.0 * covered / demand_slots, 1) if demand_slots else 100.0

    coverage_by_day = []
    for d in range(DAYS):
        dem = sum(grid.get(d, t) for t in range(grid.num_slots))
        asg = sum(result.coverage.get((d, t), (0, grid.get(d, t)))[0] for t in range(grid.num_slots))
        sh = sum(max(0, grid.get(d, t) - result.coverage.get((d, t), (0, grid.get(d, t)))[0])
                 for t in range(grid.num_slots))
        coverage_by_day.append(DayCoverage(
            day_index=d, demand_slots=dem, assigned_slots=asg, shortfall_slots=sh))
    hours = [
        HoursByUser(
            user_id=uid, user_name=name_by_id.get(uid, ""),
            assigned_hours=round(h, 1), contract_hours=contract_by_id.get(uid, 0.0),
        )
        for uid, h in result.hours_by_user.items()
    ]

    return GenerateScheduleResponse(
        department_id=department_id,
        week_start=week_start,
        status=result.status,
        slot_minutes=grid.slot_minutes,
        shifts=shifts_out,
        report=ScheduleReport(
            coverage_pct=coverage_pct,
            demand_slots=demand_slots,
            shortfall_slots=result.total_shortfall_slots,
            coverage_by_day=coverage_by_day,
            hours_by_user=hours,
        ),
    )
