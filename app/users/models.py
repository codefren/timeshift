import json
import logging
from enum import Enum

from sqlalchemy import func
from datetime import datetime, timedelta, date, UTC
from dependencies import random_string, Pagination
from typing import Optional, List, Set, Dict, Any, Self, Sequence, Tuple, Union
from pydantic.types import datetime as datetype, PastDate
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlmodel import Session, desc, select, case, and_
from passlib.hash import bcrypt
import pandas as pd
from SQLModels import Users, UserDetail, UserAddress, UserPicture, Supervision, Roles, Schedules, \
    Departments, UserDepartments, WorkLogs, AbsenceTypes, Locations, Shifts, RoleUsers
from work_logs.models import WorkLogListResponse
from work_logs.router import WorkLogResponse
from .objects import *

class UserResponse(BaseModel):
    user: Users
    detail: Optional[UserDetail] = None
    address: Optional[UserAddress] = None
    picture: Optional[bytes] = None

class UserDepartmentAssignment(BaseModel):
    DeptID: int
    DeptName: Optional[str] = Field(default=None)
    AssignedDate: date = Field(default_factory=lambda: datetime.now(UTC).date(), alias="AssignedDate")
    DeAssignedDate: Optional[date] = Field(
        default_factory=lambda: datetime.now(UTC).replace(year=datetime.now(UTC).year + 20).date(), alias="DeAssignedDate")
    IsPrimary: bool = Field(default=False)

    @classmethod
    def from_user_department(cls, user_department: UserDepartments) -> Self:
        return cls(
            DeptID=user_department.DeptID,
            DeptName=user_department.department.DeptName,
            AssignedDate=user_department.AssignedDate,
            DeAssignedDate=user_department.DeAssignedDate,
            IsPrimary=user_department.IsPrimary
        )

class UserCompleteResponse(BaseModel):
    user: Users
    detail: UserDetail | None
    address: UserAddress | None
    picture: UserPicture | None
    departments: List[UserDepartmentAssignment] | None
    supervisors: List[Supervision] | None
    subordinates: List[Supervision] | None
    current_worklog: Optional[WorkLogResponse]
    schedule: Optional[Schedules] = None
    permissions: Optional[List[str]] = None

    @classmethod
    def from_users(cls, db: Session, user: Users) -> Self:
        work_log = WorkLogs.get_actual_worklog(db, user.UserID)
        return cls(user=user,
                   detail=user.details,
                   address=user.address,
                   picture=user.picture,
                   departments=[UserDepartmentAssignment.from_user_department(x) for x in user.departments],
                   supervisors=user.supervisors,
                   subordinates=user.subordinates,
                   permissions=[perm.permission.PermissionName
                                for ur in user.roles
                                for perm in ur.role.permissions if perm.permission.ForFrontend] if user.roles else None,
                   current_worklog=WorkLogResponse(worklog=work_log, lines=work_log.lines, shift=work_log.shift) if work_log else None)

class UserDetailCreation(BaseModel):
    Email: EmailStr = Field(max_length=50)
    RoleName: str = Field(max_length=50)
    FirstName: str = Field(max_length=50)
    LastName1: str = Field(max_length=50)
    LastName2: str = Field(default="", max_length=50)
    Gender: str = Field(max_length=50)
    PhoneNumber: str = Field(max_length=15)
    EmergencePhoneNumber: Optional[str] = Field(default=None, max_length=15)
    PersonalEmail: EmailStr = Field(max_length=50)
    IdentityNumber: str = Field(max_length=20)
    Nationality: str = Field(default="España", max_length=50)
    SSNumber: str = Field(max_length=20)
    DateOfBirth: datetype = Field()
    HireDate: datetype = Field()
    JobTitle: str = Field(max_length=50)
    ContractType: str = Field(max_length=50)
    ContractWeeklyHours: float = Field(gt=0)
    Picture: Optional[bytes] = None
    Departments: Optional[List[UserDepartmentAssignment]] = Field(min_length=1)
    ScheduleName: Optional[str] = Field(max_length=50)
    SupervisorEmails: Optional[List[EmailStr]] = Field(min_length=0)
    SubordinatesEmails: Optional[List[EmailStr]] = Field(min_length=0)

    @field_validator("SupervisorEmails", "SubordinatesEmails")
    @classmethod
    def validate_emails(cls, v: List[EmailStr] | None) -> List[EmailStr] | None:
        if v is None or (isinstance(v,list) and len(v) == 0):
            return None
        if not isinstance(v, list):
            raise ValueError("Emails must be a list")
        return v

    @field_validator("Departments")
    @classmethod
    def validate_departments(cls, v: List[UserDepartmentAssignment] | None) -> List[UserDepartmentAssignment] | None:
        if v is None:
            return None

        primary = False
        for x in v:
            if x.DeAssignedDate is None:
                x.DeAssignedDate = datetime.now(UTC).replace(year=datetime.now(UTC).year + 20).date()
            if x.IsPrimary:
                if primary == True:
                    raise ValueError("Departments must have only one primary department")
                primary = True
            if x.DeAssignedDate < x.AssignedDate:
                raise ValueError("Departments last date must be posterior to initial date")
        return v

class UserDetailUpdate(BaseModel):
    Email: Optional[EmailStr] = Field(None, max_length=50)
    RoleName: Optional[str] = Field(None, max_length=50)
    FirstName: Optional[str] = Field(None, max_length=50)
    LastName1: Optional[str] = Field(None, max_length=50)
    LastName2: Optional[str] = Field(None, max_length=50)
    Gender: Optional[str] = Field(None, max_length=50)
    PhoneNumber: Optional[str] = Field(None, max_length=15)
    EmergencePhoneNumber: Optional[str] = Field(None, max_length=15)
    PersonalEmail: Optional[EmailStr] = Field(None, max_length=50)
    IdentityNumber: Optional[str] = Field(None, max_length=20)
    Nationality: Optional[str] = Field(None, max_length=50)
    SSNumber: Optional[str] = Field(None, max_length=20)
    DateOfBirth: Optional[datetype] = Field(None, )
    HireDate: Optional[datetype] = Field(None, )
    JobTitle: Optional[str] = Field(None, max_length=50)
    ContractType: Optional[str] = Field(None, max_length=50)
    ContractWeeklyHours: Optional[float] = Field(None, gt=0)
    Picture: Optional[bytes] = None
    Departments: Optional[List[UserDepartmentAssignment]] = Field(default=None)
    ScheduleName: Optional[str] = Field(None, max_length=50)
    SupervisorEmails: Optional[Set[EmailStr]] = Field(None)
    SubordinatesEmails: Optional[Set[EmailStr]] = Field(None)

    @field_validator("Departments")
    @classmethod
    def validate_departments(cls, v: List[UserDepartmentAssignment] | None) -> List[UserDepartmentAssignment] | None:
        if v is None:
            return None

        primary = False
        for x in v:
            if x.DeAssignedDate is None:
                x.DeAssignedDate = datetime.now(UTC).replace(year=datetime.now(UTC).year + 20).date()
            if not isinstance(x.AssignedDate,date) or not isinstance(x.DeAssignedDate,date):
                raise ValueError("AssignedDate and DeAssignedDate must be of type date")
            if x.IsPrimary:
                if primary == True:
                    raise ValueError("Departments must have only one primary department")
                primary = True
            if x.DeAssignedDate < x.AssignedDate:
                raise ValueError("Departments last date must be posterior to initial date")
        return v

    def dump_details(self, mode='python') -> Dict[str, Any] | str:
        d = {
            "FirstName": self.FirstName,
            "LastName1": self.LastName1,
            "LastName2": self.LastName2,
            "Gender": self.Gender,
            "PhoneNumber": self.PhoneNumber,
            "EmergencePhoneNumber": self.EmergencePhoneNumber,
            "PersonalEmail": self.PersonalEmail,
            "IdentityNumber": self.IdentityNumber,
            "Nationality": self.Nationality,
            "SSNumber": self.SSNumber,
            "DateOfBirth": self.DateOfBirth,
            "HireDate": self.HireDate,
            "JobTitle": self.JobTitle,
            "ContractType": self.ContractType,
            "ContractWeeklyHours": self.ContractWeeklyHours,
        }
        if mode == 'python':
            return d
        else:
            return json.dumps(d)


class UserAddressCreation(BaseModel):
    Address: str = Field(max_length=255)
    ZipCode: str = Field(max_length=10)
    City: str = Field(max_length=50)
    State: str = Field(max_length=50)
    Country: str = Field(max_length=50)
    IsPrimary: Optional[bool] = Field(default=True)


class UserAddressUpdate(BaseModel):
    Address: Optional[str] = Field(default=None, max_length=255)
    ZipCode: Optional[str] = Field(default=None, max_length=10)
    City: Optional[str] = Field(default=None, max_length=50)
    State: Optional[str] = Field(default=None, max_length=50)
    Country: Optional[str] = Field(default=None, max_length=50)
    IsPrimary: Optional[bool] = Field(default=None)


class UserCreation(BaseModel):
    detail: UserDetailCreation
    address: UserAddressCreation
    UserID: int | None = Field(default=None, exclude=True)
    Password: str | None = Field(default=None)

    def generate_password(self) -> str:
        return random_string(8)

    def create_user(self, db: Session):
        self.Password = self.generate_password()
        role = Roles.get_by_name(db, self.detail.RoleName) if self.detail.RoleName else None
        if not role or not role.RoleID:
            raise ValueError(f"Role {self.detail.RoleName} not found")
        if not self.UserID:
            user = Users(Email=self.detail.Email,
                         Password=bcrypt.encrypt(self.Password)
                         )
            user.update_or_create(db)
            user_role = RoleUsers(UserID=user.UserID, RoleID=role.RoleID).create(db)
        else:
            user = Users.get(db, self.UserID)
            user.Email = self.detail.Email if not Users.get_by_email(db, self.detail.Email) else None
            if user.Email is None:
                raise ValueError("Email already exists")
            user.Password = bcrypt.encrypt(self.Password) if self.Password else user.Password
            db.add(user)
            db.commit()
            db.refresh(user)
        self.UserID = user.UserID
        return user

    def create_supervisors(self, db: Session) -> List[Supervision]:
        users = [Users.get_by_email(db, email) for email in self.detail.SupervisorEmails]
        sups = [Supervision(SupervisorID=supervisor.UserID, SubordinateID=self.UserID).update_or_create(db) for
                supervisor in
                users if supervisor]
        return sups if sups else None

    def create_subordinates(self, db: Session) -> List[Supervision]:
        users = [Users.get_by_email(db, email) for email in self.detail.SubordinatesEmails] if self.detail.SubordinatesEmails else []
        subs =  [Supervision(SupervisorID=self.UserID, SubordinateID=subordinate.UserID).update_or_create(db) for
                subordinate in
                users if subordinate]
        return subs if subs else None

    def create_picture(self, db: Session) -> UserPicture:
        return UserPicture(UserID=self.UserID).update_or_create(db, picture_bytes=self.detail.Picture)

    def validate_emails_exists(self, db: Session, user_emails: List[EmailStr] | None):
        if user_emails is None:
            return
        if not isinstance(user_emails, list):
            raise ValueError("Emails must be a list")
        for email in user_emails:
            if not Users.get_by_email(db, email):
                raise ValueError(f"El correo electrónico {email} no tiene un usuario asociado")


    def validate_departments(self, db: Session):
        if not self.detail.Departments:
            raise ValueError("Se requiere al menos un departamento")
        for dept in self.detail.Departments:
            dept_db = Departments.get(db, dept.DeptID)
            dept_db = dept_db if dept_db else Departments.get_by_name(db, dept.DeptName)
            if dept_db is None:
                raise ValueError(f"Departmento {dept.DeptID} o {dept.DeptName} no ha sido encontrado")
            dept.DeptID = dept_db.DeptID
            dept.DeptName = dept_db.DeptName


    def create_departments(self, db: Session) -> List[UserDepartmentAssignment]:
        prim = None
        for dept in self.detail.Departments:
            if dept.IsPrimary and prim is None:
                prim = dept.DeptID
            elif dept.IsPrimary and prim is not None:
                raise ValueError("Solo se puede asignar un departamento como primario")

        x = [UserDepartments(UserID=self.UserID,
                                DeptID=dept.DeptID,
                                IsPrimary=dept.IsPrimary,
                                AssignedDate=dept.AssignedDate,
                                DeAssignedDate=dept.DeAssignedDate
                                ) for dept in self.detail.Departments]
        x = [dept.update_or_create(db) for dept in x]
        return [UserDepartmentAssignment.from_user_department(dept) for dept in x if dept]

    def create_address(self, db: Session) -> UserAddress:
        return UserAddress(UserID=self.UserID,
                           **self.address.model_dump(mode='python')).update_or_create(db)

    def create_detail(self, db: Session) -> UserDetail:
        return UserDetail(UserID=self.UserID,
                          FirstName=self.detail.FirstName,
                          LastName1=self.detail.LastName1,
                          LastName2=self.detail.LastName2,
                          Gender=self.detail.Gender,
                          PhoneNumber=self.detail.PhoneNumber,
                          EmergencePhoneNumber=self.detail.EmergencePhoneNumber,
                          PersonalEmail=self.detail.PersonalEmail,
                          IdentityNumber=self.detail.IdentityNumber,
                          Nationality=self.detail.Nationality,
                          SSNumber=self.detail.SSNumber,
                          DateOfBirth=self.detail.DateOfBirth,
                          HireDate=self.detail.HireDate,
                          JobTitle=self.detail.JobTitle,
                          ContractType=self.detail.ContractType,
                          ContractWeeklyHours=self.detail.ContractWeeklyHours,
                          ).update_or_create(db)

    def create(self, db: Session) -> UserCompleteResponse:
        if Users.exists(db, self.detail.Email):
            raise ValueError("Email already exists")
        self.validate_departments(db)
        self.validate_emails_exists(db, self.detail.SupervisorEmails)
        self.validate_emails_exists(db, self.detail.SubordinatesEmails)
        return UserCompleteResponse(user=self.create_user(db),
                                    picture=self.create_picture(db),
                                    #schedule=self.create_schedule(db),
                                    departments=self.create_departments(db),
                                    address=self.create_address(db),
                                    detail=self.create_detail(db),
                                    supervisors=self.create_supervisors(db),
                                    subordinates=self.create_subordinates(db),
                                    current_worklog=None,
                                    )


class UserUpdate(UserCreation):
    detail: Optional[UserDetailUpdate] = None
    address: Optional[UserAddressUpdate] = None
    UserID: int
    Password: Optional[str] = None
    user: Optional[Users] = Field(None, exclude=True)
    remove_not_present: bool = False

    _log: logging.Logger = logging.getLogger(__name__)

    def update_picture(self, db: Session):
        if self.detail.Picture:
            self.user.picture = UserPicture(UserID=self.UserID).update_or_create(db, picture_bytes=self.detail.Picture)
        return self.user.picture

    def update_departments(self, db: Session):
        depts = [Departments.get(db, dept.DeptID) for dept in self.detail.Departments]

        new_depts = {}
        for dept, det_dept in zip(depts, self.detail.Departments):
            if dept:
                dept_obj = UserDepartments(
                    DeptID=dept.DeptID,
                    UserID=self.UserID,
                    IsPrimary=det_dept.IsPrimary,
                    AssignedDate=det_dept.AssignedDate,
                    DeAssignedDate=det_dept.DeAssignedDate
                )
                new_depts[dept.DeptID] = dept_obj.update_or_create(db)

        if self.remove_not_present:
            for x in self.user.departments:
                if x.DeptID not in new_depts:
                    x.delete(db)
            db.commit()
            db.refresh(self.user)
        else:
            db.commit()
            db.refresh(self.user)

        return self.user.departments

    def update_supervisors(self, db: Session):
        users = [Users.get_by_email(db, email) for email in self.detail.SupervisorEmails]
        new_supervisors = {supervisor.UserID: Supervision(SupervisorID=supervisor.UserID, SubordinateID=self.UserID).
        update_or_create(db) for supervisor in users if supervisor}
        _ = [x.delete(db) for x in self.user.supervisors if
             x.SupervisorID not in new_supervisors.keys()] if self.remove_not_present else None
        if self.remove_not_present:
            self.user.supervisors = list(new_supervisors.values())
        else:
            new_supervisors = set(new_supervisors.values())
            new_supervisors.update(set(self.user.supervisors))
            self.user.supervisors = list(new_supervisors)
        return self.user.supervisors

    def update_subordinates(self, db: Session):
        users = [Users.get_by_email(db, email) for email in self.detail.SubordinatesEmails]
        new_subordinates = {subordinate.UserID: Supervision(SupervisorID=self.UserID, SubordinateID=subordinate.UserID).
        update_or_create(db) for subordinate in users if subordinate}
        _ = [x.delete(db) for x in self.user.subordinates if
             x.SubordinateID not in new_subordinates.keys()] if self.remove_not_present else None
        if self.remove_not_present:
            self.user.subordinates = list(new_subordinates.values())
        else:
            new_subordinates = set(new_subordinates.values())
            new_subordinates.update(set(self.user.subordinates))
            self.user.subordinates = list(new_subordinates)
        return self.user.subordinates


    def update_detail(self, db: Session):
        detail_db = self.user.details
        if not detail_db:
            detail_db = UserDetail(UserID=self.UserID, **self.detail.dump_details(mode="python"))
            detail_db = detail_db._create(db)
        else:
            detail_db = detail_db.update(db, **self.detail.dump_details(mode="python"))
        self.user.details = detail_db

        if self.detail.Departments:
            self.update_departments(db)
        if self.detail.SupervisorEmails:
            self.update_supervisors(db)
        if self.detail.SubordinatesEmails:
            self.update_subordinates(db)
        if self.detail.ScheduleName:
            self.update_schedule(db)
        if self.detail.Picture:
            self.update_picture(db)

        return detail_db

    def update_address(self, db: Session):
        address_db = self.user.address
        if not address_db:
            address_db = UserAddress(UserID=self.UserID, **self.address.model_dump(mode="python"))
            address_db = address_db._create(db)
        else:
            address_db = address_db.update(db, **self.address.model_dump(mode="python"))
        self.user.address = address_db
        return address_db

    def update_user(self, db: Session):
        self.user = Users.get(db, self.UserID)
        if not self.user:
            raise ValueError("User not found")
        if self.detail:
            self.update_detail(db)
        if self.address:
            self.update_address(db)
        role = Roles.get_by_name(db, self.detail.RoleName) if self.detail.RoleName else None
        self.user = self.user.update(db, Email=self.detail.Email, Password=self.Password, RoleID=role.RoleID if role else None)

        return UserCompleteResponse.from_users(db, self.user)
    
class UsersWorkingSimple(BaseModel):
    UserID: int
    FirstName: str
    LastName1: str
    LastName2: Optional[str] = None
    Email: EmailStr
    ContractWeeklyHours: Optional[float] = None
    Depts: List[UserDepartmentAssignment]
    IsWorking: bool
    Role: str # Job Title of the user
    LastWorkingDate: Optional[datetype] = None
    IsInactive: Optional[bool] = None
    
    @classmethod
    def get_by_deptid(cls, db: Session, dept_id: int) -> Sequence[Self]:
        latest_worklogs_subquery = (
            select(WorkLogs.UserID, func.max(WorkLogs.WorkLogID).label("latest_worklog_id"))
            .group_by(WorkLogs.UserID)
            .subquery()
        )

        # Consulta principal uniendo con la subconsulta
        res = db.exec(
            select(Users.UserID, UserDetail.FirstName, UserDetail.LastName1, UserDetail.LastName2, Users.Email,
                   UserDepartments.DeptID.label("DeptID"),
                   case((and_(WorkLogs.IsFinished == False, Shifts.DepartmentID == dept_id), True), else_=False).label(
                       "IsWorking"),
                   UserDetail.JobTitle.label("Role"))
            .join(UserDepartments, UserDepartments.UserID == Users.UserID)
            .join(UserDetail, UserDetail.UserID == Users.UserID)
            .outerjoin(latest_worklogs_subquery, latest_worklogs_subquery.c.UserID == Users.UserID)
            .outerjoin(WorkLogs, and_(
                WorkLogs.UserID == Users.UserID,
                WorkLogs.WorkLogID == latest_worklogs_subquery.c.latest_worklog_id
            ))
            .outerjoin(Shifts, Shifts.ShiftID == WorkLogs.ShiftID)
            .where(UserDepartments.DeptID == dept_id)
        ).all()
        seen = set()
        return [cls(UserID=row.UserID, FirstName=row.FirstName, LastName1=row.LastName1, Email=row.Email,
                    LastName2=row.LastName2,
                    Depts=[UserDepartmentAssignment.from_user_department(x)
                            for x in Users.get(db,row.UserID).departments],
                    Role=row.Role, IsWorking=row.IsWorking) for row in res if row.UserID not in seen and not seen.add(row.UserID)]

class AppDataResponse(BaseModel):
    user: UserCompleteResponse
    absence_types: Sequence[AbsenceTypes]
    month_worklogs: WorkLogListResponse
    today_workhours: float = 0
    departments: Sequence[Departments]
    locations: Sequence[Locations]
    teammates: Dict[int, Sequence[UsersWorkingSimple]]
    available_menus: List[str] = []
    
    @classmethod
    def load_app_data(cls, db: Session, user: Users) -> Self:
        # Get user complete data
        user_data = UserCompleteResponse.from_users(db, user)
        
        # Get all absence types
        absence_types = AbsenceTypes.get_all(db)

        mwls = WorkLogs.list_month(db, user.UserID)
        mwls = WorkLogListResponse(worklogs=[WorkLogResponse(worklog=w, lines=w.lines, totals=w.totals, shift=w.shift) for w in mwls.worklogs], total=mwls.total, pages=mwls.pages)

        pags_params = Pagination(order="desc", size=250, page=1)
        pags_params.order = desc

        departments = [dpt.department for dpt in user.departments if dpt.department.Active and (not dpt.DeAssignedDate or datetime.today().date() < dpt.DeAssignedDate)]
        locations = Locations.get_batch(location_ids=[dept.LocationID for dept in departments], db=db, active=False)

        return cls(
            user=user_data,
            absence_types=absence_types,
            month_worklogs=mwls,
            departments=departments,
            locations=locations,
            teammates= {int(dept.DeptID): [x for x in UsersWorkingSimple.get_by_deptid(db, dept.DeptID) if x.UserID != user.UserID]
                        for dept in departments},
            available_menus = list(set([x.Menu for role in user.roles for perm in role.role.permissions for x in perm.permission.menus if perm.permission.ForFrontend])) if user.roles else []
        )
