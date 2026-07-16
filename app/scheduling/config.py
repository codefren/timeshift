"""Parámetros por defecto del auto-scheduler."""
from dataclasses import dataclass


@dataclass
class SchedulerConfig:
    SLOT_MINUTES: int = 30            # granularidad temporal
    MIN_SHIFT_HOURS: float = 3.0      # duración mínima de un tramo
    MAX_SHIFT_HOURS: float = 8.0      # duración máxima de un tramo
    MAX_DAILY_HOURS: float = 9.0      # tope total de horas por empleado y día
    MAX_SHIFTS_PER_DAY: int = 2       # turnos por día (partido)
    CONTRACT_TOLERANCE: float = 0.10  # margen sobre horas de contrato (informativo)
    HISTORY_WEEKS: int = 12           # semanas de histórico para inferir demanda
    MAX_SOLVE_SECONDS: float = 20.0

    # Pesos del objetivo (cobertura pesa mucho más que el resto)
    W_SHORTFALL: int = 100            # penaliza no cubrir demanda
    W_EXCESS: int = 4                 # penaliza exceso de personal
    W_CONTRACT: int = 8              # penaliza desviación de horas de contrato

    @property
    def slot_hours(self) -> float:
        return self.SLOT_MINUTES / 60.0

    @property
    def min_slots(self) -> int:
        return int(round(self.MIN_SHIFT_HOURS * 60 / self.SLOT_MINUTES))

    @property
    def max_slots(self) -> int:
        return int(round(self.MAX_SHIFT_HOURS * 60 / self.SLOT_MINUTES))

    @property
    def max_daily_slots(self) -> int:
        return int(round(self.MAX_DAILY_HOURS * 60 / self.SLOT_MINUTES))


DEFAULT = SchedulerConfig()
