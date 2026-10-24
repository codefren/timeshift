"""
Borra un usuario (p.ej. un registro viudo de una creación fallida) y todas sus
filas dependientes.

Las tablas a limpiar se descubren con las claves foráneas reales de SQL Server
(sys.foreign_keys), recursivamente: lo que apunta a Users, lo que apunta a esas
filas, etc. Además incluye tablas con columna UserID sin FK declarada.

Por defecto solo MUESTRA lo que borraría. Para borrar hay que pasar --execute.
Si el usuario tiene actividad real (fichajes, turnos, ausencias...) se niega
salvo que se pase también --force.

Todo se hace en una única transacción: si algo falla no se borra nada.

Uso (dentro del contenedor, WORKDIR /code/app):

    python db/delete_user.py --email txellfarremirabet@gmail.com            # ver qué borraría
    python db/delete_user.py --email txellfarremirabet@gmail.com --execute  # borrar
"""

import argparse
import logging
import os
import sys

# Permite ejecutarlo como `python db/delete_user.py` desde /code/app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(1, '/code/app')

from sqlalchemy import text

from db.session import engine

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger("delete_user")

# Tablas que indican que el usuario se ha usado de verdad (no es un registro viudo)
ACTIVITY_TABLES = {"WorkLogs", "WorkLogLines", "WorkLogTotals", "Shifts", "Schedules", "AbsenceRequests",
                   "AbsenceReviews", "WorkLogAudit", "WorkLogLineAudit"}
MAX_DEPTH = 6

FK_QUERY = text("""
SELECT fk.object_id                         AS fk_id,
       OBJECT_NAME(fk.parent_object_id)     AS child_table,
       cc.name                              AS child_col,
       OBJECT_NAME(fk.referenced_object_id) AS parent_table,
       pc.name                              AS parent_col
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
JOIN sys.columns cc ON cc.object_id = fkc.parent_object_id     AND cc.column_id = fkc.parent_column_id
JOIN sys.columns pc ON pc.object_id = fkc.referenced_object_id AND pc.column_id = fkc.referenced_column_id
""")

USERID_COLUMNS_QUERY = text("""
SELECT t.name AS table_name, c.name AS col
FROM sys.columns c JOIN sys.tables t ON t.object_id = c.object_id
WHERE c.name IN ('UserID', 'SupervisorID', 'SubordinateID') AND t.name <> 'Users'
""")


def load_fks(conn) -> dict[str, list[tuple[str, str, str]]]:
    """parent_table -> [(child_table, child_col, parent_col)], solo FKs de una columna."""
    rows = conn.execute(FK_QUERY).all()
    cols_per_fk: dict[int, int] = {}
    for r in rows:
        cols_per_fk[r.fk_id] = cols_per_fk.get(r.fk_id, 0) + 1
    fks: dict[str, list[tuple[str, str, str]]] = {}
    for r in rows:
        if cols_per_fk[r.fk_id] > 1:
            raise RuntimeError(f"FK compuesta no soportada: {r.child_table} -> {r.parent_table}")
        fks.setdefault(r.parent_table, []).append((r.child_table, r.child_col, r.parent_col))
    return fks


def plan_deletes(fks, table: str, where: str, depth: int = 0) -> list[tuple[str, str]]:
    """Lista (tabla, WHERE) en orden hijos-primero para borrar las filas de `table` que cumplen `where`."""
    if depth > MAX_DEPTH:
        raise RuntimeError(f"Profundidad de dependencias excesiva en {table}")
    steps = []
    for child, child_col, parent_col in fks.get(table, []):
        if child == table:
            continue
        child_where = f"[{child_col}] IN (SELECT [{parent_col}] FROM [{table}] WHERE {where})"
        steps += plan_deletes(fks, child, child_where, depth + 1)
    steps.append((table, where))
    return steps


def main() -> int:
    parser = argparse.ArgumentParser(description="Borra un usuario y todas sus filas dependientes")
    parser.add_argument("--email", required=True, help="Email del usuario (Users.Email)")
    parser.add_argument("--execute", action="store_true", help="Borra de verdad (si no, solo muestra)")
    parser.add_argument("--force", action="store_true", help="Borra aunque el usuario tenga actividad real")
    args = parser.parse_args()

    with engine.connect() as conn:
        trans = conn.begin()
        try:
            users = conn.execute(text("SELECT UserID, Email, IsInactive, CreatedAt FROM Users WHERE Email = :e"),
                                 {"e": args.email}).all()
            if not users:
                detail = conn.execute(text("SELECT UserID FROM UserDetail WHERE PersonalEmail = :e"),
                                      {"e": args.email}).all()
                log.error(f"No hay ningún usuario con Email {args.email}"
                          + (f" (pero UserDetail.PersonalEmail coincide con UserID {[d.UserID for d in detail]})"
                             if detail else ""))
                return 1
            user = users[0]
            if user.UserID == 1:
                log.error("UserID 1 es el admin inicial; no se borra")
                return 1
            log.info(f"Usuario: UserID={user.UserID} Email={user.Email} IsInactive={user.IsInactive} "
                     f"CreatedAt={user.CreatedAt}")

            fks = load_fks(conn)
            user_where = f"[UserID] = {int(user.UserID)}"
            steps = plan_deletes(fks, "Users", user_where)

            # Tablas con columna de usuario pero sin FK declarada
            covered = {(t, w) for t, w in steps}
            fk_children = {(c, col) for children in fks.values() for c, col, _ in children}
            for r in conn.execute(USERID_COLUMNS_QUERY).all():
                if (r.table_name, r.col) not in fk_children:
                    extra = (r.table_name, f"[{r.col}] = {int(user.UserID)}")
                    if extra not in covered:
                        steps.insert(len(steps) - 1, extra)  # antes de borrar Users

            # Contar filas afectadas por tabla (antes de borrar nada)
            counts: dict[str, int] = {}
            for table, where in steps:
                n = conn.execute(text(f"SELECT COUNT(*) FROM [{table}] WHERE {where}")).scalar_one()
                counts[table] = counts.get(table, 0) + n

            log.info("Filas que se borrarían:")
            for table, n in counts.items():
                if n:
                    log.info(f"  {table:<25} {n}")

            activity = {t: n for t, n in counts.items() if t in ACTIVITY_TABLES and n}
            if activity and not args.force:
                log.error(f"El usuario tiene actividad real {activity}; no parece un registro viudo. "
                          f"Usa --force si aun así quieres borrarlo.")
                trans.rollback()
                return 1

            if not args.execute:
                trans.rollback()
                log.info("Simulación: no se ha borrado nada. Repite con --execute para borrar.")
                return 0

            for table, where in steps:
                conn.execute(text(f"DELETE FROM [{table}] WHERE {where}"))
            remaining = conn.execute(text("SELECT COUNT(*) FROM Users WHERE Email = :e"),
                                     {"e": args.email}).scalar_one()
            if remaining:
                raise RuntimeError("El usuario sigue existiendo tras el borrado")
            trans.commit()
            log.info(f"Usuario {args.email} y sus filas dependientes borrados")
            return 0
        except Exception as e:
            trans.rollback()
            log.error(f"Error, no se ha borrado nada: {e}")
            return 1


if __name__ == "__main__":
    sys.exit(main())
