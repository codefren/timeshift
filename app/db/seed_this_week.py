"""
Añade registros de trabajo para la semana actual (días que faltan hasta ayer)
y un fichaje en curso para hoy para cada usuario empleado.

Ejecutar: docker compose exec backend python /backend/db/seed_this_week.py
"""
import sys, datetime
sys.path.insert(0, '/backend')

import logging
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

from db.session import engine
from sqlmodel import Session, select
from SQLModels.Users import Users, UserDepartments
from SQLModels.WorkLogs import WorkLogs, WorkLogLines, AbsenceTypes
from SQLModels.UserShifts import Shifts, ShiftStatus

TODAY   = datetime.date.today()
ALMUERZO_NAME = "Almuerzo"

# horas por usuario: (email, start, end_work, daily_hours, has_lunch)
USER_SCHEDULE = {
    "info@phoedata.com":               (datetime.time(9,0), datetime.time(18,0), 8.0, True),
    "test@timeshift.dev":              (datetime.time(9,0), datetime.time(18,0), 8.0, True),
    "maria.garcia@timeshift.dev":      (datetime.time(9,0), datetime.time(18,0), 8.0, True),
    "pedro.martinez@timeshift.dev":    (datetime.time(9,0), datetime.time(18,0), 8.0, True),
    "ana.lopez@timeshift.dev":         (datetime.time(9,0), datetime.time(18,0), 8.0, True),
    "luis.torres@timeshift.dev":       (datetime.time(9,0), datetime.time(15,0), 6.0, False),
    "elena.sanchez@timeshift.dev":     (datetime.time(9,0), datetime.time(18,0), 8.0, True),
}

def workdays_since(start: datetime.date):
    """Días laborables desde start hasta ayer (inclusive)."""
    current = start
    yesterday = TODAY - datetime.timedelta(days=1)
    while current <= yesterday:
        if current.weekday() < 5:
            yield current
        current += datetime.timedelta(days=1)

def get_or_create_shift(db, user_id, day, dept_id, loc_id, start_t, end_t):
    shift = db.exec(
        select(Shifts).where(Shifts.UserID == user_id, Shifts.Date == day)
    ).first()
    if shift:
        return shift
    shift = Shifts(
        UserID=user_id, DepartmentID=dept_id, LocationID=loc_id,
        Date=day, StartTime=start_t, EndTime=end_t,
        BreakTime=1.0, IsPublished=True, Status=ShiftStatus.Planned,
        CreatedBy=1,
    )
    db.add(shift); db.commit(); db.refresh(shift)
    return shift

def create_completed_worklog(db, user_id, day, dept_id, loc_id,
                              start_t, daily_hours, has_lunch, almuerzo_id, admin_id=1):
    """Crea un WorkLog completado para un día laboral."""
    if WorkLogs.exists(db, user_id, day):
        return None

    shift = get_or_create_shift(db, user_id, day, dept_id, loc_id, start_t,
                                 datetime.time(18,0) if daily_hours==8.0 else datetime.time(15,0))

    wl = WorkLogs(UserID=user_id, LogDate=day, ShiftID=shift.ShiftID, IsFinished=False)
    wl = wl._create(db)

    line_id = 1
    if has_lunch:
        # Mañana 09:00-13:00
        WorkLogLines.create_line(db, WorkLogID=wl.WorkLogID, WorkLogLineID=line_id,
            StartTime=datetime.time(9,0), EndTime=datetime.time(13,0),
            IsPause=False, LoggedHours=4.0)
        line_id += 1
        # Almuerzo 13:00-14:00
        WorkLogLines.create_line(db, WorkLogID=wl.WorkLogID, WorkLogLineID=line_id,
            StartTime=datetime.time(13,0), EndTime=datetime.time(14,0),
            IsPause=True, AbsenceType=almuerzo_id, LoggedHours=1.0)
        line_id += 1
        # Tarde 14:00-18:00
        WorkLogLines.create_line(db, WorkLogID=wl.WorkLogID, WorkLogLineID=line_id,
            StartTime=datetime.time(14,0), EndTime=datetime.time(18,0),
            IsPause=False, LoggedHours=4.0)
    else:
        WorkLogLines.create_line(db, WorkLogID=wl.WorkLogID, WorkLogLineID=line_id,
            StartTime=datetime.time(9,0), EndTime=datetime.time(15,0),
            IsPause=False, LoggedHours=6.0)

    # Recargar líneas desde BD
    db.refresh(wl)
    wl.update(db, IsFinished=True)
    wl.create_totals(db)

    # Marcar turno completado
    shift.Status = ShiftStatus.Completed
    db.add(shift); db.commit()
    return wl

def create_inprogress_worklog(db, user_id, dept_id, loc_id, almuerzo_id):
    """Crea un WorkLog en curso para HOY: mañana hecha + almuerzo hecho + tarde en curso."""
    if WorkLogs.exists(db, user_id, TODAY):
        log.info(f"    Ya existe fichaje de hoy para UserID={user_id}")
        return None

    now = datetime.datetime.now().time()
    start_t = datetime.time(9, 0)

    # Horario reducido → sin almuerzo
    shift_end = datetime.time(18, 0)

    shift = get_or_create_shift(db, user_id, TODAY, dept_id, loc_id,
                                 start_t, shift_end)

    wl = WorkLogs(UserID=user_id, LogDate=TODAY, ShiftID=shift.ShiftID, IsFinished=False)
    wl = wl._create(db)

    # Líneas completadas: mañana + almuerzo
    WorkLogLines.create_line(db, WorkLogID=wl.WorkLogID, WorkLogLineID=1,
        StartTime=datetime.time(9,0), EndTime=datetime.time(13,0),
        IsPause=False, LoggedHours=4.0)
    WorkLogLines.create_line(db, WorkLogID=wl.WorkLogID, WorkLogLineID=2,
        StartTime=datetime.time(13,0), EndTime=datetime.time(14,0),
        IsPause=True, AbsenceType=almuerzo_id, LoggedHours=1.0)
    # Línea en curso: tarde sin EndTime
    WorkLogLines.create_line(db, WorkLogID=wl.WorkLogID, WorkLogLineID=3,
        StartTime=datetime.time(14,0), EndTime=None,
        IsPause=False, LoggedHours=0.0)

    db.commit()
    return wl

def main():
    log.info("Añadiendo registros de jornada para la semana actual...")
    log.info(f"Hoy: {TODAY}")

    with Session(engine) as db:
        almuerzo = db.exec(
            select(AbsenceTypes).where(AbsenceTypes.TypeName == ALMUERZO_NAME)
        ).first()
        if not almuerzo:
            log.error("AbsenceType 'Almuerzo' no encontrado. Ejecuta seed_dev_data.py primero.")
            return
        almuerzo_id = almuerzo.AbsenceTypeID

        completed = 0
        inprogress = 0

        for email, (start_t, _, daily_hours, has_lunch) in USER_SCHEDULE.items():
            user = db.exec(select(Users).where(Users.Email == email)).first()
            if not user:
                log.warning(f"Usuario no encontrado: {email}")
                continue

            # Obtener departamento principal
            ud = db.exec(
                select(UserDepartments).where(
                    UserDepartments.UserID == user.UserID,
                    UserDepartments.IsPrimary == True,
                )
            ).first()
            if not ud:
                log.warning(f"Sin departamento primario: {email}")
                continue

            dept_id = ud.DeptID
            loc_id = ud.department.LocationID if ud.department else 1

            # ── Días laborables desde el 30-mayo hasta ayer ──────────────────
            last_seeded = datetime.date(2026, 5, 29)  # último día creado por seed
            for day in workdays_since(last_seeded + datetime.timedelta(days=1)):
                wl = create_completed_worklog(
                    db, user.UserID, day, dept_id, loc_id,
                    start_t, daily_hours, has_lunch, almuerzo_id,
                )
                if wl:
                    completed += 1

            # ── Fichaje en curso HOY ─────────────────────────────────────────
            if TODAY.weekday() < 5:
                wl = create_inprogress_worklog(db, user.UserID, dept_id, loc_id, almuerzo_id)
                if wl:
                    inprogress += 1
                    log.info(f"  ✓ Fichaje en curso hoy: {email}")

        log.info(f"\n✅ {completed} jornadas completadas añadidas")
        log.info(f"✅ {inprogress} fichajes en curso creados (hoy {TODAY})")

if __name__ == "__main__":
    main()
