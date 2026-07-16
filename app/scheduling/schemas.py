"""Esquemas de entrada/salida del endpoint de generación de horarios."""
from datetime import date
from typing import List
from pydantic import BaseModel, Field


class GenerateScheduleRequest(BaseModel):
    department_id: int
    week_start: date  # se normaliza al lunes de esa semana


class ProposedShiftOut(BaseModel):
    user_id: int
    user_name: str
    date: date
    day_index: int          # 0..6 (Lun..Dom)
    start_time: str         # "HH:MM"
    end_time: str           # "HH:MM"


class HoursByUser(BaseModel):
    user_id: int
    user_name: str
    assigned_hours: float
    contract_hours: float


class DayCoverage(BaseModel):
    day_index: int          # 0..6 (Lun..Dom)
    demand_slots: int
    assigned_slots: int
    shortfall_slots: int


class ScheduleReport(BaseModel):
    coverage_pct: float
    demand_slots: int
    shortfall_slots: int
    coverage_by_day: List[DayCoverage]
    hours_by_user: List[HoursByUser]


class GenerateScheduleResponse(BaseModel):
    department_id: int
    week_start: date
    status: str                     # OPTIMAL / FEASIBLE / INFEASIBLE...
    slot_minutes: int
    shifts: List[ProposedShiftOut] = Field(default_factory=list)
    report: ScheduleReport
