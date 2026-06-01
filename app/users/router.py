import datetime
import logging
from typing import List, Sequence, Optional, Union

import pandas as pd
from PIL import Image
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from pydantic.types import PastDate
from sqlmodel import desc, asc, Session, select, and_, func, case
from dependencies import SessionDep, get_current_user, PaginationDep, UsersFiltersDep, require_permission
from SQLModels import (
    Users,
    UserDetail,
    UserAddress,
    UserDepartments,
    UserPicture, UsersList, UserWeekHoursBalance, UserTotalHoursBalance,
    WorkLogs
)
from .models import UserResponse, UserCreation, UserCompleteResponse, UserUpdate, AppDataResponse, UsersWorkingSimple, \
    UserWorkedHoursResponse, UsersWorkedHoursArgs, UserDepartmentAssignment

from .objects import WorkedHoursPeriods, UsersWorkedHoursDetailedArgs, UserWorkedHoursDetailedResponse

router = APIRouter(
    prefix="/api/employees",
    tags=["Employees"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}},
)


@router.get("/app-data/", response_model=AppDataResponse)
def get_app_data(db: SessionDep, user: Users = Depends(get_current_user)):
    """
    Return all necessary application data in a single call:
    - User data including profile, departments, current worklog
    - Absence types for worklog pauses
    - Any other app configuration data
    """
    return AppDataResponse.load_app_data(db, user)


def change_user_state(user_id: int, db: Session, deactivate: bool = True) -> UserResponse:
    log = logging.getLogger(__name__)
    log.debug(f"{'Deactivating' if deactivate else 'Activating'} user by id {user_id}")
    model = Users.get(db, user_id)
    if not model:
        raise HTTPException(status_code=404, detail="User not found")

    if deactivate:
        model.deactivate(db)
        log.debug(f"User by id {user_id} deactivated")
    else:
        model.activate(db)
        log.debug(f"User by id {user_id} activated")

    return UserResponse(user=model,
                        detail=model.details,
                        address=model.address,
                        picture=model.picture.load_bytes() if model.picture else UserPicture(UserID=model.UserID).create(db).load_bytes())

@router.delete("/{user_id}/", response_model=UserResponse)
def delete_user_by_id(user_id: int, db: SessionDep):
    return change_user_state(user_id, db, True)

@router.post("/activate/{user_id}/", response_model=UserResponse)
def activate_user_by_id(user_id: int, db: SessionDep):
    return change_user_state(user_id, db, False)

@router.get("/", response_model=UsersList)
def get_users(db: SessionDep,
              params: PaginationDep,
              filters: UsersFiltersDep,
              ) -> UsersList:
    params.order = desc if params.order == "desc" else asc
    return Users.list(db, params, filters)

@router.post("/", response_model=UserCompleteResponse)
def create_user(db: SessionDep,
                user: UserCreation,
                current_user: Users = Depends(require_permission("manage:Users")),
                ):
    return user.create(db)

@router.put("/", response_model=UserCompleteResponse)
def update_user(db: SessionDep, user: UserUpdate):
    return user.update_user(db)



@router.get("/week-balance/", response_model=UserWeekHoursBalance)
def get_week_balance(db: SessionDep,
                     user: Users = Depends(get_current_user),
                     wn: int = Query(default_factory=lambda: datetime.datetime.now().isocalendar()[1], alias="week_number"),
                     yn: int = Query(default_factory=lambda: datetime.datetime.now().isocalendar()[0], alias="year_number"),
                     ):
    return UserWeekHoursBalance.get(db, user.UserID, wn, yn) or UserWeekHoursBalance(UserID=user.UserID, WeekNumber=wn, Year=yn)

@router.get("/month-balance/", response_model=Sequence[UserWeekHoursBalance])
def get_month_balance(db: SessionDep,
                      user: Users = Depends(get_current_user),
                      mn: int = Query(default_factory=lambda: datetime.datetime.now().month, alias="month_number"),
                      yn: int = Query(default_factory=lambda: datetime.datetime.now().year, alias="year_number"),
                      ):
    return UserWeekHoursBalance.get_several(db, user.UserID, UserWeekHoursBalance.get_week_numbers(yn, mn), yn)


@router.get("/total-balance/", response_model=UserTotalHoursBalance)
def get_total_balance(db: SessionDep, user: Users = Depends(get_current_user)):
    return UserTotalHoursBalance(UserID=user.UserID).create(db)

@router.get("/worked_hours/", response_model=List[UserWorkedHoursResponse])
def get_worked_hours(db: SessionDep, 
                     user: Users = Depends(get_current_user),
                     start_date: PastDate = Query(),
                     end_date: PastDate = Query(),
                     user_id: Optional[str] = Query(None, ),
                     ):
    data = UsersWorkedHoursArgs(start_date=start_date,
                                end_date=end_date,
                                user_id=user_id)

    if data.start_date > data.end_date:
        raise HTTPException(status_code=400, detail="Start date must be before end date")
    return UserWorkedHoursResponse.from_df(UserWeekHoursBalance.get_worked_hours_by_user(db, data.start_date, data.end_date, data.user_id))


@router.get("/worked_hours/detailed/", response_model=List[UserWorkedHoursDetailedResponse])
def get_detailed_worked_hours(db: SessionDep,
                          user: Users = Depends(get_current_user),
                          start_date: PastDate = Query(),
                          end_date: PastDate = Query(),
                          user_id: Optional[str] = Query(None, ),
                          period: Optional[WorkedHoursPeriods] = Query(WorkedHoursPeriods.day),
                          ):
    log: logging.Logger = logging.getLogger(__name__)
    data = UsersWorkedHoursDetailedArgs(start_date=start_date,
                                end_date=end_date,
                                user_id=user_id,
                                period=period)

    if data.start_date > data.end_date:
        raise HTTPException(status_code=400, detail="Start date must be before end date")

    log.debug(
        f"Requested worked hours detailed report from {data.start_date} to {data.end_date} with period {data.period} of {data.user_id}")
    res = None
    if data.period == WorkedHoursPeriods.week:
        res = UserWorkedHoursDetailedResponse.from_df(
            UserWeekHoursBalance.get_weekly_worked_hours_by_user(db, data.start_date, data.end_date, data.user_id),
            period=data.period
        )
    elif data.period == WorkedHoursPeriods.month:
        return UserWorkedHoursDetailedResponse.from_df(
            WorkLogs.get_monthly_worked_hours_by_user(db, data.start_date, data.end_date, data.user_id),
            period = data.period
        )
    else:
        res = UserWorkedHoursDetailedResponse.from_df(
            WorkLogs.get_daily_worked_hours(db, data.start_date, data.end_date, data.user_id),
            period=data.period
        )

    if isinstance(data.user_id, list):
        uids_seen = [x.UserID for x in res]
        for uid in data.user_id:
            if uid not in uids_seen:
                res.append(
                    UserWorkedHoursDetailedResponse(
                        UserID=uid,
                        WorkedHours=0,
                        PausedCountedHours=0,
                        PausedUncountedHours=0,
                        Period=data.period,
                        WorkedHoursDetailed=[]
                    )
                )

    return res




@router.get("/subordinates/", response_model=List[UsersWorkingSimple])
def get_subordinates(db: SessionDep, user: Users = Depends(get_current_user)):
    """
    Obtiene todos los usuarios que son subordinados del usuario actual según sus permisos.
    
    Los permisos determinan el alcance de los subordinados visibles:
    - Subordinados directos: Siempre visibles (tabla Supervision)
    - view:OwnDepartment: Todos los miembros del departamento principal del usuario
    - view:SubDepartment: Todos los empleados de todos los subdepartamentos
    - view:FirstSubDepartment: Solo empleados del primer nivel de subdepartamentos
    - view:All: Todos los empleados
    """
    # Obtener los IDs de usuarios que el usuario actual puede ver
    viewable_user_ids = user.get_viewable_users_ids(db)
    
    # Excluir al propio usuario de la lista
    if user.UserID in viewable_user_ids:
        viewable_user_ids.remove(user.UserID)
    
    if not viewable_user_ids:
        return []
    
    # Consulta para obtener la información de los usuarios visibles
    latest_worklogs_subquery = (
        select(WorkLogs.UserID, func.max(WorkLogs.WorkLogID).label("latest_worklog_id"))
        .group_by(WorkLogs.UserID)
        .subquery()
    )
    
    # Consulta principal uniendo con la subconsulta
    res = db.exec(
        select(Users.UserID, UserDetail.FirstName, UserDetail.LastName1, UserDetail.LastName2, 
               Users.Email, Users.IsInactive, UserDetail.ContractWeeklyHours,
               UserDepartments.DeptID.label("DeptID"),
               case((WorkLogs.IsFinished == False, True), else_=False).label("IsWorking"),
               UserDetail.JobTitle.label("Role"),
               WorkLogs.LogDate.label("LastWorkingDate"))
        .join(UserDetail, UserDetail.UserID == Users.UserID)
        .join(UserDepartments, and_(UserDepartments.UserID == Users.UserID, UserDepartments.IsPrimary == True))
        .outerjoin(latest_worklogs_subquery, latest_worklogs_subquery.c.UserID == Users.UserID)
        .outerjoin(WorkLogs, and_(
            WorkLogs.UserID == Users.UserID,
            WorkLogs.WorkLogID == latest_worklogs_subquery.c.latest_worklog_id
        ))
        .where(Users.UserID.in_(list(viewable_user_ids)))
        .order_by(UserDetail.FirstName, UserDetail.LastName1, UserDetail.LastName2)
    ).all()
    seen = set()
    return [UsersWorkingSimple(
        UserID=row.UserID,
        FirstName=row.FirstName,
        LastName1=row.LastName1,
        LastName2=row.LastName2,
        Email=row.Email,
        ContractWeeklyHours=row.ContractWeeklyHours,
        Depts=[UserDepartmentAssignment.from_user_department(x) for x in Users.get(db,row.UserID).departments],
        IsWorking=row.IsWorking,
        Role=row.Role,
        LastWorkingDate=row.LastWorkingDate,
        IsInactive=row.IsInactive
    ) for row in res if row.UserID not in seen and not seen.add(row.UserID)]

@router.get("/{user_id}/", response_model=UserCompleteResponse)
@router.get("/me/", response_model=UserCompleteResponse)
def get_user_by_id(db: SessionDep,
                   user: Users = Depends(get_current_user),
                   user_id: Optional[int] = None,
                   ):
    user_id = user_id or user.UserID
    log = logging.getLogger(__name__)
    log.debug(f"Getting user by id {user_id}")
    model = Users.get(db, user_id)
    if not model:
        raise HTTPException(status_code=404, detail="User not found")
    log.debug(f"User by id {user_id} obtained")
    return UserCompleteResponse.from_users(db, model)
