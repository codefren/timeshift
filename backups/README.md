# Backups de arranque del stack en cluster

Cada base de datos del stack `docker-compose.cluster.yml` se inicializa desde el
`.bak` que le corresponde. Los nombres se configuran en `.env.cluster`:

| Base de datos | Variable del fichero | Valor por defecto |
|---|---|---|
| `DB_NAME_1` | `BAK_FILE_1` | `timeshift_1.bak` |
| `DB_NAME_2` | `BAK_FILE_2` | `timeshift_2.bak` |
| `DB_NAME_3` | `BAK_FILE_3` | `timeshift_3.bak` |

Deja los ficheros en **este directorio** (se monta como `/backups:ro` dentro de
los contenedores) y levanta el stack.

## Si un .bak no está

`docker/init-databases.sh` no falla: crea la base vacía y genera el esquema con
`SQLModel.metadata.create_all()` + `create_first_data()`, igual que hacía el
stack de un solo backend. Así el cluster arranca antes de tener los backups.

En los logs se distingue el camino que tomó cada base:

```
[init] timeshift_1 <- restaurando desde /backups/timeshift_1.bak
[init] timeshift_2 <- sin backup (/backups/timeshift_2.bak no existe): esquema desde los modelos
```

## Volver a restaurar

Las bases ya existentes no se tocan (idempotente). Para forzar una restauración
sobre una base que ya tiene datos:

```bash
FORCE_RESTORE=true docker compose -f docker-compose.cluster.yml \
  --env-file .env.cluster up -d --force-recreate db-init
```

## Formato

Backups nativos de SQL Server (`BACKUP DATABASE ... TO DISK`). El script lee los
nombres lógicos con `RESTORE FILELISTONLY`, así que no importa de qué servidor
ni con qué nombre de base se generaron.
