#!/bin/bash
set -e

echo "[entrypoint] Esperando a que SQL Server esté listo..."

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
    # Conectar a master para verificar disponibilidad
    conn = pyodbc.connect(
        f"DRIVER={{{driver}}};SERVER={host};DATABASE=master;UID={user};PWD={pwd};"
        "TrustServerCertificate=yes;Connection Timeout=5;",
        timeout=5, autocommit=True
    )
    # Crear la base de datos si no existe
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
        echo "[entrypoint] SQL Server no respondió después de $MAX_RETRIES intentos. Abortando."
        exit 1
    fi
    sleep 3
done

mkdir -p logs
echo "[entrypoint] Iniciando FastAPI..."
exec uvicorn main:app --host 0.0.0.0 --port 8000 --reload
