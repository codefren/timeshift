"""POC del auto-scheduler: genera una propuesta para 1 departamento / 1 semana
con datos reales, SIN tocar la base de datos. Imprime la propuesta y el reporte.

Uso (dentro del contenedor):
    python -m scheduling.poc                 # Depto 5, semana del 2026-06-01
    python -m scheduling.poc 5 2026-06-01
"""
import sys
from datetime import date, datetime, time, timedelta
from typing import List

from sqlmodel import Session, select

from db.session import engine
from SQLModels.Users import Users, UserDetail, UserDepartments
from SQLModels.WorkLogs import AbsenceRequests, AbsenceStatus
from SQLModels.Absences import Holidays

from .config import DEFAULT
from .demand import infer_demand
from .solver import EmployeeInput, solve
from .service import load_employees

DAYS = 7
DAY_NAMES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]

# load_employees se reutiliza desde scheduling.service (importado arriba).


def run(department_id: int = 5, week_start: date = date(2026, 6, 1)) -> None:
    if week_start.weekday() != 0:
        week_start = week_start - timedelta(days=week_start.weekday())  # normalizar a lunes
    week_end = week_start + timedelta(days=6)
    cfg = DEFAULT

    with Session(engine) as db:
        grid = infer_demand(db, department_id, week_start, cfg)
        employees = load_employees(db, department_id, week_start, week_end, grid)

        print("=" * 68)
        print(f" AUTO-SCHEDULER (POC) · Depto {department_id} · semana {week_start} → {week_end}")
        print(f" Apertura {grid.slot_start_time(0).strftime('%H:%M')}"
              f"–{grid.slot_start_time(grid.num_slots-1).strftime('%H:%M')}"
              f" · {grid.num_slots} slots de {cfg.SLOT_MINUTES} min · {len(employees)} empleados")
        print("=" * 68)

        if not employees:
            print("No hay empleados asignados al departamento en esa semana.")
            return

        result = solve(employees, grid, cfg)
        print(f"\nEstado del solver: {result.status}")
        if not result.shifts and result.status not in ("OPTIMAL", "FEASIBLE"):
            print("No se encontró solución.")
            return

        # Turnos propuestos por empleado
        name_by_id = {e.user_id: e.name for e in employees}
        print("\n── Turnos propuestos ─────────────────────────────────────────────")
        by_user = {}
        for s in result.shifts:
            by_user.setdefault(s.user_id, []).append(s)
        for uid, shifts in by_user.items():
            print(f"\n  {name_by_id[uid]}  (contrato {next(e.contract_hours for e in employees if e.user_id==uid):.0f}h/sem"
                  f" · asignado {result.hours_by_user.get(uid,0):.1f}h)")
            shifts.sort(key=lambda x: (x.day_index, x.start_slot))
            for d in range(DAYS):
                day_shifts = [s for s in shifts if s.day_index == d]
                if day_shifts:
                    tramos = ", ".join(
                        f"{grid.slot_start_time(s.start_slot).strftime('%H:%M')}"
                        f"-{grid.slot_start_time(s.end_slot).strftime('%H:%M') if s.end_slot < grid.num_slots else grid.slot_start_time(grid.num_slots-1).strftime('%H:%M')}"
                        for s in day_shifts
                    )
                    print(f"     {DAY_NAMES[d]}: {tramos}")

        # Cobertura vs demanda (resumen por día)
        print("\n── Cobertura vs demanda (déficit total de franjas: "
              f"{result.total_shortfall_slots}) ──")
        for d in range(DAYS):
            dem_total = sum(grid.get(d, t) for t in range(grid.num_slots))
            asg_total = sum(result.coverage[d, t][0] for t in range(grid.num_slots))
            short = sum(max(0, grid.get(d, t) - result.coverage[d, t][0]) for t in range(grid.num_slots))
            print(f"     {DAY_NAMES[d]}: demanda {dem_total:>3}  asignado {asg_total:>3}  déficit {short:>2}  (slots-persona)")

        print("\n(*) POC: no se ha escrito nada en la base de datos.")


if __name__ == "__main__":
    dept = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    ws = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date(2026, 6, 1)
    run(dept, ws)
