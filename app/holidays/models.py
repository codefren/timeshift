import datetime
from typing import Optional
from pydantic import BaseModel, Field


class HolidayCreateRequest(BaseModel):
    name: str = Field(max_length=100)
    date: datetime.date
    company_id: Optional[int] = None
    location_id: Optional[int] = None
    is_recurring: bool = False


class HolidayUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    date: Optional[datetime.date] = None
    company_id: Optional[int] = None
    location_id: Optional[int] = None
    is_recurring: Optional[bool] = None


class HolidayResponse(BaseModel):
    holiday_id: int
    name: str
    date: datetime.date
    company_id: Optional[int]
    location_id: Optional[int]
    is_recurring: bool
    created_by: int
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @classmethod
    def from_holiday(cls, h: "Holidays") -> "HolidayResponse":
        return cls(
            holiday_id=h.HolidayID,
            name=h.Name,
            date=h.Date,
            company_id=h.CompanyID,
            location_id=h.LocationID,
            is_recurring=h.IsRecurring,
            created_by=h.CreatedBy,
            created_at=h.CreatedAt,
            updated_at=h.UpdatedAt,
        )
