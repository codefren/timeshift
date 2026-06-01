import datetime
from typing import Self, List
from sqlmodel import SQLModel, Relationship, Field, Session, select
from sqlalchemy import Enum as SQLAlchemyEnum
from enum import Enum
from typing import Optional

class WeekDay(Enum):
    MONDAY = "Monday"
    TUESDAY = "Tuesday"
    WEDNESDAY = "Wednesday"
    THURSDAY = "Thursday"
    FRIDAY = "Friday"
    SATURDAY = "Saturday"
    SUNDAY = "Sunday"


class ScheduleTypes(Enum):
    FIXED = "Fixed"
    VARIABLE = "Variable"

class Schedules(SQLModel, table=True):
    __tablename__ = "Schedules"
    ScheduleID: int = Field(default=None, primary_key=True)
    ScheduleName: str = Field(max_length=50, unique=True)
    ScheduleType: str = Field(sa_column=SQLAlchemyEnum(ScheduleTypes, name="schedule_types"))
    StartDate: datetime.date = Field(default_factory=lambda: datetime.datetime.now())
    EndDate: datetime.date = Field(default_factory=lambda: datetime.datetime.now())
    CreatedBy: int = Field(foreign_key="Users.UserID")
    CreatedAt: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now())
    UpdatedAt: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(),
                                         sa_column_kwargs={"onupdate": lambda: datetime.datetime.now()})

    creator: "Users" = Relationship(back_populates="schedules_created")
    lines: List["ScheduleLines"] = Relationship(back_populates="schedule")
    totals: "ScheduleTotals" = Relationship(back_populates="schedule")
    shifts: List["Shifts"] = Relationship(back_populates="schedule", sa_relationship_kwargs={"lazy": True})

    @classmethod
    def get(cls, db: Session, schedule_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.ScheduleID == schedule_id)).first()

    @classmethod
    def get_by_name(cls, db: Session, schedule_name: str) -> Self | None:
        return db.exec(select(cls).where(cls.ScheduleName == schedule_name)).first()

    @classmethod
    def exists(cls, db: Session, schedule_name: str) -> bool:
        return db.exec(select(cls).where(cls.ScheduleName == schedule_name)).first() is not None

    def _create(self, db: Session) -> None:
        db.add(self)
        db.commit()
        db.refresh(self)

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.ScheduleID)
        if model_db is None:
            self._create(db)
            return self
        else:
            return model_db

    def update(self, db: Session, **kwargs) -> None:
        for key, value in kwargs.items():
            if value is None:
                continue
            setattr(self, key, value)
        db.commit()
        db.refresh(self)

    def delete(self, db: Session) -> None:
        db.delete(self)
        db.commit()

    def get_worklog_hours(self, start_date: datetime.date) -> float:
        week_day = start_date.strftime("%A")
        hours = 0
        for line in self.lines:
            if line.WeekDay == week_day:
                hours += line.DurationHours
        return hours

class ScheduleLines(SQLModel, table=True):
    __tablename__ = "ScheduleLines"
    ScheduleLineID: int = Field(primary_key=True)
    ScheduleID: int = Field(foreign_key="Schedules.ScheduleID", primary_key=True)
    WeekDay: str = Field(sa_column=SQLAlchemyEnum(WeekDay, name="week_days"))
    StartTime: datetime.time = Field(default_factory=lambda: datetime.datetime.now())
    EndTime: datetime.time = Field(default_factory=lambda: datetime.datetime.now())
    DurationHours: float = Field(default=0)

    schedule: "Schedules" = Relationship(back_populates="lines")

    @classmethod
    def get(cls, db: Session, schedule_id: int, schedule_line_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.ScheduleID == schedule_id, cls.ScheduleLineID == schedule_line_id)).first()

    @classmethod
    def get_lines(cls, db: Session, schedule_id: int) -> List[Self]:
        return db.exec(select(cls).where(cls.ScheduleID == schedule_id)).all()

    @classmethod
    def exists(cls, db: Session, schedule_id: int, schedule_line_id: int) -> bool:
        return db.exec(select(cls).where(cls.ScheduleID == schedule_id, cls.ScheduleLineID == schedule_line_id)).first() is not None
    
    @classmethod
    def exists_by_day(cls, db: Session, schedule_id: int, day: str) -> bool:
        return db.exec(select(cls).where(cls.ScheduleID == schedule_id, cls.WeekDay == day)).first() is not None

    @classmethod
    def get_by_day(cls, db: Session, schedule_id: int, day: str) -> Self | None:
        return db.exec(select(cls).where(cls.ScheduleID == schedule_id, cls.WeekDay == day)).first()

    def _create(self, db: Session) -> None:
        db.add(self)
        db.commit()
        db.refresh(self)

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.ScheduleID, self.ScheduleLineID)
        if model_db is None:
            self._create(db)
            return self
        else:
            return model_db

    def update(self, db: Session, **kwargs) -> None:
        for key, value in kwargs.items():
            if value is None:
                continue
            setattr(self, key, value)
        db.commit()
        db.refresh(self)

    def delete(self, db: Session) -> None:
        db.delete(self)
        db.commit()


class ScheduleTotals(SQLModel, table=True):
    __tablename__ = "ScheduleTotals"
    ScheduleID: int = Field(foreign_key="Schedules.ScheduleID", primary_key=True)
    TotalWeekWorkDays: int = Field(default=0)
    TotalWeekWorkHours: int = Field(default=0)

    schedule: "Schedules" = Relationship(back_populates="totals")

    @classmethod
    def get(cls, db: Session, schedule_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.ScheduleID == schedule_id)).first()

    @classmethod
    def exists(cls, db: Session, schedule_id: int) -> bool:
        return db.exec(select(cls).where(cls.ScheduleID == schedule_id)).first() is not None

    def _create(self, db: Session) -> None:
        db.add(self)
        db.commit()
        db.refresh(self)

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.ScheduleID)
        if model_db is None:
            self._create(db)
            return self
        else:
            return model_db

    def update(self, db: Session, **kwargs) -> None:
        for key, value in kwargs.items():
            if value is None:
                continue
            setattr(self, key, value)
        db.commit()
        db.refresh(self)

    def delete(self, db: Session) -> None:
        db.delete(self)
        db.commit()
