"""
Crea uno o varios departamentos y los asigna a un usuario (por defecto el admin
info@phoedata.com, creado en create_first_data).

Si la empresa (por SocialName) o la ubicación (por LocationName) no existen, las crea.
Si a la tabla Locations le falta la columna ControlRadius, la añade, y siempre
deja rellenado el ControlRadius de la ubicación usada.

Todo se hace en una única transacción: si algo falla no queda nada a medias
(--dry-run también deshace el ALTER TABLE, SQL Server lo trata como transaccional).

Uso (dentro del contenedor, WORKDIR /code/app):

    # Ver empresas, ubicaciones y departamentos existentes
    python db/add_department.py --list

    # Simular (no guarda nada)
    python db/add_department.py --name "Isabel Dona" "Isabel Homa" "Nanos" \\
        --location Barcelona --company "Tina Navarro" --tax-id <NIF> --dry-run

    # Crear: el mismo comando sin --dry-run
"""

import argparse
import datetime
import logging
import os
import sys

# Permite ejecutarlo como `python db/add_department.py` desde /code/app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(1, '/code/app')

from sqlalchemy import inspect, text
from sqlmodel import Session, select

from db.session import engine
from SQLModels import Companies, Departments, DepartmentsRelations, Locations, Users, UserDepartments

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger("add_department")

# Columnas explícitas para leer aunque falte ControlRadius en la BD
LOCATION_COLUMNS = select(Locations.LocationID, Locations.LocationName, Locations.City, Locations.Active)
DEPARTMENT_COLUMNS = select(Departments.DeptID, Departments.DeptName, Departments.CompanyID,
                            Departments.LocationID, Departments.Active)

# Centro de Barcelona, por si hay que crear la ubicación
DEFAULT_LOCATION = {"Address": "Barcelona", "ZipCode": "08001", "City": "Barcelona",
                    "State": "Cataluña", "Country": "ES", "Lat": 41.3874, "Long": 2.1686}


def is_current(ud: UserDepartments, today: datetime.date) -> bool:
    return ud.AssignedDate <= today and (ud.DeAssignedDate is None or today < ud.DeAssignedDate)


def list_data(db: Session) -> None:
    has_radius = any(c["name"] == "ControlRadius" for c in inspect(engine).get_columns("Locations"))
    print("\nEmpresas:")
    for c in db.exec(select(Companies)).all():
        print(f"  [{c.CompanyID}] {c.SocialName} ({c.TaxID}){'' if c.Active else '  [INACTIVA]'}")
    print(f"\nUbicaciones (columna ControlRadius {'presente' if has_radius else 'AUSENTE'}):")
    for loc in db.exec(LOCATION_COLUMNS).all():
        print(f"  [{loc.LocationID}] {loc.LocationName} - {loc.City}{'' if loc.Active else '  [INACTIVA]'}")
    print("\nDepartamentos:")
    parents = {r.DeptID: r.ParentDeptID for r in db.exec(select(DepartmentsRelations)).all()}
    for d in db.exec(DEPARTMENT_COLUMNS).all():
        parent = f" (padre: {parents[d.DeptID]})" if d.DeptID in parents else ""
        print(f"  [{d.DeptID}] {d.DeptName} empresa={d.CompanyID} ubicación={d.LocationID}{parent}"
              f"{'' if d.Active else '  [INACTIVO]'}")
    print()


def ensure_control_radius_column(db: Session, default_radius: float) -> None:
    exists = db.exec(text(
        "SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('Locations') AND name = 'ControlRadius'"
    )).first()
    if exists:
        return
    db.exec(text(f"ALTER TABLE [Locations] ADD [ControlRadius] FLOAT NOT NULL "
                 f"CONSTRAINT [DF_Locations_ControlRadius] DEFAULT ({float(default_radius)})"))
    log.info(f"Columna Locations.ControlRadius añadida (default {default_radius})")


def get_or_create_company(db: Session, args: argparse.Namespace) -> Companies:
    company = db.exec(select(Companies).where(Companies.SocialName == args.company)).first()
    if company:
        if not company.Active:
            raise ValueError(f"La empresa '{args.company}' existe pero está inactiva (CompanyID={company.CompanyID})")
        log.info(f"Empresa existente: {company.SocialName} (CompanyID={company.CompanyID})")
        return company
    if not args.tax_id:
        raise ValueError(f"La empresa '{args.company}' no existe; indica --tax-id para crearla")
    if db.exec(select(Companies).where(Companies.TaxID == args.tax_id)).first():
        raise ValueError(f"Ya existe otra empresa con TaxID {args.tax_id}")
    company = Companies(TaxID=args.tax_id, SocialName=args.company, FiscalName=args.company,
                        Address=DEFAULT_LOCATION["Address"], ZipCode=DEFAULT_LOCATION["ZipCode"],
                        City=DEFAULT_LOCATION["City"], State=DEFAULT_LOCATION["State"],
                        Country=DEFAULT_LOCATION["Country"])
    db.add(company)
    db.flush()
    log.info(f"Empresa creada: {company.SocialName} (CompanyID={company.CompanyID}, TaxID={company.TaxID})")
    return company


def get_or_create_location(db: Session, args: argparse.Namespace) -> Locations:
    location = db.exec(select(Locations).where(Locations.LocationName == args.location)).first()
    if location:
        if not location.Active:
            raise ValueError(f"La ubicación '{args.location}' existe pero está inactiva")
        location.ControlRadius = args.control_radius
        db.add(location)
        db.flush()
        log.info(f"Ubicación existente: {location.LocationName} (LocationID={location.LocationID}), "
                 f"ControlRadius={location.ControlRadius}")
        return location
    location = Locations(LocationName=args.location, ControlRadius=args.control_radius, **DEFAULT_LOCATION)
    db.add(location)
    db.flush()
    log.info(f"Ubicación creada: {location.LocationName} (LocationID={location.LocationID}) "
             f"lat={location.Lat} long={location.Long} ControlRadius={location.ControlRadius}")
    return location


def add_departments(db: Session, args: argparse.Namespace) -> None:
    today = datetime.date.today()

    if len(set(args.name)) != len(args.name):
        raise ValueError("Hay nombres repetidos en --name")
    # DeptName es UNIQUE en BD para activos e inactivos
    for name in args.name:
        existing = db.exec(DEPARTMENT_COLUMNS.where(Departments.DeptName == name)).first()
        if existing:
            raise ValueError(f"Ya existe el departamento '{name}' (DeptID={existing.DeptID}, "
                             f"{'activo' if existing.Active else 'inactivo'})")

    user = db.exec(select(Users).where(Users.Email == args.user_email)).first()
    if not user:
        raise ValueError(f"Usuario {args.user_email} no encontrado")

    if args.parent_id is not None:
        parent = db.exec(DEPARTMENT_COLUMNS.where(Departments.DeptID == args.parent_id)).first()
        if not parent or not parent.Active:
            raise ValueError(f"Departamento padre {args.parent_id} no encontrado o inactivo")

    ensure_control_radius_column(db, args.control_radius)
    company = get_or_create_company(db, args)
    location = get_or_create_location(db, args)

    user_depts = db.exec(select(UserDepartments).where(UserDepartments.UserID == user.UserID)).all()
    current_primary = next((ud for ud in user_depts if ud.IsPrimary and is_current(ud, today)), None)
    if args.primary == "yes" and current_primary:
        raise ValueError(f"El usuario ya tiene departamento primario vigente (DeptID={current_primary.DeptID}); "
                         f"usa --primary no o --primary auto")
    # Solo el primer departamento creado puede quedar como primario
    primary_pending = args.primary == "yes" or (args.primary == "auto" and current_primary is None)

    for name in args.name:
        dept = Departments(DeptName=name, LocationID=location.LocationID, CompanyID=company.CompanyID,
                           ForceLocation=args.force_location)
        db.add(dept)
        db.flush()  # obtiene DeptID sin commit

        if args.parent_id is not None:
            db.add(DepartmentsRelations(DeptID=dept.DeptID, ParentDeptID=args.parent_id))

        db.add(UserDepartments(UserID=user.UserID, DeptID=dept.DeptID, IsPrimary=primary_pending,
                               AssignedDate=today, DeAssignedDate=today.replace(year=today.year + 20)))
        db.flush()

        log.info(f"Departamento '{name}' DeptID={dept.DeptID} empresa={company.SocialName} "
                 f"ubicación={location.LocationName} padre={args.parent_id} ForceLocation={args.force_location}")
        log.info(f"  asignado a {user.Email} (UserID={user.UserID}) IsPrimary={primary_pending}")
        primary_pending = False

    if args.dry_run:
        db.rollback()
        log.info("DRY RUN: cambios descartados")
    else:
        db.commit()
        log.info("Cambios guardados")


def main() -> int:
    parser = argparse.ArgumentParser(description="Crea uno o varios departamentos y los asigna a un usuario")
    parser.add_argument("--list", action="store_true", help="Lista empresas, ubicaciones y departamentos")
    parser.add_argument("--name", nargs="+", help="Nombre(s) del departamento (máx. 50 c/u)")
    parser.add_argument("--location", help="LocationName; se crea en Barcelona si no existe")
    parser.add_argument("--control-radius", type=float, default=100.0,
                        help="Radio de fichaje en metros de la ubicación (por defecto 100)")
    parser.add_argument("--company", help="SocialName de la empresa; se crea si no existe")
    parser.add_argument("--tax-id", help="NIF/CIF (máx. 9), obligatorio solo si hay que crear la empresa")
    parser.add_argument("--parent-id", type=int, help="DeptID del departamento padre (opcional)")
    parser.add_argument("--user-email", default="info@phoedata.com", help="Usuario a asignar")
    parser.add_argument("--primary", choices=["auto", "yes", "no"], default="auto",
                        help="auto: primario solo si el usuario no tiene uno vigente")
    parser.add_argument("--force-location", action="store_true", help="Exigir fichaje en la ubicación")
    parser.add_argument("--dry-run", action="store_true", help="Simula sin guardar")
    args = parser.parse_args()

    with Session(engine) as db:
        if args.list:
            list_data(db)
            return 0
        if not args.name or not args.location or not args.company:
            parser.error("--name, --location y --company son obligatorios (o usa --list)")
        if any(len(n) > 50 for n in args.name + [args.location, args.company]):
            parser.error("nombres de máximo 50 caracteres")
        if args.tax_id and len(args.tax_id) > 9:
            parser.error("--tax-id admite como máximo 9 caracteres")
        try:
            add_departments(db, args)
        except ValueError as e:
            db.rollback()
            log.error(str(e))
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
