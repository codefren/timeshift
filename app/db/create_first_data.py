from sqlalchemy import Engine, insert
from passlib.hash import bcrypt
from sqlmodel import select

from SQLModels import Users, Roles
import logging


def create_first_data(engine: Engine):
    log = logging.getLogger("create_first_data")
    with engine.connect() as conn:
        log.debug("Creating first data, database connected")
        if conn.execute(select(Users)).fetchall():
            log.debug("First data already exists")
            return
        conn.execute(insert(Roles), [
            {"RoleName": "admin", "Description": "Administrator"},
        ])
        conn.commit()
        log.debug("Role admin created")
        role_id = conn.execute(select(Roles).where(Roles.RoleName == "admin")).fetchone()
        role_id = role_id.RoleID if role_id else None
        if not role_id:
            log.error("Role admin not created")
            return
        conn.execute(insert(Users), [
            {"Email": "info@phoedata.com", "Password": bcrypt.hash("admin"), "RoleID": role_id, "IsInactive": False,
             "CreatedAt": "2025-01-01 00:00:00", "UpdatedAt": "2025-01-01 00:00:00"},
        ])
        log.debug("User admin created")
        conn.commit()

    log.debug("First data created")
