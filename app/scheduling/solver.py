"""Modelo CP-SAT y resolución del auto-scheduler.

Formulación por slots: works[e,d,t] = el empleado e trabaja el día d en el slot t.
Un turno = tramo contiguo de works=1. Se permiten <= MAX_SHIFTS_PER_DAY tramos por día,
cada uno con duración en [MIN, MAX]. La cobertura y las horas de contrato son objetivos blandos.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from ortools.sat.python import cp_model

from .config import SchedulerConfig
from .demand import DemandGrid


@dataclass
class EmployeeInput:
    user_id: int
    name: str
    contract_hours: float
    # avail[d][t] -> bool (disponible ese día/slot: dentro de apertura y sin ausencia/festivo)
    avail: List[List[bool]]


@dataclass
class ProposedShift:
    user_id: int
    day_index: int          # 0..6 (Lun..Dom) dentro de la semana objetivo
    start_slot: int
    end_slot: int           # exclusivo


@dataclass
class SolveResult:
    status: str
    shifts: List[ProposedShift] = field(default_factory=list)
    coverage: Dict[Tuple[int, int], Tuple[int, int]] = field(default_factory=dict)  # (d,t) -> (asignado, demanda)
    hours_by_user: Dict[int, float] = field(default_factory=dict)
    total_shortfall_slots: int = 0


DAYS = 7


def solve(employees: List[EmployeeInput], grid: DemandGrid,
          cfg: SchedulerConfig) -> SolveResult:
    T = grid.num_slots
    E = len(employees)
    m = cp_model.CpModel()

    works: Dict[Tuple[int, int, int], cp_model.IntVar] = {}
    for e in range(E):
        for d in range(DAYS):
            for t in range(T):
                if employees[e].avail[d][t]:
                    works[e, d, t] = m.NewBoolVar(f"w_{e}_{d}_{t}")
                else:
                    works[e, d, t] = m.NewConstant(0)

    min_slots = cfg.min_slots
    max_slots = cfg.max_slots

    for e in range(E):
        for d in range(DAYS):
            starts = []
            for t in range(T):
                s = m.NewBoolVar(f"s_{e}_{d}_{t}")
                prev = works[e, d, t - 1] if t > 0 else 0
                # s == works[t] AND NOT prev
                m.Add(s <= works[e, d, t])
                m.Add(s <= 1 - prev)
                m.Add(s >= works[e, d, t] - prev)
                starts.append(s)
                # duración mínima: si empieza en t, works[t..t+min-1]=1
                for k in range(1, min_slots):
                    if t + k < T:
                        m.Add(works[e, d, t + k] >= s)
                    else:
                        m.Add(s == 0)  # no cabe el mínimo → no puede empezar aquí
            # como máximo N tramos por día
            m.Add(sum(starts) <= cfg.MAX_SHIFTS_PER_DAY)
            # duración máxima: ninguna ventana de (max+1) slots totalmente trabajada
            for t0 in range(0, T - max_slots):
                m.Add(sum(works[e, d, t0 + k] for k in range(max_slots + 1)) <= max_slots)
            # tope de horas por día (suma de ambos tramos)
            m.Add(sum(works[e, d, t] for t in range(T)) <= cfg.max_daily_slots)

    obj = []

    # Cobertura (blanda): acercarse a la demanda por slot
    coverage_terms: Dict[Tuple[int, int], cp_model.IntVar] = {}
    for d in range(DAYS):
        for t in range(T):
            dem = grid.get(d, t)
            cov = sum(works[e, d, t] for e in range(E))
            short = m.NewIntVar(0, E, f"short_{d}_{t}")
            exc = m.NewIntVar(0, E, f"exc_{d}_{t}")
            m.Add(short >= dem - cov)
            m.Add(exc >= cov - dem)
            obj.append(cfg.W_SHORTFALL * short)
            obj.append(cfg.W_EXCESS * exc)
            coverage_terms[d, t] = short

    # Horas de contrato (blanda)
    for e in range(E):
        target = int(round(employees[e].contract_hours / cfg.slot_hours))
        total = sum(works[e, d, t] for d in range(DAYS) for t in range(T))
        dev = m.NewIntVar(0, DAYS * T, f"dev_{e}")
        m.Add(dev >= total - target)
        m.Add(dev >= target - total)
        obj.append(cfg.W_CONTRACT * dev)

    m.Minimize(sum(obj))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = cfg.MAX_SOLVE_SECONDS
    solver.parameters.num_search_workers = 8
    status = solver.Solve(m)
    status_name = solver.StatusName(status)

    result = SolveResult(status=status_name)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return result

    # Extraer turnos (tramos contiguos de works=1)
    for e in range(E):
        for d in range(DAYS):
            t = 0
            while t < T:
                if solver.Value(works[e, d, t]) == 1:
                    start = t
                    while t < T and solver.Value(works[e, d, t]) == 1:
                        t += 1
                    result.shifts.append(
                        ProposedShift(employees[e].user_id, d, start, t)
                    )
                else:
                    t += 1

    # Reporte de cobertura y horas
    for d in range(DAYS):
        for t in range(T):
            assigned = sum(solver.Value(works[e, d, t]) for e in range(E))
            result.coverage[d, t] = (assigned, grid.get(d, t))
            result.total_shortfall_slots += max(0, grid.get(d, t) - assigned)

    for e in range(E):
        slots = sum(solver.Value(works[e, d, t]) for d in range(DAYS) for t in range(T))
        result.hours_by_user[employees[e].user_id] = slots * cfg.slot_hours

    return result
