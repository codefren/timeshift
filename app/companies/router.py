import datetime
import logging
from datetime import date
from typing import List, Optional, Sequence
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlmodel import desc, asc, select, and_, or_, case, func
from dependencies import SessionDep, get_current_user, PaginationDep, CompanyFiltersDep, DepartmentFiltersDep
from SQLModels import (
    Users,
    UserDetail,
    UserDepartments,
    WorkLogs,
    Companies,
    Departments, CompanyList, DepartmentList
)
from .models import (
    DepartmentCreation, DepartmentsResponse, CompanyResponse, CompanyUpdate, DepartmentUpdate,
    EmployeeStats, DepartmentStats, CompanyDeptStats, CompanyDeptStatsResponse
)

router = APIRouter(
    prefix="/api/companies",
    tags=["Companies"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}},
)


@router.post("/", response_model=Companies)
def create_company(db: SessionDep,
                   company: Companies,
                   ):
    log = logging.getLogger(__name__)
    log.debug(f"Creating company {company.TaxID}")
    if Companies.exists(db, company.TaxID):
        if Companies.exists(db, company.TaxID, Active=False):
            company = Companies.get_by_taxid(db, company.TaxID, active=False)
            company.activate(db)
            log.debug(f"Company {company.TaxID} activated")
            return company.update(db, **company.model_dump(mode='python'))
        raise HTTPException(status_code=400, detail="Company already exists")
    company.create(db)
    log.debug(f"Company {company.TaxID} created")
    return company


@router.post("/{company_id}/departments/", response_model=DepartmentsResponse)
def create_department(db: SessionDep,
                      company_id: int,
                      dept: DepartmentCreation):
    dept.CompanyID = company_id
    return dept.create(db)


@router.get("/departments/stats/", response_model=CompanyDeptStatsResponse)
def get_department_stats(db: SessionDep, current_user: Users = Depends(get_current_user)):
    """
    Retorna estadísticas de asistencia agrupadas por compañía y departamento.
    Solo incluye las compañías y departamentos visibles según los permisos del usuario.
    """
    viewable_depts = Departments.get_viewable_departments(db, current_user)
    if not viewable_depts:
        return CompanyDeptStatsResponse(companies=[])

    viewable_dept_ids = {d.DeptID for d in viewable_depts}
    viewable_user_ids = current_user.get_viewable_users_ids(db)

    latest_wl_subq = (
        select(WorkLogs.UserID, func.max(WorkLogs.WorkLogID).label("latest_id"))
        .group_by(WorkLogs.UserID)
        .subquery()
    )

    rows = db.exec(
        select(
            Companies.CompanyID,
            Companies.SocialName,
            Companies.FiscalName,
            Departments.DeptID,
            Departments.DeptName,
            Users.UserID,
            UserDetail.FirstName,
            UserDetail.LastName1,
            UserDetail.LastName2,
            UserDetail.JobTitle,
            Users.IsInactive,
            UserDepartments.IsPrimary,
            case((WorkLogs.IsFinished == False, True), else_=False).label("IsWorking"),
        )
        .join(Departments, Departments.CompanyID == Companies.CompanyID)
        .join(UserDepartments, and_(
            UserDepartments.DeptID == Departments.DeptID,
            UserDepartments.AssignedDate <= date.today(),
            or_(
                UserDepartments.DeAssignedDate == None,
                UserDepartments.DeAssignedDate > date.today(),
            ),
        ))
        .join(Users, Users.UserID == UserDepartments.UserID)
        .join(UserDetail, UserDetail.UserID == Users.UserID)
        .outerjoin(latest_wl_subq, latest_wl_subq.c.UserID == Users.UserID)
        .outerjoin(WorkLogs, and_(
            WorkLogs.UserID == Users.UserID,
            WorkLogs.WorkLogID == latest_wl_subq.c.latest_id
        ))
        .where(
            Departments.DeptID.in_(viewable_dept_ids),
            Users.UserID.in_(list(viewable_user_ids)),
            Departments.Active == True,
            Companies.Active == True,
            Users.IsInactive == False,
        )
        .order_by(Companies.SocialName, Departments.DeptName, UserDetail.FirstName)
    ).all()

    # Agrupar resultados por compañía → departamento
    companies_map: dict = {}
    for row in rows:
        c_id = row.CompanyID
        d_id = row.DeptID

        if c_id not in companies_map:
            companies_map[c_id] = {
                "CompanyID": c_id,
                "SocialName": row.SocialName,
                "FiscalName": row.FiscalName,
                "departments": {},
            }

        depts = companies_map[c_id]["departments"]
        if d_id not in depts:
            depts[d_id] = {
                "DeptID": d_id,
                "DeptName": row.DeptName,
                "employees_seen": set(),
                "employees": [],
            }

        if row.UserID not in depts[d_id]["employees_seen"]:
            depts[d_id]["employees_seen"].add(row.UserID)
            depts[d_id]["employees"].append(EmployeeStats(
                UserID=row.UserID,
                FirstName=row.FirstName,
                LastName1=row.LastName1,
                LastName2=row.LastName2,
                JobTitle=row.JobTitle,
                IsWorking=row.IsWorking,
                IsInactive=row.IsInactive,
            ))

    # Construir respuesta final
    result_companies = []
    for c_data in companies_map.values():
        dept_stats_list = []
        for d_data in c_data["departments"].values():
            emps = d_data["employees"]
            dept_stats_list.append(DepartmentStats(
                DeptID=d_data["DeptID"],
                DeptName=d_data["DeptName"],
                total_employees=len(emps),
                active_employees=sum(1 for e in emps if not e.IsInactive),
                working_today=sum(1 for e in emps if e.IsWorking),
                employees=emps,
            ))

        all_emps = [e for d in dept_stats_list for e in d.employees]
        unique_users = {e.UserID: e for e in all_emps}
        unique_list = list(unique_users.values())

        result_companies.append(CompanyDeptStats(
            CompanyID=c_data["CompanyID"],
            SocialName=c_data["SocialName"],
            FiscalName=c_data["FiscalName"],
            total_employees=len(unique_list),
            active_employees=sum(1 for e in unique_list if not e.IsInactive),
            working_today=sum(1 for e in unique_list if e.IsWorking),
            departments=dept_stats_list,
        ))

    return CompanyDeptStatsResponse(companies=result_companies)


@router.get("/{company_id}/", response_model=CompanyResponse)
def get_company_by_id(db: SessionDep,
                      company_id: int,
                      ):
    log = logging.getLogger(__name__)
    log.debug(f"Getting company by id {company_id}")
    model = Companies.get(db, company_id)
    if not model:
        raise HTTPException(status_code=404, detail="Company not found")
    log.debug(f"Company by id {company_id} obtained")
    return CompanyResponse(company=model, departments=model.departments)


@router.get("/{company_id}/departments/{dept_id}/", response_model=DepartmentsResponse)
def get_department(db: SessionDep,
                   company_id: int,
                   dept_id: int,
                   current_user: Users = Depends(get_current_user)):
    return DepartmentsResponse.get_by_ids(db, company_id, dept_id)


@router.get("/", response_model=CompanyList)
def get_companies(db: SessionDep,
                  params: PaginationDep,
                  filters: CompanyFiltersDep):
    params.order = desc if params.order == 'desc' else asc
    return Companies.list(db, params, filters)


@router.get("/{company_id}/departments/", response_model=DepartmentList)
def get_departments(db: SessionDep,
                    company_id: int,
                    params: PaginationDep,
                    filters: DepartmentFiltersDep,
                    current_user: Users = Depends(get_current_user)):
    params.order = desc if params.order == 'desc' else asc
    return Departments.list(db, params, filters, company_id=company_id, user=current_user)

@router.get("/departments/viewable/", response_model=Optional[Sequence[Departments]])
def get_viewable_departments(db: SessionDep,
                            current_user: Users = Depends(get_current_user)):
    return Departments.get_viewable_departments(db, current_user)

@router.put("/{company_id}/", response_model=Companies)
def update_company(db: SessionDep,
                   company_id: int,
                   company: CompanyUpdate):
    company.CompanyID = company_id
    log = logging.getLogger(__name__)
    log.debug(f"Updating company {company_id}")
    company = company.update(db)
    log.debug(f"Company {company_id} updated")
    return company

@router.put("/{company_id}/departments/{dept_id}/", response_model=DepartmentsResponse)
def update_department(db: SessionDep,
                      company_id: int,
                      dept_id: int,
                      dept: DepartmentUpdate):
    dept.DeptID = dept_id
    dept.CompanyID = company_id if not dept.CompanyID else dept.CompanyID
    return dept.update(db)


@router.delete("/{company_id}/", response_model=Companies)
def delete_company(db: SessionDep,
                   company_id: int,
                   ):
    log = logging.getLogger(__name__)
    log.debug(f"Deleting company {company_id}")
    company = Companies.get(db, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    company.deactivate(db)
    log.debug(f"Company {company_id} deactivated")
    return company

@router.delete("/{company_id}/departments/{dept_id}/", response_model=Departments)
def delete_department(db: SessionDep,
                      company_id: int,
                      dept_id: int,
                      ):
    log = logging.getLogger(__name__)
    log.debug(f"Deleting department {dept_id}")
    dept = Departments.get(db, dept_id, company_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    dept.deactivate(db)
    log.debug(f"Department {dept_id} deactivated")
    return dept