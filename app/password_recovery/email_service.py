import logging
import smtplib
import threading
import traceback
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from utils.Config import CONFIG


class EmailService:
    """Servicio para enviar correos electrónicos"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.smtp_server = CONFIG.SMTP_SERVER
        self.smtp_port = CONFIG.SMTP_PORT
        self.smtp_username = CONFIG.SMTP_USERNAME
        self.smtp_password = CONFIG.SMTP_PASSWORD
        self.sender_email = CONFIG.SENDER_EMAIL
        self.app_name = CONFIG.APP_NAME
    
    def _create_recovery_email(self, recipient_email: str, recovery_code: str) -> MIMEMultipart:
        """Crea el mensaje de correo electrónico para la recuperación de contraseña"""
        message = MIMEMultipart()
        message["From"] = f"{self.app_name} <{self.sender_email}>"
        message["To"] = recipient_email
        message["Subject"] = f"Recuperación de contraseña - {self.app_name}"
        
        # Crear el contenido HTML del correo
        html_content = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ text-align: center; padding: 20px 0; }}
                .content {{ padding: 20px; background-color: #f9f9f9; border-radius: 5px; }}
                .code {{ font-size: 24px; font-weight: bold; text-align: center; 
                         padding: 15px; background-color: #eaeaea; margin: 20px 0; }}
                .footer {{ text-align: center; font-size: 12px; color: #666; padding: 20px 0; }}
                .button {{ display: inline-block; padding: 10px 20px; 
                          background-color: #3498db; color: white; 
                          text-decoration: none; border-radius: 5px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>Recuperación de Contraseña</h2>
                </div>
                <div class="content">
                    <p>Hemos recibido una solicitud para restablecer la contraseña de su cuenta en {self.app_name}.</p>
                    <p>Su código de recuperación es:</p>
                    <div class="code">{recovery_code}</div>
                    <p>Si no solicitó este cambio, puede ignorar este correo electrónico y su contraseña seguirá siendo la misma.</p>
                    <p>Este código expirará en 5 minutos por razones de seguridad.</p>
                </div>
                <div class="footer">
                    <p>Este es un correo electrónico automático, por favor no responda.</p>
                    <p>&copy; {self.app_name} {datetime.now().year}</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        message.attach(MIMEText(html_content, "html"))
        self.logger.debug(f"Mensaje de recuperación creado para {recipient_email}")
        return message
    
    def send_recovery_email(self, recipient_email: str, recovery_code: str) -> None:
        """
        Envía un correo electrónico con el código de recuperación de contraseña de forma asíncrona
        
        Args:
            recipient_email: Correo electrónico del destinatario
            recovery_code: Código de recuperación generado
            
        Returns:
            none
        """
        self.logger.debug(f"Recovery email process started for {recipient_email}")
        thread = threading.Thread(target=self._send_recovery_email,args=[recipient_email, recovery_code])
        thread.start()
        self.logger.debug(f"Recovery email process started in thread {thread.name} for {recipient_email}")

    def _send_recovery_email(self, recipient_email: str, recovery_code: str) -> bool:
        """
                Envía un correo electrónico con el código de recuperación de contraseña

                Args:
                    recipient_email: Correo electrónico del destinatario
                    recovery_code: Código de recuperación generado

                Returns:
                    bool: True si el correo se envió correctamente, False en caso contrario
                """
        try:

            # Crear el mensaje
            message = self._create_recovery_email(recipient_email, recovery_code)
            self.logger.debug(f"Recovery email created for {recipient_email}")

            # Conectar al servidor SMTP y enviar el correo
            with (smtplib.SMTP_SSL(self.smtp_server, self.smtp_port) if CONFIG.SMTP_SSL else smtplib.SMTP(self.smtp_server, self.smtp_port))as server:
                server.starttls() if CONFIG.SMTP_TLS else None # Secure the connection
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(message)

            self.logger.info(f"Correo de recuperación enviado a {recipient_email}")
            return True

        except Exception as e:
            self.logger.error(f"Error al enviar correo de recuperación a {recipient_email}: {str(e)}")
            self.logger.critical(f"Error al enviar correo de recuperación a {recipient_email}: {str(e)}, traceback: {traceback.format_exc()}")
            return False


# Instancia singleton del servicio de email
email_service = EmailService()
