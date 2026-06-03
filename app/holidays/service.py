import datetime
from typing import Sequence, Optional
from sqlmodel import Session

from SQLModels.Absences import Holidays


class HolidaysService:

    @staticmethod
    def get_by_id(db: Session, holiday_id: int) -> Optional[Holidays]:
        return Holidays.get(db, holiday_id)

    @staticmethod
    def list_holidays(db: Session,
                      date_from: datetime.date,
                      date_to: datetime.date,
                      company_id: int | None = None,
                      location_id: int | None = None) -> Sequence[Holidays]:
        return Holidays.get_range(db, date_from, date_to, company_id, location_id)

    @staticmethod
    def is_holiday(db: Session, date: datetime.date) -> bool:
        return Holidays.is_holiday(db, date)

    @staticmethod
    def create(db: Session,
               name: str,
               date: datetime.date,
               created_by: int,
               company_id: int | None = None,
               location_id: int | None = None,
               is_recurring: bool = False) -> Holidays:
        holiday = Holidays(
            Name=name,
            Date=date,
            CompanyID=company_id,
            LocationID=location_id,
            IsRecurring=is_recurring,
            CreatedBy=created_by,
        )
        return holiday.create(db)

    @staticmethod
    def update(db: Session, holiday_id: int, **kwargs) -> Optional[Holidays]:
        holiday = Holidays.get(db, holiday_id)
        if holiday is None:
            return None
        return holiday.update(db, **kwargs)

    @staticmethod
    def delete(db: Session, holiday_id: int) -> bool:
        holiday = Holidays.get(db, holiday_id)
        if holiday is None:
            return False
        holiday.delete(db)
        return True
