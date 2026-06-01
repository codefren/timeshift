from pydantic import BaseModel, EmailStr, field_validator
from typing import Dict, Any, Optional


class PasswordRecoveryRequest(BaseModel):
    """Esquema para solicitud de recuperación de contraseña"""
    email: EmailStr

class PasswordCodeRequest(BaseModel):
    """
    Esquema para la solicitud de comprobación de código de recuperación
    """
    email: EmailStr
    recovery_code: str

class PasswordRecoveryResponse(BaseModel):
    """Esquema para respuesta de solicitud de recuperación de contraseña"""
    message: str
    success: bool


class ResetPasswordRequest(BaseModel):
    """Esquema para solicitud de cambio de contraseña"""
    email: EmailStr
    recovery_code: str
    new_password: str
    confirm_password: str
    
    @field_validator('new_password')
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Valida que la contraseña cumpla con requisitos mínimos de seguridad"""
        if len(v) < 8:
            raise ValueError("La contraseña debe tener al menos 8 caracteres")
        
        has_upper = any(c.isupper() for c in v)
        has_lower = any(c.islower() for c in v)
        has_digit = any(c.isdigit() for c in v)
        has_special = any(not c.isalnum() for c in v)
        
        if not (has_upper and has_lower and has_digit):
            raise ValueError("La contraseña debe contener al menos una letra mayúscula, una minúscula y un número")
        
        return v
    
    @field_validator('confirm_password')
    @classmethod
    def passwords_match(cls, v: str, info: Dict[str, Any]) -> str:
        """Valida que las contraseñas coincidan"""
        if 'new_password' in info.data and v != info.data['new_password']:
            raise ValueError("Las contraseñas no coinciden")
        return v


class ResetPasswordResponse(BaseModel):
    """Esquema para respuesta de cambio de contraseña"""
    message: str
    success: bool
