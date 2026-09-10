"""
Seed de registros adicionales para probar las funcionalidades construidas.

Crea para el mes actual y semanas recientes:
  - Turnos del mes completo para todos los empleados activos
  - WorkLogs de las últimas 2 semanas
  - Solicitudes de ausencia variadas (Pending/Approved/Rejected) para todos
  - Balance de ausencias para todos los empleados activos

Ejecutar con:
    docker compose exec backend python /backend/db/seed_extra_records.py
"""

import sys
import datetime
import logging

sys.path.insert(0, '/backend')

from db.session import engine
from sqlmodel import Session, select
from passlib.hash import bcrypt

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

from SQLModels.Departments import Departments
from SQLModels.Users import Users, UserDetail, UserDepartments
from SQLModels.UserShifts import Shifts, ShiftStatus
from SQLModels.WorkLogs import (
    WorkLogs, WorkLogLines, AbsenceTypes,
    AbsenceRequests, AbsenceReviews, AbsenceStatus,
)
from SQLModels.Absences import AbsenceBalance

today = datetime.date.today()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def workdays(start: datetime.date, end: datetime.date):
    """Días laborables L-V en el rango."""
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += datetime.timedelta(days=1)


def month_start(d: datetime.date) -> datetime.date:
    return d.replace(day=1)


def month_end(d: datetime.date) -> datetime.date:
    next_m = d.replace(day=28) + datetime.timedelta(days=4)
    return next_m - datetime.timedelta(days=next_m.day)


def get_active_employees(db: Session):
    """Empleados activos con asignación vigente."""
    rows = db.exec(
        select(Users, UserDetail, UserDepartments)
        .join(UserDetail, UserDetail.UserID == Users.UserID)
        .join(UserDepartments, (UserDepartments.UserID == Users.UserID) &
              (UserDepartments.IsPrimary == True))
        .where(
            Users.IsInactive == False,
            UserDepartments.AssignedDate <= today,
            (UserDepartments.DeAssignedDate == None) |
            (UserDepartments.DeAssignedDate > today),
        )
    ).all()
    return rows


# ─── 1. Turnos del mes actual ─────────────────────────────────────────────────

def seed_month_shifts(db: Session, employees) -> int:
    admin = db.exec(select(Users).where(Users.Email == "info@phoedata.com")).first()
    count = 0

    m_start = month_start(today)
    m_end   = month_end(today)

    shift_schedule = {
        1: (datetime.time(9, 0), datetime.time(18, 0)),   # Desarrollo
        2: (datetime.time(8, 0), datetime.time(16, 0)),   # RRHH
        3: (datetime.time(9, 0), datetime.time(18, 0)),   # Ventas
        4: (datetime.time(9, 0), datetime.time(17, 0)),   # Marketing
        5: (datetime.time(9, 0), datetime.time(15, 0)),   # Soporte
    }

    for user, detail, ud in employees:
        start_t, end_t = shift_schedule.get(ud.DeptID, (datetime.time(9, 0), datetime.time(17, 0)))

        for day in workdays(m_start, m_end):
            exists = db.exec(
                select(Shifts).where(Shifts.UserID == user.UserID, Shifts.Date == day)
            ).first()
            if exists:
                continue

            shift = Shifts(
                UserID=user.UserID,
                DepartmentID=ud.DeptID,
                LocationID=db.exec(
                    select(Departments).where(Departments.DeptID == ud.DeptID)
                ).first().LocationID,
                Date=day,
                StartTime=start_t,
                EndTime=end_t,
                BreakTime=1.0 if (end_t.hour - start_t.hour) >= 7 else 0.0,
                IsPublished=True,
                Status=ShiftStatus.Planned,
                CreatedBy=admin.UserID,
            )
            db.add(shift)
            count += 1

    db.commit()
    return count


# ─── 2. WorkLogs de las últimas 2 semanas ────────────────────────────────────

def seed_recent_worklogs(db: Session, employees) -> int:
    count = 0
    two_weeks_ago = today - datetime.timedelta(weeks=2)

    shift_hours = {
        1: 8.0, 2: 7.0, 3: 8.0, 4: 7.0, 5: 6.0,
    }

    for user, detail, ud in employees:
        daily_h = shift_hours.get(ud.DeptID, 8.0)
        start_t = datetime.time(9, 0)

        for day in workdays(two_weeks_ago, today - datetime.timedelta(days=1)):
            if WorkLogs.exists(db, user.UserID, day):
                continue

            shift = db.exec(
                select(Shifts).where(Shifts.UserID == user.UserID, Shifts.Date == day)
            ).first()
            if not shift:
                continue

            wl = WorkLogs(
                UserID=user.UserID,
                LogDate=day,
                ShiftID=shift.ShiftID,
                IsFinished=False,
            )
            wl = wl._create(db)

            end_dt = datetime.datetime.combine(day, start_t) + datetime.timedelta(hours=daily_h)
            end_t  = end_dt.time()

            if daily_h >= 7:
                lunch_start = datetime.time(13, 0)
                lunch_end   = datetime.time(14, 0)
                almuerzo_id = db.exec(
                    select(AbsenceTypes).where(AbsenceTypes.TypeName == "Almuerzo")
                ).first().AbsenceTypeID

                l1 = WorkLogLines.create_line(
                    db, WorkLogID=wl.WorkLogID, WorkLogLineID=1,
                    StartTime=start_t, EndTime=lunch_start,
                    IsPause=False,
                    LoggedHours=(datetime.datetime.combine(day, lunch_start) -
                                 datetime.datetime.combine(day, start_t)).seconds / 3600,
                )
                l2 = WorkLogLines.create_line(
                    db, WorkLogID=wl.WorkLogID, WorkLogLineID=2,
                    StartTime=lunch_start, EndTime=lunch_end,
                    IsPause=True, AbsenceType=almuerzo_id, LoggedHours=1.0,
                )
                l3 = WorkLogLines.create_line(
                    db, WorkLogID=wl.WorkLogID, WorkLogLineID=3,
                    StartTime=lunch_end, EndTime=end_t,
                    IsPause=False,
                    LoggedHours=(datetime.datetime.combine(day, end_t) -
                                 datetime.datetime.combine(day, lunch_end)).seconds / 3600,
                )
                wl.lines = [l1, l2, l3]
            else:
                l1 = WorkLogLines.create_line(
                    db, WorkLogID=wl.WorkLogID, WorkLogLineID=1,
                    StartTime=start_t, EndTime=end_t,
                    IsPause=False, LoggedHours=daily_h,
                )
                wl.lines = [l1]

            wl.update(db, IsFinished=True)
            wl.create_totals(db)

            shift.Status = ShiftStatus.Completed
            db.add(shift)
            db.commit()
            count += 1

    return count


# ─── 3. Balance de ausencias para todos ──────────────────────────────────────

def seed_all_balances(db: Session, employees) -> int:
    vacaciones = db.exec(
        select(AbsenceTypes).where(AbsenceTypes.TypeName == "Vacaciones")
    ).first()
    baja = db.exec(
        select(AbsenceTypes).where(AbsenceTypes.TypeName == "Baja médica")
    ).first()
    year = today.year
    count = 0

    for user, _, _ in employees:
        for at, accrued in [(vacaciones, 22.0), (baja, 10.0)]:
            if AbsenceBalance.get(db, user.UserID, at.AbsenceTypeID, year):
                continue
            b = AbsenceBalance(
                UserID=user.UserID,
                AbsenceTypeID=at.AbsenceTypeID,
                Year=year,
                AccruedDays=accrued,
                UsedDays=0.0,
                PendingDays=0.0,
            )
            b._create(db)
            count += 1

    return count


# ─── 4. Solicitudes de ausencia variadas ─────────────────────────────────────

def seed_absence_requests(db: Session, employees) -> int:
    admin = db.exec(select(Users).where(Users.Email == "info@phoedata.com")).first()
    vacaciones_id = db.exec(
        select(AbsenceTypes).where(AbsenceTypes.TypeName == "Vacaciones")
    ).first().AbsenceTypeID
    baja_id = db.exec(
        select(AbsenceTypes).where(AbsenceTypes.TypeName == "Baja médica")
    ).first().AbsenceTypeID
    year = today.year
    count = 0

    requests_template = [
        # (mes_inicio, dia_inicio, dias, tipo, status, motivo)
        (7,  1,  5, vacaciones_id, AbsenceStatus.APPROVED,  "Vacaciones de verano"),
        (8,  4,  3, vacaciones_id, AbsenceStatus.PENDING,   "Vacaciones agosto"),
        (9, 15,  1, baja_id,       AbsenceStatus.REJECTED,  "Cita médica"),
        (6,  today.day + 3 if today.day + 3 <= 28 else 5,
              2, vacaciones_id, AbsenceStatus.PENDING, "Días personales"),
    ]

    for i, (user, _, _) in enumerate(employees):
        if user.Email == "info@phoedata.com":
            continue

        tpl = requests_template[i % len(requests_template)]
        mes, dia, num_days, type_id, req_status, reason = tpl

        try:
            start_dt = datetime.datetime(year, mes, dia, 8, 0)
            end_dt   = datetime.datetime(year, mes, dia + num_days - 1, 17, 0)
        except ValueError:
            continue

        exists = db.exec(
            select(AbsenceRequests).where(
                AbsenceRequests.UserID == user.UserID,
                AbsenceRequests.StartTime == start_dt,
            )
        ).first()
        if exists:
            continue

        req = AbsenceRequests(
            UserID=user.UserID,
            AbsenceTypeID=type_id,
            RequestDate=today,
            StartTime=start_dt,
            EndTime=end_dt,
            Reason=reason,
            Status=req_status,
            TotalDays=float(num_days),
        )
        req._create(db)

        # Balance
        balance = AbsenceBalance.get(db, user.UserID, type_id, year)
        if balance:
            if req_status == AbsenceStatus.PENDING:
                balance.update(db, PendingDays=balance.PendingDays + num_days)
            elif req_status == AbsenceStatus.APPROVED:
                balance.update(db, UsedDays=balance.UsedDays + num_days)

        # Revisión para aprobadas/rechazadas
        if req_status in (AbsenceStatus.APPROVED, AbsenceStatus.REJECTED):
            review = AbsenceReviews(
                RequestID=req.RequestID,
                ReviewerID=admin.UserID,
                ReviewDate=datetime.datetime.now(),
                ReviewResult=req_status,
                ReviewComments="Revisado por administración",
            )
            review._create(db)

        count += 1
        log.info(f"  ✓ {user.Email[:30]:<30} → {req_status.value:<10} {reason}")

    return count


# ─── Main ─────────────────────────────────────────────────────────────────────

def seed():
    log.info("=" * 60)
    log.info("SEED — REGISTROS ADICIONALES")
    log.info(f"Fecha de referencia: {today}")
    log.info("=" * 60)

    with Session(engine) as db:
        employees = get_active_employees(db)
        log.info(f"\nEmpleados activos encontrados: {len(employees)}")

        log.info("\n[1/4] Turnos del mes actual")
        n = seed_month_shifts(db, employees)
        log.info(f"  ✓ {n} turnos creados para {today.strftime('%B %Y')}")

        log.info("\n[2/4] WorkLogs últimas 2 semanas")
        n = seed_recent_worklogs(db, employees)
        log.info(f"  ✓ {n} WorkLogs creados")

        log.info("\n[3/4] Balance de ausencias")
        n = seed_all_balances(db, employees)
        log.info(f"  ✓ {n} balances creados")

        log.info("\n[4/4] Solicitudes de ausencia")
        n = seed_absence_requests(db, employees)
        log.info(f"  ✓ {n} solicitudes creadas")

    log.info("\n" + "=" * 60)
    log.info("✅ COMPLETADO")
    log.info("=" * 60)


if __name__ == "__main__":
    seed()
