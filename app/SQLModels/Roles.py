from sqlmodel import SQLModel, Relationship, Field, Session, select
from typing import Self, Optional, List


class Roles(SQLModel, table=True):
    __tablename__ = "Roles"
    RoleID: int | None = Field(default=None, primary_key=True)
    RoleName: str = Field(max_length=50, unique=True)
    Description: str = Field(max_length=255)

    permissions: List["RolePermissions"] = Relationship(back_populates="role", sa_relationship_kwargs={"lazy": "joined"})
    users: "RoleUsers" = Relationship(back_populates="role", sa_relationship_kwargs={"lazy": "joined"})

    @classmethod
    def get(cls, db: Session, role_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.RoleID == role_id)).first()

    @classmethod
    def exists(cls, db: Session, role_name: str) -> bool:
        return db.exec(select(cls).where(cls.RoleName == role_name)).first() is not None

    @classmethod
    def get_by_name(cls, db: Session, role_name: str) -> Self | None:
        return db.exec(select(cls).where(cls.RoleName == role_name)).first()

    def _create(self, db: Session) -> Self:
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.RoleID) if self.RoleID is not None else None
        if model_db is None:
            return self._create(db)
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


class Permissions(SQLModel, table=True):
    __tablename__ = "Permissions"
    PermissionID: int | None = Field(default=None, primary_key=True)
    PermissionName: str = Field(max_length=50, unique=True)
    Description: str = Field(max_length=255)
    ForFrontend: bool = Field(default=False, description="Indicates if the permission is for frontend use")

    roles: "RolePermissions" = Relationship(back_populates="permission")
    menus: List["PermissionMenus"] = Relationship(back_populates="permission", sa_relationship_kwargs={"lazy": "joined"})

    @classmethod
    def get(cls, db: Session, permission_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.PermissionID == permission_id)).first()

    @classmethod
    def exists(cls, db: Session, permission_name: str) -> bool: 
        return db.exec(select(cls).where(cls.PermissionName == permission_name)).first() is not None

    @classmethod
    def get_by_name(cls, db: Session, permission_name: str) -> Self | None:
        return db.exec(select(cls).where(cls.PermissionName == permission_name)).first()

    def _create(self, db: Session) -> Self:
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def create(self, db: Session) -> Self | None:
        model_db = self.get(db, self.PermissionID) if self.PermissionID is not None else None
        if model_db is None and self.PermissionID is not None:
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

class PermissionMenus(SQLModel, table=True):
    __tablename__ = "PermissionMenus"
    PermissionID: int = Field(primary_key=True, foreign_key="Permissions.PermissionID")
    Menu: str = Field(primary_key=True, max_length=50, description="Menu name associated with the permission")

    permission: "Permissions" = Relationship(back_populates="menus", sa_relationship_kwargs={"uselist": False, "lazy": "joined"})



class RolePermissions(SQLModel, table=True):
    __tablename__ = "RolePermissions"
    RoleID: int = Field(primary_key=True, foreign_key="Roles.RoleID")
    PermissionID: int = Field(primary_key=True, foreign_key="Permissions.PermissionID")

    role: "Roles" = Relationship(back_populates="permissions", sa_relationship_kwargs={"uselist": False, "lazy": "joined"})
    permission: "Permissions" = Relationship(back_populates="roles", sa_relationship_kwargs={"uselist": False, "lazy": "joined"})

    @classmethod
    def get(cls, db: Session, role_id: int, permission_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.RoleID == role_id, cls.PermissionID == permission_id)).first()

    @classmethod
    def exists(cls, db: Session, role_id: int, permission_id: int) -> bool:
        return db.exec(select(cls).where(cls.RoleID == role_id, cls.PermissionID == permission_id)).first() is not None
    
    @classmethod
    def are_related(cls, db: Session, role_id: int, permission_id: int) -> bool:
        return cls.exists(db, role_id, permission_id)

    def _create(self, db: Session) -> Self:
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.RoleID, self.PermissionID) if self.RoleID is not None and self.PermissionID is not None else None
        if model_db is None and self.RoleID is not None and self.PermissionID is not None:
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

class RoleUsers(SQLModel, table=True):
    __tablename__ = "RoleUsers"
    RoleID: int = Field(primary_key=True, foreign_key="Roles.RoleID")
    UserID: int = Field(primary_key=True, foreign_key="Users.UserID")

    role: "Roles" = Relationship(back_populates="users", sa_relationship_kwargs={"uselist": False, "lazy": "joined"})
    user: "Users" = Relationship(back_populates="roles", sa_relationship_kwargs={"uselist": False, "lazy": "joined"})

    @classmethod
    def get(cls, db: Session, role_id: int, user_id: int) -> Self | None:
        return db.exec(select(cls).where(cls.RoleID == role_id, cls.UserID == user_id)).first()

    @classmethod
    def exists(cls, db: Session, role_id: int, user_id: int) -> bool:
        return db.exec(select(cls).where(cls.RoleID == role_id, cls.UserID == user_id)).first() is not None

    @classmethod
    def are_related(cls, db: Session, role_id: int, user_id: int) -> bool:
        return cls.exists(db, role_id, user_id)

    @classmethod
    def get_userid_roles(cls, db: Session, user_id: int) -> List[Roles]:
        return [x.role for x in db.exec(select(cls).where(cls.UserID == user_id)).all()]

    def _create(self, db: Session) -> Self:
        db.add(self)
        db.commit()
        db.refresh(self)
        return self

    def create(self, db: Session) -> Self:
        model_db = self.get(db, self.RoleID, self.UserID) if self.RoleID is not None and self.UserID is not None else None
        if model_db is None and self.RoleID is not None and self.UserID is not None:
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

    def create_or_update(self, db: Session) -> Self:
        existing = self.get(db, self.RoleID, self.UserID)
        if existing:
            return self.update(db, **self.model_dump(mode='python'))
        else:
            return self._create(db)

    def delete(self, db: Session) -> None:
        db.delete(self)
        db.commit()