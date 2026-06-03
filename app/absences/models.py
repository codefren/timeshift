import datetime
from typing import Optional
from pydantic import BaseModel, Field

from SQLModels.WorkLogs import AbsenceStatus


class AbsenceTypeCreateRequest(BaseModel):
    type_name: str = Field(max_length=50)
    is_counted: bool = True


class AbsenceTypeResponse(BaseModel):
    AbsenceTypeID: int
    TypeName: str
    IsCounted: bool

    @classmethod
    def from_type(cls, at: "AbsenceTypes") -> "AbsenceTypeResponse":
        return cls(
            AbsenceTypeID=at.AbsenceTypeID,
            TypeName=at.TypeName,
            IsCounted=at.IsCounted,
        )


class AbsenceRequestCreate(BaseModel):
    absence_type_id: int
    start_time: datetime.datetime
    end_time: datetime.datetime
    reason: str = Field(default="", max_length=255)
    user_id: Optional[int] = None  # si None, se usa el usuario autenticado


class AbsenceReviewRequest(BaseModel):
    comments: str = Field(default="", max_length=255)


class AbsenceRequestResponse(BaseModel):
    request_id: int
    user_id: int
    user_name: str = ""
    absence_type_id: int
    absence_type_name: str
    request_date: datetime.date
    start_time: datetime.datetime
    end_time: datetime.datetime
    reason: str
    status: str
    total_days: float
    reviewer_id: Optional[int] = None
    review_comments: Optional[str] = None

    @classmethod
    def from_request(cls, req: "AbsenceRequests") -> "AbsenceRequestResponse":
        det = req.user.details if req.user else None
        name = f"{det.FirstName} {det.LastName1}" if det else f"Usuario {req.UserID}"
        return cls(
            request_id=req.RequestID,
            user_id=req.UserID,
            user_name=name,
            absence_type_id=req.AbsenceTypeID,
            absence_type_name=req.absence_type.TypeName if req.absence_type else "",
            request_date=req.RequestDate,
            start_time=req.StartTime,
            end_time=req.EndTime,
            reason=req.Reason,
            status=req.Status.value if req.Status else "Pending",
            total_days=req.TotalDays,
            reviewer_id=req.review.ReviewerID if req.review else None,
            review_comments=req.review.ReviewComments if req.review else None,
        )


class AbsenceBalanceResponse(BaseModel):
    user_id: int
    absence_type_id: int
    absence_type_name: str
    year: int
    accrued_days: float
    used_days: float
    pending_days: float
    remaining_days: float

    @classmethod
    def from_balance(cls, b: "AbsenceBalance") -> "AbsenceBalanceResponse":
        return cls(
            user_id=b.UserID,
            absence_type_id=b.AbsenceTypeID,
            absence_type_name=b.absence_type.TypeName if b.absence_type else "",
            year=b.Year,
            accrued_days=b.AccruedDays,
            used_days=b.UsedDays,
            pending_days=b.PendingDays,
            remaining_days=b.remaining_days,
        )


class AbsenceBalanceUpdateRequest(BaseModel):
    user_id: int
    absence_type_id: int
    year: int
    accrued_days: float = Field(ge=0)
