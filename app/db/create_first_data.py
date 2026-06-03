from sqlalchemy import Engine, insert, text
from passlib.hash import bcrypt
from sqlmodel import select, Session

from SQLModels import Users, Roles
from SQLModels.Roles import Permissions, RolePermissions, RoleUsers, PermissionMenus
from SQLModels.Users import UserDetail
import logging

# Permisos del rol admin (acceso completo)
ADMIN_PERMISSIONS = [
    # Usuarios
    ("manage:Users",           "Gestionar empleados",                     False, None),
    ("view:All",               "Ver todos los usuarios",                  False, None),
    ("view:OwnDepartment",     "Ver su propio departamento",              False, None),
    ("view:SubDepartment",     "Ver subdepartamentos recursivamente",      False, None),
    ("view:FirstSubDepartment","Ver primer nivel de subdepartamentos",     False, None),
    ("update:OwnDepartment",   "Gestionar su departamento",               False, None),
    ("update:FirstSubDepartment","Gestionar primer nivel subdepartamentos",False, None),
    ("update:SubDepartments",  "Gestionar todos los subdepartamentos",     False, None),
    # Turnos
    ("create:Shifts",          "Crear turnos para cualquier usuario",      False, None),
    ("create:OwnShifts",       "Crear turnos para sí mismo",              False, None),
    ("read:Shifts",            "Ver turnos",                              False, None),
    ("update:Shifts",          "Actualizar turnos",                       False, None),
    ("delete:Shifts",          "Eliminar turnos",                         False, None),
    # Horarios
    ("manage:Schedules",       "Gestionar horarios",                      True,  "gestion_horarios"),
    ("view:Schedules",         "Ver horarios",                            False, None),
    # Worklogs
    ("manage:Shifts",          "Gestionar registros de trabajo",           True,  "gestion_empleados"),
    ("delete:Worklogs",        "Eliminar registros de trabajo",            False, None),
    # Ausencias
    ("manage:Absences",        "Aprobar/rechazar ausencias y saldos",      True,  "manage_absences"),
    ("view:Absences",          "Ver solicitudes de ausencias",             False, None),
    # Festivos
    ("manage:Holidays",        "Gestionar festivos",                       True,  "manage_holidays"),
    # Documentación
    ("view:docs",              "Ver documentación Swagger",                False, None),
]

# Permisos del rol employee — subconjunto de lectura/uso propio, sin gestión de solicitudes
EMPLOYEE_PERMISSIONS = [
    "view:OwnDepartment",   # Ver compañeros de su departamento
    "create:OwnShifts",     # Registrar sus propios turnos
    "read:Shifts",          # Ver turnos publicados
    "view:Schedules",       # Ver horarios (sin crear ni editar)
    "view:Absences",        # Ver solicitudes de ausencias (sin aprobar/rechazar)
]


def create_first_data(engine: Engine):
    log = logging.getLogger("create_first_data")
    with engine.connect() as conn:
        log.debug("Creating first data, database connected")
        if conn.execute(select(Users)).fetchall():
            log.debug("First data already exists")
            return

        # ── 1. Crear roles ─────────────────────────────────────────────────
        conn.execute(insert(Roles), [
            {"RoleName": "admin",    "Description": "Administrador con acceso completo"},
            {"RoleName": "employee", "Description": "Empleado regular sin gestión de solicitudes"},
        ])
        conn.commit()
        log.debug("Roles admin y employee creados")

        admin_row    = conn.execute(select(Roles).where(Roles.RoleName == "admin")).fetchone()
        employee_row = conn.execute(select(Roles).where(Roles.RoleName == "employee")).fetchone()
        admin_role_id    = admin_row.RoleID if admin_row else None
        employee_role_id = employee_row.RoleID if employee_row else None
        if not admin_role_id:
            log.error("Role admin not created")
            return

        # ── 2. Crear permisos ──────────────────────────────────────────────
        for perm_name, perm_desc, for_frontend, menu in ADMIN_PERMISSIONS:
            conn.execute(
                insert(Permissions),
                [{"PermissionName": perm_name, "Description": perm_desc, "ForFrontend": for_frontend}]
            )
        conn.commit()
        log.debug(f"{len(ADMIN_PERMISSIONS)} permisos creados")

        # ── 3. Vincular permisos al rol admin ──────────────────────────────
        perm_rows = conn.execute(select(Permissions)).fetchall()
        perm_map = {row.PermissionName: row.PermissionID for row in perm_rows}

        for perm_name, _, for_frontend, menu in ADMIN_PERMISSIONS:
            perm_id = perm_map.get(perm_name)
            if not perm_id:
                continue
            conn.execute(insert(RolePermissions), [{"RoleID": admin_role_id, "PermissionID": perm_id}])
            if menu:
                conn.execute(insert(PermissionMenus), [{"PermissionID": perm_id, "Menu": menu}])
        conn.commit()
        log.debug("Permisos asignados al rol admin")

        # ── 4. Vincular permisos al rol employee ───────────────────────────
        if employee_role_id:
            for perm_name in EMPLOYEE_PERMISSIONS:
                perm_id = perm_map.get(perm_name)
                if perm_id:
                    conn.execute(insert(RolePermissions), [{"RoleID": employee_role_id, "PermissionID": perm_id}])
            conn.commit()
            log.debug(f"{len(EMPLOYEE_PERMISSIONS)} permisos asignados al rol employee")

        # ── 4. Crear usuario admin ─────────────────────────────────────────
        conn.execute(insert(Users), [{
            "Email": "info@phoedata.com",
            "Password": bcrypt.hash("admin"),
            "IsInactive": False,
            "CreatedAt": "2025-01-01 00:00:00",
            "UpdatedAt": "2025-01-01 00:00:00",
        }])
        conn.commit()
        log.debug("User admin created")

        user_row = conn.execute(select(Users).where(Users.Email == "info@phoedata.com")).fetchone()
        user_id = user_row.UserID if user_row else None
        if not user_id:
            log.error("User admin not found after creation")
            return

        # ── 5. Vincular usuario al rol admin ───────────────────────────────
        conn.execute(insert(RoleUsers), [{"RoleID": admin_role_id, "UserID": user_id}])
        conn.commit()
        log.debug("User admin linked to admin role")

        # ── 6. Crear UserDetail para el admin ──────────────────────────────
        conn.execute(insert(UserDetail), [{
            "UserID": user_id,
            "FirstName": "Admin",
            "LastName1": "TimeShift",
            "LastName2": "",
            "Gender": "M",
            "PhoneNumber": "000000000",
            "PersonalEmail": "info@phoedata.com",
            "IdentityNumber": "00000000A",
            "Nationality": "ES",
            "SSNumber": "000000000000",
            "DateOfBirth": "1990-01-01",
            "HireDate": "2025-01-01",
            "JobTitle": "Administrator",
            "ContractType": "Indefinido",
            "ContractWeeklyHours": 40.0,
        }])
        conn.commit()
        log.debug("UserDetail created for admin")

    log.debug("First data created")
