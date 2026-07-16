# Seeds de desarrollo (`db/dev`)

Scripts SQL que **insertan datos de ejemplo** para probar la interfaz en local.
**No son migraciones ni deben ejecutarse en producción** — solo pueblan datos
de demo. Las migraciones de esquema reales están en `../migrations/`.

Motor: SQL Server (T-SQL). Base de datos: `ShiftZone`.

## Scripts

| Script | Qué hace |
|--------|----------|
| `seed_calendar_demo.sql`    | Inserta turnos (incluidos **turnos partidos**) y worklogs para la semana 2026-07-13 .. 2026-07-19 en los usuarios 23, 24, 25, 26, para ver el calendario con datos. Idempotente. |
| `cleanup_calendar_demo.sql` | Elimina lo insertado por el seed anterior. |

## Cómo ejecutar

```bash
docker cp seed_calendar_demo.sql timeshift-sqlserver:/tmp/seed.sql
docker exec timeshift-sqlserver /opt/mssql-tools18/bin/sqlcmd \
  -S localhost -U sa -P "TimeShift!2024" -C -d ShiftZone -i /tmp/seed.sql
```

## Notas

- `WorkLogLines.WorkLogLineID` no es `IDENTITY`; el seed calcula los IDs en
  tiempo de ejecución (`MAX(WorkLogLineID) + n`).
- El seed desactiva temporalmente el trigger `trg_UpdateUserHoursBalance`
  alrededor del `INSERT` en `WorkLogTotals`: en la base restaurada ese trigger
  referencia una columna inexistente (`TotalPauseHours`) y aborta el insert.
  Es un **bug del backup** (afecta también al cierre real de worklogs), aquí
  solo se sortea para poder sembrar datos de demo.
