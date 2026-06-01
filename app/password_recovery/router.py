import logging
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session

from dependencies import get_db
from SQLModels.Users import Users
from SQLModels.PasswordRecovery import PasswordRecovery
from .schemas import (
    PasswordRecoveryRequest,
    PasswordRecoveryResponse,
    ResetPasswordRequest,
    ResetPasswordResponse, PasswordCodeRequest
)
from .email_service import email_service


class PasswordRecoveryController:
    """Controlador para las rutas de recuperación de contraseña"""
    
    def __init__(self):
        self.router = APIRouter(prefix="/api/password", tags=["password"])
        self.logger = logging.getLogger(__name__)
        
        # Registrar las rutas
        self.router.add_api_route(
            "/request-recovery",
            self.request_recovery,
            methods=["POST"],
            response_model=PasswordRecoveryResponse
        )

        self.router.add_api_route(
            "/check-code",
            self.check_code,
            methods=["POST"],
            response_model=PasswordRecoveryResponse
        )
        
        self.router.add_api_route(
            "/reset-password",
            self.reset_password,
            methods=["POST"],
            response_model=ResetPasswordResponse
        )
    
    async def request_recovery(
        self,
        request: PasswordRecoveryRequest,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_db)
    ) -> PasswordRecoveryResponse:
        """
        Endpoint para solicitar la recuperación de contraseña.
        Verifica si el email existe y envía un correo con el código de recuperación.
        """
        self.logger.info(f"Solicitud de recuperación de contraseña para: {request.email}")
        
        # Verificar si el email existe en la base de datos
        user = Users.get_by_email(db, request.email)
        if not user:
            # Por seguridad, no indicamos si el email existe o no
            self.logger.warning(f"Intento de recuperación para email no existente: {request.email}")
            return PasswordRecoveryResponse(
                message="Si el email existe en nuestra base de datos, recibirás un correo con instrucciones para recuperar tu contraseña.",
                success=True
            )
        
        # Generar código de recuperación
        recovery = PasswordRecovery.create_recovery(db, user.UserID, request.email)
        
        # Enviar email en segundo plano para no bloquear la respuesta
        background_tasks.add_task(
            email_service.send_recovery_email,
            request.email,
            recovery.RecoveryCode
        )
        
        return PasswordRecoveryResponse(
            message="Si el email existe en nuestra base de datos, recibirás un correo con instrucciones para recuperar tu contraseña.",
            success=True
        )

    async def check_code(self,
                   request: PasswordCodeRequest,
                         db: Session = Depends(get_db),
                         ) -> PasswordRecoveryResponse:

        recovery = PasswordRecovery.validate_code(db, request.email, request.recovery_code)
        if not recovery:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Código de recuperación inválido o expirado"
            )

        return PasswordRecoveryResponse(
            message="Código de recuperación válido",
            success=True
        )

    async def reset_password(
        self,
        request: ResetPasswordRequest,
        db: Session = Depends(get_db)
    ) -> ResetPasswordResponse:
        """
        Endpoint para restablecer la contraseña con el código de recuperación.
        """
        self.logger.info(f"Solicitud de restablecimiento de contraseña para: {request.email}")
        
        # Verificar si el código de recuperación es válido
        recovery = PasswordRecovery.validate_code(db, request.email, request.recovery_code)
        if not recovery:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Código de recuperación inválido o expirado"
            )
        
        # Obtener el usuario
        user = Users.get_by_email(db, request.email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Usuario no encontrado"
            )
        
        # Actualizar la contraseña
        from passlib.hash import bcrypt
        user.Password = bcrypt.hash(request.new_password)
        db.add(user)
        
        # Marcar el código como utilizado
        recovery.mark_as_used(db)
        
        # Confirmar los cambios
        db.commit()
        
        self.logger.info(f"Contraseña restablecida exitosamente para: {request.email}")
        
        return ResetPasswordResponse(
            message="Contraseña restablecida exitosamente",
            success=True
        )


# Crear instancia del controlador
password_recovery_controller = PasswordRecoveryController()
router = password_recovery_controller.router
