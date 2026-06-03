import datetime
from typing import Self, Optional, List, Sequence
from sqlmodel import SQLModel, Relationship, Field, Session, select, and_
from sqlalchemy import extract


class Holidays(SQLModel, table=True):
    __tablename__ = "Holidays"

    HolidayID: int | None = Field(default=None, primary_key=True)
    Name: str = Field(max_length=100)
    Date: datetime.date
    CompanyID: int | None = Field(default=None, foreign_key="Companies.CompanyID", nullable=True)
    LocationID: int | None = Field(default=None, foreign_key="Locations.LocationID", nullable=True)
    IsRecurring: bool = Field(default=False)
    CreatedBy: int = Field(foreign_key="Users.UserID")
    CreatedAt: datetime.datetime = Field(default_factory=datetime.datetime.now)
    UpdatedAt: datetime.datetime = Field(default_factory=datetime.datetime.now)

    creator: "Users" = Relationship()

    @classmethod
    def get(cls, db: Session, holiday_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.HolidayID == holiday_id)).first()

    @classmethod
    def get_for_date(cls, db: Session, date: datetime.date) -> Sequence[Self]:
        """Devuelve festivos que aplican a una fecha dada, incluyendo recurrentes."""
        results = db.exec(
            select(cls).where(
                (cls.Date == date) |
                (
                    (cls.IsRecurring == True) &  # noqa: E712
                    (extract("month", cls.Date) == date.month) &
                    (extract("day",   cls.Date) == date.day)
                )
            )
        ).all()
        return results

    @classmethod
    def is_holiday(cls, db: Session, date: datetime.date) -> bool:
        return len(cls.get_for_date(db, date)) > 0

    @classmethod
    def get_range(cls, db: Session,
                  date_from: datetime.date,
                  date_to: datetime.date,
                  company_id: int | None = None,
                  location_id: int | None = None) -> Sequence[Self]:
        q = select(cls).where(cls.Date.between(date_from, date_to))
        if company_id is not None:
            q = q.where((cls.CompanyID == company_id) | (cls.CompanyID == None))  # noqa: E711
        if location_id is not None:
            q = q.where((cls.LocationID == location_id) | (cls.LocationID == None))  # noqa: E711
        return db.exec(q).all()

    @classmethod
    def exists(cls, db: Session, holiday_id: int) -> bool:
        return db.exec(select(cls).where(cls.HolidayID == holiday_id)).first() is not None

    def _create(self, db: Session) -> Self:
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def create(self, db: Session) -> Self:
        return self._create(db)

    def update(self, db: Session, **kwargs) -> Self:
        for key, value in kwargs.items():
            if value is None:
                continue
            setattr(self, key, value)
        self.UpdatedAt = datetime.datetime.now()
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def delete(self, db: Session) -> None:
        db.delete(self)
        db.commit()


class AbsenceBalance(SQLModel, table=True):
    __tablename__ = "AbsenceBalance"

    UserID: int = Field(foreign_key="Users.UserID", primary_key=True)
    AbsenceTypeID: int = Field(foreign_key="AbsenceTypes.AbsenceTypeID", primary_key=True)
    Year: int = Field(primary_key=True)
    AccruedDays: float = Field(default=0)
    UsedDays: float = Field(default=0)
    PendingDays: float = Field(default=0)
    UpdatedAt: datetime.datetime = Field(default_factory=datetime.datetime.now)

    user: "Users" = Relationship(back_populates="absence_balances")
    absence_type: "AbsenceTypes" = Relationship()

    @property
    def remaining_days(self) -> float:
        return max(0.0, self.AccruedDays - self.UsedDays - self.PendingDays)

    @classmethod
    def get(cls, db: Session, user_id: int, absence_type_id: int, year: int) -> Self | None:
        return db.exec(select(cls).where(
            and_(cls.UserID == user_id,
                 cls.AbsenceTypeID == absence_type_id,
                 cls.Year == year)
        )).first()

    @classmethod
    def get_by_user(cls, db: Session, user_id: int, year: int | None = None) -> Sequence[Self]:
        q = select(cls).where(cls.UserID == user_id)
        if year is not None:
            q = q.where(cls.Year == year)
        return db.exec(q).all()

    @classmethod
    def get_or_create(cls, db: Session, user_id: int, absence_type_id: int, year: int) -> Self:
        existing = cls.get(db, user_id, absence_type_id, year)
        if existing:
            return existing
        new_balance = cls(UserID=user_id, AbsenceTypeID=absence_type_id, Year=year)
        db.add(new_balance)
        db.commit()
        db.refresh(new_balance)
        return new_balance

    def _create(self, db: Session) -> Self:
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def update(self, db: Session, **kwargs) -> Self:
        for key, value in kwargs.items():
            if value is None:
                continue
            setattr(self, key, value)
        self.UpdatedAt = datetime.datetime.now()
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def delete(self, db: Session) -> None:
        db.delete(self)
        db.commit()
