"""Generador de horarios por heurística voraz, en Python puro (sin ortools).

Motivo: los binarios nativos de ortools (CP-SAT) hacen *segfault* en CPUs antiguas
o virtualizadas que no soportan las instrucciones que requieren (AVX2, etc.). Esta
implementación produce una propuesta razonable sin dependencias nativas, así que
funciona en cualquier servidor.

Estrategia: para cada día se recorren los empleados disponibles (priorizando a los
que están más por debajo de sus horas de contrato) y a cada uno se le asigna el
mejor tramo contiguo posible —de duración válida [MIN, MAX], respetando el tope
diario y el máximo de tramos/día, y dejando un hueco entre tramos de un mismo día—
que cubra más demanda aún sin cubrir. Se deja de asignar cuando no queda demanda que
un empleado pueda cubrir (para no generar exceso). Es una heurística: no garantiza
el óptimo, pero es adecuada para una propuesta que el responsable revisa antes de
publicar. Mantiene el mismo API público que la versión CP-SAT anterior.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

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


def _best_window(blocked_row: List[bool], assigned_row: List[int], demand_row: List[int],
                 min_slots: int, max_len: int, T: int) -> Optional[Tuple[int, int, int, int]]:
    """Mejor tramo contiguo para un empleado en un día.

    Devuelve (marginal, -excess, start, length) o None. 'marginal' = nº de slots con
    demanda aún sin cubrir que el tramo cubriría; se maximiza marginal y, a igualdad,
    se minimiza el exceso (slots del tramo que no aportan cobertura). Un slot está
    'blocked' si no está disponible, ya lo ocupa el empleado, o es adyacente a un
    tramo ya asignado (para forzar un hueco entre tramos partidos)."""
    best: Optional[Tuple[int, int, int, int]] = None
    t = 0
    while t < T:
        if blocked_row[t]:
            t += 1
            continue
        # run contiguo utilizable [t, run_end)
        run_end = t
        while run_end < T and not blocked_row[run_end]:
            run_end += 1
        # probar tramos que empiecen dentro del run y quepan con el mínimo
        for s in range(t, run_end - min_slots + 1):
            limit = min(max_len, run_end - s)
            marginal = 0
            for length in range(1, limit + 1):
                slot = s + length - 1
                if assigned_row[slot] < demand_row[slot]:
                    marginal += 1
                if length >= min_slots:
                    excess = length - marginal
                    cand = (marginal, -excess, s, length)
                    if best is None or cand > best:
                        best = cand
        t = run_end
    return best


def solve(employees: List[EmployeeInput], grid: DemandGrid,
          cfg: SchedulerConfig) -> SolveResult:
    T = grid.num_slots
    E = len(employees)
    slot_hours = cfg.slot_hours
    min_slots = cfg.min_slots
    max_slots = cfg.max_slots
    max_daily_slots = cfg.max_daily_slots
    max_shifts = cfg.MAX_SHIFTS_PER_DAY

    demand = [[grid.get(d, t) for t in range(T)] for d in range(DAYS)]
    assigned = [[0] * T for _ in range(DAYS)]

    target_slots = [max(0, int(round(e.contract_hours / slot_hours))) for e in employees]
    weekly_slots = [0] * E

    result = SolveResult(status="FEASIBLE")

    for d in range(DAYS):
        demand_row = demand[d]
        assigned_row = assigned[d]
        if sum(demand_row) == 0:
            continue

        occ = [[False] * T for _ in range(E)]   # slots que ya trabaja cada empleado ese día
        daily_slots = [0] * E
        shifts_count = [0] * E

        # empleados más por debajo de su contrato primero (reparto justo de horas)
        order = sorted(range(E), key=lambda e: weekly_slots[e] - target_slots[e])

        for e in order:
            avail_row = employees[e].avail[d]
            if not any(avail_row):
                continue
            while shifts_count[e] < max_shifts:
                remaining_daily = max_daily_slots - daily_slots[e]
                if remaining_daily < min_slots:
                    break
                max_len = min(max_slots, remaining_daily)

                # bloqueado = no disponible, ya ocupado, o adyacente a un tramo propio
                occ_e = occ[e]
                blocked = [
                    (not avail_row[t]) or occ_e[t]
                    or (t > 0 and occ_e[t - 1]) or (t < T - 1 and occ_e[t + 1])
                    for t in range(T)
                ]
                best = _best_window(blocked, assigned_row, demand_row, min_slots, max_len, T)
                if best is None or best[0] <= 0:
                    break  # no cubre demanda nueva → no añadir exceso

                _marginal, _neg_excess, s, length = best
                for k in range(s, s + length):
                    occ_e[k] = True
                    assigned_row[k] += 1
                daily_slots[e] += length
                weekly_slots[e] += length
                shifts_count[e] += 1
                result.shifts.append(ProposedShift(employees[e].user_id, d, s, s + length))

    # reporte de cobertura y horas
    for d in range(DAYS):
        for t in range(T):
            asg = assigned[d][t]
            dem = demand[d][t]
            result.coverage[d, t] = (asg, dem)
            result.total_shortfall_slots += max(0, dem - asg)

    for e in range(E):
        result.hours_by_user[employees[e].user_id] = weekly_slots[e] * slot_hours

    return result
