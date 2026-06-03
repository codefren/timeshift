"""
Script de seed de datos de desarrollo para TimeShift.
Crea datos de prueba completos para verificar el funcionamiento del frontend.

Ejecutar con:
    docker compose exec backend python /backend/db/seed_dev_data.py
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

# ── Importaciones de modelos ──────────────────────────────────────────────────
from SQLModels.Departments import Companies, Departments, Locations
from SQLModels.Schedules import Schedules, ScheduleLines, ScheduleTotals, ScheduleTypes
from SQLModels.WorkLogs import (
    AbsenceTypes, AbsenceRequests, AbsenceReviews, AbsenceStatus,
    WorkLogs, WorkLogLines, WorkLogTotals,
)
from SQLModels.Absences import Holidays, AbsenceBalance
from SQLModels.Roles import Roles, RoleUsers
from SQLModels.Users import Users, UserDetail, UserAddress, UserDepartments, Supervision
from SQLModels.UserShifts import Shifts, ShiftStatus


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_or_none(db, model, **kwargs):
    q = select(model)
    for k, v in kwargs.items():
        q = q.where(getattr(model, k) == v)
    return db.exec(q).first()


def workday_range(start: datetime.date, end: datetime.date):
    """Genera fechas laborables (L-V) en el rango."""
    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current
        current += datetime.timedelta(days=1)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Empresas
# ─────────────────────────────────────────────────────────────────────────────

def seed_companies(db: Session) -> dict:
    companies = {
        "TimeShift Dev SL": {"TaxID": "B12345678", "SocialName": "TimeShift Dev SL",
                              "FiscalName": "TimeShift Dev SL", "Address": "Calle Mayor 1",
                              "ZipCode": "28001", "City": "Madrid", "State": "Madrid", "Country": "ES"},
        "Retail España SL": {"TaxID": "B87654321", "SocialName": "Retail España SL",
                              "FiscalName": "Retail España SL", "Address": "Calle Serrano 45",
                              "ZipCode": "28006", "City": "Madrid", "State": "Madrid", "Country": "ES"},
        "Tech Solutions SA": {"TaxID": "A11223344", "SocialName": "Tech Solutions SA",
                               "FiscalName": "Tech Solutions SA", "Address": "Avenida Diagonal 100",
                               "ZipCode": "08018", "City": "Barcelona", "State": "Cataluña", "Country": "ES"},
    }
    result = {}
    for name, data in companies.items():
        existing = get_or_none(db, Companies, TaxID=data["TaxID"])
        if existing:
            result[name] = existing
            log.info(f"  Empresa ya existe: {name}")
        else:
            c = Companies(**data, Active=True)
            db.add(c)
            db.commit()
            db.refresh(c)
            result[name] = c
            log.info(f"  ✓ Empresa creada: {name} (ID={c.CompanyID})")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 2. Ubicaciones
# ─────────────────────────────────────────────────────────────────────────────

def seed_locations(db: Session) -> dict:
    locations_data = [
        {"LocationName": "Oficina Madrid", "Address": "Calle Mayor 1", "ZipCode": "28001",
         "City": "Madrid", "State": "Madrid", "Country": "ES", "Lat": 40.4168, "Long": -3.7038,
         "ControlRadius": 100.0, "Active": True},
        {"LocationName": "Oficina Barcelona", "Address": "Avenida Diagonal 100", "ZipCode": "08018",
         "City": "Barcelona", "State": "Cataluña", "Country": "ES", "Lat": 41.3851, "Long": 2.1734,
         "ControlRadius": 150.0, "Active": True},
        {"LocationName": "Oficina Valencia", "Address": "Calle Colón 50", "ZipCode": "46004",
         "City": "Valencia", "State": "Valencia", "Country": "ES", "Lat": 39.4699, "Long": -0.3763,
         "ControlRadius": 100.0, "Active": True},
        {"LocationName": "Remoto", "Address": "Teletrabajo", "ZipCode": "00000",
         "City": "España", "State": "España", "Country": "ES", "Lat": 40.4168, "Long": -3.7038,
         "ControlRadius": 999999.0, "Active": True},
    ]
    result = {}
    for data in locations_data:
        name = data["LocationName"]
        existing = get_or_none(db, Locations, LocationName=name)
        if existing:
            result[name] = existing
            log.info(f"  Ubicación ya existe: {name}")
        else:
            loc = Locations(**data)
            db.add(loc)
            db.commit()
            db.refresh(loc)
            result[name] = loc
            log.info(f"  ✓ Ubicación creada: {name} (ID={loc.LocationID})")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 3. Departamentos
# ─────────────────────────────────────────────────────────────────────────────

def seed_departments(db: Session, companies: dict, locations: dict) -> dict:
    depts_data = [
        {"DeptName": "Desarrollo",   "LocationID": locations["Oficina Madrid"].LocationID,    "CompanyID": companies["TimeShift Dev SL"].CompanyID},
        {"DeptName": "RRHH",         "LocationID": locations["Oficina Madrid"].LocationID,    "CompanyID": companies["TimeShift Dev SL"].CompanyID},
        {"DeptName": "Ventas",       "LocationID": locations["Oficina Madrid"].LocationID,    "CompanyID": companies["TimeShift Dev SL"].CompanyID},
        {"DeptName": "Marketing",    "LocationID": locations["Oficina Barcelona"].LocationID, "CompanyID": companies["TimeShift Dev SL"].CompanyID},
        {"DeptName": "Soporte",      "LocationID": locations["Remoto"].LocationID,            "CompanyID": companies["TimeShift Dev SL"].CompanyID},
        {"DeptName": "Retail Madrid","LocationID": locations["Oficina Madrid"].LocationID,    "CompanyID": companies["Retail España SL"].CompanyID},
        {"DeptName": "Tech Dev",     "LocationID": locations["Oficina Barcelona"].LocationID, "CompanyID": companies["Tech Solutions SA"].CompanyID},
    ]
    result = {}
    for data in depts_data:
        name = data["DeptName"]
        existing = get_or_none(db, Departments, DeptName=name)
        if existing:
            result[name] = existing
            log.info(f"  Departamento ya existe: {name}")
        else:
            dept = Departments(**data, Active=True, ForceLocation=False)
            db.add(dept)
            db.commit()
            db.refresh(dept)
            result[name] = dept
            log.info(f"  ✓ Departamento creado: {name} (ID={dept.DeptID})")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 4. Horarios
# ─────────────────────────────────────────────────────────────────────────────

def seed_schedules(db: Session) -> dict:
    schedules_data = [
        {
            "name": "Horario Estandar",
            "lines": [
                ("Monday", "09:00", "18:00"), ("Tuesday", "09:00", "18:00"),
                ("Wednesday", "09:00", "18:00"), ("Thursday", "09:00", "18:00"),
                ("Friday", "09:00", "18:00"),
            ]
        },
        {
            "name": "Horario Reducido",
            "lines": [
                ("Monday", "09:00", "15:00"), ("Tuesday", "09:00", "15:00"),
                ("Wednesday", "09:00", "15:00"), ("Thursday", "09:00", "15:00"),
                ("Friday", "09:00", "15:00"),
            ]
        },
    ]
    result = {}
    admin_id = db.exec(select(Users).where(Users.Email == "info@phoedata.com")).first().UserID

    for sched in schedules_data:
        name = sched["name"]
        existing = get_or_none(db, Schedules, ScheduleName=name)
        if existing:
            result[name] = existing
            log.info(f"  Horario ya existe: {name}")
            continue

        s = Schedules(
            ScheduleName=name,
            ScheduleType=ScheduleTypes.FIXED.value,
            StartDate=datetime.date(2024, 1, 1),
            EndDate=datetime.date(2030, 12, 31),
            CreatedBy=admin_id,
        )
        db.add(s)
        db.commit()
        db.refresh(s)

        hours_per_day = []
        for i, (day, start, end) in enumerate(sched["lines"], 1):
            st = datetime.time.fromisoformat(start)
            et = datetime.time.fromisoformat(end)
            dur = (datetime.datetime.combine(datetime.date.today(), et) -
                   datetime.datetime.combine(datetime.date.today(), st)).total_seconds() / 3600
            line = ScheduleLines(
                ScheduleLineID=i, ScheduleID=s.ScheduleID,
                WeekDay=day, StartTime=st, EndTime=et, DurationHours=dur,
            )
            db.add(line)
            hours_per_day.append(dur)

        total = ScheduleTotals(
            ScheduleID=s.ScheduleID,
            TotalWeekWorkDays=len(sched["lines"]),
            TotalWeekWorkHours=int(sum(hours_per_day)),
        )
        db.add(total)
        db.commit()
        result[name] = s
        log.info(f"  ✓ Horario creado: {name} (ID={s.ScheduleID})")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 5. Tipos de ausencia
# ─────────────────────────────────────────────────────────────────────────────

def seed_absence_types(db: Session) -> dict:
    types_data = [
        {"TypeName": "Vacaciones",   "IsCounted": True},
        {"TypeName": "Baja médica",  "IsCounted": True},
        {"TypeName": "Almuerzo",     "IsCounted": False},
    ]
    result = {}
    for data in types_data:
        name = data["TypeName"]
        existing = get_or_none(db, AbsenceTypes, TypeName=name)
        if existing:
            result[name] = existing
            log.info(f"  AbsenceType ya existe: {name}")
        else:
            at = AbsenceTypes(**data)
            at._create(db)
            result[name] = at
            log.info(f"  ✓ AbsenceType creado: {name} (ID={at.AbsenceTypeID})")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 6. Festivos
# ─────────────────────────────────────────────────────────────────────────────

def seed_holidays(db: Session, companies: dict) -> None:
    admin_id = db.exec(select(Users).where(Users.Email == "info@phoedata.com")).first().UserID
    holidays_data = [
        {"Name": "Año Nuevo",              "Date": datetime.date(2026, 1,  1)},
        {"Name": "Día del Trabajo",        "Date": datetime.date(2026, 5,  1)},
        {"Name": "Fiesta Nacional",        "Date": datetime.date(2026, 10, 12)},
        {"Name": "Todos los Santos",       "Date": datetime.date(2026, 11, 1)},
        {"Name": "Inmaculada Concepción",  "Date": datetime.date(2026, 12, 8)},
        {"Name": "Navidad",                "Date": datetime.date(2026, 12, 25)},
    ]
    for data in holidays_data:
        existing = get_or_none(db, Holidays, Name=data["Name"])
        if existing:
            log.info(f"  Festivo ya existe: {data['Name']}")
            continue
        h = Holidays(**data, IsRecurring=True, CreatedBy=admin_id)
        h.create(db)
        log.info(f"  ✓ Festivo creado: {data['Name']}")


# ─────────────────────────────────────────────────────────────────────────────
# 7. Usuarios
# ─────────────────────────────────────────────────────────────────────────────

USERS_DATA = [
    {
        "email": "maria.garcia@timeshift.dev",
        "first_name": "María", "last_name1": "García", "last_name2": "Fernández",
        "gender": "F", "phone": "611000001", "job_title": "Responsable RRHH",
        "contract_type": "Indefinido", "weekly_hours": 40.0,
        "identity": "11111111A", "ss_number": "280111111111",
        "dob": "1985-03-12", "hire_date": "2022-06-01",
        "dept_name": "RRHH", "schedule_name": "Horario Estandar",
        "address": {"Address": "Calle Serrano 20", "ZipCode": "28006", "City": "Madrid", "State": "Madrid", "Country": "ES"},
    },
    {
        "email": "pedro.martinez@timeshift.dev",
        "first_name": "Pedro", "last_name1": "Martínez", "last_name2": "López",
        "gender": "M", "phone": "622000002", "job_title": "Comercial",
        "contract_type": "Indefinido", "weekly_hours": 40.0,
        "identity": "22222222B", "ss_number": "280222222222",
        "dob": "1990-07-25", "hire_date": "2023-01-15",
        "dept_name": "Ventas", "schedule_name": "Horario Estandar",
        "address": {"Address": "Calle Velázquez 10", "ZipCode": "28001", "City": "Madrid", "State": "Madrid", "Country": "ES"},
    },
    {
        "email": "ana.lopez@timeshift.dev",
        "first_name": "Ana", "last_name1": "López", "last_name2": "Gómez",
        "gender": "F", "phone": "633000003", "job_title": "Marketing Manager",
        "contract_type": "Indefinido", "weekly_hours": 40.0,
        "identity": "33333333C", "ss_number": "080333333333",
        "dob": "1988-11-05", "hire_date": "2021-09-01",
        "dept_name": "Marketing", "schedule_name": "Horario Estandar",
        "address": {"Address": "Paseo de Gracia 55", "ZipCode": "08008", "City": "Barcelona", "State": "Cataluña", "Country": "ES"},
    },
    {
        "email": "luis.torres@timeshift.dev",
        "first_name": "Luis", "last_name1": "Torres", "last_name2": "Ruiz",
        "gender": "M", "phone": "644000004", "job_title": "Técnico Soporte",
        "contract_type": "Indefinido", "weekly_hours": 30.0,
        "identity": "44444444D", "ss_number": "280444444444",
        "dob": "1995-02-18", "hire_date": "2024-03-01",
        "dept_name": "Soporte", "schedule_name": "Horario Reducido",
        "address": {"Address": "Calle Gran Vía 40", "ZipCode": "28013", "City": "Madrid", "State": "Madrid", "Country": "ES"},
    },
    {
        "email": "elena.sanchez@timeshift.dev",
        "first_name": "Elena", "last_name1": "Sánchez", "last_name2": "Morales",
        "gender": "F", "phone": "655000005", "job_title": "Desarrolladora Senior",
        "contract_type": "Indefinido", "weekly_hours": 40.0,
        "identity": "55555555E", "ss_number": "280555555555",
        "dob": "1993-08-30", "hire_date": "2023-06-15",
        "dept_name": "Desarrollo", "schedule_name": "Horario Estandar",
        "address": {"Address": "Calle Atocha 80", "ZipCode": "28012", "City": "Madrid", "State": "Madrid", "Country": "ES"},
    },
]

def seed_users(db: Session, departments: dict, schedules: dict) -> dict:
    admin_role    = db.exec(select(Roles).where(Roles.RoleName == "admin")).first()
    employee_role = db.exec(select(Roles).where(Roles.RoleName == "employee")).first()
    # Si aún no existe el rol employee (BD antigua), usar admin como fallback
    if not employee_role:
        employee_role = admin_role
    result = {}
    hashed_pwd = bcrypt.hash("Test1234!")

    for u in USERS_DATA:
        existing = db.exec(select(Users).where(Users.Email == u["email"])).first()
        if existing:
            result[u["email"]] = existing
            log.info(f"  Usuario ya existe: {u['email']}")
            continue

        # Users
        user = Users(Email=u["email"], Password=hashed_pwd, IsInactive=False)
        db.add(user)
        db.commit()
        db.refresh(user)

        # UserDetail
        dob  = datetime.datetime.fromisoformat(u["dob"])
        hire = datetime.datetime.fromisoformat(u["hire_date"])
        detail = UserDetail(
            UserID=user.UserID,
            FirstName=u["first_name"], LastName1=u["last_name1"], LastName2=u["last_name2"],
            Gender=u["gender"], PhoneNumber=u["phone"],
            PersonalEmail=u["email"], IdentityNumber=u["identity"],
            Nationality="ES", SSNumber=u["ss_number"],
            DateOfBirth=dob, HireDate=hire,
            JobTitle=u["job_title"], ContractType=u["contract_type"],
            ContractWeeklyHours=u["weekly_hours"],
        )
        db.add(detail)

        # UserAddress
        addr = UserAddress(UserID=user.UserID, **u["address"], IsPrimary=True)
        db.add(addr)

        # UserDepartments
        dept = departments[u["dept_name"]]
        ud = UserDepartments(
            UserID=user.UserID, DeptID=dept.DeptID, IsPrimary=True,
            AssignedDate=datetime.date.fromisoformat(u["hire_date"]),
            DeAssignedDate=datetime.date(2045, 12, 31),
        )
        db.add(ud)

        # RoleUsers — usuarios regulares reciben rol employee
        ru = RoleUsers(RoleID=employee_role.RoleID, UserID=user.UserID)
        db.add(ru)

        db.commit()
        result[u["email"]] = user
        log.info(f"  ✓ Usuario creado: {u['first_name']} {u['last_name1']} <{u['email']}> (ID={user.UserID})")

    # Actualizar Carlos García (UserID=2) con departamento Desarrollo si no lo tiene
    carlos = db.exec(select(Users).where(Users.Email == "test@timeshift.dev")).first()
    if carlos:
        result["test@timeshift.dev"] = carlos
        has_dept = db.exec(select(UserDepartments).where(UserDepartments.UserID == carlos.UserID)).first()
        if not has_dept:
            ud = UserDepartments(
                UserID=carlos.UserID, DeptID=departments["Desarrollo"].DeptID, IsPrimary=True,
                AssignedDate=datetime.date(2024, 1, 10),
                DeAssignedDate=datetime.date(2045, 12, 31),
            )
            db.add(ud)
            db.commit()
            log.info(f"  ✓ Departamento asignado a Carlos García")

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 8. Supervisión (admin supervisa a todos)
# ─────────────────────────────────────────────────────────────────────────────

def seed_supervision(db: Session, users: dict) -> None:
    admin = db.exec(select(Users).where(Users.Email == "info@phoedata.com")).first()
    for email, user in users.items():
        if email == "info@phoedata.com":
            continue
        existing = db.exec(
            select(Supervision).where(
                Supervision.SupervisorID == admin.UserID,
                Supervision.SubordinateID == user.UserID,
            )
        ).first()
        if not existing:
            sup = Supervision(
                SupervisorID=admin.UserID,
                SubordinateID=user.UserID,
                AssignedDate=datetime.date.today(),
            )
            db.add(sup)
    db.commit()
    log.info(f"  ✓ Supervisión: admin supervisa a {len(users)-1} usuarios")


# ─────────────────────────────────────────────────────────────────────────────
# 9. Turnos (semana actual + siguiente)
# ─────────────────────────────────────────────────────────────────────────────

def get_week_range(week_offset: int = 0):
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday()) + datetime.timedelta(weeks=week_offset)
    friday = monday + datetime.timedelta(days=4)
    return monday, friday


def seed_shifts(db: Session, users: dict, departments: dict) -> None:
    admin = db.exec(select(Users).where(Users.Email == "info@phoedata.com")).first()

    user_dept_map = {
        "test@timeshift.dev":              ("Desarrollo",  datetime.time(9, 0),  datetime.time(18, 0)),
        "maria.garcia@timeshift.dev":      ("RRHH",        datetime.time(9, 0),  datetime.time(18, 0)),
        "pedro.martinez@timeshift.dev":    ("Ventas",      datetime.time(9, 0),  datetime.time(18, 0)),
        "ana.lopez@timeshift.dev":         ("Marketing",   datetime.time(9, 0),  datetime.time(18, 0)),
        "luis.torres@timeshift.dev":       ("Soporte",     datetime.time(9, 0),  datetime.time(15, 0)),
        "elena.sanchez@timeshift.dev":     ("Desarrollo",  datetime.time(9, 0),  datetime.time(18, 0)),
    }

    count = 0
    for week_offset in [0, 1]:
        monday, friday = get_week_range(week_offset)
        for email, (dept_name, start_t, end_t) in user_dept_map.items():
            user = users.get(email)
            if not user:
                continue
            dept = departments[dept_name]
            for day in workday_range(monday, friday):
                existing = db.exec(
                    select(Shifts).where(
                        Shifts.UserID == user.UserID,
                        Shifts.Date == day,
                    )
                ).first()
                if existing:
                    continue
                shift = Shifts(
                    UserID=user.UserID,
                    DepartmentID=dept.DeptID,
                    LocationID=dept.LocationID,
                    Date=day,
                    StartTime=start_t,
                    EndTime=end_t,
                    BreakTime=1.0,
                    IsPublished=True,
                    Status=ShiftStatus.Planned,
                    CreatedBy=admin.UserID,
                )
                db.add(shift)
                count += 1
    db.commit()
    log.info(f"  ✓ {count} turnos creados (semanas actual y siguiente)")


# ─────────────────────────────────────────────────────────────────────────────
# 10. WorkLogs históricos (últimas 3 semanas)
# ─────────────────────────────────────────────────────────────────────────────

def seed_worklogs(db: Session, users: dict, departments: dict, absence_types: dict) -> None:
    almuerzo_id = absence_types["Almuerzo"].AbsenceTypeID

    today = datetime.date.today()
    three_weeks_ago = today - datetime.timedelta(weeks=3)

    user_dept_map = {
        "test@timeshift.dev":           ("Desarrollo",  datetime.time(9, 0),  datetime.time(18, 0), 8.0),
        "info@phoedata.com":            ("Desarrollo",  datetime.time(9, 0),  datetime.time(18, 0), 8.0),
        "maria.garcia@timeshift.dev":   ("RRHH",        datetime.time(9, 0),  datetime.time(18, 0), 8.0),
        "pedro.martinez@timeshift.dev": ("Ventas",      datetime.time(9, 0),  datetime.time(18, 0), 8.0),
        "ana.lopez@timeshift.dev":      ("Marketing",   datetime.time(9, 0),  datetime.time(18, 0), 8.0),
        "luis.torres@timeshift.dev":    ("Soporte",     datetime.time(9, 0),  datetime.time(15, 0), 6.0),
        "elena.sanchez@timeshift.dev":  ("Desarrollo",  datetime.time(9, 0),  datetime.time(18, 0), 8.0),
    }

    wl_count = 0
    incomplete_created = False  # Solo un fichaje incompleto por usuario

    for email, (dept_name, start_t, _, daily_hours) in user_dept_map.items():
        user = db.exec(select(Users).where(Users.Email == email)).first()
        if not user:
            continue
        dept = departments.get(dept_name)
        if not dept:
            continue

        incomplete_done = False
        for day in workday_range(three_weeks_ago, today - datetime.timedelta(days=1)):
            # Verificar si ya existe WorkLog para este usuario+día
            if WorkLogs.exists(db, user.UserID, day):
                continue

            # Crear turno si no existe
            shift = db.exec(
                select(Shifts).where(
                    Shifts.UserID == user.UserID,
                    Shifts.Date == day,
                )
            ).first()
            if not shift:
                shift = Shifts(
                    UserID=user.UserID, DepartmentID=dept.DeptID, LocationID=dept.LocationID,
                    Date=day, StartTime=start_t,
                    EndTime=datetime.time(18, 0) if daily_hours == 8.0 else datetime.time(15, 0),
                    BreakTime=1.0 if daily_hours == 8.0 else 0.0,
                    IsPublished=True, Status=ShiftStatus.Planned,
                    CreatedBy=1,
                )
                db.add(shift)
                db.commit()
                db.refresh(shift)

            # Crear WorkLog
            wl = WorkLogs(UserID=user.UserID, LogDate=day, ShiftID=shift.ShiftID, IsFinished=False)
            wl = wl._create(db)

            # Crear líneas
            if daily_hours == 8.0:
                # Mañana + almuerzo + tarde
                l1 = WorkLogLines.create_line(
                    db, WorkLogID=wl.WorkLogID, WorkLogLineID=1,
                    StartTime=datetime.time(9, 0), EndTime=datetime.time(13, 0),
                    IsPause=False, LoggedHours=4.0,
                )
                l2 = WorkLogLines.create_line(
                    db, WorkLogID=wl.WorkLogID, WorkLogLineID=2,
                    StartTime=datetime.time(13, 0), EndTime=datetime.time(14, 0),
                    IsPause=True, AbsenceType=almuerzo_id, LoggedHours=1.0,
                )
                l3 = WorkLogLines.create_line(
                    db, WorkLogID=wl.WorkLogID, WorkLogLineID=3,
                    StartTime=datetime.time(14, 0), EndTime=datetime.time(18, 0),
                    IsPause=False, LoggedHours=4.0,
                )
                lines = [l1, l2, l3]
            else:
                # Jornada continua (6h)
                l1 = WorkLogLines.create_line(
                    db, WorkLogID=wl.WorkLogID, WorkLogLineID=1,
                    StartTime=datetime.time(9, 0), EndTime=datetime.time(15, 0),
                    IsPause=False, LoggedHours=6.0,
                )
                lines = [l1]

            # Un fichaje incompleto por empleado (ayer sin EndTime en la línea)
            if not incomplete_done and day == today - datetime.timedelta(days=1):
                # Fichaje incompleto: solo una línea sin EndTime
                for l in lines:
                    l.delete(db)
                lines = []
                l_inc = WorkLogLines.create_line(
                    db, WorkLogID=wl.WorkLogID, WorkLogLineID=1,
                    StartTime=datetime.time(9, 0), EndTime=None,
                    IsPause=False, LoggedHours=0.0,
                )
                lines = [l_inc]
                wl.lines = lines
                # No crear totals para fichaje incompleto
                incomplete_done = True
                wl_count += 1
                continue

            wl.lines = lines
            wl.update(db, IsFinished=True)
            wl.create_totals(db)

            # Marcar turno como completado
            shift.Status = ShiftStatus.Completed
            db.add(shift)
            db.commit()

            wl_count += 1

    log.info(f"  ✓ {wl_count} WorkLogs creados (últimas 3 semanas)")


# ─────────────────────────────────────────────────────────────────────────────
# 11. Balance de ausencias
# ─────────────────────────────────────────────────────────────────────────────

def seed_balances(db: Session, users: dict, absence_types: dict) -> None:
    vacaciones_id = absence_types["Vacaciones"].AbsenceTypeID
    year = datetime.date.today().year
    count = 0
    all_users = list(users.values())
    # Incluir admin y carlos
    for email in ["info@phoedata.com", "test@timeshift.dev"]:
        u = db.exec(select(Users).where(Users.Email == email)).first()
        if u and u not in all_users:
            all_users.append(u)

    for user in all_users:
        existing = AbsenceBalance.get(db, user.UserID, vacaciones_id, year)
        if existing:
            continue
        balance = AbsenceBalance(
            UserID=user.UserID, AbsenceTypeID=vacaciones_id,
            Year=year, AccruedDays=22.0, UsedDays=0.0, PendingDays=0.0,
        )
        balance._create(db)
        count += 1
    log.info(f"  ✓ {count} balances de vacaciones creados (22 días, año {year})")


# ─────────────────────────────────────────────────────────────────────────────
# 12. Solicitudes de ausencia
# ─────────────────────────────────────────────────────────────────────────────

def seed_requests(db: Session, users: dict, absence_types: dict) -> None:
    admin_id = db.exec(select(Users).where(Users.Email == "info@phoedata.com")).first().UserID
    vacaciones_id = absence_types["Vacaciones"].AbsenceTypeID
    year = datetime.date.today().year
    count = 0

    requests_data = [
        {
            "email": "test@timeshift.dev",
            "start": datetime.datetime(year, 7, 1, 8, 0),
            "end":   datetime.datetime(year, 7, 5, 17, 0),
            "reason": "Vacaciones de verano",
            "status": AbsenceStatus.PENDING,
            "total_days": 3.0,
        },
        {
            "email": "pedro.martinez@timeshift.dev",
            "start": datetime.datetime(year, 8, 3, 8, 0),
            "end":   datetime.datetime(year, 8, 5, 17, 0),
            "reason": "Vacaciones agosto",
            "status": AbsenceStatus.APPROVED,
            "total_days": 3.0,
        },
        {
            "email": "ana.lopez@timeshift.dev",
            "start": datetime.datetime(year, 9, 15, 8, 0),
            "end":   datetime.datetime(year, 9, 15, 17, 0),
            "reason": "Asunto personal",
            "status": AbsenceStatus.REJECTED,
            "total_days": 1.0,
        },
    ]

    for req_data in requests_data:
        user = db.exec(select(Users).where(Users.Email == req_data["email"])).first()
        if not user:
            continue
        # Verificar si ya existe
        existing = db.exec(
            select(AbsenceRequests).where(
                AbsenceRequests.UserID == user.UserID,
                AbsenceRequests.StartTime == req_data["start"],
            )
        ).first()
        if existing:
            log.info(f"  Solicitud ya existe para {req_data['email']}")
            continue

        req = AbsenceRequests(
            UserID=user.UserID,
            AbsenceTypeID=vacaciones_id,
            RequestDate=datetime.date.today(),
            StartTime=req_data["start"],
            EndTime=req_data["end"],
            Reason=req_data["reason"],
            Status=req_data["status"],
            TotalDays=req_data["total_days"],
        )
        req._create(db)

        # Actualizar balance
        balance = AbsenceBalance.get(db, user.UserID, vacaciones_id, year)
        if balance:
            if req_data["status"] == AbsenceStatus.PENDING:
                balance.update(db, PendingDays=balance.PendingDays + req_data["total_days"])
            elif req_data["status"] == AbsenceStatus.APPROVED:
                balance.update(db, UsedDays=balance.UsedDays + req_data["total_days"])

        # Crear revisión para aprobada/rechazada
        if req_data["status"] in (AbsenceStatus.APPROVED, AbsenceStatus.REJECTED):
            review = AbsenceReviews(
                RequestID=req.RequestID,
                ReviewerID=admin_id,
                ReviewDate=datetime.datetime.now(),
                ReviewResult=req_data["status"],
                ReviewComments="Revisado por administración",
            )
            review._create(db)

        count += 1
    log.info(f"  ✓ {count} solicitudes de ausencia creadas")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def seed():
    log.info("=" * 60)
    log.info("SEED DE DATOS DE DESARROLLO — TIMESHIFT")
    log.info("=" * 60)

    with Session(engine) as db:
        log.info("\n[1/12] Empresas")
        companies = seed_companies(db)

        log.info("\n[2/12] Ubicaciones")
        locations = seed_locations(db)

        log.info("\n[3/12] Departamentos")
        departments = seed_departments(db, companies, locations)

        log.info("\n[4/12] Horarios")
        schedules = seed_schedules(db)

        log.info("\n[5/12] Tipos de ausencia")
        absence_types = seed_absence_types(db)

        log.info("\n[6/12] Festivos")
        seed_holidays(db, companies)

        log.info("\n[7/12] Usuarios")
        users = seed_users(db, departments, schedules)

        log.info("\n[8/12] Supervisión")
        seed_supervision(db, users)

        log.info("\n[9/12] Turnos (semana actual + siguiente)")
        seed_shifts(db, users, departments)

        log.info("\n[10/12] WorkLogs históricos (3 semanas)")
        seed_worklogs(db, users, departments, absence_types)

        log.info("\n[11/12] Balance de ausencias")
        seed_balances(db, users, absence_types)

        log.info("\n[12/12] Solicitudes de ausencia")
        seed_requests(db, users, absence_types)

    log.info("\n" + "=" * 60)
    log.info("✅ SEED COMPLETADO")
    log.info("=" * 60)
    log.info("\nUsuarios disponibles:")
    log.info("  info@phoedata.com          / admin      (Administrador)")
    log.info("  test@timeshift.dev         / Test1234!  (Carlos García - Desarrollo)")
    log.info("  maria.garcia@timeshift.dev / Test1234!  (María García - RRHH)")
    log.info("  pedro.martinez@timeshift.dev / Test1234! (Pedro Martínez - Ventas)")
    log.info("  ana.lopez@timeshift.dev    / Test1234!  (Ana López - Marketing)")
    log.info("  luis.torres@timeshift.dev  / Test1234!  (Luis Torres - Soporte)")
    log.info("  elena.sanchez@timeshift.dev / Test1234! (Elena Sánchez - Desarrollo)")


if __name__ == "__main__":
    seed()
