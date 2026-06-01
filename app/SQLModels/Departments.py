import datetime
from math import ceil
from typing import Self, List, Set

import googlemaps
from pydantic import BaseModel
from sqlalchemy import Sequence, func
from sqlalchemy.orm import aliased
from sqlalchemy.sql import literal
from sqlmodel import SQLModel, Relationship, Field, Session, select, or_

from utils.geo import haversine_distance
from .Users import UserDepartments, Users
from utils import CONFIG


class CompanyList(BaseModel):
    companies: List["Companies"]
    pages: int


class Companies(SQLModel, table=True):
    __tablename__ = "Companies"
    CompanyID: int | None = Field(default=None, primary_key=True)
    TaxID: str = Field(max_length=9, unique=True)
    SocialName: str = Field(max_length=50)
    FiscalName: str = Field(max_length=50)
    Address: str = Field(max_length=50)
    ZipCode: str = Field(max_length=10)
    City: str = Field(max_length=50)
    State: str = Field(max_length=50)
    Country: str = Field(max_length=50)
    Active: bool = Field(default=True)

    departments: "Departments" = Relationship(back_populates="company")

    @classmethod
    def get_list_select(cls, params: "Pagination", filters: "CompanyFilters" = None, count_only: bool = False):
        if not count_only:
            q = select(cls).order_by(params.order(cls.CompanyID))
        else:
            q = select(func.count(cls.CompanyID))
        if not filters:
            return q

        if filters.tax_id:
            q = q.where(cls.TaxID == filters.tax_id)
        if filters.social_name:
            q = q.where(cls.SocialName == filters.social_name)
        if filters.fiscal_name:
            q = q.where(cls.FiscalName == filters.fiscal_name)
        if filters.address:
            q = q.where(cls.Address == filters.address)
        if filters.zip_code:
            q = q.where(cls.ZipCode == filters.zip_code)
        if filters.city:
            q = q.where(cls.City == filters.city)
        if filters.state:
            q = q.where(cls.State == filters.state)
        if filters.country:
            q = q.where(cls.Country == filters.country)
        if filters.active is not None:
            q = q.where(cls.Active == filters.active)
        return q

    @classmethod
    def list(cls, db: Session, params: "Pagination", filters: "CompanyFilters") -> CompanyList:
        q = cls.get_list_select(params, filters, count_only=False)
        q_count = cls.get_list_select(params, filters, count_only=True)
        count = db.exec(q_count).one()
        q = q.offset((params.page - 1) * params.size).limit(params.size)
        pages = ceil(count / params.size)
        if params.page > pages:
            return CompanyList(companies=[], pages=0)
        items = db.exec(q).unique().all()
        return CompanyList(companies=items, pages=pages)

    @classmethod
    def get(cls, db: Session, company_id: int, active: bool = True) -> Self | None:
        return db.exec(select(cls).where(cls.CompanyID == company_id, cls.Active == active)).first()

    @classmethod
    def get_by_taxid(cls, db: Session, tax_id: str, active: bool = True) -> Self | None:
        return db.exec(select(cls).where(cls.TaxID == tax_id, cls.Active == active)).first()

    @classmethod
    def exists(cls, db: Session, tax_id: str, **kwargs) -> bool:
        return db.exec(select(cls).where(cls.TaxID == tax_id).where(
            *[getattr(cls, key) == value for key, value in kwargs.items() if hasattr(cls, key)])).first() is not None

    def _create(self, db: Session) -> Self:
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.CompanyID) if self.CompanyID is not None else None
        if model_db is None:
            return self._create(db)
        else:
            return model_db

    def update(self, db: Session, **kwargs) -> Self:
        for key, value in kwargs.items():
            if value is None or key in ("CompanyID", "TaxID"):
                continue
            setattr(self, key, value)
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def delete(self, db: Session) -> None:
        db.delete(self)
        db.commit()

    def deactivate(self, db: Session) -> Self:
        if not self.Active:
            return
        self.Active = False
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def activate(self, db: Session) -> Self:
        if self.Active:
            return
        self.Active = True
        db.add(self)
        db.commit()
        db.refresh(self)
        return self


class DepartmentList(BaseModel):
    departments: List["Departments"]
    pages: int


class Departments(SQLModel, table=True):
    __tablename__ = "Departments"
    DeptID: int | None = Field(default=None, primary_key=True, index=True)
    DeptName: str = Field(max_length=50, unique=True)
    LocationID: int = Field(foreign_key="Locations.LocationID")
    CompanyID: int = Field(foreign_key="Companies.CompanyID")
    Active: bool = Field(default=True)
    ForceLocation: bool = Field(default=False, description="If True, the starting location to start worklog and end must be in this department's location", nullable=False)

    users: List["UserDepartments"] = Relationship(back_populates="department", sa_relationship_kwargs={"uselist":True,"lazy": "joined"})
    location: "Locations" = Relationship(back_populates="departments")
    company: "Companies" = Relationship(back_populates="departments")
    shifts: List["Shifts"] = Relationship(back_populates="department", sa_relationship_kwargs={"lazy": True})

    parent_department: "DepartmentsRelations" = Relationship(
        back_populates="child_department",
        sa_relationship_kwargs={"foreign_keys": "[DepartmentsRelations.DeptID]"}
    )
    child_departments: List["DepartmentsRelations"] = Relationship(
        back_populates="parent_department",
        sa_relationship_kwargs={"foreign_keys": "[DepartmentsRelations.ParentDeptID]"}
    )

    @classmethod
    def get_list_select(cls, params: "Pagination", filters: "DepartmentFilters" = None, count_only: bool = False):
        if not count_only:
            q = select(cls).order_by(params.order(cls.DeptID))
        else:
            q = select(func.count(cls.DeptID))
        if not filters:
            return q

        if filters.dept_name:
            q = q.where(cls.DeptName == filters.dept_name)
        if filters.location_name:
            q = q.join(Locations, cls.LocationID == Locations.LocationID)
            q = q.where(Locations.LocationName == filters.location_name)
        if filters.subdepartment_of:
            q = q.join(DepartmentsRelations, cls.DeptID == DepartmentsRelations.DeptID)
            q = q.where(DepartmentsRelations.ParentDeptID == filters.subdepartment_of)
        if filters.parentdepartment_of:
            q = q.where(
                cls.DeptID.in_(
                    select(DepartmentsRelations.ParentDeptID)
                    .join(Departments, Departments.DeptID == DepartmentsRelations.DeptID)
                    .where(Departments.DeptID == filters.parentdepartment_of)
                )
            )

        if filters.user_is_in:
            q = q.where(
                cls.DeptID.in_(
                    select(UserDepartments.DeptID).
                    join(Departments, Departments.DeptID == UserDepartments.DeptID).
                    where(UserDepartments.UserID == filters.user_is_in,
                          UserDepartments.DeAssignedDate is None
                          )
                )
            )

        if filters.active is not None:
            q = q.where(cls.Active == filters.active)

        return q

    @classmethod
    def list(cls, db: Session, params: "Pagination", filters: "DepartmentFilters",
             company_id: int = None, user: Users = None) -> DepartmentList:
        q = cls.get_list_select(params, filters, count_only=False).where(
            cls.CompanyID == company_id) if company_id else cls.get_list_select(params, filters, count_only=False)
        if user:
            # Special handling based on permission type
            if user.has_permission("view:All"):
                # No additional filter needed for view:All
                pass
            elif user.has_permission("view:SubDepartment"):
                print("view:SubDepartment")
                root_id = user.get_main_department()
                root_id = root_id if isinstance(root_id, int) else root_id.DeptID if root_id else None
                if root_id:
                    # Include root department and all subdepartments
                    subdepts_query = DepartmentsRelations.get_all_subdepartments_query(root_id)
                    subdept_ids = select(Departments.DeptID).select_from(subdepts_query)
                    q = q.where(cls.DeptID.in_(subdept_ids.union(select(literal(root_id)))))
                else:
                    # No main department found, restrict access
                    q = q.where(literal(False))
            elif user.has_permission("view:OwnDepartment"):
                # Get only departments the user is directly assigned to
                q = q.join(UserDepartments, Departments.DeptID == UserDepartments.DeptID, isouter=True)
                q = q.where(UserDepartments.UserID == user.UserID, or_(UserDepartments.DeAssignedDate.is_(None),
                                                                       datetime.date.today() <= UserDepartments.DeAssignedDate))
            else:
                # No permissions, restrict access completely
                q = q.where(literal(False))
        q_count = cls.get_list_select(params, filters, count_only=True).where(
            cls.CompanyID == company_id) if company_id else cls.get_list_select(params, filters, count_only=True)
        if user:
            # Special handling based on permission type
            if user.has_permission("view:All"):
                # No additional filter needed for view:All
                pass
            elif user.has_permission("view:SubDepartment"):
                root_id = user.get_main_department()
                root_id = root_id if isinstance(root_id, int) else root_id.DeptID if root_id else None
                if root_id:
                    # Include root department and all subdepartments
                    subdepts_query = DepartmentsRelations.get_all_subdepartments_query(root_id)
                    subdept_ids = select(Departments.DeptID).select_from(subdepts_query)
                    q_count = q_count.where(cls.DeptID.in_(subdept_ids.union(select(literal(root_id)))))
                else:
                    # No main department found, restrict access
                    q_count = q_count.where(literal(False))
            elif user.has_permission("view:OwnDepartment"):
                # Get only departments the user is directly assigned to
                q_count = q_count.join(UserDepartments, Departments.DeptID == UserDepartments.DeptID, isouter=True)
                q_count = q_count.where(UserDepartments.UserID == user.UserID, UserDepartments.DeAssignedDate.is_(None))
            else:
                # No permissions, restrict access completely
                q_count = q_count.where(literal(False))
        count = db.exec(q_count).one()
        q = q.offset((params.page - 1) * params.size).limit(params.size)
        pages = ceil(count / params.size)
        if params.page > pages:
            return DepartmentList(departments=[], pages=0)
        items = db.exec(q).unique().all()
        return DepartmentList(departments=items, pages=pages)

    @classmethod
    def get(cls, db: Session, dept_id: int, company_id: int = None, active: bool = True) -> Self | None:
        q = select(cls).where(cls.DeptID == dept_id, cls.Active == active)
        if company_id:
            q = q.where(cls.CompanyID == company_id)
        return db.exec(q).first()

    @classmethod
    def exists(cls, db: Session, dept_name: str, active: bool = True) -> bool:
        return db.exec(select(1).where(cls.DeptName == dept_name, cls.Active == active)).first() is not None

    @classmethod
    def exists_by_id(cls, db: Session, dept_id: int, active: bool = True) -> bool:
        return db.exec(select(1).where(cls.DeptID == dept_id, cls.Active == active)).first() is not None

    @classmethod
    def batch_exists(cls, db: Session, dept_ids: List[int], active: bool = True) -> bool:
        return len(db.exec(select(1).where(cls.DeptID.in_(dept_ids), cls.Active == active)).all()) == len(dept_ids)

    @classmethod
    def get_by_name(cls, db: Session, dept_name: str, active: bool = True) -> Self | None:
        return db.exec(select(cls).where(cls.DeptName == dept_name, cls.Active == active)).first()

    def _create(self, db: Session) -> Self:
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.DeptID) if self.DeptID is not None else None
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

    def deactivate(self, db: Session) -> Self:
        if not self.Active:
            return self
        self.Active = False
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def activate(self, db: Session) -> Self:
        if self.Active:
            return self
        self.Active = True
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    @classmethod
    def get_viewable_departments(cls, db: Session, user: Users) -> Sequence[Self]:
        """
        Returns a list of departments that the user can view.
        If the user is an admin, returns all departments.
        If the user is not an admin, returns only the departments that the user is assigned to.
        """
        return db.exec(cls._get_viewable_departments_query(user)).unique().all()

    @classmethod
    def _get_viewable_departments_query(cls, user: Users, root_id: int = None) -> select:
        if user.has_permission("view:All"):
            return select(Departments).where(Departments.Active == True)
        elif user.has_permission("view:SubDepartment"):
            root_id = root_id or user.get_main_department()
            root_id = root_id if isinstance(root_id, int) else root_id.DeptID if isinstance(root_id,cls) else None
            return DepartmentsRelations.get_all_subdepartments_query(root_id) if root_id else select(None)
        elif user.has_permission("view:OwnDepartment"):
            return select(Departments).join(UserDepartments, Departments.DeptID == UserDepartments.DeptID) \
                .where(UserDepartments.UserID == user.UserID, Departments.Active == True)

        return select(None)


    def replace_subdepts(self, db: Session, subdepts: Set[int]) -> Self:
        subdepts.discard(self.DeptID)
        for child in self.child_departments.copy():
            if child.DeptID not in subdepts:
                child.delete(db)
            else:
                subdepts.remove(child.DeptID)
        for subdept_id in subdepts:
            self.child_departments.append(DepartmentsRelations(ParentDeptID=self.DeptID, DeptID=subdept_id).create(db))

        db.refresh(self)
        return self

    def replace_parentdept(self, db: Session, parentdept: int) -> Self:
        if self.parent_department and not self.parent_department.ParentDeptID == parentdept and not parentdept == self.DeptID:
            self.parent_department.delete(db)
            self.parent_department = DepartmentsRelations(ParentDeptID=parentdept, DeptID=self.DeptID).create(db) if int(parentdept) != 0 else None
        elif not self.parent_department and not parentdept == self.DeptID:
            self.parent_department = DepartmentsRelations(ParentDeptID=parentdept, DeptID=self.DeptID).create(db) if int(parentdept) != 0 else None

        db.refresh(self)
        return self

    def is_in_location(self, latitude: float, longitude: float, threshold_m: float = None) -> bool:
        #Calculate distance from self.location to (latitude, longitude) and if more than threshold in meters, return False else True
        if not self.location:
            return False

        if not threshold_m:
            threshold_m = self.location.ControlRadius if self.location.ControlRadius else 100

        return haversine_distance(self.location.Lat, self.location.Long, latitude, longitude) <= threshold_m


class LocationList(BaseModel):
    locations: List["Locations"]
    pages: int


class Locations(SQLModel, table=True):
    __tablename__ = "Locations"
    LocationID: int | None = Field(default=None, primary_key=True)
    LocationName: str = Field(max_length=50, unique=True)
    Address: str = Field(max_length=250)
    ZipCode: str = Field(max_length=10)
    City: str = Field(max_length=50)
    State: str = Field(max_length=50)
    Country: str = Field(max_length=50)
    Lat: float = Field()
    Long: float = Field()
    Active: bool = Field(default=True, exclude=True)
    ControlRadius: float = Field(default=100, description="Control radius in meters for worklog start and end", nullable=False)

    departments: "Departments" = Relationship(back_populates="location")
    shifts: List["Shifts"] = Relationship(back_populates="location", sa_relationship_kwargs={"lazy": True})

    @classmethod
    def get_select(cls, params: "Pagination", filters: "LocationFilters" = None, count_only: bool = False):
        if count_only:
            q = select(func.count(cls.LocationID))
        else:
            q = select(cls).order_by(params.order(cls.LocationID))
        if not filters:
            return q

        if filters.location_name:
            q = q.where(cls.LocationName == filters.location_name)
        if filters.address:
            q = q.where(cls.Address == filters.address)
        if filters.zip_code:
            q = q.where(cls.ZipCode == filters.zip_code)
        if filters.city:
            q = q.where(cls.City == filters.city)
        if filters.state:
            q = q.where(cls.State == filters.state)
        if filters.country:
            q = q.where(cls.Country == filters.country)
        if filters.active is not None:
            q = q.where(cls.Active == filters.active)
        return q

    @staticmethod
    def validate_address_google(address: str, zip_code: str, city: str, state: str, country: str):
        gmaps = googlemaps.Client(key=CONFIG.GOOGLE_API_KEY)
        full_address = f"{address}, {zip_code}, {city}, {state}, {country}"

        geocode_result = gmaps.geocode(full_address)

        if geocode_result:
            location = geocode_result[0]['geometry']['location']
            return {
                "latitude": location['lat'],
                "longitude": location['lng'],
                "formatted_address": geocode_result[0]['formatted_address'],
                "partial_match": geocode_result[0].get('partial_match', False),
                "is_valid": not geocode_result[0].get('partial_match', False)  # True if it's an exact match
            }
        return {"latitude": None, "longitude": None, "formatted_address": None, "is_valid": False}

    @classmethod
    def get(cls, db: Session, location_id: int, active: bool = True) -> Self | None:
        q = select(cls).where(cls.LocationID == location_id)
        return db.exec(q.where(cls.Active == True)).first() if active else db.exec(q).first()

    @classmethod
    def get_batch(cls, db: Session, location_ids: List[int], active: bool = True) -> List[Self]:
        q = select(cls).where(cls.LocationID.in_(location_ids))
        return db.exec(q.where(cls.Active == True)).all() if active else db.exec(q).all()

    @classmethod
    def get_by_name(cls, db: Session, location_name: str, active: bool = True) -> Self | None:
        q = select(cls).where(cls.LocationName == location_name)
        return db.exec(q.where(cls.Active == True)).first() if active else db.exec(q).first()

    @classmethod
    def exists(cls, db: Session, location_name: str, active: bool = True) -> bool:
        q = select(cls).where(cls.LocationName == location_name)
        return db.exec(q.where(cls.Active == True)).first() is not None if active else db.exec(q).first() is not None

    @classmethod
    def get_by_address(cls, db: Session, address: str, zip_code: str = None, city: str = None, state: str = None,
                       country: str = None, first: bool = True, active: bool = True) -> Self | Sequence[Self] | None:
        q = select(cls).where(cls.Address == address)
        if zip_code:
            q = q.where(cls.ZipCode == zip_code)
        if city:
            q = q.where(cls.City == city)
        if state:
            q = q.where(cls.State == state)
        if country:
            q = q.where(cls.Country == country)
        if active:
            q = q.where(cls.Active == True)
        return db.exec(q).first() if first else db.exec(q).all()

    @classmethod
    def list(cls, db: Session, params: "Pagination", filters: "LocationFilters") -> LocationList:
        q = cls.get_select(params, filters, count_only=False)
        q_count = cls.get_select(params, filters, count_only=True)
        count = db.exec(q_count).one()
        q = q.offset((params.page - 1) * params.size).limit(params.size)
        pages = ceil(count / params.size)
        if params.page > pages:
            return LocationList(locations=[], pages=0)
        items = db.exec(q).unique().all()
        return LocationList(locations=items, pages=pages)

    def deactivate(self, db: Session) -> Self:
        if not self.Active:
            return
        return self.update(db, Active=False)

    def _create(self, db: Session) -> Self:
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.LocationID, active=False) if self.LocationID is not None else self.get_by_name(db,
                                                                                                                    self.LocationName,
                                                                                                                    active=False)
        if model_db is None:
            return self._create(db)
        else:
            if model_db.Active is False:
                return model_db.update(db, **self.model_dump(mode='python'), Active=True)
            return model_db

    def update(self, db: Session, **kwargs) -> Self:
        for key, value in kwargs.items():
            if value is None or key == "LocationID" or not hasattr(self, key):
                continue
            elif key == "LocationName":
                if self.exists(db, value):
                    raise ValueError("Location Name already exists")
            setattr(self, key, value)
        db.commit()
        db.refresh(self)
        return self

    def delete(self, db: Session) -> None:
        db.delete(self)
        db.commit()


class DepartmentsRelations(SQLModel, table=True):
    __tablename__ = "DepartmentsRelations"
    DeptID: int = Field(foreign_key="Departments.DeptID", primary_key=True)
    ParentDeptID: int = Field(foreign_key="Departments.DeptID", primary_key=True)

    parent_department: "Departments" = Relationship(
        back_populates="child_departments",
        sa_relationship_kwargs={"primaryjoin": "DepartmentsRelations.ParentDeptID == Departments.DeptID"}
    )
    child_department: "Departments" = Relationship(
        back_populates="parent_department",
        sa_relationship_kwargs={"primaryjoin": "DepartmentsRelations.DeptID == Departments.DeptID"}
    )

    @classmethod
    def get(cls, db: Session, dept_id: int, parent_dept_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.DeptID == dept_id, cls.ParentDeptID == parent_dept_id)).first()

    @classmethod
    def exists(cls, db: Session, dept_id: int, parent_dept_id: int) -> bool:
        return db.exec(select(cls).where(cls.DeptID == dept_id, cls.ParentDeptID == parent_dept_id)).first() is not None

    @classmethod
    def get_by_parent(cls, db: Session, parent_dept_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.ParentDeptID == parent_dept_id)).first()

    @classmethod
    def get_by_child(cls, db: Session, child_dept_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.DeptID == child_dept_id)).first()

    @classmethod
    def are_related(cls, db: Session, dept_id: int, parent_dept_id: int) -> bool:
        return cls.exists(db, dept_id, parent_dept_id)

    def _create(self, db: Session) -> None:
        db.add(self)
        db.commit()
        db.refresh(self)

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.DeptID, self.ParentDeptID)
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
    def get_relation(cls, db: Session, dept_id: int, parent_dept_id: int) -> Self:
        return db.exec(select(cls).where(cls.DeptID == dept_id, cls.ParentDeptID == parent_dept_id)).first()

    @classmethod
    def create_relation(cls, db: Session, dept_id: int, parent_dept_id: int) -> Self:
        if cls.get_relation(db, dept_id, parent_dept_id):
            return None
        relation = cls(DeptID=dept_id, ParentDeptID=parent_dept_id)
        db.add(relation)
        db.commit()
        db.refresh(relation)
        return relation

    @classmethod
    def get_all_subdepartments(cls, session: Session, root_id: int) -> Sequence[Departments]:
        stmt = cls.get_all_subdepartments_query(root_id)
        return session.exec(stmt).all()

    @classmethod
    def get_all_subdepartments_query(cls, root_id: int) -> select:
        # Paso 1: definimos el CTE recursivo
        sub_depts = (
            select(
                cls.DeptID.label("dept_id"),
                cls.ParentDeptID.label("parent_id"),
            )
            .where(DepartmentsRelations.ParentDeptID == root_id)
            .cte(name="sub_depts", recursive=True)
        )

        dr_alias = aliased(DepartmentsRelations)
        # Paso 2: union recursiva: seguimos bajando mientras haya hijos
        sub_depts = sub_depts.union_all(
            select(
                dr_alias.DeptID.label("dept_id"),
                dr_alias.ParentDeptID.label("parent_id"),
            ).join(sub_depts, dr_alias.ParentDeptID == sub_depts.c.dept_id)
        )

        # Paso 3: sacamos los objetos Departments cuyos IDs estén en el CTE
        return (
            select(Departments)
            .where(Departments.DeptID.in_(select(sub_depts.c.dept_id)))
        )
