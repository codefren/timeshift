"""
Seed de empleados inactivos para pruebas de visualización.

Crea dos tipos de empleados que NO deben aparecer en listados operacionales:

  Caso A — IsInactive = True
    Empleados dados de baja explícitamente del sistema (despedidos, bajas voluntarias, etc.)

  Caso B — DeAssignedDate vencido
    Empleados con contrato/asignación de departamento ya expirado.
    IsInactive = False, pero su período de asignación terminó → no están activos en ninguna tienda.

  Caso C — AssignedDate futuro
    Empleados cuya asignación aún no ha comenzado.

Ejecutar con:
    docker compose exec backend python /backend/db/seed_inactive_employees.py
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
from SQLModels.Roles import Roles, RoleUsers
from SQLModels.Users import Users, UserDetail, UserAddress, UserDepartments, Supervision

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_or_none(db: Session, model, **kwargs):
    q = select(model)
    for k, v in kwargs.items():
        q = q.where(getattr(model, k) == v)
    return db.exec(q).first()


def get_dept(db: Session, name: str) -> Departments:
    dept = get_or_none(db, Departments, DeptName=name)
    if not dept:
        raise RuntimeError(
            f"Departamento '{name}' no encontrado. "
            "Ejecuta seed_dev_data.py antes de este script."
        )
    return dept


# ─────────────────────────────────────────────────────────────────────────────
# Datos de los empleados inactivos
# ─────────────────────────────────────────────────────────────────────────────

today      = datetime.date.today()
two_years_ago = today.replace(year=today.year - 2)

INACTIVE_USERS = [
    # ── Caso A: IsInactive = True (dados de baja explícitamente) ─────────────
    {
        "caso": "A",
        "label": "Despedido",
        "email": "roberto.vega@timeshift.dev",
        "first_name": "Roberto", "last_name1": "Vega", "last_name2": "Blanco",
        "gender": "M", "phone": "600100001", "job_title": "Vendedor",
        "contract_type": "Indefinido", "weekly_hours": 40.0,
        "identity": "91000001Z", "ss_number": "280910000001",
        "dob": "1987-04-15", "hire_date": "2020-01-10",
        "dept_name": "Ventas",
        "address": {"Address": "Calle Luna 3", "ZipCode": "28004",
                    "City": "Madrid", "State": "Madrid", "Country": "ES"},
        # Asignación en rango válido, pero usuario dado de baja del sistema
        "assigned_date": datetime.date(2020, 1, 10),
        "de_assigned_date": datetime.date(today.year + 10, 12, 31),
        "is_inactive": True,
    },
    {
        "caso": "A",
        "label": "Baja voluntaria",
        "email": "carmen.ruiz@timeshift.dev",
        "first_name": "Carmen", "last_name1": "Ruiz", "last_name2": "Herrera",
        "gender": "F", "phone": "600100002", "job_title": "Técnica RRHH",
        "contract_type": "Indefinido", "weekly_hours": 40.0,
        "identity": "91000002Y", "ss_number": "280910000002",
        "dob": "1991-09-22", "hire_date": "2019-06-01",
        "dept_name": "RRHH",
        "address": {"Address": "Avenida Libertad 7", "ZipCode": "28010",
                    "City": "Madrid", "State": "Madrid", "Country": "ES"},
        "assigned_date": datetime.date(2019, 6, 1),
        "de_assigned_date": datetime.date(today.year + 10, 12, 31),
        "is_inactive": True,
    },

    # ── Caso B: DeAssignedDate vencido (período de contratación expirado) ────
    {
        "caso": "B",
        "label": "Contrato temporal expirado",
        "email": "javier.molina@timeshift.dev",
        "first_name": "Javier", "last_name1": "Molina", "last_name2": "Soto",
        "gender": "M", "phone": "600200001", "job_title": "Desarrollador Junior",
        "contract_type": "Temporal", "weekly_hours": 40.0,
        "identity": "92000001X", "ss_number": "280920000001",
        "dob": "1998-03-05", "hire_date": "2022-01-01",
        "dept_name": "Desarrollo",
        "address": {"Address": "Calle Paz 12", "ZipCode": "28012",
                    "City": "Madrid", "State": "Madrid", "Country": "ES"},
        # Asignación terminó hace más de un año
        "assigned_date": datetime.date(2022, 1, 1),
        "de_assigned_date": today - datetime.timedelta(days=400),
        "is_inactive": False,
    },
    {
        "caso": "B",
        "label": "Proyecto finalizado",
        "email": "sofia.iglesias@timeshift.dev",
        "first_name": "Sofía", "last_name1": "Iglesias", "last_name2": "Castro",
        "gender": "F", "phone": "600200002", "job_title": "Analista Marketing",
        "contract_type": "Obra y servicio", "weekly_hours": 30.0,
        "identity": "92000002W", "ss_number": "080920000002",
        "dob": "1994-11-18", "hire_date": "2023-02-15",
        "dept_name": "Marketing",
        "address": {"Address": "Paseo Colón 22", "ZipCode": "08002",
                    "City": "Barcelona", "State": "Cataluña", "Country": "ES"},
        # Asignación terminó el mes pasado
        "assigned_date": datetime.date(2023, 2, 15),
        "de_assigned_date": today.replace(day=1) - datetime.timedelta(days=1),
        "is_inactive": False,
    },
    {
        "caso": "B",
        "label": "Excedencia sin reincorporar",
        "email": "miguel.pardo@timeshift.dev",
        "first_name": "Miguel", "last_name1": "Pardo", "last_name2": "Nieto",
        "gender": "M", "phone": "600200003", "job_title": "Técnico Soporte",
        "contract_type": "Indefinido", "weekly_hours": 30.0,
        "identity": "92000003V", "ss_number": "280920000003",
        "dob": "1989-07-30", "hire_date": "2021-05-01",
        "dept_name": "Soporte",
        "address": {"Address": "Calle Norte 4", "ZipCode": "28020",
                    "City": "Madrid", "State": "Madrid", "Country": "ES"},
        # Asignación terminó hace exactamente 1 año
        "assigned_date": datetime.date(2021, 5, 1),
        "de_assigned_date": today.replace(year=today.year - 1),
        "is_inactive": False,
    },

    # ── Caso C: AssignedDate en el futuro (aún no ha comenzado) ──────────────
    {
        "caso": "C",
        "label": "Incorporación futura",
        "email": "laura.fuentes@timeshift.dev",
        "first_name": "Laura", "last_name1": "Fuentes", "last_name2": "Peña",
        "gender": "F", "phone": "600300001", "job_title": "Comercial",
        "contract_type": "Indefinido", "weekly_hours": 40.0,
        "identity": "93000001U", "ss_number": "280930000001",
        "dob": "1996-06-14", "hire_date": "2025-01-01",
        "dept_name": "Ventas",
        "address": {"Address": "Calle Sur 9", "ZipCode": "28007",
                    "City": "Madrid", "State": "Madrid", "Country": "ES"},
        # Asignación empieza en el futuro
        "assigned_date": today + datetime.timedelta(days=60),
        "de_assigned_date": datetime.date(today.year + 5, 12, 31),
        "is_inactive": False,
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Función principal de seed
# ─────────────────────────────────────────────────────────────────────────────

def seed_inactive_employees(db: Session) -> None:
    role = get_or_none(db, Roles, RoleName="admin")
    if not role:
        raise RuntimeError("Rol 'admin' no encontrado. Ejecuta create_first_data primero.")

    admin = get_or_none(db, Users, Email="info@phoedata.com")
    if not admin:
        raise RuntimeError("Usuario admin (info@phoedata.com) no encontrado.")

    hashed_pwd = bcrypt.hash("Test1234!")
    counts = {"A": 0, "B": 0, "C": 0}

    for u in INACTIVE_USERS:
        # ── Idempotencia ──────────────────────────────────────────────────────
        existing = get_or_none(db, Users, Email=u["email"])
        if existing:
            log.info(f"  Ya existe: {u['email']}")
            continue

        dept = get_dept(db, u["dept_name"])

        # ── Users ─────────────────────────────────────────────────────────────
        user = Users(
            Email=u["email"],
            Password=hashed_pwd,
            IsInactive=u["is_inactive"],
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # ── UserDetail ────────────────────────────────────────────────────────
        dob  = datetime.datetime.fromisoformat(u["dob"])
        hire = datetime.datetime.fromisoformat(u["hire_date"])
        detail = UserDetail(
            UserID=user.UserID,
            FirstName=u["first_name"],
            LastName1=u["last_name1"],
            LastName2=u["last_name2"],
            Gender=u["gender"],
            PhoneNumber=u["phone"],
            PersonalEmail=u["email"],
            IdentityNumber=u["identity"],
            Nationality="ES",
            SSNumber=u["ss_number"],
            DateOfBirth=dob,
            HireDate=hire,
            JobTitle=u["job_title"],
            ContractType=u["contract_type"],
            ContractWeeklyHours=u["weekly_hours"],
        )
        db.add(detail)

        # ── UserAddress ───────────────────────────────────────────────────────
        addr = UserAddress(UserID=user.UserID, **u["address"], IsPrimary=True)
        db.add(addr)

        # ── UserDepartments ───────────────────────────────────────────────────
        ud = UserDepartments(
            UserID=user.UserID,
            DeptID=dept.DeptID,
            IsPrimary=True,
            AssignedDate=u["assigned_date"],
            DeAssignedDate=u["de_assigned_date"],
        )
        db.add(ud)

        # ── RoleUsers ─────────────────────────────────────────────────────────
        db.add(RoleUsers(RoleID=role.RoleID, UserID=user.UserID))

        # ── Supervision (admin lo puede ver en el listado admin) ──────────────
        sup_exists = get_or_none(
            db, Supervision,
            SupervisorID=admin.UserID,
            SubordinateID=user.UserID,
        )
        if not sup_exists:
            db.add(Supervision(
                SupervisorID=admin.UserID,
                SubordinateID=user.UserID,
                AssignedDate=datetime.date.today(),
            ))

        db.commit()
        counts[u["caso"]] += 1

        status_tag = (
            "IsInactive=True"
            if u["is_inactive"]
            else f"DeAssignedDate={u['de_assigned_date']}"
            if u["assigned_date"] <= today
            else f"AssignedDate futuro={u['assigned_date']}"
        )
        log.info(
            f"  ✓ [Caso {u['caso']}] {u['first_name']} {u['last_name1']} "
            f"<{u['email']}> — {u['label']} ({status_tag})"
        )

    log.info("")
    log.info(f"  Caso A (IsInactive=True):          {counts['A']} empleados")
    log.info(f"  Caso B (DeAssignedDate vencido):   {counts['B']} empleados")
    log.info(f"  Caso C (AssignedDate futuro):       {counts['C']} empleados")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def seed():
    log.info("=" * 60)
    log.info("SEED — EMPLEADOS INACTIVOS / FUERA DE PERIODO")
    log.info("=" * 60)

    with Session(engine) as db:
        seed_inactive_employees(db)

    log.info("")
    log.info("=" * 60)
    log.info("✅ COMPLETADO")
    log.info("=" * 60)
    log.info("")
    log.info("Empleados creados (NO deben aparecer en endpoints operacionales):")
    log.info("")
    log.info("  CASO A — IsInactive = True (dados de baja del sistema):")
    log.info("    roberto.vega@timeshift.dev   / Test1234!  (Despedido)")
    log.info("    carmen.ruiz@timeshift.dev    / Test1234!  (Baja voluntaria)")
    log.info("")
    log.info("  CASO B — DeAssignedDate vencido (contrato/período expirado):")
    log.info("    javier.molina@timeshift.dev  / Test1234!  (Contrato temporal expirado)")
    log.info("    sofia.iglesias@timeshift.dev / Test1234!  (Proyecto finalizado)")
    log.info("    miguel.pardo@timeshift.dev   / Test1234!  (Excedencia sin reincorporar)")
    log.info("")
    log.info("  CASO C — AssignedDate en el futuro (aún no incorporado):")
    log.info("    laura.fuentes@timeshift.dev  / Test1234!  (Incorporación futura +60 días)")
    log.info("")
    log.info("  Todos DEBEN aparecer en GET /employees/ (listado admin, ordenados al final).")
    log.info("  Ninguno debe aparecer en /subordinates/, /app-data/ teammates, ni /companies/.")


if __name__ == "__main__":
    seed()
