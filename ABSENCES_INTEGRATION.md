# Integración de Vacaciones, Días Libres y Festivos

## Contexto

El sistema TimeShift ya tenía los modelos `AbsenceTypes`, `AbsenceRequests` y `AbsenceReviews` definidos en `SQLModels/WorkLogs.py`, pero estaban completamente desconectados de la lógica de negocio: sin endpoints, sin integración con balances de horas y sin modelo de festivos.

Esta integración cierra el ciclo completo:

```
Solicitud → Aprobación → WorkLog automático → Trigger SQL → Balance actualizado
```

---

## Nuevas tablas

### `Holidays` — Festivos
```
HolidayID   (PK, autoincrement)
Name        (max 100 chars)
Date        (date)
CompanyID   (FK Companies, nullable → null = aplica a todos)
LocationID  (FK Locations, nullable → null = aplica a todos)
IsRecurring (bool — si True, se repite cada año mismo día/mes)
CreatedBy   (FK Users)
CreatedAt / UpdatedAt
```

**Alcance:** un festivo con `CompanyID=null` y `LocationID=null` aplica a todos los empleados. Se puede restringir a empresa o ubicación específica.

**Recurrencia:** `IsRecurring=True` permite registrar festivos nacionales una sola vez. Al consultar por rango de fechas, se expanden automáticamente.

---

### `AbsenceBalance` — Saldo de ausencias
```
UserID          (FK Users, PK)
AbsenceTypeID   (FK AbsenceTypes, PK)
Year            (int, PK)
AccruedDays     (float — asignado manualmente por admin)
UsedDays        (float — suma de solicitudes APROBADAS)
PendingDays     (float — suma de solicitudes PENDIENTES)
UpdatedAt
```

**Propiedad calculada:** `RemainingDays = AccruedDays - UsedDays - PendingDays`

El admin asigna `AccruedDays` manualmente vía `PUT /api/absences/balance/`. No hay acumulación automática.

---

### Cambio en `AbsenceRequests`
Se añadió el campo:
```
TotalDays (float — calculado al crear, excluye fines de semana y festivos)
```

---

## Módulo `absences/`

### Endpoints `/api/absences/`

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| GET | `/types/` | autenticado | Listar tipos de ausencia |
| POST | `/types/` | `manage:Absences` | Crear tipo de ausencia |
| GET | `/requests/` | `view:Absences` | Listar solicitudes con filtros |
| POST | `/requests/` | autenticado | Crear solicitud (propio o subordinado) |
| GET | `/requests/{id}/` | autenticado | Ver solicitud individual |
| POST | `/requests/{id}/approve/` | `manage:Absences` | Aprobar solicitud |
| POST | `/requests/{id}/reject/` | `manage:Absences` | Rechazar solicitud |
| DELETE | `/requests/{id}/` | autenticado | Cancelar solicitud propia (solo Pending) |
| GET | `/balance/` | autenticado | Ver saldo (propio o de subordinado) |
| PUT | `/balance/` | `manage:Absences` | Asignar días acumulados (admin) |

---

### Lógica de negocio clave

#### `calculate_working_days(start_date, end_date, db)`
Cuenta días laborables en un rango excluyendo:
- Sábados y domingos (`weekday() >= 5`)
- Festivos registrados en la tabla `Holidays`

Usado para calcular `TotalDays` al crear una solicitud.

---

#### `create_absence_worklog(db, user_id, date, absence_type_id)`
Crea un WorkLog completo para un día de ausencia aprobado.

**Pasos:**
1. Verifica que no exista ya un WorkLog para ese usuario y fecha
2. Obtiene las horas del día: busca turno asignado (`Shifts.get_actual`) → si no hay, usa `ContractWeeklyHours / 5` → fallback: 8h
3. Vincula el `ShiftID` al WorkLog (clave para balance neutro — ver abajo)
4. Crea `WorkLogLine` con `IsPause=True`, `AbsenceType=absence_type_id`, `LoggedHours=hours`
5. Llama a `WorkLog.create_totals()` → el trigger SQL actualiza automáticamente `UserWeekHoursBalance` y `UserTotalHoursBalance`

**¿Por qué vincular el ShiftID?**

`create_totals` calcula:
```
BalanceScheduleHours = (WorkedHours + PausedCountedHours) - shift.total_hours()
```

Sin vincular el turno:
```
BalanceScheduleHours = 0 + hours - 0 = +hours  ← balance positivo (incorrecto)
```

Vinculando el turno (shift.total_hours() == hours):
```
BalanceScheduleHours = 0 + hours - hours = 0   ← balance neutro (correcto)
```

Los días de vacación no generan ni deuda ni superávit de horas.

---

#### Flujo de aprobación de solicitud

```
1. Empleado crea solicitud (POST /requests/)
   → TotalDays = calculate_working_days(start, end)
   → Valida: RemainingDays >= TotalDays
   → AbsenceBalance.PendingDays += TotalDays

2. Supervisor aprueba (POST /requests/{id}/approve/)
   → AbsenceRequests.Status = Approved
   → Crea AbsenceReviews
   → AbsenceBalance.UsedDays += TotalDays
   → AbsenceBalance.PendingDays -= TotalDays
   → Por cada día laborable en el rango:
       create_absence_worklog() → WorkLogTotals → trigger SQL → balance de horas

3. Supervisor rechaza (POST /requests/{id}/reject/)
   → AbsenceRequests.Status = Rejected
   → Crea AbsenceReviews
   → AbsenceBalance.PendingDays -= TotalDays
   → No se crean WorkLogs

4. Empleado cancela (DELETE /requests/{id}/)
   → Solo permitido si Status = Pending
   → AbsenceBalance.PendingDays -= TotalDays
   → Elimina la solicitud
```

---

#### Integración con el trigger SQL existente

El trigger `trg_UpdateUserHoursBalance` (definido en `db/triggers.py`) se dispara en INSERT/UPDATE de `WorkLogTotals` y actualiza:
- `UserWeekHoursBalance` (por semana ISO)
- `UserTotalHoursBalance` (histórico)

Al aprobar una ausencia, cada día genera un `WorkLogTotals` con `BalanceScheduleHours = 0`, lo que deja las tablas de balance sin cambios negativos. El empleado no "debe" horas por estar de vacaciones.

---

## Módulo `holidays/`

### Endpoints `/api/holidays/`

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| GET | `/` | autenticado | Listar festivos en rango (filtros: date_from, date_to, company_id, location_id) |
| POST | `/` | `manage:Holidays` | Crear festivo |
| GET | `/{id}/` | autenticado | Ver festivo |
| PUT | `/{id}/` | `manage:Holidays` | Actualizar festivo |
| DELETE | `/{id}/` | `manage:Holidays` | Eliminar festivo |

---

## Nuevos permisos necesarios

Estos permisos deben crearse en la tabla `Permissions` y asignarse a los roles correspondientes:

| Permiso | Descripción |
|---------|-------------|
| `manage:Absences` | Crear tipos, aprobar/rechazar solicitudes, gestionar saldos |
| `view:Absences` | Ver listado de solicitudes de otros usuarios |
| `manage:Holidays` | Crear, editar y eliminar festivos |

> Los empleados sin permisos especiales pueden: crear su propia solicitud, ver su propio saldo y cancelar sus solicitudes pendientes.

---

## Archivos creados/modificados

### Nuevos
```
app/SQLModels/Absences.py       — modelos Holidays, AbsenceBalance
app/absences/__init__.py
app/absences/service.py         — lógica de negocio
app/absences/models.py          — Pydantic request/response
app/absences/router.py          — endpoints FastAPI
app/holidays/__init__.py
app/holidays/service.py
app/holidays/models.py
app/holidays/router.py
```

### Modificados
```
app/SQLModels/WorkLogs.py       — TotalDays en AbsenceRequests, relación absence_type
app/SQLModels/Users.py          — relación absence_balances
app/SQLModels/__init__.py       — from .Absences import *
app/main.py                     — registrar absences_router y holidays_router
```

---

## Flujo de datos completo

```
Admin asigna saldo:
  PUT /api/absences/balance/ → AbsenceBalance.AccruedDays = 22

Empleado solicita vacaciones:
  POST /api/absences/requests/
    → TotalDays calculado (excluye fines de semana y festivos)
    → AbsenceBalance.PendingDays += TotalDays

Supervisor aprueba:
  POST /api/absences/requests/{id}/approve/
    → AbsenceBalance: UsedDays += TotalDays, PendingDays -= TotalDays
    → Por cada día: WorkLog + WorkLogLine(IsPause=True, AbsenceType)
    → WorkLog.create_totals() → WorkLogTotals
    → Trigger SQL: UserWeekHoursBalance.BalanceHours += 0 (neutro)

Vista de saldo:
  GET /api/absences/balance/?user_id=X&year=2026
    → { accrued: 22, used: 5, pending: 0, remaining: 17 }
```
