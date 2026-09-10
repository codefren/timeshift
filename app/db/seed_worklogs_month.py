"""
Seed de work logs para todo el mes actual hasta hoy, con variaciones realistas.

Patrones simulados:
  - Llegadas: hasta 15 min antes o hasta 10 min tarde
  - Salidas: hasta 30 min antes (salida prematura) o hasta 15 min tarde
  - Almuerzo: inicio variable (12:30 / 13:00 / 13:30), duración 30 min o 1 h
  - ~10% de días sin pausa de almuerzo (jornadas cortas o muy ocupadas)
  - Determinístico por (UserID, día) → reproducible

Ejecutar desde la carpeta app/ con el venv activo:
    python db/seed_worklogs_month.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DB_HOST", "localhost")

import datetime
import logging
import random
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env.dev"))
os.environ["DB_HOST"] = "localhost"

from db.session import engine
from sqlmodel import Session, select

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

from SQLModels.Departments import Departments
from SQLModels.Users import Users, UserDetail, UserDepartments
from SQLModels.UserShifts import Shifts, ShiftStatus
from SQLModels.WorkLogs import WorkLogs, WorkLogLines, WorkLogTotals, AbsenceTypes

today = datetime.date.today()

SHIFT_SCHEDULE = {
    1: (datetime.time(9, 0),  datetime.time(18, 0)),
    2: (datetime.time(8, 0),  datetime.time(16, 0)),
    3: (datetime.time(9, 0),  datetime.time(18, 0)),
    4: (datetime.time(9, 0),  datetime.time(17, 0)),
    5: (datetime.time(9, 0),  datetime.time(15, 0)),
}
DEFAULT_SHIFT = (datetime.time(9, 0), datetime.time(17, 0))


def _rng(user_id: int, day: datetime.date) -> random.Random:
    """RNG determinístico por empleado y día."""
    return random.Random(user_id * 10000 + day.toordinal())


def _add_minutes(t: datetime.time, minutes: int) -> datetime.time:
    base = datetime.datetime(2000, 1, 1, t.hour, t.minute)
    result = base + datetime.timedelta(minutes=minutes)
    return result.time()


def realistic_times(
    shift_start: datetime.time,
    shift_end: datetime.time,
    user_id: int,
    day: datetime.date,
) -> dict:
    """
    Devuelve un dict con los tiempos reales de entrada, almuerzo y salida.

    Variaciones:
      - arrival_offset:  [-15, +10] min, ponderado hacia [-5, +2]
      - exit_offset:     [-30, +15] min, ponderado hacia [-10, +5]
      - lunch_start:     12:30 / 13:00 / 13:30 (pesos 20/60/20)
      - lunch_duration:  30 min (20%) o 60 min (80%)
      - skip_lunch:      True en ~10% de jornadas ≥ 7 h
    """
    rng = _rng(user_id, day)

    # Llegada
    arrival_offset = int(rng.gauss(-3, 7))          # media: 3 min antes, σ=7
    arrival_offset = max(-15, min(arrival_offset, 10))
    actual_start = _add_minutes(shift_start, arrival_offset)

    # Salida
    exit_offset = int(rng.gauss(-5, 12))            # media: 5 min antes, σ=12
    exit_offset = max(-30, min(exit_offset, 15))
    actual_end = _add_minutes(shift_end, exit_offset)

    # Garantizar al menos 4 h de jornada
    min_end = _add_minutes(actual_start, 4 * 60)
    if actual_end < min_end:
        actual_end = min_end

    shift_hours = (
        datetime.datetime.combine(day, actual_end)
        - datetime.datetime.combine(day, actual_start)
    ).seconds / 3600

    # Almuerzo
    lunch_info = None
    if shift_hours >= 6:
        skip = rng.random() < 0.10
        if not skip:
            lunch_start_time = rng.choices(
                [datetime.time(12, 30), datetime.time(13, 0), datetime.time(13, 30)],
                weights=[20, 60, 20],
            )[0]
            lunch_mins = rng.choices([30, 60], weights=[20, 80])[0]
            lunch_end_time = _add_minutes(lunch_start_time, lunch_mins)

            # El almuerzo no puede solaparse con entrada/salida
            if lunch_start_time > actual_start and lunch_end_time < actual_end:
                lunch_info = {
                    "start": lunch_start_time,
                    "end": lunch_end_time,
                    "hours": lunch_mins / 60,
                }

    return {
        "actual_start": actual_start,
        "actual_end": actual_end,
        "lunch": lunch_info,
        "arrival_offset": arrival_offset,
        "exit_offset": exit_offset,
    }


def workdays(start: datetime.date, end: datetime.date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += datetime.timedelta(days=1)


def get_active_employees(db: Session):
    return db.exec(
        select(Users, UserDetail, UserDepartments)
        .join(UserDetail, UserDetail.UserID == Users.UserID)
        .join(
            UserDepartments,
            (UserDepartments.UserID == Users.UserID) & (UserDepartments.IsPrimary == True),
        )
        .where(
            Users.IsInactive == False,
            UserDepartments.AssignedDate <= today,
            (UserDepartments.DeAssignedDate == None)
            | (UserDepartments.DeAssignedDate > today),
        )
    ).all()


def get_or_create_shift(db: Session, user, ud, day: datetime.date, admin_id: int) -> Shifts:
    shift = db.exec(
        select(Shifts).where(Shifts.UserID == user.UserID, Shifts.Date == day)
    ).first()
    if shift:
        return shift

    start_t, end_t = SHIFT_SCHEDULE.get(ud.DeptID, DEFAULT_SHIFT)
    dept = db.exec(select(Departments).where(Departments.DeptID == ud.DeptID)).first()

    shift = Shifts(
        UserID=user.UserID,
        DepartmentID=ud.DeptID,
        LocationID=dept.LocationID if dept else None,
        Date=day,
        StartTime=start_t,
        EndTime=end_t,
        BreakTime=1.0 if (end_t.hour - start_t.hour) >= 7 else 0.0,
        IsPublished=True,
        Status=ShiftStatus.Planned,
        CreatedBy=admin_id,
    )
    db.add(shift)
    db.commit()
    db.refresh(shift)
    return shift


def create_worklog_for_day(
    db: Session,
    user_id: int,
    shift: Shifts,
    day: datetime.date,
    almuerzo_id: int,
) -> tuple[bool, str]:
    if WorkLogs.exists(db, user_id, day):
        return False, "skip"

    times = realistic_times(shift.StartTime, shift.EndTime, user_id, day)
    actual_start = times["actual_start"]
    actual_end   = times["actual_end"]
    lunch        = times["lunch"]

    wl = WorkLogs(UserID=user_id, LogDate=day, ShiftID=shift.ShiftID, IsFinished=False)
    wl = wl._create(db)

    lines = []
    line_num = 1

    if lunch:
        h_before = (
            datetime.datetime.combine(day, lunch["start"])
            - datetime.datetime.combine(day, actual_start)
        ).seconds / 3600
        h_after = (
            datetime.datetime.combine(day, actual_end)
            - datetime.datetime.combine(day, lunch["end"])
        ).seconds / 3600

        lines.append(WorkLogLines.create_line(
            db, WorkLogID=wl.WorkLogID, WorkLogLineID=line_num,
            StartTime=actual_start, EndTime=lunch["start"],
            IsPause=False, LoggedHours=h_before,
        ))
        line_num += 1
        lines.append(WorkLogLines.create_line(
            db, WorkLogID=wl.WorkLogID, WorkLogLineID=line_num,
            StartTime=lunch["start"], EndTime=lunch["end"],
            IsPause=True, AbsenceType=almuerzo_id, LoggedHours=lunch["hours"],
        ))
        line_num += 1
        lines.append(WorkLogLines.create_line(
            db, WorkLogID=wl.WorkLogID, WorkLogLineID=line_num,
            StartTime=lunch["end"], EndTime=actual_end,
            IsPause=False, LoggedHours=h_after,
        ))
    else:
        total_h = (
            datetime.datetime.combine(day, actual_end)
            - datetime.datetime.combine(day, actual_start)
        ).seconds / 3600
        lines.append(WorkLogLines.create_line(
            db, WorkLogID=wl.WorkLogID, WorkLogLineID=line_num,
            StartTime=actual_start, EndTime=actual_end,
            IsPause=False, LoggedHours=total_h,
        ))

    wl.lines = lines
    wl.update(db, IsFinished=True)
    wl.create_totals(db)

    shift.Status = ShiftStatus.Completed
    db.add(shift)
    db.commit()

    tag = ""
    if times["arrival_offset"] <= -10:
        tag += " [+temprano]"
    elif times["arrival_offset"] >= 5:
        tag += " [tarde]"
    if times["exit_offset"] <= -20:
        tag += " [salida prematura]"
    if not lunch:
        tag += " [sin pausa]"

    return True, tag


def delete_month_worklogs(db: Session, m_start: datetime.date, m_end: datetime.date) -> int:
    """Borra todos los WorkLogs (y sus líneas/totales) del rango dado."""
    worklogs = db.exec(
        select(WorkLogs).where(
            WorkLogs.LogDate >= m_start,
            WorkLogs.LogDate <= m_end,
        )
    ).all()
    for wl in worklogs:
        wl.complete_removal(db)
    return len(worklogs)


def seed():
    m_start = today.replace(day=1)
    log.info("=" * 60)
    log.info("SEED — WORK LOGS DEL MES ACTUAL (con variaciones realistas)")
    log.info(f"Rango: {m_start} → {today}")
    log.info("=" * 60)

    with Session(engine) as db:
        log.info("Borrando work logs existentes del mes...")
        deleted = delete_month_worklogs(db, m_start, today)
        log.info(f"  {deleted} work logs eliminados\n")

        employees = get_active_employees(db)
        log.info(f"Empleados activos: {len(employees)}")

        admin = db.exec(select(Users).where(Users.IsInactive == False)).first()
        admin_id = admin.UserID

        almuerzo = db.exec(
            select(AbsenceTypes).where(AbsenceTypes.TypeName == "Almuerzo")
        ).first()
        if not almuerzo:
            log.error("No se encontró el AbsenceType 'Almuerzo'.")
            return
        almuerzo_id = almuerzo.AbsenceTypeID

        days = list(workdays(m_start, today))
        log.info(f"Días laborables a procesar: {len(days)}\n")

        shifts_created = logs_created = logs_skipped = 0

        for user, detail, ud in employees:
            name = f"{detail.FirstName} {detail.LastName1}"
            log.info(f"  {name}")
            for day in days:
                shift = get_or_create_shift(db, user, ud, day, admin_id)
                if shift.Status == ShiftStatus.Planned:
                    shifts_created += 1

                created, tag = create_worklog_for_day(db, user.UserID, shift, day, almuerzo_id)
                if created:
                    logs_created += 1
                    times = realistic_times(shift.StartTime, shift.EndTime, user.UserID, day)
                    log.info(
                        f"    {day} | entrada {times['actual_start'].strftime('%H:%M')} "
                        f"(turno {shift.StartTime.strftime('%H:%M')}) | "
                        f"salida {times['actual_end'].strftime('%H:%M')} "
                        f"(turno {shift.EndTime.strftime('%H:%M')}){tag}"
                    )
                else:
                    logs_skipped += 1
                    log.info(f"    {day} | ya existía — omitido")

    log.info("")
    log.info(f"Turnos creados  : {shifts_created}")
    log.info(f"WorkLogs creados: {logs_created}")
    log.info(f"Ya existían     : {logs_skipped}")
    log.info("=" * 60)
    log.info("✅ COMPLETADO")
    log.info("=" * 60)


if __name__ == "__main__":
    seed()
