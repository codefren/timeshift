#!/bin/bash
# =============================================================================
#  Inicialización única del esquema de TimeShiftZone.
#
#  Con 3 backends en paralelo no se puede dejar que cada uno ejecute init_db()
#  y create_first_data(): chocarían creando las mismas tablas y haciendo
#  DROP/CREATE del trigger a la vez. Este contenedor lo hace una sola vez y
#  termina; los backends arrancan después con SKIP_DB_INIT=true.
# =============================================================================
set -e

cd /code/app
mkdir -p logs

echo "[init-db] Esperando a que SQL Server esté listo..."

MAX_RETRIES=30
RETRY=0

until python - <<'EOF'
import pyodbc, os, sys
driver  = os.getenv("DB_DRIVER",   "ODBC Driver 18 for SQL Server")
host    = os.getenv("DB_HOST",     "sqlserver")
user    = os.getenv("DB_USERNAME", "sa")
pwd     = os.getenv("DB_PASSWORD", "")
db_name = os.getenv("DB_NAME",     "timeshift")

try:
    conn = pyodbc.connect(
        f"DRIVER={{{driver}}};SERVER={host};DATABASE=master;UID={user};PWD={pwd};"
        "TrustServerCertificate=yes;Connection Timeout=5;",
        timeout=5, autocommit=True
    )
    cursor = conn.cursor()
    cursor.execute(
        f"IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = N'{db_name}') "
        f"CREATE DATABASE [{db_name}]"
    )
    conn.close()
    print(f"SQL Server listo. Base de datos '{db_name}' disponible.")
    sys.exit(0)
except Exception as e:
    print(f"  ... no disponible aún ({e})")
    sys.exit(1)
EOF
do
    RETRY=$((RETRY + 1))
    if [ "$RETRY" -ge "$MAX_RETRIES" ]; then
        echo "[init-db] SQL Server no respondió tras $MAX_RETRIES intentos. Abortando."
        exit 1
    fi
    sleep 3
done

echo "[init-db] Creando esquema, triggers y datos iniciales..."
python - <<'EOF'
from db.session import init_db, engine
from db.create_first_data import create_first_data

init_db()
create_first_data(engine)
engine.dispose()
print("[init-db] Esquema y datos iniciales listos.")
EOF

echo "[init-db] Completado. Los backends pueden arrancar."
