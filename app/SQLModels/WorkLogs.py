import datetime
import json

import pandas as pd
from pydantic.types import PastDate
from math import ceil
from typing import Self, List, Sequence, Optional, Tuple, Dict, Any
from sqlalchemy.orm import aliased
from pydantic import BaseModel
from sqlmodel import SQLModel, Relationship, Field, Session, select, asc
from sqlalchemy import Enum as SQLAlchemyEnum, and_, Select, func, Text
from enum import Enum
from pydantic.types import datetime as datetype
from .UserShifts import Shifts
import logging

log = logging.getLogger(__name__)

class WorkLogsList(BaseModel):
    worklogs: Sequence["WorkLogs"]
    pages: int
    total: int

class WorkLogs(SQLModel, table=True):
    __tablename__ = "WorkLogs"
    WorkLogID: int = Field(default=None, primary_key=True)
    UserID: int = Field(foreign_key="Users.UserID")
    LogDate: datetime.date = Field(default_factory=lambda: datetime.datetime.now())
    ShiftID: Optional[int] = Field(foreign_key="Shifts.ShiftID", nullable=True)
    IsFinished: bool = Field(default=False)
    IsApproved: bool = Field(default=False)

    user: "Users" = Relationship(back_populates="worklogs")
    lines: List["WorkLogLines"] = Relationship(back_populates="worklog")
    shift: "Shifts" = Relationship(back_populates="worklogs")
    totals: "WorkLogTotals" = Relationship(back_populates="worklog")
    operations: List["WorkLogOperations"] = Relationship(back_populates="worklog")

    @classmethod
    def get(cls, db: Session, work_log_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.WorkLogID == work_log_id)).first()

    @classmethod
    def get_list_select(cls, params: "Pagination", filters: "WorkLogFilters" = None, count_only: bool = False) -> Select:
        if not count_only:
            c = select(cls).order_by(params.order(getattr(cls, filters.sort_by, "WorkLogID")))
        else:
            c = select(func.count(cls.WorkLogID))
        if not filters:
            return c

        if filters.user_id is not None:
            c = c.where(cls.UserID == filters.user_id)

        if filters.log_date is not None:
            c = c.where(cls.LogDate == filters.log_date)

        if filters.log_before is not None:
            c = c.where(cls.LogDate <= filters.log_before)
        if filters.log_after is not None:
            c = c.where(cls.LogDate >= filters.log_after)

        min_line = aliased(WorkLogLines)
        max_line = aliased(WorkLogLines)

        if filters.start_time_before is not None:
            subq1 = select(min_line.StartTime) \
                .filter(min_line.WorkLogID == cls.WorkLogID) \
                .order_by(asc(min_line.WorkLogLineID)) \
                .limit(1).correlate(cls).scalar_subquery()
            c = c.where(
                    filters.start_time_before >= subq1
            )
        if filters.start_time_after is not None:
            subq1 = select(min_line.StartTime) \
                .filter(min_line.WorkLogID == cls.WorkLogID) \
                .order_by(asc(min_line.WorkLogLineID)) \
                .limit(1).correlate(cls).scalar_subquery()
            c = c.where(
                filters.start_time_after <= subq1
            )
        if filters.final_time_before is not None:
            subq1 = select(max_line.EndTime) \
                .filter(max_line.WorkLogID == cls.WorkLogID) \
                .order_by(asc(max_line.WorkLogLineID)) \
                .limit(1).correlate(cls).scalar_subquery()
            c = c.where(
                filters.final_time_before >= subq1
            )
        if filters.final_time_after is not None:
            subq1 = select(max_line.EndTime) \
                .filter(max_line.WorkLogID == cls.WorkLogID) \
                .order_by(asc(max_line.WorkLogLineID)) \
                .limit(1).correlate(cls).scalar_subquery()
            c = c.where(
                filters.final_time_after <= subq1
            )
        if filters.is_finished is not None:
            c = c.where(cls.IsFinished == filters.is_finished)
        if filters.is_approved is not None:
            c = c.where(cls.IsApproved == filters.is_approved)
        if filters.department_id is not None:
            c = c.where(cls.shift.DepartmentID == filters.department_id)
        if filters.has_shift is not None:
            c = c.where(cls.ShiftID is filters.has_shift)


        return c

    @classmethod
    def list(cls, db: Session, params: "Pagination", filters: "WorkLogFilters" = None) -> WorkLogsList:
        query = cls.get_list_select(params, filters)
        count_query = cls.get_list_select(params, filters, count_only=True)
        count = db.exec(count_query).one()
        query = query.offset((params.page - 1) * params.size).limit(params.size)
        pages = ceil(count / params.size)
        if params.page > pages:
            return WorkLogsList(worklogs=[], pages=pages, total=count   )
        items = db.exec(query).unique().all()
        return WorkLogsList(worklogs=items, pages=pages, total=count)

    @classmethod
    def list_month(cls, db: Session, user_id: int) -> WorkLogsList:
        month_ago = datetime.datetime.now() - datetime.timedelta(days=30)
        query = db.exec(select(cls).where(
            cls.UserID == user_id,
            cls.LogDate > month_ago.date()
        ))
        items = query.all()
        return WorkLogsList(worklogs=items, pages=1, total=len(items))

    @classmethod
    def exists(cls, db: Session, user_id: int, log_date: datetime.date) -> bool:
        return db.exec(select(cls).where(
            and_(cls.UserID == user_id, cls.LogDate == log_date)
        )).first() is not None

    def _create(self, db: Session) -> Self:
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.WorkLogID)
        if model_db is None:
            return self._create(db)
        else:
            return model_db

    def update(self, db: Session, **kwargs) -> Self:
        for key, value in kwargs.items():
            if value is None:
                continue
            setattr(self, key, value)
        db.commit()
        db.refresh(self)
        return self

    def delete(self, db: Session) -> None:
        db.delete(self)
        db.commit()

    def create_totals(self, db: Session) -> "WorkLogTotals":
        total = WorkLogTotals(WorkLogID=self.WorkLogID,
                              **WorkLogTotals.calculate_hours_from_workloglines(self.lines, self.LogDate),
                              )
        total.BalanceScheduleHours -= self.shift.total_hours() if self.shift and total.EndTime else 0
        return total.create(db)

    @classmethod
    def start_worklog(cls,db: Session,
                      user_id: int,
                      shift_id: Optional[int],
                      start_time: datetime.datetime = datetime.datetime.now()) -> Self:
        worklog = cls(UserID=user_id, ShiftID=shift_id, LogDate=start_time.date())
        worklog = worklog._create(db)
        worklog.lines = [WorkLogLines.create_line(db, WorkLogID=worklog.WorkLogID, StartTime=start_time.time(), WorkLogLineID=1)]
        return worklog

    @classmethod
    def create_worklog(cls, db: Session,
                       user_id: int,
                       shift_id: int = None,
                    log_date: datetime.datetime = datetime.datetime.now()) -> Self:
        exists = cls.get_actual_worklog(db, user_id)
        if exists is not None:
            return exists
        if shift_id is None:
            shift_id = Shifts.get_actual(db, user_id)
            shift_id = shift_id[0].ShiftID if isinstance(shift_id, list) else shift_id.ShiftID if shift_id else None

        return cls.start_worklog(db, user_id, shift_id, log_date)

    @classmethod
    def get_actual_worklog(cls, db: Session, user_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.UserID == user_id, cls.IsFinished == False)).first()

    @classmethod
    def is_working(cls, db: Session, user_id: int) -> bool:
        return cls.get_actual_worklog(db, user_id) is not None

    @classmethod
    def is_working_in(cls, db: Session, user_id: int, department_id: int) -> bool:
        worklog = cls.get_actual_worklog(db, user_id)
        if worklog is None:
            return False
        if worklog.shift and worklog.shift.DepartmentID == department_id:
            return True
        return False

    @classmethod
    def pause_worklog(cls, db: Session,
                      worklog_id: int,
                      user_id: int,
                      pause_time: datetime.time = datetime.datetime.now().time(),
                      absence_type: int = None,
                      ) -> Self | None:
        worklog = cls.get(db, worklog_id)
        if worklog is not None and worklog.UserID == user_id:
            last_l = worklog.lines[-1]
            if last_l.IsPause:
                return None
            last_l.finish(db, start_date=worklog.LogDate, end_time=pause_time)
            worklog.lines.append(WorkLogLines.create_line(db,
                                                          WorkLogID=worklog_id,
                                                          StartTime=pause_time,
                                                          WorkLogLineID=last_l.WorkLogLineID + 1,
                                                          IsPause=True,
                                                          AbsenceType=absence_type))
            return worklog
        return None

    @classmethod
    def resume_worklog(cls, db: Session,
                       worklog_id: int,
                       user_id: int,
                       resume_time: datetime.time = datetime.datetime.now().time(),
                       ) -> Self | None:
        worklog = cls.get(db, worklog_id)
        if worklog is not None and worklog.UserID == user_id:
            last_l = worklog.lines[-1]
            if not last_l.IsPause:
                return None
            last_l.finish(db, start_date=worklog.LogDate, end_time=resume_time)
            worklog.lines.append(WorkLogLines.create_line(db, WorkLogID=worklog_id, StartTime=resume_time,
                                                          WorkLogLineID=last_l.WorkLogLineID + 1,))
        return worklog

    @classmethod
    def finish_worklog(cls, db: Session,
                            worklog_id: int,
                            user_id: int,
                            end_time: Optional[datetime.time] = datetime.datetime.now().time()) -> Self | None:
          worklog = cls.get(db, worklog_id)
          if worklog is not None and worklog.UserID == user_id:
                if worklog.IsFinished:
                    return None
                last_l = worklog.lines[-1]
                last_l.finish(db, start_date=worklog.LogDate, end_time=end_time) if last_l.EndTime is None else None
                worklog = worklog.update(db, IsFinished=True)
                worklog.create_totals(db)
          return worklog

    def complete_removal(self, db: Session):
        """
        Completes the removal of a worklog by deleting all associated lines and operations.
        """
        for line in self.lines:
            line.delete(db)
        for operation in self.operations:
            operation.delete(db)
        self.totals.delete(db) if self.totals else None
        self.shift = None  # Clear the shift relationship
        db.delete(self)
        db.commit()

    @classmethod
    def get_worked_hours(cls, db: Session, start_date: PastDate, end_date: PastDate, user_id: int | List[int] = None) -> pd.DataFrame:
        q = select(cls.UserID,
                   func.sum(WorkLogTotals.TotalWorkedHours).label("WorkedHours"),
                   func.sum(WorkLogTotals.TotalPauseCountedHours).label("PausedCountedHours"),
                   func.sum(WorkLogTotals.TotalPauseUncountedHours).label("PausedUncountedHours")
                   ).join(WorkLogTotals, cls.WorkLogID == WorkLogTotals.WorkLogID).where(
            cls.LogDate.between(start_date, end_date),
        ).group_by(
            cls.UserID
        )

        if user_id:
            q = q.where(cls.UserID == user_id) if isinstance(user_id, int) else q.where(cls.UserID.in_(user_id))

        res = db.exec(q).all()
        df = pd.DataFrame(res,
                          columns=["UserID", "WorkedHours", "PausedCountedHours", "PausedUncountedHours"])
        return df


    @classmethod
    def get_daily_worked_hours(cls, db: Session, start_date: PastDate, end_date: PastDate, user_id: int | List[int] = None) -> pd.DataFrame:
        """
        Obtiene las horas trabajadas agrupadas diáriamente por el usuario en un rango de fechas específico.

        Args:
            db: Sesión de base de datos
            start_date: Fecha de inicio del rango
            end_date: Fecha de fin del rango
        Returns:
            pd.DataFrame: DataFrame con las horas trabajadas por día
        """

        q = select(cls.UserID,
                   cls.LogDate.label("Period"),
                   func.sum(WorkLogTotals.TotalWorkedHours).label("WorkedHours"),
                   func.sum(WorkLogTotals.TotalPauseCountedHours).label("PausedCountedHours"),
                   func.sum(WorkLogTotals.TotalPauseUncountedHours).label("PausedUncountedHours")
                   ).join(WorkLogTotals, cls.WorkLogID == WorkLogTotals.WorkLogID).where(
            cls.LogDate.between(start_date, end_date),
        ).group_by(
            cls.UserID, cls.LogDate
        )

        if user_id:
            q = q.where(cls.UserID == user_id) if isinstance(user_id, int) else q.where(cls.UserID.in_(user_id))

        res = db.exec(q).all()
        df = pd.DataFrame(res, columns=["UserID","Period","WorkedHours", "PausedCountedHours","PausedUncountedHours"])
        return df

    @classmethod
    def get_monthly_worked_hours_by_user(cls, db: Session, start_date: PastDate, end_date: PastDate,
                                         user_id: int | List[int] = None) -> pd.DataFrame:
        """
        Obtiene las horas trabajadas por usuario agrupadas por mes en un rango de fechas específico.
        Si un mes está parcialmente incluido (ej: del 15 al 30 de abril), solo cuenta las horas
        trabajadas en ese período.

        Args:
            db: Sesión de base de datos
            start_date: Fecha de inicio del período
            end_date: Fecha de fin del período
            user_id: ID de usuario o lista de IDs (opcional)

        Returns:
            DataFrame con las columnas: UserID, Period, WorkedHours, PausedCountedHours, PausedUncountedHours
            donde Period es una cadena en formato 'YYYY-MM'
        """

        log.debug(
            f"Getting monthly worked hours from {start_date} to {end_date}")

        # Obtenemos las horas trabajadas por semana dentro del rango
        df = cls.get_daily_worked_hours(db, start_date, end_date, user_id)

        if not isinstance(df, pd.DataFrame) or df.empty:
            # Si no hay resultados, devolvemos un DataFrame vacío con la estructura correcta
            return pd.DataFrame(
                columns=["UserID", "Period", "WorkedHours", "PausedCountedHours", "PausedUncountedHours"])

        # Creamos la columna de período mensual en formato 'YYYY-MM'
        df['Month'] = pd.to_datetime(df['Period']).dt.month
        df['Year'] = pd.to_datetime(df['Period']).dt.year
        df['Period'] = df['Year'].astype(str) + '-' + df['Month'].astype(str).str.zfill(2)

        # Agrupamos por usuario y período mensual
        df_grouped = df.groupby(['UserID', 'Period']).agg({
            'WorkedHours': 'sum',
            'PausedCountedHours': 'sum',
            'PausedUncountedHours': 'sum'
        }).reset_index()

        log.debug(f"Monthly worked hours result: {df_grouped}")
        return df_grouped



class OperationTypes(str, Enum):
    START = "Start"
    PAUSE = "Pause"
    RESUME = "Resume"
    END = "End"

class WorkLogOperations(SQLModel, table=True):
    __tablename__ = 'WorkLogOperations'
    WorkLogID: int = Field(foreign_key="WorkLogs.WorkLogID", primary_key=True)
    Operation: OperationTypes = Field(default=OperationTypes.START, nullable=False, primary_key=True)
    Lat: float = Field(nullable=False)
    Long: float = Field(nullable=False)
    IpAddr: str = Field(nullable=False, max_length=15)
    CreatedAt: datetime.datetime = Field(default_factory=datetime.datetime.now)

    worklog: "WorkLogs" = Relationship(back_populates="operations")

    @classmethod
    def get(cls, db: Session, work_log_id: int, operation: Enum = OperationTypes.START) -> Optional[Self]:
        return db.exec(select(cls).where(cls.WorkLogID == work_log_id, cls.Operation==operation)).first()

    def _create(self, db: Session) -> Self:
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.WorkLogID, self.Operation)
        if model_db is None:
            return self._create(db)
        else:
            return model_db

    def delete(self, db: Session) -> None:
        db.delete(self)
        db.commit()



class WorkLogLines(SQLModel, table=True):
    __tablename__ = "WorkLogLines"
    WorkLogLineID: int = Field(primary_key=True)
    WorkLogID: int = Field(foreign_key="WorkLogs.WorkLogID", primary_key=True)
    StartTime: datetime.time = Field(default_factory=lambda: datetime.datetime.now().time())
    EndTime: datetime.time | None = Field(default = None)
    IsPause: bool = Field(default=False)
    AbsenceType: int | None = Field(default=None, foreign_key="AbsenceTypes.AbsenceTypeID")
    LoggedHours: float | None = Field(default=None)

    worklog: "WorkLogs" = Relationship(back_populates="lines")
    absence: "AbsenceTypes" = Relationship(back_populates="workloglines")

    @classmethod
    def get(cls, db: Session, work_log_id: int, work_log_line_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.WorkLogID == work_log_id, cls.WorkLogLineID == work_log_line_id)).first()

    @classmethod
    def get_lines(cls, db: Session, work_log_id: int) -> Sequence[Self] | None:
        return db.exec(select(cls).where(cls.WorkLogID == work_log_id)).all()

    @classmethod
    def exists(cls, db: Session, work_log_id: int, start_time: datetime.time) -> bool:
        return db.exec(select(cls).where(
            and_(cls.WorkLogID == work_log_id, cls.StartTime == start_time)
        )).first() is not None

    @classmethod
    def create_line(cls, db: Session, **kwargs) -> Self:
        return cls(**kwargs)._create(db)

    def _create(self, db: Session) -> Self:
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.WorkLogLineID, self.WorkLogID)
        if model_db is None:
            return self._create(db)
        else:
            return model_db

    def update(self, db: Session, **kwargs) -> Self:
        for key, value in kwargs.items():
            if value is None:
                continue
            setattr(self, key, value)
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def delete(self, db: Session) -> None:
        db.delete(self)
        db.commit()

    def calculate_loghours(self, start_date: datetime.date, endtime: datetime.time()) -> float:
        diff = (datetime.datetime.combine(datetime.datetime.now().date(), endtime) -
                datetime.datetime.combine(start_date, self.StartTime)) if endtime else None
        return (diff.total_seconds() / 3600) if diff else 0

    def time_to_compute(self) -> float:
        return self.LoggedHours if not self.IsPause else (
            self.LoggedHours if self.absence and self.absence.IsCounted else 0
        )

    def finish(self, db: Session, start_date: datetime.date, end_time: Optional[datetime.time]) -> Self:
        return self.update(db, EndTime=end_time, LoggedHours=self.calculate_loghours(start_date, end_time))

class WorkLogTotals(SQLModel, table=True):
    __tablename__ = "WorkLogTotals"
    WorkLogID: int = Field(foreign_key="WorkLogs.WorkLogID", primary_key=True)
    StartTime: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now())
    EndTime: Optional[datetime.datetime | None] = Field(None,nullable=True)
    TotalWorkedHours: float = Field(default=0)
    TotalPauseCountedHours: float = Field(default=0)
    TotalPauseUncountedHours: float = Field(default=0)
    BalanceScheduleHours: float = Field(default=0)

    worklog: "WorkLogs" = Relationship(back_populates="totals")

    @classmethod
    def get(cls, db: Session, work_log_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.WorkLogID == work_log_id)).first()

    @classmethod
    def exists(cls, db: Session, work_log_id: int) -> bool:
        return db.exec(select(cls).where(
            cls.WorkLogID == work_log_id
        )).first() is not None

    @classmethod
    def get_worked_hours_by_user(cls, db: Session, start_date: PastDate, end_date: PastDate, user_id: int | List[int] = None) -> Sequence[Tuple[int, float, float, float]]:
        q = select(WorkLogs.UserID, func.sum(cls.TotalWorkedHours).label("WorkedHours"), func.sum(cls.TotalPauseCountedHours).label("PausedCountedHours"), func.sum(cls.TotalPauseUncountedHours).label("PausedUncountedHours")).where(
            and_(WorkLogs.LogDate >= start_date, WorkLogs.LogDate <= end_date)
        ).join(WorkLogs).group_by(WorkLogs.UserID)
        if user_id is not None:
            q = q.where(WorkLogs.UserID.in_(user_id)) if isinstance(user_id, list) else q.where(WorkLogs.UserID == user_id)
        return db.exec(q).all()

    def _create(self, db: Session) -> None:
        print(self)
        db.add(self)
        db.commit()
        db.refresh(self)

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.WorkLogID)
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

    @classmethod
    def calculate_hours_from_workloglines(cls, lines: List[WorkLogLines], start_date: datetime.date) -> dict:
        start_time = datetime.datetime.now()
        end_time = datetime.datetime.now()
        total_worked_time = 0
        total_pause_counted_time = 0
        total_pause_uncounted_time = 0
        balance_time = 0
        for line in lines:
            if line.IsPause:
                if line.absence and line.absence.IsCounted:
                    total_pause_counted_time += line.LoggedHours
                else:
                    total_pause_uncounted_time += line.LoggedHours
            else:
                total_worked_time += line.LoggedHours
            start_time = min(start_time, datetime.datetime.combine(start_date, line.StartTime))
            end_time = max(end_time, datetime.datetime.combine(datetime.datetime.now().date(), line.EndTime)) if line.EndTime else end_time
            balance_time += line.time_to_compute()
        if lines[-1].EndTime is None:
            end_time = None

        return {
            "StartTime": start_time,
            "EndTime": end_time,
            "TotalWorkedHours": total_worked_time,
            "TotalPauseCountedHours": total_pause_counted_time,
            "TotalPauseUncountedHours": total_pause_uncounted_time,
            "BalanceScheduleHours": balance_time if end_time else 0
        }


class AbsenceTypes(SQLModel, table=True):
    __tablename__ = "AbsenceTypes"

    AbsenceTypeID: int | None = Field(default=None, primary_key=True)
    TypeName: str = Field(max_length=50)
    IsCounted: bool = Field(default=True)

    workloglines: List["WorkLogLines"] = Relationship(back_populates="absence")

    @classmethod
    def get(cls, db: Session, absence_type_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.AbsenceTypeID == absence_type_id)).first()

    @classmethod
    def get_all(cls, db: Session) -> Sequence[Self] | None:
        return db.exec(select(cls)).all()

    @classmethod
    def exists(cls, db: Session, absence_type_id: int) -> bool:
        return db.exec(select(cls).where(
            cls.AbsenceTypeID == absence_type_id
        )).first() is not None

    def _create(self, db: Session) -> None:
        db.add(self)
        db.commit()
        db.refresh(self)

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.AbsenceTypeID)
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


class AbsenceStatus(str, Enum):
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


class AbsenceRequests(SQLModel, table=True):
    __tablename__ = "AbsenceRequests"

    RequestID: int | None = Field(default=None, primary_key=True)
    UserID: int = Field(foreign_key="Users.UserID")
    AbsenceTypeID: int = Field(foreign_key="AbsenceTypes.AbsenceTypeID")
    RequestDate: datetime.date = Field(default_factory=datetime.datetime.now)
    StartTime: datetime.datetime = Field()
    EndTime: datetime.datetime = Field()
    Reason: str = Field(max_length=255, default="")
    Status: AbsenceStatus = Field(default=AbsenceStatus.PENDING)
    TotalDays: float = Field(default=0)

    user: "Users" = Relationship(back_populates="absence_requests")
    review: "AbsenceReviews" = Relationship(back_populates="request")
    absence_type: "AbsenceTypes" = Relationship()

    @classmethod
    def get(cls, db: Session, request_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.RequestID == request_id)).first()

    @classmethod
    def exists(cls, db: Session, request_id: int) -> bool:
        return db.exec(select(cls).where(
            cls.RequestID == request_id
        )).first() is not None

    def _create(self, db: Session) -> None:
        db.add(self)
        db.commit()
        db.refresh(self)

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.RequestID) if self.RequestID is not None else None
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


class AbsenceReviews(SQLModel, table=True):
    __tablename__ = "AbsenceReviews"

    RequestID: int = Field(foreign_key="AbsenceRequests.RequestID", primary_key=True)
    ReviewerID: int = Field(foreign_key="Users.UserID")
    ReviewDate: datetime.datetime = Field(default_factory=datetime.datetime.now)
    ReviewResult: AbsenceStatus = Field(default=AbsenceStatus.PENDING)
    ReviewComments: str = Field(max_length=255, default="")

    request: "AbsenceRequests" = Relationship(back_populates="review")
    reviewer: "Users" = Relationship()

    @classmethod
    def get(cls, db: Session, request_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.RequestID == request_id)).first()

    @classmethod
    def exists(cls, db: Session, request_id: int) -> bool:
        return db.exec(select(cls).where(
            cls.RequestID == request_id
        )).first() is not None

    def _create(self, db: Session) -> None:
        db.add(self)
        db.commit()
        db.refresh(self)

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.RequestID)
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


# Audit Trail Models

class AuditActionType(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    ADD_LINE = "ADD_LINE"
    REMOVE_LINE = "REMOVE_LINE"

class WorkLogAudit(SQLModel, table=True):
    __tablename__ = "WorkLogAudit"
    
    AuditID: int = Field(default=None, primary_key=True)
    WorkLogID: int = Field(foreign_key="WorkLogs.WorkLogID")
    ModifiedByUserID: int = Field(foreign_key="Users.UserID")
    ModificationDate: datetime.datetime = Field(default_factory=datetime.datetime.now)
    ActionType: AuditActionType = Field(default=AuditActionType.UPDATE)
    FieldName: str = Field(max_length=100)  # Field that was changed
    OldValue: str = Field(nullable=True, max_length=250)  # JSON string of old value
    NewValue: str = Field(nullable=True, max_length=250)  # JSON string of new value
    Reason: str = Field(max_length=500, default="")  # Optional reason for change
    
    worklog: "WorkLogs" = Relationship()
    modified_by: "Users" = Relationship()

    @classmethod
    def create_audit_record(cls, db: Session, worklog_id: int, modified_by_user_id: int, 
                           action_type: AuditActionType, field_name: str, 
                           old_value: Any = None, new_value: Any = None, reason: str = "") -> Self:
        """Create an audit record for worklog changes"""
        audit = cls(
            WorkLogID=worklog_id,
            ModifiedByUserID=modified_by_user_id,
            ActionType=action_type,
            FieldName=field_name,
            OldValue=json.dumps(old_value, default=str) if old_value is not None else None,
            NewValue=json.dumps(new_value, default=str) if new_value is not None else None,
            Reason=reason
        )
        db.add(audit)
        db.commit()
        db.refresh(audit)
        return audit

    @classmethod
    def get_worklog_history(cls, db: Session, worklog_id: int) -> Sequence[Self]:
        """Get all audit records for a specific worklog"""
        return db.exec(
            select(cls)
            .where(cls.WorkLogID == worklog_id)
            .order_by(cls.ModificationDate.desc())
        ).all()

class WorkLogLineAudit(SQLModel, table=True):
    __tablename__ = "WorkLogLineAudit"
    
    AuditID: int = Field(default=None, primary_key=True)
    WorkLogID: int = Field(foreign_key="WorkLogs.WorkLogID")
    WorkLogLineID: Optional[int] = Field(nullable=True)  # Nullable for deleted lines
    ModifiedByUserID: int = Field(foreign_key="Users.UserID")
    ModificationDate: datetime.datetime = Field(default_factory=datetime.datetime.now)
    ActionType: AuditActionType = Field(default=AuditActionType.UPDATE)
    FieldName: str = Field(max_length=100)  # Field that was changed
    OldValue: str = Field(nullable=True, max_length=250)  # JSON string of old value
    NewValue: str = Field(nullable=True, max_length=250)  # JSON string of new value
    Reason: str = Field(max_length=500, default="")  # Optional reason for change
    
    worklog: "WorkLogs" = Relationship()
    modified_by: "Users" = Relationship()

    @classmethod
    def create_audit_record(cls, db: Session, worklog_id: int, worklog_line_id: int, 
                           modified_by_user_id: int, action_type: AuditActionType, 
                           field_name: str, old_value: Any = None, new_value: Any = None, 
                           reason: str = "") -> Self:
        """Create an audit record for worklog line changes"""
        audit = cls(
            WorkLogID=worklog_id,
            WorkLogLineID=worklog_line_id,
            ModifiedByUserID=modified_by_user_id,
            ActionType=action_type,
            FieldName=field_name,
            OldValue=json.dumps(old_value, default=str) if old_value is not None else None,
            NewValue=json.dumps(new_value, default=str) if new_value is not None else None,
            Reason=reason
        )
        db.add(audit)
        db.commit()
        db.refresh(audit)
        return audit

    @classmethod
    def get_line_history(cls, db: Session, worklog_id: int, worklog_line_id: int = None) -> Sequence[Self]:
        """Get all audit records for worklog lines"""
        query = select(cls).where(cls.WorkLogID == worklog_id)
        if worklog_line_id is not None:
            query = query.where(cls.WorkLogLineID == worklog_line_id)
        return db.exec(query.order_by(cls.ModificationDate.desc())).all()


