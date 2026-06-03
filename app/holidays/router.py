import datetime
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status

from dependencies import SessionDep, get_current_user, require_permission
from SQLModels import Users
from holidays.models import HolidayCreateRequest, HolidayUpdateRequest, HolidayResponse
from holidays.service import HolidaysService

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/holidays",
    tags=["Holidays"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}},
)


@router.get("/", response_model=List[HolidayResponse])
def list_holidays(
        db: SessionDep,
        date_from: datetime.date = Query(default_factory=lambda: datetime.date.today().replace(month=1, day=1)),
        date_to: datetime.date = Query(default_factory=lambda: datetime.date.today().replace(month=12, day=31)),
        company_id: Optional[int] = Query(default=None),
        location_id: Optional[int] = Query(default=None),
) -> List[HolidayResponse]:
    holidays = HolidaysService.list_holidays(db, date_from, date_to, company_id, location_id)
    return [HolidayResponse.from_holiday(h) for h in holidays]


@router.post("/", response_model=HolidayResponse)
def create_holiday(
        db: SessionDep,
        req: HolidayCreateRequest,
        current_user: Users = Depends(require_permission("manage:Holidays")),
) -> HolidayResponse:
    holiday = HolidaysService.create(
        db,
        name=req.name,
        date=req.date,
        created_by=current_user.UserID,
        company_id=req.company_id,
        location_id=req.location_id,
        is_recurring=req.is_recurring,
    )
    log.info(f"Holiday '{holiday.Name}' created by user {current_user.UserID}")
    return HolidayResponse.from_holiday(holiday)


@router.get("/{holiday_id}/", response_model=HolidayResponse)
def get_holiday(db: SessionDep, holiday_id: int) -> HolidayResponse:
    holiday = HolidaysService.get_by_id(db, holiday_id)
    if holiday is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Festivo no encontrado")
    return HolidayResponse.from_holiday(holiday)


@router.put("/{holiday_id}/", response_model=HolidayResponse)
def update_holiday(
        db: SessionDep,
        holiday_id: int,
        req: HolidayUpdateRequest,
        current_user: Users = Depends(require_permission("manage:Holidays")),
) -> HolidayResponse:
    update_data = {k: v for k, v in {
        "Name": req.name,
        "Date": req.date,
        "CompanyID": req.company_id,
        "LocationID": req.location_id,
        "IsRecurring": req.is_recurring,
    }.items() if v is not None}

    holiday = HolidaysService.update(db, holiday_id, **update_data)
    if holiday is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Festivo no encontrado")
    log.info(f"Holiday {holiday_id} updated by user {current_user.UserID}")
    return HolidayResponse.from_holiday(holiday)


@router.delete("/{holiday_id}/", status_code=status.HTTP_204_NO_CONTENT)
def delete_holiday(
        db: SessionDep,
        holiday_id: int,
        current_user: Users = Depends(require_permission("manage:Holidays")),
) -> None:
    deleted = HolidaysService.delete(db, holiday_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Festivo no encontrado")
    log.info(f"Holiday {holiday_id} deleted by user {current_user.UserID}")
