# TimeShift API

TimeShift API es un backend desarrollado con **FastAPI** y **SQLModel** destinado a la gestión de empleados, empresas y turnos de trabajo. Incluye autenticación JWT, recuperación de contraseña, un sistema de permisos y registro de horas.

## Características principales
- Administración de empleados, empresas, localizaciones y turnos.
- Endpoints protegidos mediante autenticación y roles.
- Registro de jornada con control de horas trabajadas.
- Envío de correos de recuperación de contraseña.
- Ficheros estáticos servidos desde `app/static`.
- Documentación de la API restringida por el permiso `view:docs`.

## Requisitos
- Python 3.10+
- Dependencias listadas en `requirements.txt`.
- Base de datos SQL Server accesible.

## Instalación
```bash
pip install -r requirements.txt
```

## Variables de entorno
El proyecto lee su configuración a través de variables de entorno (ver `app/utils/Config.py`). Las más importantes son:

| Variable | Descripción |
| -------- | ----------- |
| `DB_USERNAME` | Usuario de la base de datos |
| `DB_PASSWORD` | Contraseña de la base de datos |
| `DB_HOST` | Host del servidor SQL |
| `DB_NAME` | Nombre de la base de datos |
| `DB_DRIVER` | Driver ODBC a utilizar |
| `DB_TRUSTED_CONNECTION` | Si la conexión es de confianza |
| `SECRET_KEY` | Clave secreta para firmar tokens |
| `SECURITY_ALGORITHM` | Algoritmo JWT (p.ej. HS256) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Minutos de validez del token |
| `SMTP_SERVER` | Servidor SMTP para correos |
| `SMTP_PORT` | Puerto SMTP |
| `SMTP_USERNAME` | Usuario SMTP |
| `SMTP_PASSWORD` | Contraseña SMTP |
| `SENDER_EMAIL` | Email remitente para notificaciones |
| `APP_NAME` | Nombre de la aplicación |
| `LOG_LEVEL` | Nivel de registro (debug, info, ...) |

## Puesta en marcha
Ejecute el servidor con:
```bash
uvicorn app.main:app --reload
```
La documentación interactiva estará disponible en `http://localhost:8000/docs`.
Solo los usuarios autenticados con el permiso `view:docs` pueden acceder.

## Autenticación
Para obtener un token use `POST /api/token` enviando usuario y contraseña. El token debe enviarse en la cabecera `Authorization: Bearer <token>`. Puede renovarse mediante `POST /api/refresh-token`.

## Endpoints principales
Los routers se encuentran bajo el prefijo `/api`:
- `/api/employees` – operaciones sobre usuarios.
- `/api/companies` – gestión de empresas y departamentos.
- `/api/locations` – localizaciones de trabajo.
- `/api/shifts` – definición de turnos.
- `/api/work-logs` – registro de jornadas.
- `/api/password` – recuperación de contraseña.

## Estructura del proyecto
El código reside en `app/` y se organiza por módulos. Los modelos se definen en `app/SQLModels`, los routers en carpetas del mismo nombre y la configuración de la base de datos en `app/db`.

## Logging
La configuración de logging se encuentra en `app/utils/logging_configdict.json` y genera ficheros JSON en `app/logs`. Puede ajustar el nivel mediante `LOG_LEVEL`.

## Tests
Actualmente el proyecto no incluye pruebas automatizadas. Se recomienda utilizar `pytest` para crear una suite de tests que cubra los distintos routers y modelos.

## Contribución
¡Las contribuciones son bienvenidas! Puede abrir issues o pull requests con mejoras y correcciones.

## Licencia
Distribuido bajo los términos de la licencia MIT.
