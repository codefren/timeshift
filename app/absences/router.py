import datetime
import logging
from typing import List, Optional, Sequence
from fastapi import APIRouter, Depends, Query, HTTPException, status

from dependencies import SessionDep, get_current_user, require_permission
from SQLModels import Users
from SQLModels.WorkLogs import AbsenceStatus
from absences.models import (
    AbsenceTypeCreateRequest, AbsenceTypeResponse,
    AbsenceRequestCreate, AbsenceReviewRequest,
    AbsenceRequestResponse,
    AbsenceBalanceResponse, AbsenceBalanceUpdateRequest,
)
from absences.service import AbsencesService

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/absences",
    tags=["Absences"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}},
)


# ------------------------------------------------------------------ #
# AbsenceTypes                                                        #
# ------------------------------------------------------------------ #

@router.get("/types/", response_model=List[AbsenceTypeResponse])
def list_absence_types(db: SessionDep) -> List[AbsenceTypeResponse]:
    types = AbsencesService.list_types(db)
    return [AbsenceTypeResponse.from_type(t) for t in types]


@router.post("/types/", response_model=AbsenceTypeResponse)
def create_absence_type(
        db: SessionDep,
        req: AbsenceTypeCreateRequest,
        current_user: Users = Depends(require_permission("manage:Absences")),
) -> AbsenceTypeResponse:
    at = AbsencesService.create_type(db, req.type_name, req.is_counted)
    log.info(f"AbsenceType '{at.TypeName}' created by user {current_user.UserID}")
    return AbsenceTypeResponse.from_type(at)


# ------------------------------------------------------------------ #
# AbsenceRequests                                                     #
# ------------------------------------------------------------------ #

@router.get("/requests/", response_model=List[AbsenceRequestResponse])
def list_requests(
        db: SessionDep,
        current_user: Users = Depends(require_permission("view:Absences")),
        user_id: Optional[int] = Query(default=None),
        request_status: Optional[AbsenceStatus] = Query(default=None, alias="status"),
        start_after: Optional[datetime.datetime] = Query(default=None),
        start_before: Optional[datetime.datetime] = Query(default=None),
) -> List[AbsenceRequestResponse]:
    can_manage = current_user.has_permission("manage:Absences")
    viewable = current_user.get_viewable_users_ids(db)

    if user_id:
        if user_id not in viewable:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="No tienes permiso para ver las solicitudes de este usuario")
        filter_user = user_id
    elif can_manage:
        # Gestores ven todas las solicitudes de usuarios bajo su supervisión
        filter_user = None
    else:
        # Empleados regulares solo ven sus propias solicitudes
        filter_user = current_user.UserID

    requests = AbsencesService.list_requests(db, filter_user, request_status, start_after, start_before)
    return [AbsenceRequestResponse.from_request(r) for r in requests]


@router.post("/requests/", response_model=AbsenceRequestResponse)
def create_request(
        db: SessionDep,
        req: AbsenceRequestCreate,
        current_user: Users = Depends(get_current_user),
) -> AbsenceRequestResponse:
    target_user_id = req.user_id or current_user.UserID

    if target_user_id != current_user.UserID:
        manageable = current_user.get_manageable_users_ids(db)
        if target_user_id not in manageable:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="No puedes crear solicitudes para este usuario")

    if req.end_time <= req.start_time:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="La fecha de fin debe ser posterior a la de inicio")

    try:
        absence_req = AbsencesService.create_request(
            db,
            user_id=target_user_id,
            absence_type_id=req.absence_type_id,
            start_time=req.start_time,
            end_time=req.end_time,
            reason=req.reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    log.info(f"Absence request {absence_req.RequestID} created for user {target_user_id}")
    return AbsenceRequestResponse.from_request(absence_req)


@router.get("/requests/{request_id}/", response_model=AbsenceRequestResponse)
def get_request(
        db: SessionDep,
        request_id: int,
        current_user: Users = Depends(get_current_user),
) -> AbsenceRequestResponse:
    req = AbsencesService.get_request(db, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Solicitud no encontrada")

    viewable = current_user.get_viewable_users_ids(db)
    if req.UserID not in viewable:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="No tienes permiso para ver esta solicitud")

    return AbsenceRequestResponse.from_request(req)


@router.post("/requests/{request_id}/approve/", response_model=AbsenceRequestResponse)
def approve_request(
        db: SessionDep,
        request_id: int,
        review: AbsenceReviewRequest,
        current_user: Users = Depends(require_permission("manage:Absences")),
) -> AbsenceRequestResponse:
    try:
        req = AbsencesService.approve_request(db, request_id, current_user.UserID, review.comments)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return AbsenceRequestResponse.from_request(req)


@router.post("/requests/{request_id}/reject/", response_model=AbsenceRequestResponse)
def reject_request(
        db: SessionDep,
        request_id: int,
        review: AbsenceReviewRequest,
        current_user: Users = Depends(require_permission("manage:Absences")),
) -> AbsenceRequestResponse:
    try:
        req = AbsencesService.reject_request(db, request_id, current_user.UserID, review.comments)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return AbsenceRequestResponse.from_request(req)


@router.delete("/requests/{request_id}/", status_code=status.HTTP_204_NO_CONTENT)
def cancel_request(
        db: SessionDep,
        request_id: int,
        current_user: Users = Depends(get_current_user),
) -> None:
    try:
        deleted = AbsencesService.cancel_request(db, request_id, current_user.UserID)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Solicitud no encontrada o no pertenece al usuario")


# ------------------------------------------------------------------ #
# AbsenceBalance                                                      #
# ------------------------------------------------------------------ #

@router.get("/balance/", response_model=List[AbsenceBalanceResponse])
def get_balance(
        db: SessionDep,
        current_user: Users = Depends(get_current_user),
        user_id: Optional[int] = Query(default=None),
        year: Optional[int] = Query(default=None),
) -> List[AbsenceBalanceResponse]:
    target = user_id or current_user.UserID
    if target != current_user.UserID:
        viewable = current_user.get_viewable_users_ids(db)
        if target not in viewable:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="No tienes permiso para ver el saldo de este usuario")

    balances = AbsencesService.get_balance(db, target, year)
    return [AbsenceBalanceResponse.from_balance(b) for b in balances]


@router.put("/balance/", response_model=AbsenceBalanceResponse)
def update_balance(
        db: SessionDep,
        req: AbsenceBalanceUpdateRequest,
        current_user: Users = Depends(require_permission("manage:Absences")),
) -> AbsenceBalanceResponse:
    balance = AbsencesService.set_accrued_days(
        db, req.user_id, req.absence_type_id, req.year, req.accrued_days
    )
    log.info(f"Balance updated for user {req.user_id} by {current_user.UserID}: {req.accrued_days} days")
    return AbsenceBalanceResponse.from_balance(balance)
