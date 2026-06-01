import datetime
import logging
from typing import List, Optional, Sequence
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlmodel import desc, asc
from dependencies import SessionDep, get_current_user, PaginationDep, CompanyFiltersDep, DepartmentFiltersDep
from SQLModels import (
    Users,
    Companies,
    Departments, CompanyList, DepartmentList
)
from .models import DepartmentCreation, DepartmentsResponse, CompanyResponse, CompanyUpdate, DepartmentUpdate

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