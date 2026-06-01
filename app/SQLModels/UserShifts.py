import os
from sqlalchemy import Enum as SQLAlchemyEnum, select, func, text, Time, Column
from enum import Enum
from sqlmodel import SQLModel, Field, Session, Relationship, cast, or_, and_
from datetime import datetime, date, time, timedelta
from typing import Optional, Self

from . import Users
from .Departments import Departments
from utils.geo import haversine_distance
from typing import List

class ShiftStatus(str, Enum):
    Planned = "Planned"
    Confirmed = "Confirmed"
    Canceled = "Canceled"
    Completed = "Completed"
    Approved = "Approved"
    Rejected = "Rejected"

class Shifts(SQLModel, table=True):
    __tablename__ = "Shifts"

    ShiftID: int = Field(default=None, primary_key=True)
    UserID: int = Field(foreign_key="Users.UserID")
    DepartmentID: int = Field(foreign_key="Departments.DeptID")
    LocationID: Optional[int] = Field(foreign_key="Locations.LocationID", nullable=True)
    ScheduleID: Optional[int] = Field(foreign_key="Schedules.ScheduleID", nullable=True)
    Date: date
    StartTime: time
    EndTime: time
    BreakTime: float = Field(default=0.0)
    IsPublished: bool = Field(default=False)
    Status: ShiftStatus = Field(default=ShiftStatus.Planned)  # Planned, Confirmed, Canceled, Completed, Approved, Rejected
    CreatedBy: int = Field(foreign_key="Users.UserID")
    CreatedAt: datetime = Field(default_factory=datetime.now)
    UpdatedAt: datetime = Field(default_factory=datetime.now)

    user: "Users" = Relationship(back_populates="shifts", sa_relationship_kwargs={"foreign_keys": "Shifts.UserID"})
    creator: "Users" = Relationship(back_populates="created_shifts", sa_relationship_kwargs={"foreign_keys": "Shifts.CreatedBy"})
    department: "Departments" = Relationship(back_populates="shifts")
    location: "Locations" = Relationship(back_populates="shifts")
    schedule: "Schedules" = Relationship(back_populates="shifts")
    worklogs: List["WorkLogs"] = Relationship(back_populates="shift")

    @classmethod
    def get_actual(cls, db: Session,
                   user_id: int,
                   day: date = datetime.now().date(),
                   before: time = (datetime.now()-timedelta(minutes=os.environ.get("SHIFT_BEFORE_MINUTES_MARGIN",15))).time()) -> Optional[Self]:
        now = datetime.now().time()
        res = db.exec(select(cls).where(and_(cls.UserID == user_id,
                                         cls.Date == day,
                                        or_(cls.Status == ShiftStatus.Planned,
                                        cls.Status == ShiftStatus.Confirmed),
                                         or_(cls.StartTime >= before,
                                         and_(cls.StartTime <= now,cls.EndTime >= now)))).
                       order_by(func.abs(func.DATEDIFF(text("SECOND"),cls.StartTime, cast(str(datetime.now().time()), Time))))
                       ).first()
        return res[0] if res else None

    @classmethod
    def get(cls, db: Session, shift_id: int) -> Optional[Self]:
        return db.exec(select(cls).where(cls.ShiftID == shift_id)).first()


    def get_location_id(self, db: Session) -> None:
        if self.LocationID or (self.LocationID and not self.DepartmentID):
            return None
        self.LocationID = Departments.get(db, self.DepartmentID).LocationID
        return None

    def is_in_location(self, latitude: float, longitude: float, threshold_m: float = None) -> bool:
        #Calculate distance from self.location to (latitude, longitude) and if more than threshold in meters, return False else True
        if not self.location:
            return False
        if not threshold_m:
            threshold_m = self.location.ControlRadius if self.location.ControlRadius else 100

        return haversine_distance(self.location.Lat, self.location.Long, latitude, longitude) <= threshold_m


    @classmethod
    def create(cls, db: Session, **kwargs) -> Self:
        shift = cls(**kwargs)
        if shift.intersects(db):
            user = Users.get(db, shift.UserID)
            raise ValueError(f"El turno con fecha {shift.Date}, de {shift.StartTime.strftime("%H:%M")} a {shift.EndTime.strftime("%H:%M")} para el usuario {user.details.FirstName if user and user.details else shift.UserID} colisiona con otro turno existente.")
        shift.get_location_id(db)
        db.add(shift)
        db.commit()
        db.refresh(shift)
        return shift

    def total_hours(self):
        return (datetime.combine(date.today(), self.EndTime) - datetime.combine(date.today(), self.StartTime)).seconds / 3600

    def update(self, db: Session, **kwargs) -> 'Shifts':
        """Update shift attributes"""
        for key, value in kwargs.items():
            if value is None:
                continue
            # Update the UpdatedAt timestamp
            if key == 'UpdatedAt':
                value = datetime.now()
            setattr(self, key, value)
        
        # Always update the timestamp when modifying
        self.UpdatedAt = datetime.now()
        
        # Recalculate location if department changed
        if 'DepartmentID' in kwargs:
            self.get_location_id(db)

        if self.intersects(db):
            raise ValueError("Este turno colisiona con otro turno existente para el mismo usuario.")

        db.add(self)
        db.commit()
        db.refresh(self)
        return self
    
    def soft_delete(self, db: Session) -> 'Shifts':
        """Soft delete by setting status to Canceled"""
        if self.worklogs:
            raise ValueError("No se puede eliminar un turno que tiene registros de trabajo asociados.")
        self.Status = ShiftStatus.Canceled
        self.UpdatedAt = datetime.now()
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def intersects(self, db: Session):
        """Check if this shift intersects with any existing shifts for the same user"""
        return db.exec(
            select(Shifts).where(
                and_(Shifts.UserID == self.UserID,
            Shifts.Date == self.Date,
                    Shifts.ShiftID != self.ShiftID,  # Exclude itself
                    Shifts.Status != ShiftStatus.Canceled,
                    or_(
                        and_(Shifts.StartTime <= self.EndTime, Shifts.StartTime >= self.StartTime),
                        and_(Shifts.EndTime <= self.EndTime, Shifts.EndTime >= self.StartTime)

                        )
                    )
            )
        ).first() is not None