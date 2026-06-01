import logging
from datetime import datetime, timedelta
import secrets
import random
from typing import Optional, Self
from sqlmodel import SQLModel, Field, Session, select
from pydantic.types import datetime as datetype


class PasswordRecovery(SQLModel, table=True):
    """Modelo para almacenar códigos de recuperación de contraseña"""
    __tablename__ = "PwdRecoveries"
    
    RecoveryID: int | None = Field(default=None, primary_key=True)
    UserID: int = Field(foreign_key="Users.UserID", index=True)
    Email: str = Field(index=True, max_length=255)
    RecoveryCode: str = Field(max_length=64)
    CreatedAt: datetype = Field(default_factory=datetime.now)
    ExpiresAt: datetype = Field()
    IsUsed: bool = Field(default=False)
    
    @classmethod
    def generate_code(cls) -> str:
        """Genera un código de recuperación numérico simple de 6 dígitos"""
        return ''.join(str(random.randint(0, 9)) for _ in range(6))
    
    @classmethod
    def create_recovery(cls, db: Session, user_id: int, email: str, expiry_minutes: int = 5) -> Self:
        """Crea un nuevo registro de recuperación de contraseña"""
        # Desactivar códigos anteriores del mismo usuario
        db.exec(
            select(cls)
            .where(cls.UserID == user_id, cls.IsUsed == False)
        ).all()
        
        for old_recovery in db.exec(
            select(cls)
            .where(cls.UserID == user_id, cls.IsUsed == False)
        ).all():
            old_recovery.IsUsed = True
            db.add(old_recovery)
        
        # Crear nuevo código
        recovery = cls(
            UserID=user_id,
            Email=email,
            RecoveryCode=cls.generate_code(),
            ExpiresAt=datetime.now() + timedelta(minutes=expiry_minutes)
        )
        
        db.add(recovery)
        db.commit()
        db.refresh(recovery)
        return recovery
    
    @classmethod
    def validate_code(cls, db: Session, email: str, code: str) -> Optional[Self]:
        """Valida si un código de recuperación es válido y no ha expirado"""
        recovery = db.exec(
            select(cls)
            .where(
                cls.Email == email,
                cls.RecoveryCode == code,
                cls.IsUsed == False,
                cls.ExpiresAt > datetime.now()
            )
        ).first()
        
        return recovery
    
    def mark_as_used(self, db: Session) -> None:
        """Marca el código como utilizado"""
        self.IsUsed = True
        db.add(self)
        db.commit()
