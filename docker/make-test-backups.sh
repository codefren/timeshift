#!/bin/bash
# =============================================================================
#  Genera 3 backups de PRUEBA en backups/ para el primer deploy del cluster.
#
#  Parte de un .bak existente (por defecto el del repo) y produce
#  timeshift_1.bak, timeshift_2.bak y timeshift_3.bak, cada uno con una tabla
#  _DeployMarker distinta. Ese marcador es lo que permite comprobar que el
#  backup 2 acabó en la base 2 y no en otra: con 3 copias idénticas no habría
#  forma de saber si el enrutado es correcto.
#
#  NO es un backup de producción: es andamiaje para validar el despliegue.
#
#  Sobre la escritura del fichero: BACKUP DATABASE lo ejecuta el proceso de SQL
#  Server, que corre como uid 10001 (mssql) y NO puede escribir en el bind mount
#  backups/ (del usuario del host). Así que el servidor vuelca dentro de su
#  propio volumen —del que sí es dueño— y este contenedor, que corre como root,
#  copia el fichero a backups/. Evita tener que hacer chmod 777 al directorio.
#
#  Uso:
#    docker compose -f docker-compose.cluster.yml --env-file .env.cluster \
#      --profile testdata run --rm make-test-backups
#
#  Variables:
#    SOURCE_BAK   .bak de partida dentro de /sql   (def. timeshift_20250610.bak)
#    DB_NAME_1..3 nombres de las bases destino (solo para nombrar los ficheros)
# =============================================================================
set -euo pipefail

SQLCMD="/opt/mssql-tools18/bin/sqlcmd -S sqlserver -U sa -P ${MSSQL_SA_PASSWORD} -No -b"
SOURCE_BAK="${SOURCE_BAK:-timeshift_20250610.bak}"
SOURCE_PATH="/sql/${SOURCE_BAK}"
DATA_DIR="/var/opt/mssql/data"

echo "[mkbak] Backup de partida: ${SOURCE_PATH}"

if ! $SQLCMD -h -1 -W -Q "SET NOCOUNT ON; SELECT 1" > /dev/null 2>&1; then
    echo "[mkbak] ERROR: no se puede conectar a sqlserver."
    exit 1
fi

# Nombres lógicos del backup de partida (varían según de dónde salió)
FILELIST=$($SQLCMD -h -1 -W -s "|" \
    -Q "SET NOCOUNT ON; RESTORE FILELISTONLY FROM DISK = N'${SOURCE_PATH}'")

DATA_LOGICAL=$(echo "$FILELIST" | awk -F'|' '$3=="D" {gsub(/^[ \t]+|[ \t]+$/,"",$1); print $1; exit}')
LOG_LOGICAL=$(echo  "$FILELIST" | awk -F'|' '$3=="L" {gsub(/^[ \t]+|[ \t]+$/,"",$1); print $1; exit}')

if [ -z "$DATA_LOGICAL" ] || [ -z "$LOG_LOGICAL" ]; then
    echo "[mkbak] ERROR: no se pudieron leer los ficheros lógicos de ${SOURCE_BAK}"
    echo "$FILELIST"
    exit 1
fi
echo "[mkbak] Ficheros lógicos: ${DATA_LOGICAL} (D), ${LOG_LOGICAL} (L)"

for n in 1 2 3; do
    db_var="DB_NAME_$n"
    target_db="${!db_var:-timeshift_$n}"
    tmp_db="tsz_mkbak_$n"
    out="/backups/${target_db}.bak"
    # Ruta escribible por el propio SQL Server (dentro de su volumen de datos)
    staged="${DATA_DIR}/_mkbak_${target_db}.bak"

    echo ""
    echo "[mkbak] ── Generando ${out} (tenant-${n}) ──"

    # 1. Restaurar el backup de partida en una base temporal
    $SQLCMD -Q "
IF DB_ID(N'${tmp_db}') IS NOT NULL
    ALTER DATABASE [${tmp_db}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;

RESTORE DATABASE [${tmp_db}]
FROM DISK = N'${SOURCE_PATH}'
WITH  MOVE N'${DATA_LOGICAL}' TO N'${DATA_DIR}/${tmp_db}.mdf',
      MOVE N'${LOG_LOGICAL}'  TO N'${DATA_DIR}/${tmp_db}_log.ldf',
      REPLACE, RECOVERY, STATS = 50;

ALTER DATABASE [${tmp_db}] SET MULTI_USER;
" | grep -Ev "^$|upgrade step|^Processed|RESTORE DATABASE successfully" || true

    # 2. Marcar de qué tenant es este backup
    $SQLCMD -d "${tmp_db}" -Q "
IF OBJECT_ID(N'dbo._DeployMarker', N'U') IS NOT NULL DROP TABLE dbo._DeployMarker;
CREATE TABLE dbo._DeployMarker (
    Tenant     NVARCHAR(50) NOT NULL,
    SourceBak  NVARCHAR(260) NOT NULL,
    CreatedAt  DATETIME NOT NULL DEFAULT GETDATE()
);
INSERT INTO dbo._DeployMarker (Tenant, SourceBak)
VALUES (N'tenant-${n}', N'${SOURCE_BAK}');
" > /dev/null

    # 3. Volcar dentro del volumen del servidor (única ruta que puede escribir)
    $SQLCMD -Q "
BACKUP DATABASE [${tmp_db}] TO DISK = N'${staged}'
WITH FORMAT, INIT, NAME = N'TimeShiftZone test backup tenant-${n}', STATS = 50;
"

    # 4. Sacarlo al bind mount (este contenedor corre como root) y limpiar.
    #    El cp deja root:root 0640; hay que dejarlo legible por SQL Server
    #    (uid 10001) para el RESTORE, y del usuario del host para poder borrarlo.
    cp "/mssql/data/_mkbak_${target_db}.bak" "$out"
    rm -f "/mssql/data/_mkbak_${target_db}.bak"
    chmod 0644 "$out"
    chown "$(stat -c '%u:%g' /backups)" "$out"

    $SQLCMD -Q "
ALTER DATABASE [${tmp_db}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
DROP DATABASE [${tmp_db}];
" > /dev/null

    echo "[mkbak] ✓ ${out} listo (marcador: tenant-${n})"
done

echo ""
echo "[mkbak] Los 3 backups de prueba están en backups/."
echo "[mkbak] Siguiente paso:"
echo "[mkbak]   docker compose -f docker-compose.cluster.yml --env-file .env.cluster up -d --build"
