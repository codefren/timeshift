"""
Verifica que los datos de la instancia son coherentes y que la app los ve bien.
SOLO LECTURA: no modifica nada (todo se hace dentro de una transacción que se deshace).

Comprueba:
  - Esquema: columnas de los modelos que faltan en la BD (p.ej. Locations.ControlRadius)
  - Empresas: existe la CompanyID=1 (el frontend la tiene fija) y está activa
  - Ubicaciones: coordenadas y ControlRadius rellenos
  - Departamentos: empresa/ubicación válidas y activas, jerarquía sin ciclos ni varios padres
  - Usuarios: detalle, rol y un único departamento primario vigente; registros viudos
  - Supervisiones incoherentes
  - Lógica de la app con el admin: departamentos y usuarios visibles

Uso (dentro del contenedor, WORKDIR /code/app):

    python -W ignore db/check_data.py
    python -W ignore db/check_data.py --admin-email info@phoedata.com

Código de salida: 0 si no hay errores, 1 si hay algún [ERROR].
"""

import argparse
import datetime
import os
import sys

# Permite ejecutarlo como `python db/check_data.py` desde /code/app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(1, '/code/app')

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, select

from db.session import engine
import SQLModels  # registra todos los modelos en SQLModel.metadata

FRONTEND_COMPANY_ID = 1
# Tablas que cargan las comprobaciones ORM de check_app_logic
APP_LOGIC_TABLES = {"Users", "Departments", "UserDepartments", "DepartmentsRelations", "Supervision",
                    "RoleUsers", "Roles", "RolePermissions", "Permissions"}


class Report:
    def __init__(self):
        self.errors = 0
        self.warnings = 0

    def section(self, title: str):
        print(f"\n== {title}")

    def ok(self, msg: str):
        print(f"  [OK]    {msg}")

    def warn(self, msg: str):
        self.warnings += 1
        print(f"  [WARN]  {msg}")

    def error(self, msg: str):
        self.errors += 1
        print(f"  [ERROR] {msg}")

    def rows(self, rows, fmt, limit: int = 10):
        for r in rows[:limit]:
            print(f"          - {fmt(r)}")
        if len(rows) > limit:
            print(f"          ... y {len(rows) - limit} más")


def check_schema(rep: Report) -> set[tuple[str, str]]:
    rep.section("Esquema (modelos vs BD)")
    insp = inspect(engine)
    db_tables = set(insp.get_table_names())
    missing = set()
    for table in SQLModel.metadata.tables.values():
        if table.name not in db_tables:
            rep.error(f"Falta la tabla {table.name}")
            continue
        db_cols = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name not in db_cols:
                missing.add((table.name, col.name))
                rep.error(f"Falta la columna {table.name}.{col.name}: las consultas de la app sobre "
                          f"{table.name} fallarán")
    if not missing:
        rep.ok("Todas las tablas y columnas de los modelos existen en la BD")
    return missing


def check_companies(rep: Report, conn):
    rep.section("Empresas")
    rows = conn.execute(text("SELECT CompanyID, SocialName, TaxID, Active FROM Companies ORDER BY CompanyID")).all()
    if not rows:
        rep.error("No hay ninguna empresa")
        return
    for r in rows:
        print(f"          [{r.CompanyID}] {r.SocialName} ({r.TaxID}){'' if r.Active else ' INACTIVA'}")
    first = next((r for r in rows if r.CompanyID == FRONTEND_COMPANY_ID), None)
    if not first:
        rep.error(f"No existe CompanyID={FRONTEND_COMPANY_ID}: el frontend pide companies/1/departments/ "
                  f"y no mostrará ningún departamento")
    elif not first.Active:
        rep.error(f"CompanyID={FRONTEND_COMPANY_ID} está inactiva")
    else:
        rep.ok(f"CompanyID={FRONTEND_COMPANY_ID} existe y está activa ({first.SocialName})")


def check_locations(rep: Report, conn, missing_cols):
    rep.section("Ubicaciones")
    has_radius = ("Locations", "ControlRadius") not in missing_cols
    radius = "ControlRadius" if has_radius else "NULL AS ControlRadius"
    rows = conn.execute(text(f"SELECT LocationID, LocationName, Lat, Long, Active, {radius} FROM Locations")).all()
    if not rows:
        rep.error("No hay ninguna ubicación")
        return
    for r in rows:
        print(f"          [{r.LocationID}] {r.LocationName} lat={r.Lat} long={r.Long} "
              f"radio={r.ControlRadius}{'' if r.Active else ' INACTIVA'}")
    bad_coords = [r for r in rows if r.Lat is None or r.Long is None or (r.Lat == 0 and r.Long == 0)]
    if bad_coords:
        rep.error(f"{len(bad_coords)} ubicación(es) sin coordenadas válidas (el geofence de fichaje no funcionará)")
    bad_radius = [r for r in rows if r.ControlRadius is None or r.ControlRadius <= 0]
    if bad_radius:
        rep.error(f"{len(bad_radius)} ubicación(es) sin ControlRadius válido")
    if not bad_coords and not bad_radius:
        rep.ok(f"{len(rows)} ubicación(es) con coordenadas y ControlRadius")


def check_departments(rep: Report, conn):
    rep.section("Departamentos")
    rows = conn.execute(text("""
        SELECT d.DeptID, d.DeptName, d.Active, d.CompanyID, c.Active AS CompanyActive,
               d.LocationID, l.Active AS LocationActive
        FROM Departments d
        LEFT JOIN Companies c ON c.CompanyID = d.CompanyID
        LEFT JOIN Locations l ON l.LocationID = d.LocationID
        ORDER BY d.DeptID""")).all()
    if not rows:
        rep.error("No hay ningún departamento")
        return
    active = [r for r in rows if r.Active]
    rep.ok(f"{len(active)} departamento(s) activo(s) de {len(rows)}")
    for r in active:
        if r.CompanyActive is None or not r.CompanyActive:
            rep.error(f"Depto [{r.DeptID}] {r.DeptName}: empresa {r.CompanyID} inexistente o inactiva")
        elif r.CompanyID != FRONTEND_COMPANY_ID:
            rep.warn(f"Depto [{r.DeptID}] {r.DeptName}: pertenece a CompanyID={r.CompanyID}; "
                     f"el frontend solo muestra los de la empresa {FRONTEND_COMPANY_ID}")
        if r.LocationActive is None or not r.LocationActive:
            rep.error(f"Depto [{r.DeptID}] {r.DeptName}: ubicación {r.LocationID} inexistente o inactiva")

    no_users = conn.execute(text("""
        SELECT d.DeptID, d.DeptName FROM Departments d
        WHERE d.Active = 1 AND NOT EXISTS (
            SELECT 1 FROM UserDepartments ud WHERE ud.DeptID = d.DeptID
              AND ud.AssignedDate <= CAST(GETDATE() AS date)
              AND (ud.DeAssignedDate IS NULL OR ud.DeAssignedDate > CAST(GETDATE() AS date)))""")).all()
    if no_users:
        rep.warn(f"{len(no_users)} departamento(s) activo(s) sin ningún usuario asignado vigente")
        rep.rows(no_users, lambda r: f"[{r.DeptID}] {r.DeptName}")

    # Jerarquía
    rels = conn.execute(text("SELECT DeptID, ParentDeptID FROM DepartmentsRelations")).all()
    dept_ids = {r.DeptID for r in rows}
    dangling = [r for r in rels if r.DeptID not in dept_ids or r.ParentDeptID not in dept_ids]
    if dangling:
        rep.error(f"{len(dangling)} relación(es) padre/hijo apuntan a departamentos inexistentes")
    parents: dict[int, list[int]] = {}
    for r in rels:
        parents.setdefault(r.DeptID, []).append(r.ParentDeptID)
    multi = {d: p for d, p in parents.items() if len(p) > 1}
    if multi:
        rep.error(f"Departamentos con varios padres (la app solo soporta uno): {multi}")
    cycles = set()
    for start in parents:
        seen, cur = set(), start
        while cur in parents and cur not in seen:
            seen.add(cur)
            cur = parents[cur][0]
        if cur in seen:
            cycles.add(start)
    if cycles:
        rep.error(f"Ciclo en la jerarquía de departamentos (la consulta recursiva fallará): {sorted(cycles)}")
    if not dangling and not multi and not cycles:
        rep.ok(f"Jerarquía correcta ({len(rels)} relación(es) padre/hijo)")


def check_users(rep: Report, conn):
    rep.section("Usuarios")
    total = conn.execute(text("SELECT COUNT(*) FROM Users")).scalar_one()
    active = conn.execute(text("SELECT COUNT(*) FROM Users WHERE IsInactive = 0")).scalar_one()
    rep.ok(f"{total} usuario(s), {active} activo(s)")

    widows = {
        "UserDetail sin Users": "SELECT UserID FROM UserDetail WHERE UserID NOT IN (SELECT UserID FROM Users)",
        "UserAddress sin Users": "SELECT UserID FROM UserAddress WHERE UserID NOT IN (SELECT UserID FROM Users)",
        "UserPicture sin Users": "SELECT UserID FROM UserPicture WHERE UserID NOT IN (SELECT UserID FROM Users)",
        "UserDepartments sin Users": "SELECT UserID FROM UserDepartments WHERE UserID NOT IN (SELECT UserID FROM Users)",
        "RoleUsers sin Users": "SELECT UserID FROM RoleUsers WHERE UserID NOT IN (SELECT UserID FROM Users)",
        "Users sin UserDetail (creación a medias)":
            "SELECT UserID, Email FROM Users WHERE UserID NOT IN (SELECT UserID FROM UserDetail)",
        "Users sin rol": "SELECT UserID, Email FROM Users WHERE UserID NOT IN (SELECT UserID FROM RoleUsers)",
    }
    for label, q in widows.items():
        found = conn.execute(text(q)).all()
        if found:
            rep.error(f"{label}: {len(found)}")
            rep.rows(found, lambda r: ", ".join(f"{k}={v}" for k, v in r._mapping.items()))
    if all(not conn.execute(text(q)).first() for q in widows.values()):
        rep.ok("Sin registros viudos (todas las filas de usuario tienen su Users, detalle y rol)")

    primaries = conn.execute(text("""
        SELECT u.UserID, u.Email,
               SUM(CASE WHEN ud.IsPrimary = 1
                         AND ud.AssignedDate <= CAST(GETDATE() AS date)
                         AND (ud.DeAssignedDate IS NULL OR ud.DeAssignedDate > CAST(GETDATE() AS date))
                        THEN 1 ELSE 0 END) AS NPrimary,
               SUM(CASE WHEN ud.DeptID IS NOT NULL
                         AND ud.AssignedDate <= CAST(GETDATE() AS date)
                         AND (ud.DeAssignedDate IS NULL OR ud.DeAssignedDate > CAST(GETDATE() AS date))
                        THEN 1 ELSE 0 END) AS NCurrent
        FROM Users u LEFT JOIN UserDepartments ud ON ud.UserID = u.UserID
        WHERE u.IsInactive = 0
        GROUP BY u.UserID, u.Email""")).all()
    no_dept = [r for r in primaries if r.NCurrent == 0]
    no_primary = [r for r in primaries if r.NCurrent > 0 and r.NPrimary == 0]
    many_primary = [r for r in primaries if r.NPrimary > 1]
    if no_dept:
        rep.warn(f"{len(no_dept)} usuario(s) activo(s) sin ningún departamento vigente")
        rep.rows(no_dept, lambda r: f"[{r.UserID}] {r.Email}")
    if no_primary:
        rep.error(f"{len(no_primary)} usuario(s) sin departamento primario vigente "
                  f"(no verán a sus compañeros)")
        rep.rows(no_primary, lambda r: f"[{r.UserID}] {r.Email}")
    if many_primary:
        rep.error(f"{len(many_primary)} usuario(s) con varios primarios vigentes (la app elige uno al azar)")
        rep.rows(many_primary, lambda r: f"[{r.UserID}] {r.Email} ({r.NPrimary} primarios)")
    if not no_dept and not no_primary and not many_primary:
        rep.ok("Todos los usuarios activos tienen exactamente un departamento primario vigente")

    inactive_dept = conn.execute(text("""
        SELECT ud.UserID, ud.DeptID, d.DeptName FROM UserDepartments ud
        JOIN Departments d ON d.DeptID = ud.DeptID
        WHERE d.Active = 0
          AND (ud.DeAssignedDate IS NULL OR ud.DeAssignedDate > CAST(GETDATE() AS date))""")).all()
    if inactive_dept:
        rep.warn(f"{len(inactive_dept)} asignación(es) vigente(s) a departamentos inactivos")
        rep.rows(inactive_dept, lambda r: f"UserID={r.UserID} -> [{r.DeptID}] {r.DeptName}")

    rep.section("Supervisiones")
    self_sup = conn.execute(text("SELECT SupervisorID FROM Supervision WHERE SupervisorID = SubordinateID")).all()
    if self_sup:
        rep.error(f"{len(self_sup)} usuario(s) se supervisan a sí mismos")
    n = conn.execute(text("SELECT COUNT(*) FROM Supervision")).scalar_one()
    if not self_sup:
        rep.ok(f"{n} supervisión(es), ninguna incoherente")


def check_app_logic(rep: Report, db: Session, admin_email: str, missing_cols):
    from SQLModels import Departments, Users
    from dependencies import Pagination
    from sqlmodel import desc

    rep.section(f"Lógica de la app (como la ve {admin_email})")
    blocking = {t for t, _ in missing_cols} & APP_LOGIC_TABLES
    if blocking:
        rep.warn(f"Se omite: faltan columnas en {sorted(blocking)} y las consultas ORM fallarían")
        return
    admin = db.exec(select(Users).where(Users.Email == admin_email)).first()
    if not admin:
        rep.error(f"No existe el usuario {admin_email}")
        return
    if admin.IsInactive:
        rep.error(f"{admin_email} está inactivo y no podrá iniciar sesión")
    perms = admin.permissions
    for p in ("manage:Users", "view:All"):
        if p in perms:
            rep.ok(f"{admin_email} tiene {p}")
        else:
            rep.error(f"{admin_email} no tiene {p}")

    # Lo mismo que GET /api/companies/1/departments/ (lo que pinta el desplegable del frontend)
    try:
        params = Pagination(order="desc", size=250, page=1)
        params.order = desc
        listed = Departments.list(db, params, None, company_id=FRONTEND_COMPANY_ID, user=admin)
        names = [d.DeptName for d in listed.departments if d.Active]
        expected = db.exec(select(Departments).where(Departments.CompanyID == FRONTEND_COMPANY_ID,
                                                     Departments.Active == True)).unique().all()
        if len(names) == len(expected) and names:
            rep.ok(f"GET companies/{FRONTEND_COMPANY_ID}/departments/ devuelve {len(names)}: {', '.join(names)}")
        else:
            rep.error(f"GET companies/{FRONTEND_COMPANY_ID}/departments/ devuelve {len(names)} activos, "
                      f"se esperaban {len(expected)}")
    except Exception as e:
        rep.error(f"Departments.list falló: {e}")

    try:
        viewable = admin.get_viewable_users_ids(db)
        all_active = set(db.exec(select(Users.UserID).where(Users.IsInactive == False)).all())
        hidden = all_active - set(viewable)
        if hidden:
            rep.error(f"{len(hidden)} usuario(s) activo(s) no visibles para el admin: {sorted(hidden)}")
        else:
            rep.ok(f"El admin ve a los {len(all_active)} usuario(s) activo(s)")
    except Exception as e:
        rep.error(f"get_viewable_users_ids falló: {e}")

    main_dept = admin.get_main_department()
    if main_dept:
        rep.ok(f"Departamento primario del admin: [{main_dept.DeptID}] {main_dept.DeptName}")
    else:
        rep.warn("El admin no tiene departamento primario vigente")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verifica la coherencia de los datos (solo lectura)")
    parser.add_argument("--admin-email", default="info@phoedata.com")
    args = parser.parse_args()

    rep = Report()
    print(f"Verificación de datos - BD {engine.url.database} - {datetime.datetime.now():%Y-%m-%d %H:%M}")

    missing_cols = check_schema(rep)
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            check_companies(rep, conn)
            check_locations(rep, conn, missing_cols)
            check_departments(rep, conn)
            check_users(rep, conn)
        finally:
            trans.rollback()

    with Session(engine) as db:
        try:
            check_app_logic(rep, db, args.admin_email, missing_cols)
        finally:
            db.rollback()

    print(f"\nResumen: {rep.errors} error(es), {rep.warnings} aviso(s)")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
