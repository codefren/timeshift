"""Inferencia de demanda a partir del histórico de turnos (Shifts).

Devuelve, por (día_de_semana, slot), el headcount típico (mediana) de personas
trabajando a la vez, más la rejilla de slots (horario de apertura) derivada del histórico.
"""
import statistics
from collections import defaultdict
from datetime import date, time, timedelta
from typing import Dict, List, Tuple

from sqlmodel import Session, select

from SQLModels.UserShifts import Shifts
from .config import SchedulerConfig


def _to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


class DemandGrid:
    """Rejilla de demanda y de slots para un departamento."""
    def __init__(self, open_min: int, close_min: int, slot_minutes: int,
                 demand: Dict[Tuple[int, int], int]):
        self.open_min = open_min
        self.close_min = close_min
        self.slot_minutes = slot_minutes
        self.num_slots = (close_min - open_min) // slot_minutes
        # demand[(weekday, slot_idx)] -> headcount
        self.demand = demand

    def slot_start_time(self, slot_idx: int) -> time:
        m = self.open_min + slot_idx * self.slot_minutes
        return time(m // 60, m % 60)

    def get(self, weekday: int, slot_idx: int) -> int:
        return self.demand.get((weekday, slot_idx), 0)


def infer_demand(db: Session, department_id: int, ref_date: date,
                 cfg: SchedulerConfig) -> DemandGrid:
    start = ref_date - timedelta(weeks=cfg.HISTORY_WEEKS)
    rows: List[Shifts] = db.exec(
        select(Shifts).where(
            Shifts.DepartmentID == department_id,
            Shifts.Date >= start,
            Shifts.Date < ref_date,
        )
    ).all()

    if not rows:
        raise ValueError(
            f"Sin histórico de turnos para el departamento {department_id} "
            f"entre {start} y {ref_date}."
        )

    # Horario de apertura = min inicio / max fin observados, alineado a slots
    slot = cfg.SLOT_MINUTES
    open_min = min(_to_minutes(r.StartTime) for r in rows)
    close_min = max(_to_minutes(r.EndTime) for r in rows)
    open_min = (open_min // slot) * slot
    close_min = ((close_min + slot - 1) // slot) * slot
    num_slots = (close_min - open_min) // slot

    # headcount por (fecha, slot)
    per_date: Dict[date, List[int]] = defaultdict(lambda: [0] * num_slots)
    for r in rows:
        s = _to_minutes(r.StartTime)
        e = _to_minutes(r.EndTime)
        for idx in range(num_slots):
            slot_start = open_min + idx * slot
            if s <= slot_start < e:
                per_date[r.Date][idx] += 1

    # agrupar por día de la semana y quedarnos con la mediana por slot
    by_weekday: Dict[int, List[List[int]]] = defaultdict(list)
    for d, counts in per_date.items():
        by_weekday[d.weekday()].append(counts)

    demand: Dict[Tuple[int, int], int] = {}
    for weekday, day_counts in by_weekday.items():
        for idx in range(num_slots):
            vals = [c[idx] for c in day_counts]
            demand[(weekday, idx)] = int(round(statistics.median(vals))) if vals else 0

    return DemandGrid(open_min, close_min, slot, demand)
