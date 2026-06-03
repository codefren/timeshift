import datetime
import logging
from typing import Sequence, Optional
from sqlmodel import Session, select

from SQLModels.Absences import Holidays, AbsenceBalance
from SQLModels.WorkLogs import (
    AbsenceTypes, AbsenceRequests, AbsenceReviews, AbsenceStatus,
    WorkLogs, WorkLogLines, WorkLogTotals,
)
from SQLModels.Users import Users, UserDetail

log = logging.getLogger(__name__)


class AbsencesService:

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def calculate_working_days(start_date: datetime.date,
                                end_date: datetime.date,
                                db: Session) -> float:
        """Cuenta días laborables (L-V) excluyendo festivos registrados."""
        count = 0
        current = start_date
        while current <= end_date:
            if current.weekday() < 5 and not Holidays.is_holiday(db, current):
                count += 1
            current += datetime.timedelta(days=1)
        return float(count)

    @staticmethod
    def _shift_and_hours_for_day(db: Session, user_id: int, date: datetime.date):
        """Devuelve (shift_id, hours) para un día de ausencia.

        Prioridad: turno asignado ese día → ContractWeeklyHours / 5 → 8h por defecto.
        Retornar el shift_id permite que create_totals reste correctamente las horas
        programadas y deje el balance del día en 0 (neutralidad).
        """
        from SQLModels.UserShifts import Shifts
        shift = Shifts.get_actual(db, user_id, day=date)
        if shift:
            s = shift[0] if isinstance(shift, list) else shift
            return s.ShiftID, s.total_hours()

        detail: Optional[UserDetail] = UserDetail.get(db, user_id)
        hours = detail.ContractWeeklyHours / 5.0 if detail and detail.ContractWeeklyHours else 8.0
        return None, hours

    @staticmethod
    def create_absence_worklog(db: Session,
                                user_id: int,
                                date: datetime.date,
                                absence_type_id: int) -> WorkLogs:
        """Crea un WorkLog de ausencia completo para un día.

        Si ya existe un WorkLog para ese usuario+fecha se omite.
        Vincula el turno del día (si existe) para que create_totals calcule
        BalanceScheduleHours = 0 (días de vacaciones no generan deuda de horas).
        """
        if WorkLogs.exists(db, user_id, date):
            log.debug(f"WorkLog already exists for user {user_id} on {date}, skipping")
            return WorkLogs.get_actual_worklog(db, user_id)

        shift_id, hours = AbsencesService._shift_and_hours_for_day(db, user_id, date)
        start_time = datetime.time(8, 0)
        end_dt = datetime.datetime.combine(date, start_time) + datetime.timedelta(hours=hours)
        end_time = end_dt.time()

        worklog = WorkLogs(UserID=user_id, LogDate=date, ShiftID=shift_id, IsFinished=False)
        worklog = worklog._create(db)

        line = WorkLogLines.create_line(
            db,
            WorkLogID=worklog.WorkLogID,
            WorkLogLineID=1,
            StartTime=start_time,
            EndTime=end_time,
            IsPause=True,
            AbsenceType=absence_type_id,
            LoggedHours=hours,
        )
        worklog.lines = [line]

        worklog.update(db, IsFinished=True)
        worklog.create_totals(db)

        log.debug(f"Absence worklog created for user {user_id} on {date} ({hours}h, shift={shift_id})")
        return worklog

    # ------------------------------------------------------------------ #
    # AbsenceTypes CRUD                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def list_types(db: Session) -> Sequence[AbsenceTypes]:
        return AbsenceTypes.get_all(db)

    @staticmethod
    def create_type(db: Session, type_name: str, is_counted: bool) -> AbsenceTypes:
        at = AbsenceTypes(TypeName=type_name, IsCounted=is_counted)
        at._create(db)
        return at

    @staticmethod
    def get_type(db: Session, absence_type_id: int) -> Optional[AbsenceTypes]:
        return AbsenceTypes.get(db, absence_type_id)

    # ------------------------------------------------------------------ #
    # AbsenceRequests CRUD                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def list_requests(db: Session,
                      user_id: int | None = None,
                      status: AbsenceStatus | None = None,
                      start_after: datetime.datetime | None = None,
                      start_before: datetime.datetime | None = None) -> Sequence[AbsenceRequests]:
        q = select(AbsenceRequests)
        if user_id is not None:
            q = q.where(AbsenceRequests.UserID == user_id)
        if status is not None:
            q = q.where(AbsenceRequests.Status == status)
        if start_after is not None:
            q = q.where(AbsenceRequests.StartTime >= start_after)
        if start_before is not None:
            q = q.where(AbsenceRequests.StartTime <= start_before)
        return db.exec(q).all()

    @staticmethod
    def create_request(db: Session,
                       user_id: int,
                       absence_type_id: int,
                       start_time: datetime.datetime,
                       end_time: datetime.datetime,
                       reason: str,
                       validate_balance: bool = True) -> AbsenceRequests:
        total_days = AbsencesService.calculate_working_days(
            start_time.date(), end_time.date(), db
        )

        if validate_balance:
            year = start_time.year
            balance = AbsenceBalance.get_or_create(db, user_id, absence_type_id, year)
            if balance.remaining_days < total_days:
                raise ValueError(
                    f"Saldo insuficiente: disponibles {balance.remaining_days:.1f} días, "
                    f"solicitados {total_days:.1f} días"
                )
            balance.update(db, PendingDays=balance.PendingDays + total_days)

        request = AbsenceRequests(
            UserID=user_id,
            AbsenceTypeID=absence_type_id,
            StartTime=start_time,
            EndTime=end_time,
            Reason=reason,
            TotalDays=total_days,
        )
        request._create(db)
        return request

    @staticmethod
    def get_request(db: Session, request_id: int) -> Optional[AbsenceRequests]:
        return AbsenceRequests.get(db, request_id)

    @staticmethod
    def cancel_request(db: Session, request_id: int, user_id: int) -> bool:
        """El empleado cancela su propia solicitud en estado Pending."""
        req = AbsenceRequests.get(db, request_id)
        if req is None or req.UserID != user_id:
            return False
        if req.Status != AbsenceStatus.PENDING:
            raise ValueError("Solo se pueden cancelar solicitudes en estado Pendiente")

        year = req.StartTime.year
        balance = AbsenceBalance.get(db, user_id, req.AbsenceTypeID, year)
        if balance:
            balance.update(db, PendingDays=max(0.0, balance.PendingDays - req.TotalDays))

        req.delete(db)
        return True

    # ------------------------------------------------------------------ #
    # Approval / Rejection                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def approve_request(db: Session,
                        request_id: int,
                        reviewer_id: int,
                        comments: str = "") -> AbsenceRequests:
        req = AbsenceRequests.get(db, request_id)
        if req is None:
            raise ValueError("Solicitud no encontrada")
        if req.Status != AbsenceStatus.PENDING:
            raise ValueError("Solo se pueden aprobar solicitudes en estado Pendiente")

        req.update(db, Status=AbsenceStatus.APPROVED)

        review = AbsenceReviews(
            RequestID=request_id,
            ReviewerID=reviewer_id,
            ReviewResult=AbsenceStatus.APPROVED,
            ReviewComments=comments,
        )
        review._create(db)

        year = req.StartTime.year
        balance = AbsenceBalance.get_or_create(db, req.UserID, req.AbsenceTypeID, year)
        balance.update(db,
                       UsedDays=balance.UsedDays + req.TotalDays,
                       PendingDays=max(0.0, balance.PendingDays - req.TotalDays))

        current = req.StartTime.date()
        end = req.EndTime.date()
        while current <= end:
            if current.weekday() < 5 and not Holidays.is_holiday(db, current):
                try:
                    AbsencesService.create_absence_worklog(db, req.UserID, current, req.AbsenceTypeID)
                except Exception as e:
                    log.warning(f"Could not create absence worklog for {current}: {e}")
            current += datetime.timedelta(days=1)

        log.info(f"Absence request {request_id} approved by {reviewer_id}")
        return req

    @staticmethod
    def reject_request(db: Session,
                       request_id: int,
                       reviewer_id: int,
                       comments: str = "") -> AbsenceRequests:
        req = AbsenceRequests.get(db, request_id)
        if req is None:
            raise ValueError("Solicitud no encontrada")
        if req.Status != AbsenceStatus.PENDING:
            raise ValueError("Solo se pueden rechazar solicitudes en estado Pendiente")

        req.update(db, Status=AbsenceStatus.REJECTED)

        review = AbsenceReviews(
            RequestID=request_id,
            ReviewerID=reviewer_id,
            ReviewResult=AbsenceStatus.REJECTED,
            ReviewComments=comments,
        )
        review._create(db)

        year = req.StartTime.year
        balance = AbsenceBalance.get(db, req.UserID, req.AbsenceTypeID, year)
        if balance:
            balance.update(db, PendingDays=max(0.0, balance.PendingDays - req.TotalDays))

        log.info(f"Absence request {request_id} rejected by {reviewer_id}")
        return req

    # ------------------------------------------------------------------ #
    # AbsenceBalance                                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def get_balance(db: Session,
                    user_id: int,
                    year: int | None = None) -> Sequence[AbsenceBalance]:
        return AbsenceBalance.get_by_user(db, user_id, year)

    @staticmethod
    def set_accrued_days(db: Session,
                         user_id: int,
                         absence_type_id: int,
                         year: int,
                         accrued_days: float) -> AbsenceBalance:
        balance = AbsenceBalance.get_or_create(db, user_id, absence_type_id, year)
        balance.update(db, AccruedDays=accrued_days)
        return balance
