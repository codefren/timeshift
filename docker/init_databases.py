#!/usr/bin/env python3
"""
Inicializa las 3 bases de datos del stack en cluster, cada una desde su backup.

Por cada par (DB_NAME_n, BAK_FILE_n):
  · la base ya existe            -> no se toca (idempotente)
  · hay /backups/<BAK_FILE_n>    -> RESTORE DATABASE desde ese backup
  · no hay backup                -> CREATE DATABASE + esquema desde los modelos
                                    SQLModel + create_first_data()

Corre una sola vez: los 3 backends esperan a que termine
(service_completed_successfully). Si cada backend hiciera su propio init_db(),
los tres crearían las mismas tablas y harían DROP/CREATE del trigger
trg_UpdateUserHoursBalance en paralelo.

Variables de entorno:
  DB_NAME_1..3            nombres de las bases        (def. timeshift_1..3)
  BAK_FILE_1..3           .bak dentro de backups/     (def. timeshift_1..3.bak)
  FORCE_RESTORE           true -> rehace la base aunque ya exista
  MIGRATE_AFTER_RESTORE   true (def.) -> tras restaurar, create_all() para
                          añadir tablas que el backup no trajera
  BACKUP_DIR              def. /backups
"""
import os
import subprocess
import sys
import time

import pyodbc

DRIVER      = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")
HOST        = os.getenv("DB_HOST", "sqlserver")
USER        = os.getenv("DB_USERNAME", "sa")
PWD         = os.getenv("DB_PASSWORD", "")
BACKUP_DIR  = os.getenv("BACKUP_DIR", "/backups")
FORCE       = os.getenv("FORCE_RESTORE", "false").strip().lower() in ("1", "true", "yes")
MIGRATE     = os.getenv("MIGRATE_AFTER_RESTORE", "true").strip().lower() in ("1", "true", "yes")

DATA_DIR    = "/var/opt/mssql/data"   # ruta dentro del contenedor de SQL Server


def log(msg):
    print(f"[init] {msg}", flush=True)


def connect_master(timeout=5):
    """Conexión a master en autocommit: RESTORE y CREATE DATABASE no admiten
    transacción explícita."""
    return pyodbc.connect(
        f"DRIVER={{{DRIVER}}};SERVER={HOST};DATABASE=master;UID={USER};PWD={PWD};"
        f"TrustServerCertificate=yes;Connection Timeout={timeout};",
        timeout=timeout,
        autocommit=True,
    )


def wait_for_sqlserver(attempts=40, delay=3):
    log(f"Esperando a que SQL Server ({HOST}) esté listo...")
    for i in range(1, attempts + 1):
        try:
            with connect_master() as conn:
                conn.cursor().execute("SELECT 1").fetchone()
            log(f"SQL Server listo (intento {i}).")
            return
        except pyodbc.Error as exc:
            if i == attempts:
                log(f"ERROR: SQL Server no respondió tras {attempts} intentos: {exc}")
                sys.exit(1)
            time.sleep(delay)


def db_exists(cur, name):
    return cur.execute("SELECT DB_ID(?)", name).fetchone()[0] is not None


def read_backup_filelist(cur, bak_path):
    """Devuelve [(logical_name, type), ...] leídos del propio .bak. Los nombres
    lógicos dependen de la base de la que se sacó el backup, así que no se
    pueden asumir."""
    rows = cur.execute(f"RESTORE FILELISTONLY FROM DISK = N'{bak_path}'").fetchall()
    cols = [c[0] for c in cur.description]
    i_name, i_type = cols.index("LogicalName"), cols.index("Type")
    return [(r[i_name], str(r[i_type]).upper()) for r in rows]


def build_move_clauses(filelist, db):
    """Un MOVE por fichero del backup, con destino único por base para que las
    3 restauraciones no se pisen los .mdf/.ldf."""
    moves, n_data, n_log = [], 0, 0
    for logical, ftype in filelist:
        if ftype == "D":
            n_data += 1
            suffix = "" if n_data == 1 else f"_{n_data}"
            target = f"{DATA_DIR}/{db}{suffix}.mdf"
        elif ftype == "L":
            n_log += 1
            suffix = "" if n_log == 1 else f"_{n_log}"
            target = f"{DATA_DIR}/{db}{suffix}_log.ldf"
        else:
            # 'F' (FILESTREAM) y demás: se restauran a un directorio propio
            n_data += 1
            target = f"{DATA_DIR}/{db}_{n_data}"
        safe_logical = logical.replace("'", "''")
        moves.append(f"MOVE N'{safe_logical}' TO N'{target}'")
    return moves


def restore_db(cur, db, bak_name):
    bak_path = f"{BACKUP_DIR}/{bak_name}"
    log(f"{db} <- restaurando desde {bak_path}")

    filelist = read_backup_filelist(cur, bak_path)
    moves = build_move_clauses(filelist, db)
    if not moves:
        raise RuntimeError(f"el backup {bak_name} no declara ficheros lógicos")

    log(f"{db} <- ficheros en el backup: " +
        ", ".join(f"{n} ({t})" for n, t in filelist))

    if db_exists(cur, db):
        cur.execute(f"ALTER DATABASE [{db}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE")

    cur.execute(
        f"RESTORE DATABASE [{db}] FROM DISK = N'{bak_path}' WITH "
        + ", ".join(moves)
        + ", REPLACE, RECOVERY, STATS = 20"
    )
    while cur.nextset():          # consume los mensajes de progreso del RESTORE
        pass

    cur.execute(f"ALTER DATABASE [{db}] SET MULTI_USER")
    log(f"{db} <- restaurada.")

    if MIGRATE:
        # create_all() solo AÑADE lo que falte; no altera ni borra lo que ya
        # venga en el backup. Cubre backups anteriores a tablas nuevas
        # (Holidays, AbsenceBalance...).
        log(f"{db} <- alineando esquema con los modelos actuales")
        run_in_db(db, "init_only")


def create_db_from_models(cur, db, reason):
    log(f"{db} <- sin backup ({reason}): esquema desde los modelos")
    if not db_exists(cur, db):
        cur.execute(f"CREATE DATABASE [{db}]")
    run_in_db(db, "init_and_seed")
    log(f"{db} <- creada con esquema y datos iniciales.")


def run_in_db(db, mode):
    """db/session.py construye el engine al importarse, leyendo DB_NAME del
    entorno. Para tocar 3 bases hace falta un proceso por base."""
    snippets = {
        "init_only": (
            "from db.session import init_db, engine\n"
            "init_db()\n"
            "engine.dispose()\n"
        ),
        "init_and_seed": (
            "from db.session import init_db, engine\n"
            "from db.create_first_data import create_first_data\n"
            "init_db()\n"
            "create_first_data(engine)\n"
            "engine.dispose()\n"
        ),
    }
    env = {**os.environ, "DB_NAME": db}
    result = subprocess.run(
        [sys.executable, "-c", snippets[mode]],
        cwd="/code/app",
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"el init de {db} falló (código {result.returncode})")


def main():
    wait_for_sqlserver()

    targets = []
    for n in (1, 2, 3):
        targets.append((
            os.getenv(f"DB_NAME_{n}", f"timeshift_{n}"),
            os.getenv(f"BAK_FILE_{n}", f"timeshift_{n}.bak"),
        ))

    failures = []
    with connect_master(timeout=30) as conn:
        cur = conn.cursor()
        for n, (db, bak) in enumerate(targets, start=1):
            print("", flush=True)
            print("─" * 63, flush=True)
            log(f"Base {n}/3: {db}   (backup esperado: {bak})")

            try:
                if db_exists(cur, db) and not FORCE:
                    log(f"{db} ya existe: no se toca "
                        f"(FORCE_RESTORE=true para rehacerla).")
                    continue

                if os.path.isfile(f"{BACKUP_DIR}/{bak}"):
                    restore_db(cur, db, bak)
                else:
                    create_db_from_models(cur, db, f"{BACKUP_DIR}/{bak} no existe")
            except Exception as exc:
                log(f"ERROR con {db}: {exc}")
                failures.append(db)

    print("", flush=True)
    print("─" * 63, flush=True)
    if failures:
        log(f"Terminado CON ERRORES en: {', '.join(failures)}")
        sys.exit(1)
    log("Las 3 bases están listas. Los backends pueden arrancar.")


if __name__ == "__main__":
    main()
