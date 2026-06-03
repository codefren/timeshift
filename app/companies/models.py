from typing import List, Optional, Set
import googlemaps
from pydantic import BaseModel, Field
from sqlmodel import Session
from dependencies import CONFIG
from SQLModels import Departments, DepartmentsRelations, Locations, Companies


class EmployeeStats(BaseModel):
    UserID: int
    FirstName: str
    LastName1: str
    LastName2: Optional[str] = None
    JobTitle: Optional[str] = None
    IsWorking: bool
    IsInactive: bool


class DepartmentStats(BaseModel):
    DeptID: int
    DeptName: str
    total_employees: int
    active_employees: int
    working_today: int
    employees: List[EmployeeStats]


class CompanyDeptStats(BaseModel):
    CompanyID: int
    SocialName: str
    FiscalName: str
    total_employees: int
    active_employees: int
    working_today: int
    departments: List[DepartmentStats]


class CompanyDeptStatsResponse(BaseModel):
    companies: List[CompanyDeptStats]

class CompanyResponse(BaseModel):
    company: Companies
    departments: List[Departments] | None = None

    @classmethod
    def from_company(cls, company: Companies):
        return cls(company=company, departments=company.departments)


class DepartmentsResponse(BaseModel):
    department: Departments
    parent_department: Departments | None = None
    child_departments: List[Departments] | None = None

    @classmethod
    def get_by_ids(cls, db: Session, company_id: int, dept_id: int):
        dept_model = Departments.get(db, dept_id=dept_id, company_id=company_id)
        if not dept_model:
            raise ValueError("Department not found")
        return cls(department=dept_model,
                   parent_department=dept_model.parent_department.parent_department if
                   dept_model.parent_department else None,
                   child_departments=[child.child_department for child in dept_model.child_departments] if
                   dept_model.child_departments else [])

class DepartmentCreation(BaseModel):
    DeptName: str = Field(max_length=50, unique=True)
    LocationName: str = Field(max_length=50)
    ParentDeptID: int | None = Field(None, description="Parent department ID", ge=1)
    SubDeptsID: List[int] | None = Field(None, description="List of sub departments IDs", ge=1)
    CompanyID: int | None = Field(None, description="Company ID", ge=1)

    def check_location(self, db: Session):
        loc = Locations.get_by_name(db, self.LocationName)
        if not loc:
            raise ValueError("Location not found")
        return loc.LocationID

    def check_company(self, db: Session):
        if not Companies.get(db, self.CompanyID):
            raise ValueError("Company not found")

    def check_dept(self, db: Session):
        if self.ParentDeptID is not None:
            if not Departments.get(db, self.ParentDeptID):
                raise ValueError("Parent department not found")
        if self.SubDeptsID:
            for sub_dept_id in self.SubDeptsID:
                if not Departments.get(db, sub_dept_id):
                    raise ValueError("Sub department not found")

        if Departments.exists(db, self.DeptName):
            raise ValueError("Department already exists and active")

    def create(self, db: Session) -> DepartmentsResponse:
        loc_id = self.check_location(db)
        self.check_company(db)
        self.check_dept(db)
        model_db = Departments.get_by_name(db, self.DeptName, False)
        if model_db:
            model_db.activate(db)
            return DepartmentsResponse(department=model_db,
                                       parent_department=model_db.parent_department.parent_department if
                                       model_db.parent_department else None,
                                       child_departments=[child.child_department for child in model_db.child_departments] if
                                       model_db.child_departments else [])
        dept = Departments(DeptName=self.DeptName, LocationID=loc_id, CompanyID=self.CompanyID)
        dept.create(db)
        if self.ParentDeptID is not None:
            parent_dept = DepartmentsRelations(ParentDeptID=self.ParentDeptID, DeptID=dept.DeptID)
            parent_dept.create(db)
        if self.SubDeptsID:
            for sub_dept_id in self.SubDeptsID:
                sub_dept = DepartmentsRelations(ParentDeptID=dept.DeptID, DeptID=sub_dept_id)
                sub_dept.create(db)
        db.refresh(dept)
        db.commit()
        return DepartmentsResponse(department=dept,
                                   parent_department=dept.parent_department.parent_department if
                                    dept.parent_department else None,
                                   child_departments=[child.child_department for child in dept.child_departments] if
                                    dept.child_departments else [])

class DepartmentUpdate(BaseModel):
    DeptID: Optional[int] = Field(default=None, exclude=True)
    CompanyID: Optional[int] = Field(default=None, exclude=True)
    DeptName: Optional[str] = Field(max_length=50)
    LocationName: Optional[str] = Field(max_length=50)
    ParentDeptID: Optional[int] = Field(None, description="Parent department ID", ge=0)
    SubDeptsID: Optional[Set[int]] = Field(None, description="List of sub departments IDs")

    def check_depts_relation(self, db:Session, dept:Departments) -> None:
        current_child_deptsids = [x.DeptID for x in dept.child_departments]

        if (self.SubDeptsID is None and self.ParentDeptID is None) or \
                (self.SubDeptsID == set(current_child_deptsids) and self.ParentDeptID is not None and
                 dept.parent_department is not None and self.ParentDeptID == dept.parent_department.ParentDeptID):
            return

        if (self.ParentDeptID is not None and (dept.parent_department is None or dept.parent_department and
                self.ParentDeptID != dept.parent_department.ParentDeptID)):

            if self.ParentDeptID == dept.DeptID:
                raise ValueError("Department cannot be parent of itself")

            if self.ParentDeptID in self.SubDeptsID:
                raise ValueError("Parent department cannot be a sub department")

            if self.ParentDeptID != 0 and not Departments.exists_by_id(db, self.ParentDeptID):
                raise ValueError("Parent department not found")

        if self.SubDeptsID and not self.SubDeptsID.issubset(set(current_child_deptsids)):
            if (self.ParentDeptID is None and dept.parent_department and dept.parent_department.ParentDeptID in
                    self.SubDeptsID):
                raise ValueError("Parent department cannot be a sub department")

            for sub_dept_id in self.SubDeptsID:
                if sub_dept_id not in current_child_deptsids and not Departments.exists_by_id(db, sub_dept_id):
                    raise ValueError("Sub department not found")

    def update(self, db: Session) -> DepartmentsResponse:
        if not self.DeptID or not self.CompanyID:
            raise ValueError("Department ID and Company ID required")
        dept = Departments.get(db, self.DeptID)
        if not dept:
            raise ValueError("Department not found")
        if self.CompanyID != dept.CompanyID:
            if not Companies.get(db, self.CompanyID, active=True):
                raise ValueError("Company not found or not active")
            dept.CompanyID = self.CompanyID
        if self.DeptName and self.DeptName != dept.DeptName:
            if Departments.exists(db, self.DeptName):
                raise ValueError("Department name already exists")
            dept.DeptName = self.DeptName
        if self.LocationName and self.LocationName != dept.location.LocationName:
            loc = Locations.get_by_name(db, self.LocationName)
            if not loc:
                raise ValueError("Location not found")
            dept.LocationID = loc.LocationID

        dept = dept.update(db)
        self.check_depts_relation(db, dept)
        if self.ParentDeptID is not None:
            dept = dept.replace_parentdept(db, self.ParentDeptID)
        if self.SubDeptsID:
            dept = dept.replace_subdepts(db, self.SubDeptsID)
        return DepartmentsResponse(department=dept,
                                   parent_department=dept.parent_department.parent_department if
                                   dept.parent_department else None,
                                   child_departments=[child.child_department for child in dept.child_departments] if
                                   dept.child_departments else [])


class CompanyUpdate(BaseModel):
    CompanyID: int | None = Field(None, exclude=True)
    SocialName: Optional[str] = Field(None, max_length=50)
    FiscalName: Optional[str] = Field(None, max_length=50)
    Address: Optional[str] = Field(None, max_length=50)
    ZipCode: Optional[str] = Field(None, max_length=10)
    City: Optional[str] = Field(None, max_length=50)
    State: Optional[str] = Field(None, max_length=50)
    Country: Optional[str] = Field(None, max_length=50)

    def update(self, db: Session) -> Companies:
        if not self.CompanyID:
            raise ValueError("Company ID required")
        company = Companies.get(db, self.CompanyID)
        if not company:
            raise ValueError("Company not found")
        company.update(db, **self.model_dump(mode='python'))
        return company
