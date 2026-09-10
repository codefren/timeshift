#!/bin/bash
# =============================================================================
#  Restaura un backup .bak de SQL Server dentro del contenedor timeshift-sqlserver.
#
#  El .bak debe ser visible POR EL SERVIDOR (no por este contenedor): el servicio
#  sqlserver monta el raíz del proyecto en /backups:ro, así que basta con dejar
#  el fichero en la raíz del repositorio.
#
#  Uso:  docker compose --profile restore run --rm restore
#        BAK_FILE=otro.bak docker compose --profile restore run --rm restore
# =============================================================================
set -euo pipefail

BAK_FILE="${BAK_FILE:-timeshift_20250610.bak}"
DB_NAME="${DB_NAME:-timeshift}"
BAK_PATH="/backups/${BAK_FILE}"
SQLCMD="/opt/mssql-tools18/bin/sqlcmd -S sqlserver -U sa -P ${MSSQL_SA_PASSWORD} -No -b"

echo "[restore] Backup .......: ${BAK_PATH}"
echo "[restore] Base de datos : ${DB_NAME}"

# 1) Leer los nombres lógicos de los ficheros del backup (data + log)
echo "[restore] Leyendo la lista de ficheros del backup..."
FILELIST=$($SQLCMD -h -1 -W -s "|" -Q \
  "SET NOCOUNT ON; RESTORE FILELISTONLY FROM DISK = N'${BAK_PATH}'")

DATA_LOGICAL=$(echo "$FILELIST" | awk -F'|' '$3=="D" {print $1; exit}')
LOG_LOGICAL=$(echo  "$FILELIST" | awk -F'|' '$3=="L" {print $1; exit}')

if [ -z "$DATA_LOGICAL" ] || [ -z "$LOG_LOGICAL" ]; then
    echo "[restore] ERROR: no se pudieron leer los nombres lógicos del backup."
    echo "$FILELIST"
    exit 1
fi

echo "[restore] Fichero de datos : ${DATA_LOGICAL}"
echo "[restore] Fichero de log   : ${LOG_LOGICAL}"

# 2) Restaurar con MOVE a las rutas del contenedor, cerrando conexiones abiertas
echo "[restore] Restaurando (esto puede tardar)..."
$SQLCMD -Q "
IF DB_ID(N'${DB_NAME}') IS NOT NULL
BEGIN
    ALTER DATABASE [${DB_NAME}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
END;

RESTORE DATABASE [${DB_NAME}]
FROM DISK = N'${BAK_PATH}'
WITH  MOVE N'${DATA_LOGICAL}' TO N'/var/opt/mssql/data/${DB_NAME}.mdf',
      MOVE N'${LOG_LOGICAL}'  TO N'/var/opt/mssql/data/${DB_NAME}_log.ldf',
      REPLACE, RECOVERY, STATS = 10;

ALTER DATABASE [${DB_NAME}] SET MULTI_USER;
"

echo "[restore] Restauración completada."
echo "[restore] Recuerda arrancar el backend con SKIP_DB_INIT=true si no quieres"
echo "[restore] que SQLModel recree el esquema sobre los datos restaurados."
