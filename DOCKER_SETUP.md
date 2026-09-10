# Docker Setup — TimeShift Backend

## Resumen

Contenedor de desarrollo que levanta **SQL Server 2022** y el **backend FastAPI** con un solo comando. La base de datos se crea automáticamente en el primer arranque y se puebla con datos iniciales (roles, permisos y usuario admin).

---

## Estructura de archivos

```
TimeShiftApp-master/
├── Dockerfile                  # Imagen Python 3.12 + ODBC Driver 18
├── docker-compose.yml          # SQL Server + Backend + perfiles opcionales
├── docker-entrypoint.sh        # Espera BD, crea DB, lanza uvicorn
├── .dockerignore               # Excluye venv, .env, .bak y docs de la imagen
├── .env.docker.example         # Plantilla versionada del entorno
├── .env.dev                    # Entorno real (ignorado por git)
├── docker/
│   └── restore-backup.sh       # Restaura un .bak dentro de SQL Server
└── app/
    ├── logs/                   # Directorio de logs (necesario en runtime)
    ├── static/images/          # Fotos de perfil (volumen profile-pictures)
    └── ...
```

### Servicios

| Servicio | Perfil | Qué hace |
|---|---|---|
| `sqlserver` | *(por defecto)* | SQL Server 2022 Developer, datos en el volumen `sqlserver-data` |
| `backend` | *(por defecto)* | FastAPI + uvicorn, sirve la API y el frontend estático de `app/static` |
| `seeder` | `seed` | Aplica `create_absences_tables.sql`, `seed_absences_permissions.sql` y `seed_users.sql` |
| `restore` | `restore` | Restaura un backup `.bak` sobre la base `timeshift` |
| `sqlcmd` | `tools` | Shell `sqlcmd` interactiva contra la base |

Los servicios con perfil **no arrancan** con `docker compose up`; se lanzan a mano.

---

## Requisitos

- Docker >= 24
- Docker Compose >= 2.20

---

## Inicio rápido

```bash
# 1. Situarse en el directorio raíz del backend
cd TimeShiftApp-master

# 2. Crear el fichero de entorno (solo la primera vez)
cp .env.docker.example .env.dev

# 3. Levantar todos los servicios
docker compose --env-file .env.dev up -d --build

# 4. Seguir los logs hasta ver "Application startup completed"
docker compose logs -f backend
```

> `--env-file .env.dev` sirve para que `docker compose` interpole variables como
> `BACKEND_PORT`, `SQLSERVER_PORT` o `MSSQL_SA_PASSWORD`. Sin ese flag el stack
> también funciona, pero usa los valores por defecto escritos en
> `docker-compose.yml`.

Opcionalmente, tras el primer arranque:

```bash
# Datos de ejemplo: tablas de ausencias, permisos y usuarios demo
docker compose --env-file .env.dev --profile seed run --rm seeder

# Restaurar un backup en lugar de partir de cero
docker compose --env-file .env.dev --profile restore run --rm restore

# Abrir una consola SQL
docker compose --env-file .env.dev --profile tools run --rm sqlcmd
```

La primera vez tarda ~90 segundos: SQL Server arranca, se crea la base de datos `timeshift`, se ejecutan las migraciones, se instalan los datos iniciales y arranca uvicorn en modo hot-reload.

La API queda disponible en: **http://localhost:8000**  
Documentación Swagger: **http://localhost:8000/docs**

---

## Stack en cluster: red privada + 3 backends

`docker-compose.cluster.yml` es una variante del stack pensada para varias
instancias del backend detrás de un balanceador, con la base de datos aislada.

```
 host:8001 ─┐                          ┌─ backend-1 ─► timeshift_1  ◄─ BAK_FILE_1
 host:8002 ─┼─► tsz-nginx (enruta) ────┼─ backend-2 ─► timeshift_2  ◄─ BAK_FILE_2
 host:8003 ─┤   red timeshift-web      └─ backend-3 ─► timeshift_3  ◄─ BAK_FILE_3
 host:8000 ─┘   (Host: t1/t2/t3.localhost)          tsz-sqlserver
                                          red timeshift-db → internal: true
```

Cada backend tiene **su propia base de datos**, restaurada de su propio backup.
Por eso nginx **enruta de forma determinista y no balancea**: un round-robin
entre los tres devolvería datos de una base distinta en cada petición.

| Red | `internal` | Quién está dentro |
|---|---|---|
| `timeshift-web` | no | nginx + los 3 backends. Único puerto publicado: `8000 → nginx:80` |
| `timeshift-db` | **sí** | sqlserver + los 3 backends + `db-init`. Sin salida ni entrada desde fuera |

SQL Server **no publica ningún puerto**: solo es accesible por nombre
(`sqlserver:1433`) desde los contenedores de la red privada.

### Las 3 bases y sus backups

`docker/init_databases.py` corre una sola vez (los backends esperan con
`service_completed_successfully`) y, por cada par `DB_NAME_n` / `BAK_FILE_n`:

| Situación | Qué hace |
|---|---|
| La base ya existe | No la toca (idempotente) |
| Hay `backups/<BAK_FILE_n>` | `RESTORE DATABASE` desde ese backup |
| No hay backup | `CREATE DATABASE` + esquema de los modelos + `create_first_data()` |

Los nombres lógicos del `.bak` se leen con `RESTORE FILELISTONLY`, así que no
importa de qué servidor ni con qué nombre de base salieron; el `MOVE` va a
`/var/opt/mssql/data/<DB_NAME_n>.mdf` para que las 3 no se pisen los ficheros.

Con `MIGRATE_AFTER_RESTORE=true` (por defecto), tras restaurar se ejecuta
`create_all()`: solo **añade** tablas que el backup no trajera, no altera ni
borra las que ya vienen.

Para rehacer las bases sobre datos existentes: `FORCE_RESTORE=true` (destructivo).

### Enrutado

| Entrada | Va a | Base |
|---|---|---|
| `http://localhost:8001` | backend-1 | `timeshift_1` |
| `http://localhost:8002` | backend-2 | `timeshift_2` |
| `http://localhost:8003` | backend-3 | `timeshift_3` |
| `http://t1.localhost:8000` | backend-1 | `timeshift_1` |
| `http://t2.localhost:8000` | backend-2 | `timeshift_2` |
| `http://t3.localhost:8000` | backend-3 | `timeshift_3` |

La respuesta lleva `X-TimeShift-Instance` y `X-TimeShift-Database` para saber
qué instancia contestó.

### Arranque

```bash
cp .env.cluster.example .env.cluster
# deja los 3 .bak en backups/ (opcional: sin ellos las bases se crean vacías)
docker compose -f docker-compose.cluster.yml --env-file .env.cluster up -d --build

# Seeds opcionales
docker compose -f docker-compose.cluster.yml --env-file .env.cluster \
  --profile seed run --rm seeder

# Consola SQL (única forma de entrar a la BD: desde dentro de la red privada)
docker compose -f docker-compose.cluster.yml --env-file .env.cluster \
  --profile tools run --rm sqlcmd
```

### Decisiones de diseño

- **`db-init` crea el esquema una sola vez.** Los 3 backends arrancan con
  `SKIP_DB_INIT=true` y dependen de `db-init` con
  `condition: service_completed_successfully`. Si cada backend ejecutara
  `init_db()` + `init_triggers()` a la vez, chocarían creando las mismas tablas
  y haciendo DROP/CREATE del trigger `trg_UpdateUserHoursBalance` en paralelo.
- **Un volumen de imágenes por instancia** (`profile-pictures-1/2/3`): las fotos
  se guardan como `<UserID>.png` y los `UserID` se repiten entre bases distintas,
  así que un volumen compartido haría que la foto de un usuario de `timeshift_1`
  pisara la de otro en `timeshift_2`.
- **El seeder reescribe el `USE [...]` al vuelo**: los `.sql` del repo llevan
  `USE [timeshift]` fijo y ahora las bases se llaman `timeshift_1..3`.
- **Un directorio de logs por instancia** (`docker/logs/backend-N/`): los
  handlers de `logging_configdict.json` escriben en rutas relativas a `logs/`,
  y tres procesos rotando el mismo fichero se pisan.
- **`UVICORN_RELOAD=false`** en este stack: hot-reload con 3 réplicas no aporta
  y multiplica los watchers. El código sigue montado, así que basta
  `docker compose ... restart backend-1` para recargar cambios.
- **nginx no está en la red de la BD**, así que un fallo del balanceador no da
  ninguna ruta hacia SQL Server.

### Escalar

Para cambiar el número de instancias hay que tocar tres sitios: el servicio
`backend-N` en el compose, su `upstream` + `server` block en
`docker/nginx.conf`, y el bucle `for n in (1, 2, 3)` de
`docker/init_databases.py`.

---

## Comandos de uso frecuente

### Ciclo de vida

```bash
# Levantar (sin borrar datos)
docker compose up -d

# Parar (conserva volumen de datos)
docker compose stop

# Parar y eliminar contenedores (conserva datos)
docker compose down

# Reset completo: eliminar contenedores + volumen de BD
docker compose down -v && docker compose up -d

# Reconstruir imagen (tras cambios en Dockerfile o requirements)
docker compose build backend --no-cache && docker compose up -d
```

### Logs

```bash
# Logs en tiempo real
docker compose logs -f backend

# Últimas N líneas
docker compose logs backend --tail=50

# Solo errores
docker compose logs backend 2>&1 | grep ERROR
```

### Base de datos

```bash
# Conectarse a SQL Server via sqlcmd
docker compose exec sqlserver /opt/mssql-tools18/bin/sqlcmd \
  -S localhost -U sa -P "TimeShift@Dev2024" -No

# Listar tablas (dentro de sqlcmd)
USE timeshift; SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES; GO

# Salir de sqlcmd
EXIT
```

### Backend

```bash
# Ejecutar comando Python dentro del contenedor
docker compose exec backend python -c "print('ok')"

# Reiniciar solo el backend (sin tocar SQL Server)
docker compose restart backend

# Ver variables de entorno activas
docker compose exec backend env | sort
```

---

## Variables de entorno (`.env.dev`)

| Variable | Valor por defecto | Descripción |
|---|---|---|
| `DB_DRIVER` | `ODBC Driver 18 for SQL Server` | Driver pyodbc |
| `DB_HOST` | `sqlserver` | Hostname del contenedor SQL Server |
| `DB_PORT` | `1433` | Puerto SQL Server |
| `DB_NAME` | `timeshift` | Nombre de la base de datos |
| `DB_USERNAME` | `sa` | Usuario SA |
| `DB_PASSWORD` | `TimeShift@Dev2024` | Contraseña SA |
| `DB_TRUSTED_CONNECTION` | `no` | Autenticación Windows (no aplica en Linux) |
| `SECRET_KEY` | `dev-secret-key-…` | Clave JWT — **cambiar en producción** |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Expiración access token |
| `LOG_LEVEL` | `DEBUG` | Nivel de logging (debe ser MAYÚSCULAS) |
| `MSSQL_SA_PASSWORD` | `TimeShift@Dev2024` | Contraseña SA del contenedor SQL Server |
| `BACKEND_PORT` | `8000` | Puerto publicado en el host para la API |
| `SQLSERVER_PORT` | `1433` | Puerto publicado en el host para SQL Server |
| `SKIP_DB_INIT` | `false` | `true` → no crea esquema ni datos iniciales (usar tras restaurar un `.bak`) |
| `PROFILE_PICTURES_PATH` | `/code/app/static/images` | Destino de las fotos de perfil (volumen `profile-pictures`) |
| `SMTP_TLS` | `false` | STARTTLS en el envío de correo |
| `FRONTEND_URL` | `http://localhost:8000` | URL base usada en los correos de recuperación |
| `MAX_REQUESTS_PER_MINUTE` | `100` | Límite de peticiones por cliente |
| `UVICORN_RELOAD` | `true` | `false` → arranca sin hot-reload (producción) |
| `UVICORN_WORKERS` | `1` | Nº de workers cuando `UVICORN_RELOAD=false` |
| `BAK_FILE` | `timeshift_20250610.bak` | Backup que usa el perfil `restore` |

> `GOOGLE_API_KEY` se deja comentada en `.env.docker.example` a propósito: el
> contenedor monta `./app`, así que `load_dotenv()` toma el valor de `app/.env`
> para todo lo que no venga ya del entorno. Definirla vacía en `.env.dev`
> machacaría ese valor.

> **Nota:** `LOG_LEVEL` debe ser `DEBUG`, `INFO`, `WARNING`, `ERROR` o `CRITICAL` (mayúsculas). Minúsculas causan un error de `dictConfig`.

---

## Usuario admin inicial

| Campo | Valor |
|---|---|
| Email | `info@phoedata.com` |
| Password | `admin` |
| Rol | `admin` |

El usuario `admin` recibe todos los permisos disponibles en el primer arranque.

---

## Permisos creados automáticamente

| Permiso | Descripción | Menú frontend |
|---|---|---|
| `manage:Users` | Gestionar empleados | — |
| `view:All` | Ver todos los usuarios | — |
| `view:OwnDepartment` | Ver su propio departamento | — |
| `view:SubDepartment` | Ver subdepartamentos recursivamente | — |
| `view:FirstSubDepartment` | Ver primer nivel de subdepartamentos | — |
| `update:OwnDepartment` | Gestionar su departamento | — |
| `update:FirstSubDepartment` | Gestionar primer nivel subdepartamentos | — |
| `update:SubDepartments` | Gestionar todos los subdepartamentos | — |
| `create:Shifts` | Crear turnos para cualquier usuario | — |
| `create:OwnShifts` | Crear turnos para sí mismo | — |
| `read:Shifts` | Ver turnos | — |
| `update:Shifts` | Actualizar turnos | — |
| `delete:Shifts` | Eliminar turnos | — |
| `manage:Schedules` | Gestionar horarios | `gestion_horarios` |
| `view:Schedules` | Ver horarios | — |
| `manage:Shifts` | Gestionar registros de trabajo | `gestion_empleados` |
| `delete:Worklogs` | Eliminar registros de trabajo | — |
| `manage:Absences` | Aprobar/rechazar ausencias y saldos | `manage_absences` |
| `view:Absences` | Ver solicitudes de ausencias | — |
| `manage:Holidays` | Gestionar festivos | `manage_holidays` |
| `view:docs` | Ver documentación Swagger | — |

---

## Arquitectura de los contenedores

```
┌──────────────────────────────────────────────────────────┐
│  docker-compose network: timeshiftapp-master_timeshift   │
│                                                          │
│  ┌─────────────────────┐    ┌──────────────────────────┐ │
│  │  timeshift-sqlserver│    │  timeshift-backend       │ │
│  │                     │    │                          │ │
│  │  SQL Server 2022    │◄───│  FastAPI + uvicorn       │ │
│  │  Developer Edition  │    │  Python 3.12             │ │
│  │  puerto: 1433       │    │  puerto: 8000            │ │
│  │                     │    │  sirve app/static        │ │
│  │  Volúmenes:         │    │                          │ │
│  │  sqlserver-data     │    │  Volúmenes:              │ │
│  │  ./ → /backups:ro   │    │  ./app → /code/app       │ │
│  │                     │    │  profile-pictures →      │ │
│  │                     │    │    /code/app/static/     │ │
│  │                     │    │    images                │ │
│  └─────────────────────┘    │  (hot-reload activo)     │ │
│                             └──────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
         │                              │
    localhost:1433                 localhost:8000
```

**Health check:** el backend espera a que SQL Server responda antes de arrancar. Si SQL Server no responde en 30 intentos (×3s = 90s), el backend se detiene con error.

---

## Flujo del entrypoint

```
docker-entrypoint.sh
│
├── Bucle de espera (máx 30 reintentos × 3s)
│   └── pyodbc → conecta a master
│       └── IF NOT EXISTS CREATE DATABASE [timeshift]
│
├── mkdir -p logs
│
└── exec uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Al arrancar FastAPI:
```
lifespan()
├── init_db()           → SQLModel.metadata.create_all() — crea todas las tablas
│   └── init_triggers() → crea trigger trg_UpdateUserHoursBalance en SQL Server
└── create_first_data() → si no hay usuarios:
    ├── Crea rol admin
    ├── Crea 21 permisos + PermissionMenus para frontend
    ├── Asigna permisos al rol admin
    ├── Crea usuario info@phoedata.com
    └── Vincula usuario ↔ rol
```

---

## Bugs corregidos durante el setup

Estos bugs existían en el código fuente pero solo se manifestaron al ejecutar bajo Python 3.11 en un entorno limpio:

### 1. f-string con comillas anidadas — `SQLModels/UserShifts.py:88`

**Problema:** Python < 3.12 no permite comillas dobles dentro de un f-string delimitado por comillas dobles.
```python
# ❌ Antes (falla en Python 3.11)
raise ValueError(f"... {shift.StartTime.strftime("%H:%M")} ...")

# ✅ Después
nombre = user.details.FirstName if user and user.details else shift.UserID
raise ValueError(f"... {shift.StartTime.strftime('%H:%M')} ... {nombre} ...")
```

### 2. `os.environ.get()` retorna `str` — `SQLModels/UserShifts.py:50`

**Problema:** `timedelta(minutes=...)` requiere un número; `os.environ.get()` devuelve `str` cuando la variable existe.
```python
# ❌ Antes
timedelta(minutes=os.environ.get("SHIFT_BEFORE_MINUTES_MARGIN", 15))

# ✅ Después
timedelta(minutes=int(os.environ.get("SHIFT_BEFORE_MINUTES_MARGIN", 15)))
```

### 3. `AbsenceStatus` no heredaba de `str` — `SQLModels/WorkLogs.py`

**Problema:** SQLModel no puede serializar/deserializar un `Enum` puro como columna. Debe ser `str, Enum` para que funcione correctamente con pyodbc y la ORM.
```python
# ❌ Antes
class AbsenceStatus(Enum):
    PENDING = "Pending"

Status: Enum = Field(default="Pending", sa_column=SQLAlchemyEnum(AbsenceStatus))

# ✅ Después
class AbsenceStatus(str, Enum):
    PENDING = "Pending"

Status: AbsenceStatus = Field(default=AbsenceStatus.PENDING)
```

### 4. `extract()` en lugar de atributos Python en queries — `SQLModels/Absences.py`

**Problema:** Los atributos `.month` y `.day` no existen en columnas SQLAlchemy instrumentadas. Hay que usar `extract()` de SQLAlchemy.
```python
# ❌ Antes
(cls.Date.month == date.month) & (cls.Date.day == date.day)

# ✅ Después
(extract("month", cls.Date) == date.month) & (extract("day", cls.Date) == date.day)
```

### 5. `LOG_LEVEL` en minúsculas — `.env.dev`

**Problema:** `logging.config.dictConfig` llama a `logging._checkLevel()` que solo acepta niveles en MAYÚSCULAS.
```
# ❌ Antes
LOG_LEVEL=debug

# ✅ Después
LOG_LEVEL=DEBUG
```

---

## Prueba end-to-end del flujo de ausencias

El siguiente flujo fue ejecutado y validado contra la BD en contenedor:

```bash
BASE="http://localhost:8000/api"
TOKEN=$(curl -s -X POST $BASE/token \
  -d "username=info@phoedata.com&password=admin" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 1. Crear tipo de ausencia
curl -s -X POST $BASE/absences/types/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"type_name":"Vacaciones","is_counted":true}'

# 2. Crear festivo recurrente
curl -s -X POST $BASE/holidays/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"Navidad","date":"2026-12-25","is_recurring":true}'

# 3. Asignar 22 días de vacaciones al usuario 1
curl -s -X PUT $BASE/absences/balance/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"user_id":1,"absence_type_id":1,"year":2026,"accrued_days":22}'

# 4. Crear solicitud 1-5 julio (3 días laborables: lun/mar/mié)
curl -s -X POST $BASE/absences/requests/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"absence_type_id":1,"start_time":"2026-07-01T08:00:00","end_time":"2026-07-05T17:00:00","reason":"Vacaciones verano"}'
# → request_id=1, total_days=3.0, status=Pending
# → AbsenceBalance.pending_days = 3.0

# 5. Aprobar solicitud
curl -s -X POST $BASE/absences/requests/1/approve/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"comments":"Aprobadas"}'
# → status=Approved
# → AbsenceBalance: used=3.0, pending=0.0, remaining=19.0
# → 3 WorkLogs creados (1 por día laborable):
#     WorkLog 1: 2026-07-01 | IsPause=True | AbsenceType=1 | 8h
#     WorkLog 2: 2026-07-02 | IsPause=True | AbsenceType=1 | 8h
#     WorkLog 3: 2026-07-03 | IsPause=True | AbsenceType=1 | 8h
# → Trigger SQL actualizó UserWeekHoursBalance automáticamente

# 6. Verificar balance final
curl -s "$BASE/absences/balance/?year=2026" \
  -H "Authorization: Bearer $TOKEN"
# → {"accrued_days":22,"used_days":3,"pending_days":0,"remaining_days":19}
```

### Resultados verificados

| Paso | Resultado |
|---|---|
| Login | ✅ Token JWT generado |
| Crear AbsenceType | ✅ ID=1, TypeName="Vacaciones" |
| Crear Festivo | ✅ ID=1, recurrente, 25-dic |
| Asignar balance | ✅ AccruedDays=22 |
| Crear solicitud | ✅ TotalDays=3.0 (excluye sáb/dom) |
| Balance pendiente | ✅ PendingDays=3.0 |
| Aprobar | ✅ Status=Approved |
| Balance final | ✅ UsedDays=3, Remaining=19 |
| WorkLogs generados | ✅ 3 registros (Jul 1, 2, 3) |
| Trigger SQL | ✅ UserWeekHoursBalance actualizado |

---

## Endpoints disponibles (53 total)

### Nuevos endpoints integrados

| Método | Ruta | Permiso | Descripción |
|---|---|---|---|
| GET | `/api/absences/types/` | autenticado | Listar tipos de ausencia |
| POST | `/api/absences/types/` | `manage:Absences` | Crear tipo de ausencia |
| GET | `/api/absences/requests/` | `view:Absences` | Listar solicitudes |
| POST | `/api/absences/requests/` | autenticado | Crear solicitud propia |
| GET | `/api/absences/requests/{id}/` | autenticado | Ver solicitud |
| POST | `/api/absences/requests/{id}/approve/` | `manage:Absences` | Aprobar |
| POST | `/api/absences/requests/{id}/reject/` | `manage:Absences` | Rechazar |
| DELETE | `/api/absences/requests/{id}/` | autenticado | Cancelar (solo Pending) |
| GET | `/api/absences/balance/` | autenticado | Ver saldo |
| PUT | `/api/absences/balance/` | `manage:Absences` | Asignar días acumulados |
| GET | `/api/holidays/` | autenticado | Listar festivos |
| POST | `/api/holidays/` | `manage:Holidays` | Crear festivo |
| GET | `/api/holidays/{id}/` | autenticado | Ver festivo |
| PUT | `/api/holidays/{id}/` | `manage:Holidays` | Actualizar festivo |
| DELETE | `/api/holidays/{id}/` | `manage:Holidays` | Eliminar festivo |

---

## Notas de producción

- Cambiar `SECRET_KEY` en `.env` por un valor aleatorio seguro (`openssl rand -hex 32`)
- Cambiar `DB_PASSWORD` y `MSSQL_SA_PASSWORD` por una contraseña segura
- Reemplazar `Developer Edition` de SQL Server por `Standard` o `Enterprise` según licencia
- Eliminar `--reload` del entrypoint (hot-reload solo para desarrollo)
- Agregar HTTPS (nginx reverse proxy recomendado)
- Configurar SMTP real para recuperación de contraseñas
