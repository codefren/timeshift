# Migraciones de esquema (base restaurada)

Scripts que **crean tablas / columnas que faltan** en entornos donde la base de
datos se restaura desde un backup y el backend arranca con `SKIP_DB_INIT=true`.
En ese modo `init_db()` / `create_all()` **no se ejecuta**, así que las tablas que
el backup no traía nunca se crean, y `create_all` **tampoco añade columnas** a
tablas ya existentes. Estos scripts cubren esos huecos.

Todos son **idempotentes** (se pueden ejecutar varias veces sin efecto) y están
escritos para **SQL Server (T-SQL)** sobre la base `ShiftZone`.

## Scripts

| Script | Qué hace |
|--------|----------|
| `migrate_absencebalance_table.sql` | Crea la tabla `AbsenceBalance` (saldos de ausencias). |
| `migrate_holidays_table.sql`       | Crea la tabla `Holidays`. |
| `migrate_schedules_updatedat.sql`  | Añade la columna `UpdatedAt` a `Schedules`. |
| `migrate_fix_worklog_balance_trigger.sql` | Reemplaza el trigger `trg_UpdateUserHoursBalance` (la versión del backup referencia columnas inexistentes y aborta el cierre de worklogs). |
| `seed_holidays_permission.sql`     | Crea el permiso `manage:Holidays` + menú y lo concede al rol admin. |
| `grant_holidays_permission_admin.sql` | Asigna `manage:Holidays` al/los rol(es) `admin` (por nombre). |

> Relacionados (en el directorio padre `../`): `migrate_absencetypes_leave.sql`
> y `seed_absence_balances.sql`.

## Cómo ejecutarlos

Selecciona la base `ShiftZone` y ejecuta cada `.sql`. Por ejemplo, contra el
contenedor local:

```bash
MSYS_NO_PATHCONV=1 docker exec -i timeshift-sqlserver \
  /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "TimeShift!2024" -C -d ShiftZone \
  -i /ruta/al/script.sql
```

En SSMS / Azure Data Studio: selecciona `ShiftZone` en el desplegable y ejecuta.
Para producción, antepón `USE [ShiftZone];` + `GO` o asegúrate de tener la base
correcta seleccionada.

## Verificar el esquema completo

Para comprobar si faltan tablas o columnas respecto a los modelos:

```bash
docker exec -i -w /code/app timeshift-backend python - <<'PY'
import SQLModels
from sqlmodel import SQLModel
from db.session import engine
from sqlalchemy import inspect
insp = inspect(engine)
db_tables = set(insp.get_table_names())
problems = 0
for tname, tbl in sorted(SQLModel.metadata.tables.items()):
    if tname not in db_tables:
        print(f'[TABLA FALTA] {tname}'); problems += 1; continue
    missing = {c.name for c in tbl.columns} - {c["name"] for c in insp.get_columns(tname)}
    if missing:
        print(f'[COLUMNAS FALTAN] {tname}: {sorted(missing)}'); problems += 1
print('OK: esquema sincronizado' if problems == 0 else f'{problems} problema(s)')
PY
```
