import calendar, traceback
import logging
import os.path
from pydantic.types import PastDate
from datetime import datetime, date, timedelta
from math import ceil
from typing import List, Self, Sequence, Optional, Set, Tuple, Dict, Union
from PIL import Image
from PIL.Image import Image
from passlib.hash import bcrypt
from sqlalchemy import func
from sqlalchemy.testing import in_
from sqlmodel import SQLModel, Relationship, Field, Session, or_, and_, select
from pydantic import EmailStr, BaseModel, field_serializer
from pydantic.types import datetime as datetype
from pydantic import PrivateAttr
from typing import Any
from utils import CONFIG
from .Roles import Permissions, RoleUsers
import pandas as pd

log = logging.getLogger(__name__)

class UsersList(BaseModel):
    users: List["Users"]
    pages: int

class Users(SQLModel, table=True):
    __tablename__ = "Users"
    UserID: int | None = Field(default=None, primary_key=True)
    Email: EmailStr = Field(max_length=50, unique=True, index=True)
    Password: str = Field(max_length=255, exclude=True)
    IsInactive: bool = Field(default=False)
    CreatedAt: datetype = Field(default_factory=datetime.now)
    UpdatedAt: datetype | None = Field(default_factory=datetime.now, nullable=True)

    roles: List[RoleUsers] = Relationship(back_populates="user", sa_relationship_kwargs={"uselist": True})
    departments: List["UserDepartments"] = Relationship(back_populates="user")
    address: "UserAddress" = Relationship(back_populates="user", sa_relationship_kwargs={"uselist": False})
    details: "UserDetail" = Relationship(back_populates="user", sa_relationship_kwargs={"uselist": False})
    picture: "UserPicture" = Relationship(back_populates="user", sa_relationship_kwargs={"uselist": False})
    shifts: List["Shifts"] = Relationship(back_populates="user", sa_relationship_kwargs={"uselist": True, "lazy": True, "foreign_keys": "Shifts.UserID"})
    created_shifts: List["Shifts"] = Relationship(back_populates="creator", sa_relationship_kwargs={"uselist": True, "lazy": True, "foreign_keys": "Shifts.UserID"})

    subordinates: List["Supervision"] = Relationship(
        back_populates="supervisor",
        sa_relationship_kwargs={"foreign_keys": "Supervision.SupervisorID"}
    )
    supervisors: List["Supervision"] = Relationship(
        back_populates="subordinate",
        sa_relationship_kwargs={"foreign_keys": "Supervision.SubordinateID"}
    )

    schedules_created: List["Schedules"] = Relationship(back_populates="creator")
    worklogs: List["WorkLogs"] = Relationship(back_populates="user")
    absence_requests: List["AbsenceRequests"] = Relationship(back_populates="user")
    week_hours_balance: List["UserWeekHoursBalance"] = Relationship(back_populates="user")
    total_hours_balance: "UserTotalHoursBalance" = Relationship(back_populates="user")
    notifications: List["Notifications"] = Relationship(back_populates="user")
    absence_balances: List["AbsenceBalance"] = Relationship(back_populates="user")
    
    __permissions_set__: set[str] | None = None
    __viewable_users_ids__: set[int] | None = None
    __manageable_users_ids__: set[int] | None = None
    __logger__: logging.Logger = logging.getLogger(__name__)
    # Atributos privados para caché - no son parte del modelo SQLModel

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        self.__permissions_set__ = None
        self.__viewable_users_ids__ = None
        self.__manageable_users_ids__ = None
        self.__logger__ = logging.getLogger(__name__)


    @classmethod
    def get(cls, db: Session, user_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.UserID == user_id)).first()

    @classmethod
    def get_by_email(cls, db: Session, email: str) -> Self | None:
        return db.exec(select(cls).where(cls.Email == email)).first()

    @classmethod
    def exists(cls, db: Session, email: str) -> bool:
        return db.exec(select(cls).where(cls.Email == email)).first() is not None

    @classmethod
    def get_all_ids(cls, db: Session) -> List[int]:
        return [u for u in db.exec(select(cls.UserID)).all()]

    @classmethod
    def get_list_select(cls, params: "Pagination", filters: "UsersFilters" = None, count_only: bool = False):
        if not count_only:
            # Activos (IsInactive=False=0) primero, luego inactivos (True=1)
            c = select(cls).order_by(cls.IsInactive.asc(), params.order(cls.UserID))
        else:
            c = select(func.count(cls.UserID))
        if not filters:
            return c

        if filters.name is not None:
            c = c.where(cls.Name.like(f"%{filters.name}%"))
        if filters.phone is not None:
            c = c.where(cls.Phone.like(f"%{filters.phone}"))
        if filters.IDNumber is not None:
            c = c.where(cls.IDNumber == filters.IDNumber)
        if filters.hired_after is not None:
            c = c.where(cls.HireDate >= filters.hired_after)
        if filters.hired_before is not None:
            c = c.where(cls.HireDate <= filters.hired_before)
        if filters.job_title is not None:
            c = c.where(cls.JobTitle.like(f"%{filters.job_title}%"))
        if getattr(filters, 'roles', None) is not None:
            c = c.where(in_(filters.roles, [x.RoleID for ur in cls.roles for x in ur.permissions]))
        if getattr(filters, 'department', None) is not None:
            c = c.where(cls.departments.any(UserDepartments.DeptID == filters.department))
        if getattr(filters, 'updated_before', None) is not None:
            c = c.where(cls.UpdatedAt <= filters.updated_before)
        if getattr(filters, 'updated_after', None) is not None:
            c = c.where(cls.UpdatedAt >= filters.updated_after)
        if getattr(filters, 'created_before', None) is not None:
            c = c.where(cls.CreatedAt <= filters.created_before)
        if getattr(filters, 'created_after', None) is not None:
            c = c.where(cls.CreatedAt >= filters.created_after)
        if getattr(filters, 'active', None) is not None:
            c = c.where(cls.IsInactive == (not filters.active))
        if getattr(filters, 'has_picture', None) is not None:
            subquery2 = select(UserPicture.UserID).where(UserPicture.UserID == cls.UserID).exists()
            if getattr(filters, 'has_schedule', None):
                c = c.where(subquery2)
            else:
                c = c.where(~subquery2)
        if getattr(filters, 'supervisor_of', None) is not None:
            c = c.where(or_(cls.subordinates.any(Supervision.SubordinateID == cls.UserID),
                            cls.supervisors.any(Supervision.SupervisorID == filters.supervisor_of)))
        if getattr(filters, 'subordinate_of', None) is not None:
            c = c.where(or_(cls.supervisors.any(Supervision.SupervisorID == cls.UserID),
                            cls.subordinates.any(Supervision.SubordinateID == filters.subordinate_of)))
        if filters.owes_hours is not None:
            if filters.owes_hours:
                c = c.where(cls.total_hours_balance.BalanceHours < 0)
            else:
                c = c.where(cls.total_hours_balance.BalanceHours >= 0)
        return c

    @classmethod
    def list(cls, db: Session, params: "Pagination", filters: "UsersFilters") -> UsersList:
        query = cls.get_list_select(params, filters)
        count_query = cls.get_list_select(params, filters, count_only=True)
        count = db.exec(count_query).one()
        query = query.offset((params.page - 1) * params.size).limit(params.size)
        pages = ceil(count / params.size)
        if params.page > pages:
            return UsersList(users=[], pages=pages)
        items = db.exec(query).unique().all()
        return UsersList(users=items, pages=pages)

    def get_permisions(self) -> List[Permissions]:
        return [x.permission for ur in self.roles for x in ur.permissions] if self.roles and \
                                                                getattr(self, "_sa_instance_state",
                                                                        None) and self._sa_instance_state.session is not None else []

    def get_permisions_names(self) -> List[str]:
        return [x.PermissionName for x in self.get_permisions()]

    def get_main_department(self) -> Union[None,"Departments"]:
        for dept in self.departments:
            if dept.IsPrimary and (dept.DeAssignedDate is None or date.today() < dept.DeAssignedDate):
                return dept.department
        return None

    def deactivate(self, db: Session) -> Self:
        return self.update(db, IsInactive=True, UpdatedAt=datetime.now())

    def activate(self, db: Session) -> Self:
        return self.update(db, IsInactive=False, UpdatedAt=datetime.now()) if self.IsInactive else self

    def _create(self, db: Session) -> Self:
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.UserID) if self.UserID is not None else None
        if model_db is None:
            return self._create(db)
        else:
            return model_db

    def update(self, db: Session, **kwargs) -> Self:
        for key, value in kwargs.items():
            if value is None:
                continue
            if key == "Password":
                value = bcrypt.hash(str(value))
            elif key == 'Email':
                if self.Email != value and self.get_by_email(db, value):
                    raise ValueError(f"User with email {value} already exists")
            setattr(self, key, value) if value is not None else None
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def update_or_create(self, db:Session):
        model_db = self.get(db, self.UserID)
        if model_db:
            self.Password = model_db.Password
            return model_db.update(db, **self.model_dump(mode='python'))
        else:
            return self._create(db)

    def delete(self, db: Session) -> None:
        db.delete(self)
        db.commit()

    def verify_password(self, password: str) -> bool:
        return bcrypt.verify(password, self.Password)

    @classmethod
    def hash_password(cls, password: str) -> str:
        """
        Hashes the given password using bcrypt.

        Args:
            password: The password to hash

        Returns:
            str: The hashed password
        """
        return bcrypt.hash(str(password))
    
    
    def get_permissions(self) -> List[str]:
        return [x.permission.PermissionName for ur in self.roles for x in ur.role.permissions] if self.roles and \
            getattr(self, "_sa_instance_state",None) and self._sa_instance_state.session is not None else []
            
    @property
    def permissions(self) -> set[str]:
        """
        Propiedad que devuelve un set con todos los permisos del usuario.
        El set se carga la primera vez que se accede y se almacena en caché.
        """
        if self.__permissions_set__ is None:
            self.__permissions_set__ = set(self.get_permissions())
            self.__logger__.debug(f"Permissions for user {self.UserID}: {self.__permissions_set__}")
        return self.__permissions_set__
        
    def has_permission(self, permission_name: str) -> bool:
        """
        Verifica si el usuario tiene un permiso específico.
        
        Args:
            permission_name: Nombre del permiso a verificar
            
        Returns:
            bool: True si el usuario tiene el permiso, False en caso contrario
        """
        return permission_name in self.permissions
        
    def has_any_permission(self, permission_names: List[str]) -> bool:
        """
        Verifica si el usuario tiene al menos uno de los permisos especificados.
        
        Args:
            permission_names: Lista de nombres de permisos a verificar
            
        Returns:
            bool: True si el usuario tiene al menos uno de los permisos, False en caso contrario
        """
        return bool(set(permission_names).intersection(self.permissions))
    
    def get_viewable_users_ids(self, db: Session) -> set[int]:
        """
        Obtiene los IDs de los usuarios que este usuario puede ver según sus permisos.
        
        Args:
            db: Sesión de base de datos
            
        Returns:
            set[int]: Conjunto de IDs de usuarios visibles para este usuario
        """
        self.__logger__.debug(f"Getting viewable users for user {self.UserID}")
        # Si ya tenemos los IDs en caché, los devolvemos
        if self.__viewable_users_ids__ is not None:
            self.__logger__.debug(f"Using cached viewable users for user {self.UserID}")
            return self.__viewable_users_ids__
            
        result = set()
        
        # Siempre puede verse a sí mismo
        result.add(self.UserID)
        
        # Si tiene permiso para ver todos los usuarios
        if self.has_permission("view:All"):
            self.__logger__.debug(f"User {self.UserID} has permission to view all users.")
            # Obtener todos los IDs de usuarios
            user_ids = self.get_all_ids(db)
            result.update(user_ids)
            self.__viewable_users_ids__ = result
            return result
            
        # Obtener subordinados directos (supervisados)
        if self.subordinates:
            result.update([s.SubordinateID for s in self.subordinates if s.DeAssignedDate is None or date.today() < s.DeAssignedDate])
        
        # Si tiene permiso para ver su propio departamento
        if self.has_permission("view:OwnDepartment") and self.departments:
            self.__logger__.debug(f"User {self.UserID} has permission to view its own department.")
            # Obtener el departamento principal del usuario
            primary_dept: UserDepartments = next((d for d in self.departments if d.IsPrimary and (d.DeAssignedDate is None or date.today() < d.DeAssignedDate)), None)
            if primary_dept:
                # Obtener todos los usuarios en ese departamento
                dept_users: List[UserDepartments] = primary_dept.department.users
                result.update([u.UserID for u in dept_users if u.DeAssignedDate is None or date.today() < u.DeAssignedDate])
        
        # Si tiene permiso para ver subdepartamentos
        if self.has_any_permission(["view:SubDepartment", "view:FirstSubDepartment"]) and self.departments:
            # Obtener el departamento principal del usuario
            primary_dept = next((d for d in self.departments if d.IsPrimary and (d.DeAssignedDate is None or date.today() < d.DeAssignedDate)), None)
            if primary_dept and primary_dept.department:
                # Obtener subdepartamentos
                if self.has_permission("view:FirstSubDepartment"):
                    self.__logger__.debug(f"User {self.UserID} has permission to view first subdepartment.")
                    # Solo primer nivel de subdepartamentos
                    subdepts = primary_dept.department.child_departments
                    # Añadir usuarios de los subdepartamentos de primer nivel
                    for subdept_rel in subdepts:
                        if subdept_rel.child_department and subdept_rel.child_department.users:
                            for user_dept in subdept_rel.child_department.users:
                                result.add(user_dept.UserID) if not user_dept.DeAssignedDate or date.today() < user_dept.DeAssignedDate else None
                if self.has_permission("view:SubDepartment"):  # view:SubDepartment - todos los niveles
                    self.__logger__.debug(f"User {self.UserID} has permission to view all subdepartments.")
                    # Función recursiva para obtener todos los usuarios de subdepartamentos
                    def get_all_subdept_users(dept, collected_users=None, seen_depts=None):
                        if collected_users is None:
                            collected_users = set()
                        if seen_depts is None:
                            seen_depts = set()
                        
                        # Marcar este departamento como visto
                        seen_depts.add(dept.DeptID)
                        
                        # Añadir usuarios de este departamento
                        if dept.users:
                            for user_dept in dept.users:
                                collected_users.add(user_dept.UserID) if not user_dept.DeAssignedDate or date.today() < user_dept.DeAssignedDate else None
                        
                        # Procesar subdepartamentos
                        if dept.child_departments:
                            for subdept_rel in dept.child_departments:
                                if subdept_rel.DeptID not in seen_depts and subdept_rel.child_department:
                                    get_all_subdept_users(subdept_rel.child_department, collected_users, seen_depts)
                        
                        return collected_users
                    
                    # Obtener usuarios de todos los subdepartamentos recursivamente
                    subdept_users = get_all_subdept_users(primary_dept.department)
                    result.update(subdept_users)
        
        # Guardar en caché
        self.__viewable_users_ids__ = result
        self.__logger__.debug(f"Updated viewable users for user {self.UserID} with len: {len(result)}")
        return result
    
    def get_manageable_users_ids(self, db: Session) -> set[int]:
        """
        Obtiene los IDs de los usuarios que este usuario puede gestionar.
        Por ahora, solo incluye a los subordinados directos.
        
        Args:
            db: Sesión de base de datos
            
        Returns:
            set[int]: Conjunto de IDs de usuarios gestionables por este usuario
        """
        # Si ya tenemos los IDs en caché, los devolvemos
        if self.__manageable_users_ids__ is not None:
            return self.__manageable_users_ids__
            
        result = set()
        
        # Obtener subordinados directos (supervisados)
        if self.subordinates:
            result.update([s.SubordinateID for s in self.subordinates])

        if self.has_permission("manage:Users"):
            result.update(self.get_viewable_users_ids(db))
            return result

        if self.has_permission("update:OwnDepartment"):
            # Obtener el departamento principal del usuario
            primary_dept: UserDepartments = next((d for d in self.departments if d.IsPrimary and (
                        d.DeAssignedDate is None or date.today() < d.DeAssignedDate)), None)
            if primary_dept:
                # Obtener todos los usuarios en ese departamento
                dept_users: List[UserDepartments] = primary_dept.department.users
                result.update(
                    [u.UserID for u in dept_users if u.DeAssignedDate is None or date.today() < u.DeAssignedDate])

        if self.has_any_permission("update:FirstSubDepartment","update:SubDepartments"):
            primary_dept = next((d for d in self.departments if
                                 d.IsPrimary and (d.DeAssignedDate is None or date.today() < d.DeAssignedDate)), None)
            if primary_dept and primary_dept.department:
                if self.has_permission("update:FirstSubDepartment"):
                    self.__logger__.debug(f"User {self.UserID} has permission to view first subdepartment.")
                    # Solo primer nivel de subdepartamentos
                    subdepts = primary_dept.department.child_departments
                    # Añadir usuarios de los subdepartamentos de primer nivel
                    for subdept_rel in subdepts:
                        if subdept_rel.child_department and subdept_rel.child_department.users:
                            for user_dept in subdept_rel.child_department.users:
                                result.add(
                                    user_dept.UserID) if not user_dept.DeAssignedDate or date.today() < user_dept.DeAssignedDate else None

                if self.has_permission("update:SubDepartments"):  # view:SubDepartment - todos los niveles
                    self.__logger__.debug(f"User {self.UserID} has permission to view all subdepartments.")

                    # Función recursiva para obtener todos los usuarios de subdepartamentos
                    def get_all_subdept_users(dept, collected_users=None, seen_depts=None):
                        if collected_users is None:
                            collected_users = set()
                        if seen_depts is None:
                            seen_depts = set()

                        # Marcar este departamento como visto
                        seen_depts.add(dept.DeptID)

                        # Añadir usuarios de este departamento
                        if dept.users:
                            for user_dept in dept.users:
                                collected_users.add(
                                    user_dept.UserID) if not user_dept.DeAssignedDate or date.today() < user_dept.DeAssignedDate else None

                        # Procesar subdepartamentos
                        if dept.child_departments:
                            for subdept_rel in dept.child_departments:
                                if subdept_rel.DeptID not in seen_depts and subdept_rel.child_department:
                                    get_all_subdept_users(subdept_rel.child_department, collected_users, seen_depts)

                        return collected_users

                    # Obtener usuarios de todos los subdepartamentos recursivamente
                    subdept_users = get_all_subdept_users(primary_dept.department)
                    result.update(subdept_users)

        # Guardar en caché
        self.__manageable_users_ids__ = result
        return result

class UserAddress(SQLModel, table=True):
    __tablename__ = "UserAddress"
    AddressID: int | None = Field(default=None, primary_key=True)
    UserID: int = Field(foreign_key="Users.UserID")
    Address: str = Field(max_length=255)
    ZipCode: str = Field(max_length=10)
    City: str = Field(max_length=50)
    State: str = Field(max_length=50)
    Country: str = Field(max_length=50)
    IsPrimary: bool = Field(default=True)

    user: "Users" = Relationship(back_populates="address")

    @classmethod
    def get(cls, db: Session, user_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.UserID == user_id)).first()

    @classmethod
    def exists(cls, db: Session, user_id: int) -> bool:
        return db.exec(select(cls).where(cls.UserID == user_id)).first() is not None

    def _create(self, db: Session) -> Self:
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.UserID)
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

    def update_or_create(self, db:Session) -> Self:
        model_db = self.get(db, self.UserID)
        if model_db:
            return model_db.update(db, **self.model_dump(mode='python'))
        else:
            return self._create(db)

    def delete(self, db: Session) -> None:
        db.delete(self)
        db.commit()


class UserDetail(SQLModel, table=True):
    __tablename__ = "UserDetail"
    UserID: int = Field(foreign_key="Users.UserID", primary_key=True)
    FirstName: str = Field(max_length=50)
    LastName1: str = Field(max_length=50)
    LastName2: str = Field(max_length=50)
    Gender: str = Field(max_length=10)
    PhoneNumber: str = Field(max_length=15)
    EmergencePhoneNumber: Optional[str] = Field(default=None, max_length=15, nullable=True)
    PersonalEmail: EmailStr = Field(max_length=50)
    IdentityNumber: str = Field(max_length=20)
    Nationality: str = Field(max_length=50)
    SSNumber: str = Field(max_length=20)
    DateOfBirth: datetype = Field()
    HireDate: datetype = Field()
    JobTitle: str = Field(max_length=50)
    ContractType: str = Field(default=None, max_length=50)
    ContractWeeklyHours: float = Field(default=0)

    user: "Users" = Relationship(back_populates="details")

    @classmethod
    def get(cls, db: Session, user_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.UserID == user_id)).first()

    @classmethod
    def exists(cls, db: Session, user_id: int) -> bool:
        return db.exec(select(cls).where(cls.UserID == user_id)).first() is not None

    def _create(self, db: Session) -> Self:
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.UserID)
        if model_db is None:
            return self._create(db)
        else:
            return model_db

    def update(self, db: Session, **kwargs) -> Self:
        for key, value in kwargs.items():
            if value is None:
                continue
            if key == 'UserID' or value is None:
                continue
            setattr(self, key, value)
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def update_or_create(self, db: Session) -> Self:
        model_db = self.get(db, self.UserID)
        if model_db:
            return model_db.update(db, **self.model_dump(mode='python'))
        else:
            return self._create(db)

    def delete(self, db: Session) -> None:
        db.delete(self)
        db.commit()

class UserPicture(SQLModel, table=True):
    __tablename__ = "UserPicture"
    UserID: int = Field(foreign_key="Users.UserID", primary_key=True)
    FilePath: str = Field(default="")

    user: "Users" = Relationship(back_populates="picture")

    _log: logging.Logger = logging.getLogger(__name__)

    class Config:
        arbitrary_types_allowed = True

    @classmethod
    def get(cls, db: Session, user_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.UserID == user_id)).first()


    def file_path_from_bytes(self, picture_bytes: bytes) -> str:
        file_path = os.path.join(CONFIG.PROFILE_PICTURES_PATH or '/images/', f"{self.UserID}.png")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        try:
            with open(file_path, "wb") as file:
                Image.frombytes(picture_bytes).save(file, format="PNG")
        except Exception as e:
            self._log.error(f"Error saving image for user {self.UserID}: {e},\ntraceback: {e.__traceback__}")
            file_path = ""
        self.FilePath = file_path
        return self.FilePath

    def _create(self, db: Session) -> Self:
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def create(self, db: Session, picture_bytes: bytes = None) -> Self:
        model = self.get(db, self.UserID)
        if model:
            return model
        if picture_bytes and not self.FilePath:
            self.file_path_from_bytes(picture_bytes)
        return self._create(db)

    def update(self, db: Session, **kwargs) -> Self:
        for key, value in kwargs.items():
            if value is None:
                continue
            setattr(self, key, value)
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def update_or_create(self, db:Session, picture_bytes: bytes = None):
        model_db = self.get(db, self.UserID)
        if picture_bytes:
            self.file_path_from_bytes(picture_bytes)
        if model_db:
            return model_db.update(db, **self.model_dump(mode='python'))
        else:
            return self._create(db)

    def load_image(self) -> Image | None:
        if self and self.FilePath and os.path.exists(self.FilePath):
            try:
                with open(self.FilePath, "rb") as file:
                    return Image.frombytes(file.read())
            except Exception as e:
                self._log.error(f"Error loading image for user {self.UserID}: {e},\ntraceback: {e.__traceback__}")
                return None
        return None

    def load_bytes(self) -> bytes | None:
        if self and self.FilePath and self.FilePath != '' and os.path.exists(self.FilePath):
            try:
                with open(self.FilePath, "rb") as file:
                    return file.read()
            except Exception as e:
                self._log.error(f"Error loading image as bytes for user {self.UserID}: {e},\ntraceback: {e.__traceback__}")
                return None
        return None


class UserWeekHoursBalance(SQLModel, table=True):
    __tablename__ = "UserWeekHoursBalance"
    UserID: int = Field(foreign_key="Users.UserID", primary_key=True)
    WeekNumber: int = Field(primary_key=True, ge=1, le=53)
    Year: int = Field(primary_key=True, ge=2025, le=2100)
    WorkedHours: float = Field(default=0)
    PausedCountedHours: float = Field(default=0)
    PausedUncountedHours: float = Field(default=0)
    BalanceHours: float = Field(default=0)
    UpdatedAt: datetype = Field(default_factory=datetime.now)

    user: "Users" = Relationship(back_populates="week_hours_balance")

    @staticmethod
    def get_start_and_end_date_from_calendar_week(year: int, calendar_week: int) -> Tuple[date, date]:       
        monday = date.fromisocalendar(year, calendar_week, 1)
        return monday, monday + timedelta(days=6.9)

    @classmethod
    def get(cls, db: Session, user_id: int, week_number: int, year: int) -> Self | None:
        return db.exec(select(cls).where(
            and_(cls.UserID == user_id, cls.WeekNumber == week_number, cls.Year == year)
        )).first()

    @classmethod
    def get_several(cls, db: Session, user_id: int, week_numbers: List[int], year: int) -> Sequence[Self]:
        return db.exec(select(cls).where(
            and_(cls.UserID == user_id, cls.WeekNumber.in_(week_numbers), cls.Year == year)
        )).all()

    @classmethod
    def exists(cls, db: Session, user_id: int, week_number: int, year: int) -> bool:
        return db.exec(select(cls).where(
            and_(cls.UserID == user_id, cls.WeekNumber == week_number, cls.Year == year)
        )).first() is not None

    @staticmethod
    def get_week_numbers(year: int, month: int) -> List[int]:
        # Get all the dates in the month
        month_days = [date(year, month, day) for day in range(1, calendar.monthrange(year, month)[1] + 1)]
        # Get the corresponding week numbers
        week_numbers = sorted(set(date.isocalendar().week for date in month_days))
        return week_numbers

    @classmethod
    def _get_static_weeks_condition(cls, first_week: int, first_year: int, last_week: int, last_year: int):
        return or_(
            # Same year case
            and_(first_year == last_year, cls.Year == first_year, cls.WeekNumber >= first_week,
                 cls.WeekNumber <= last_week),
            and_(first_year < last_year, or_(
                and_(cls.Year == first_year, cls.WeekNumber >= first_week),
                and_(cls.Year == last_year, cls.WeekNumber <= last_week)
            )),
        )

    @classmethod
    def _substract_worked_hours(cls, db: Session, start_date: PastDate, end_date: PastDate, first_week: int, first_year: int, last_week: int, last_year: int, user_id: int | List[int], df: pd.DataFrame) -> pd.DataFrame:
        from .WorkLogs import WorkLogTotals
        first_week_start = cls.get_start_and_end_date_from_calendar_week(first_year, first_week)[0]
        last_week_end = cls.get_start_and_end_date_from_calendar_week(last_year, last_week)[1]
        print(df.columns)
        log.debug(f"Difference between {start_date} and {first_week_start}: {(start_date - first_week_start).days} days")
        if (start_date - first_week_start).days > 0:
            # Select worked hours on days on the first week that should be excluded
            df_wh_sub_init = WorkLogTotals.get_worked_hours_by_user(db, first_week_start,
                                                                    start_date - timedelta(days=1), user_id)
            df_wh_sub_init = pd.DataFrame(df_wh_sub_init)
            log.debug(f"DF of start week difference days {df_wh_sub_init}")
            if not df_wh_sub_init.empty:
                if not 'Period' in df.columns:
                    df_wh_sub_init.set_index("UserID", inplace=True)
                    df_wh_sub_init.fillna(0, inplace=True)
                    df = df.sub(df_wh_sub_init, fill_value=0)
                else:
                    # Para DataFrames con columna Period, procesamos cada usuario por separado
                    df_grouped = df.groupby(['UserID'])
                    log.debug(f"Substracting at first period")
                    for uid, group in df_grouped:
                        # Convertir valores a float para operaciones numéricas
                        uid = int(uid[0])
                        if uid in df_wh_sub_init['UserID'].values:
                            # Obtener las horas a restar para este usuario
                            user_hours = df_wh_sub_init[df_wh_sub_init['UserID'] == uid]
                            # Restar de la primera fila del usuario (suma mensual/semanal)
                            log.debug(f"User {uid} has to be substracted at init")
                            idx = group.index[0]
                            df.at[idx, 'WorkedHours'] = float(df.at[idx, 'WorkedHours']) - float(user_hours['WorkedHours'].values[0])
                            df.at[idx, 'PausedCountedHours'] = float(df.at[idx, 'PausedCountedHours']) - float(user_hours['PausedCountedHours'].values[0])
                            df.at[idx, 'PausedUncountedHours'] = float(df.at[idx, 'PausedUncountedHours']) - float(user_hours['PausedUncountedHours'].values[0])
        log.debug(
            f"Difference between {end_date} and {last_week_end}: {(last_week_end - end_date).days} days")
        if (last_week_end - end_date).days > 0:
            # Select worked hours on days on the last week that should be excluded
            df_wh_sub_end = WorkLogTotals.get_worked_hours_by_user(db, end_date + timedelta(days=1), last_week_end,
                                                                   user_id)
            df_wh_sub_end = pd.DataFrame(df_wh_sub_end)
            log.debug(f"DF of end week difference days {df_wh_sub_end}")
            if not df_wh_sub_end.empty:
                if not 'Period' in df.columns:
                    df_wh_sub_end.set_index("UserID", inplace=True)
                    df_wh_sub_end.fillna(0, inplace=True)
                    df = df.sub(df_wh_sub_end, fill_value=0)
                else:
                    # Para DataFrames con columna Period, procesamos cada usuario por separado
                    df_grouped = df.groupby(['UserID'])
                    log.debug(f"Substracting at last period")
                    for uid, group in df_grouped:
                        # Convertir valores a float para operaciones numéricas
                        uid = int(uid[0])
                        if uid in df_wh_sub_end['UserID'].values:
                            # Obtener las horas a restar para este usuario
                            user_hours = df_wh_sub_end[df_wh_sub_end['UserID'] == uid]
                            # Restar de la primera fila del usuario (suma mensual/semanal)
                            idx = group.index[-1]
                            log.debug(
                                f"User {uid} has to be substracted at fin, theoric {df.at[idx, 'WorkedHours']}, {df.at[idx, 'PausedCountedHours']}, {df.at[idx, 'PausedUncountedHours']}")
                            df.at[idx, 'WorkedHours'] = float(df.at[idx, 'WorkedHours']) - float(user_hours['WorkedHours'].values[0])
                            df.at[idx, 'PausedCountedHours'] = float(df.at[idx, 'PausedCountedHours']) - float(user_hours['PausedCountedHours'].values[0])
                            df.at[idx, 'PausedUncountedHours'] = float(df.at[idx, 'PausedUncountedHours']) - float(user_hours['PausedUncountedHours'].values[0])

        # Convertimos las columnas a tipo float antes de aplicar clip
        if 'WorkedHours' in df.columns:
            df['WorkedHours'] = pd.to_numeric(df['WorkedHours'], errors='coerce').fillna(0)
            df['WorkedHours'] = df['WorkedHours'].apply(lambda x: max(0, float(x)))
        if 'PausedCountedHours' in df.columns:
            df['PausedCountedHours'] = pd.to_numeric(df['PausedCountedHours'], errors='coerce').fillna(0)
            df['PausedCountedHours'] = df['PausedCountedHours'].apply(lambda x: max(0, float(x)))
        if 'PausedUncountedHours' in df.columns:
            df['PausedUncountedHours'] = pd.to_numeric(df['PausedUncountedHours'], errors='coerce').fillna(0)
            df['PausedUncountedHours'] = df['PausedUncountedHours'].apply(lambda x: max(0, float(x)))
        return df

    @classmethod
    def get_weekly_worked_hours(cls, db: Session, first_week: int, first_year: int, last_week: int, last_year: int, user_id: int | List[int] = None) -> Sequence[Self]:
        condition = cls._get_static_weeks_condition(first_week, first_year, last_week, last_year)

        q = select(cls).where(condition)

        if user_id:
            q = q.where(cls.UserID == user_id) if isinstance(user_id, int) else q.where(cls.UserID.in_(user_id))

        return db.exec(q).all()

    @classmethod
    def get_monthly_worked_hours(cls, db: Session, first_week: int, first_year: int, last_week: int, last_year: int, user_id: int | List[int] = None) -> pd.DataFrame:
        data = cls.get_weekly_worked_hours(db, first_week, first_year, last_week, last_year, user_id)
        df = pd.DataFrame(data, columns=["UserID", "Week", "Year", "WorkedHours", "PausedCountedHours", "PausedUncountedHours", "BalanceHours", "UpdatedAt"])
        df['Month'] = df.apply(
            lambda row: date.fromisocalendar(int(row['Year']), int(row['Week']), 1).month,
            axis=1
        )
        df['Period'] = df['Year']+'-'+df['Month']
        df.drop(["Week","Year","Month","BalanceHours","UpdatedAt"], axis="columns", inplace=True)
        df = df.groupby(["UserID","Period"]).agg(
            {"WorkedHours": "sum",
             "PausedCountedHours": "sum",
             "PausedUncountedHours": "sum"}
        ).reset_index()
        return df

    @classmethod
    def get_worked_hours_by_week(cls, db: Session, first_week: int, first_year: int, last_week: int, last_year: int, user_id: int | List[int] = None) -> Sequence[Tuple[int, float, float, float]]:
        condition = cls._get_static_weeks_condition(first_week, first_year, last_week, last_year)

        #Query to get all worked hours grouped by user between first and last week
        query = select(cls.UserID, func.sum(cls.WorkedHours).label("WorkedHours"), func.sum(cls.PausedCountedHours).label("PausedCountedHours"), func.sum(cls.PausedUncountedHours).label("PausedUncountedHours")).where(
            condition
        ).group_by(cls.UserID)

        if user_id:
            query = query.where(cls.UserID == user_id) if isinstance(user_id, int) else query.where(cls.UserID.in_(user_id))

        return db.exec(query).all()

    @classmethod
    def get_worked_hours_by_user(cls, db: Session, start_date: PastDate, end_date: PastDate, user_id: int | List[int] = None) -> pd.DataFrame:
        from .WorkLogs import WorkLogTotals
        #Get the first and last weeks numbers by date
        first_week = start_date.isocalendar().week
        first_year = start_date.isocalendar().year
        last_week = end_date.isocalendar().week
        last_year = end_date.isocalendar().year

        worked_hours_week = cls.get_worked_hours_by_week(db, first_week, first_year, last_week, last_year, user_id)
        # Definir nombres de columnas explícitamente
        column_names = ["UserID", "WorkedHours", "PausedCountedHours", "PausedUncountedHours"]
    
        if not worked_hours_week:  # Si no hay resultados
            # Crear DataFrame vacío con estructura correcta
            df = pd.DataFrame(columns=column_names[1:])
            df.index.name = "UserID"
            return df
    
        # Si hay resultados, crear DataFrame con nombres explícitos
        df = pd.DataFrame(worked_hours_week, columns=column_names)
        df.set_index("UserID", inplace=True)
        df.fillna(0, inplace=True)

        #substract the worked days that are not included in the first and last week
        df_f = cls._substract_worked_hours(db, start_date, end_date, first_week, first_year, last_week, last_year, user_id, df)
        df_f = df_f.reindex(user_id if isinstance(user_id, list) else [user_id], fill_value=0)
        df_f.index.name = df.index.name
        df_f.sort_index(inplace=True)
        return df_f


    @classmethod
    def get_weekly_worked_hours_by_user(cls, db: Session, start_date: PastDate, end_date: PastDate, user_id: int | List[int] = None) -> pd.DataFrame:
        # Get the first and last weeks numbers by date
        first_week = start_date.isocalendar().week
        first_year = start_date.isocalendar().year
        last_week = end_date.isocalendar().week
        last_year = end_date.isocalendar().year

        worked_hours = cls.get_weekly_worked_hours(db, first_week, first_year, last_week, last_year, user_id)
        if not worked_hours:
            # If no results, return an empty DataFrame with the correct structure
            return pd.DataFrame(columns=["UserID", "Period", "WorkedHours", "PausedCountedHours", "PausedUncountedHours"])

        df = pd.DataFrame([x.model_dump(mode='python') for x in worked_hours], dtype=str)
        df['Period'] = df['Year'] + '-' + df['WeekNumber']
        df.drop(["WeekNumber", "Year", "BalanceHours", "UpdatedAt"], axis="columns", inplace=True)

        df_f = cls._substract_worked_hours(db, start_date, end_date, first_week, first_year, last_week, last_year, user_id, df)
        return df_f





    def _create(self, db: Session) -> None:
        db.add(self)
        db.commit()
        db.refresh(self)

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.UserID, self.WeekNumber, self.Year)
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


class UserTotalHoursBalance(SQLModel, table=True):
    __tablename__ = "UserTotalHoursBalance"
    UserID: int = Field(foreign_key="Users.UserID", primary_key=True)
    TotalHours: float = Field(default=0)
    TotalPausedCountedHours: float = Field(default=0)
    TotalPausedUncountedHours: float = Field(default=0)
    BalanceHours: float = Field(default=0)
    UpdatedAt: datetype = Field(default_factory=datetime.now)

    user: "Users" = Relationship(back_populates="total_hours_balance")

    @classmethod
    def get(cls, db: Session, user_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.UserID == user_id)).first()

    @classmethod
    def exists(cls, db: Session, user_id: int) -> bool:
        return db.exec(select(cls).where(cls.UserID == user_id)).first() is not None

    def _create(self, db: Session) -> None:
        db.add(self)
        db.commit()
        db.refresh(self)

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.UserID)
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


class UserDepartments(SQLModel, table=True):
    __tablename__ = "UserDepartments"
    UserID: int = Field(foreign_key="Users.UserID", primary_key=True)
    DeptID: int = Field(foreign_key="Departments.DeptID", primary_key=True)
    IsPrimary: bool = Field(default=False)
    AssignedDate: date = Field(default_factory=lambda: date.today(), primary_key=True)
    DeAssignedDate: Optional[date] = Field(default_factory=lambda: date.today().replace(year=date.today().year+20))

    user: "Users" = Relationship(back_populates="departments", sa_relationship_kwargs={"uselist": False})
    department: "Departments" = Relationship(back_populates="users", sa_relationship_kwargs={"uselist": False})

    _logger: logging.Logger = logging.getLogger(__name__)

    @classmethod
    def get(cls, db: Session, user_id: int, dept_id: int, assigned_date: date = None) -> Self | None:
        q = select(cls).where(
            and_(cls.UserID == user_id, cls.DeptID == dept_id)
        )
        if assigned_date:
            q = q.where(cls.AssignedDate == assigned_date)

        return db.exec(q).first()

    @classmethod
    def exists(cls, db: Session, user_id: int, dept_id: int) -> bool:
        return db.exec(select(cls).where(
            and_(cls.UserID == user_id, cls.DeptID == dept_id)
        )).first() is not None

    def _create(self, db: Session) -> Self:
        user_id = self.UserID
        dept_id = self.DeptID
        assigned_date = self.AssignedDate
        db.add(self)
        db.commit()
        try:
            self.UserID
        except Exception as e:
            self._logger.error(f"Error creating UserDepartments: {e}, traceback: {traceback.format_exc()}")
            self = self.get(db, user_id, dept_id, assigned_date)
        db.refresh(self)
        return self

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.UserID, self.DeptID)
        if model_db is None:
            self._create(db)
            return self
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

    def update_or_create(self, db:Session) -> Self:
        model_db = self.get(db, self.UserID, self.DeptID)
        if model_db:
            self.AssignedDate = model_db.AssignedDate
            return model_db.update(db, **self.model_dump(mode='python')) if model_db.IsPrimary != self.IsPrimary else model_db
        else:
            return self._create(db)

    def delete(self, db: Session) -> None:
        db.delete(self)
        db.commit()


class Supervision(SQLModel, table=True):
    __tablename__ = "Supervision"
    SupervisorID: int = Field(foreign_key="Users.UserID", primary_key=True)
    SubordinateID: int = Field(foreign_key="Users.UserID", primary_key=True)
    AssignedDate: date = Field(default=date.today())
    DeAssignedDate: date | None = Field(default=None)

    supervisor: "Users" = Relationship(
            back_populates="subordinates",
            sa_relationship_kwargs={"primaryjoin": "Supervision.SupervisorID == Users.UserID"}
        )
    subordinate: "Users" = Relationship(
            back_populates="supervisors",
            sa_relationship_kwargs={"primaryjoin": "Supervision.SubordinateID == Users.UserID"}
        )

    @classmethod
    def get(cls, db: Session, supervisor_id: int, subordinate_id: int) -> Self | None:
        return db.exec(select(cls).where(
            and_(cls.SupervisorID == supervisor_id, cls.SubordinateID == subordinate_id)
        )).first()

    @classmethod
    def exists(cls, db: Session, supervisor_id: int, subordinate_id: int) -> bool:
        return db.exec(select(cls).where(
            and_(cls.SupervisorID == supervisor_id, cls.SubordinateID == subordinate_id)
        )).first() is not None

    def _create(self, db: Session) -> Self:
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.SupervisorID, self.SubordinateID)
        if model_db is None:
            return self._create(db)
        else:
            return model_db

    def update(self, db: Session, **kwargs) -> Self:
        for key, value in kwargs.items():
            if value is None:
                continue
            setattr(self, key, value)
        db.commit()
        db.refresh(self)
        return self

    def update_or_create(self, db:Session) -> Self:
        model_db = self.get(db, self.SupervisorID, self.SubordinateID)
        if model_db:
            self.AssignedDate = model_db.AssignedDate
            return model_db.update(db, **self.model_dump(mode='python'))
        else:
            return self._create(db)

    def delete(self, db: Session) -> None:
        db.delete(self)
        db.commit()


class Notifications(SQLModel, table=True):
    __tablename__ = "Notifications"
    NotificationID: int = Field(default=None, primary_key=True)
    UserID: int = Field(foreign_key="Users.UserID")
    NotificationType: str = Field(max_length=50)
    NotificationText: str = Field(max_length=255)
    Severity: str = Field(max_length=10)
    IsRead: bool = Field(default=False)
    CreatedAt: datetype = Field(default=datetime.now())

    user: "Users" = Relationship(back_populates="notifications")

    @classmethod
    def get(cls, db: Session, notification_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.NotificationID == notification_id)).first()

    @classmethod
    def exists(cls, db: Session, notification_id: int) -> bool:
        return db.exec(select(cls).where(cls.NotificationID == notification_id)).first() is not None

    def _create(self, db: Session) -> None:
        db.add(self)
        db.commit()
        db.refresh(self)

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.NotificationID)
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
