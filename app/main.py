import os
from contextlib import asynccontextmanager
from datetime import timedelta, datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, status, BackgroundTasks, Query
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi import Response
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse
from fastapi.openapi.docs import get_swagger_ui_html

from utils import setup_logging
from utils.Config import CONFIG
from pydantic import BaseModel
from sqlalchemy.orm import Session
import logging, traceback
from db.session import init_db, engine
from db.create_first_data import create_first_data
from SQLModels.Users import Users
from fastapi.staticfiles import StaticFiles

setup_logging()
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting application...")
    try:
        logger.info("📦 Initializing database...")
        init_db()
        logger.info("✅ Database initialized successfully")
        create_first_data(engine)
        logger.info("✅ First data created successfully")
        logger.info("✅ Application startup completed")
        yield
    except Exception as e:
        logger.error(f"❌ Application startup failed: {str(e)}")
        raise e
    finally:
        try:
            logger.info("🧹 Cleaning up resources...")
            # Cerrar conexiones de base de datos
            engine.dispose()
            logger.info("✅ Cleanup completed")
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {str(e)}")


app = FastAPI(lifespan=lifespan, docs_url=None, openapi_url=None)
logger = logging.getLogger("init")
logger.info("FastAPI app created")


@app.middleware("http")
async def log_request_exception(request, call_next):
    logger_exc = logging.getLogger("Exception")
    try:
        response = await call_next(request)
        return response
    except ValueError as e:
        error_trace = traceback.format_exc()
        logger_exc.error(f"Error de validación: {str(e)}\n{error_trace}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"message": str(e)})
    except Exception as e:
        error_trace = traceback.format_exc()
        logger_exc.error(f"Error interno del servidor: {str(e)}\n{error_trace}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": "Servicio temporalmente no disponible, porfavor reintente más tarde"})


from dependencies import (
    get_db,
    verify_token,
    get_current_user,
    oauth2_scheme,
    create_access_token,
    authenticate_user,
    log_back,
    RateLimiterMiddleware,
    create_refresh_token,
    verify_refresh_token,
    require_permission,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:59835",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)
logger.info("CORS middleware added")

app.add_middleware(RateLimiterMiddleware)

from work_logs import router as work_logs_router
from users import router as users_router
from companies import router as companies_router
from locations import router as locations_router
from password_recovery import router as password_recovery_router
from shifts import router as shifts_router
from schedules import router as schedules_router
from absences import router as absences_router
from holidays import router as holidays_router
app.include_router(work_logs_router.router)
app.include_router(users_router.router)
app.include_router(companies_router.router)
app.include_router(locations_router.router)
app.include_router(password_recovery_router)
app.include_router(shifts_router.router)
app.include_router(schedules_router.router)
app.include_router(absences_router.router)
app.include_router(holidays_router.router)

'''# New tenant-aware routers
from users.tenant_router import router as tenant_users_router
from work_logs.tenant_router import router as tenant_work_logs_router
app.include_router(tenant_users_router)
app.include_router(tenant_work_logs_router)'''

# Swagger UI and OpenAPI with permission check
@app.get("/docs", include_in_schema=False)
def custom_swagger_ui(): # current_user: Users = Depends(require_permission("view:docs"))
    return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{CONFIG.APP_NAME or 'API'} Docs")


@app.get("/openapi.json", include_in_schema=False)
def custom_openapi(): #current_user: Users = Depends(require_permission("view:docs"))
    return JSONResponse(app.openapi())

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    user_id: int
    expires: datetime
    refresh_expires: datetime
    permissions: List[str]


class RefreshRequest(BaseModel):
    refresh_token: str


# Ruta para obtener el token de acceso
@app.post("/api/token", response_model=Token)
def login_for_access_token(bac: BackgroundTasks,
                           resp: Response, form_data: OAuth2PasswordRequestForm = Depends(),
                           db: Session = Depends(get_db),
                           remember: bool = Query(False, description="Remember me for 30 days")):
    logger = logging.getLogger("__name__")
    bac.add_task(log_back, f"Login request for user {form_data.username}", logger, 'info')
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create access token with short expiration (e.g., 15 minutes)
    access_token_expires = timedelta(minutes=CONFIG.ACCESS_TOKEN_EXPIRE_MINUTES if not remember else 30 * 24 * 60)  # 30 days if remember is True
    access_token = create_access_token(
        data={"sub": str(user.UserID)}, expires_delta=access_token_expires
    )
    
    # Create refresh token with longer expiration (e.g., 7 days or 30 days)
    refresh_token_expires = timedelta(days=7 if not remember else 30)  # 7 days if remember is False, 30 days if True
    refresh_token = create_refresh_token(
        data={"sub": str(user.UserID)}, expires_delta=refresh_token_expires
    )
    
    bac.add_task(log_back, f"Access token created for user {form_data.username}", logger, 'debug')
    resp.set_cookie(key='auth_token', value=access_token)
    resp.set_cookie(key='expires_at', value=(datetime.now(timezone.utc) + access_token_expires).isoformat())
    resp.set_cookie(key='refresh_expires_at', value=(datetime.now(timezone.utc) + refresh_token_expires).isoformat())
    resp.set_cookie(key='refresh_token', value=refresh_token)
    resp.set_cookie(key='user_id', value=user.UserID)
    return {
        "access_token": access_token, 
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user_id": user.UserID, 
        "expires": datetime.now(timezone.utc) + access_token_expires,
        "refresh_expires": datetime.now(timezone.utc) + refresh_token_expires,
        "permissions": user.get_permissions()
    }


@app.post("/api/refresh-token", response_model=Token)
def refresh_access_token(refresh_request: RefreshRequest, db: Session = Depends(get_db)):
    logger = logging.getLogger("__name__")
    
    try:
        # Verify the refresh token
        user_id = verify_refresh_token(refresh_request.refresh_token)
        
        # Get the user from the database
        from SQLModels.Users import Users
        user: Optional[Users] = db.query(Users).filter(Users.UserID == user_id).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Create new access token
        access_token_expires = timedelta(minutes=CONFIG.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": str(user.UserID)}, expires_delta=access_token_expires
        )
        
        # Create new refresh token
        refresh_token_expires = timedelta(days=7)
        refresh_token = create_refresh_token(
            data={"sub": str(user.UserID)}, expires_delta=refresh_token_expires
        )
        
        logger.info(f"Tokens refreshed for user {user.UserID}")
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user_id": user.UserID,
            "expires": datetime.now(timezone.utc) + access_token_expires,
            "refresh_expires": datetime.now(timezone.utc) + refresh_token_expires,
            "permissions": user.get_permissions()
        }
    except Exception as e:
        logger.error(f"Token refresh error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )


@app.get("/api/verify-token/{token}", dependencies=[])
async def verify_user_token(token: str):
    verify_token(token=token)
    return {"message": "Token is valid"}


@app.get("/api/users/me/")
def read_users_me(current_user: Users = Depends(get_current_user)):
    return current_user

@app.get("/{file_path:path}", include_in_schema=False)
async def read_static(file_path: str):
    # Si el archivo existe en static, lo devolvemos
    static_file = os.path.join("static", file_path)
    if os.path.isfile(static_file):
        return FileResponse(static_file)
    
    # Si es una ruta de frontend no encontrada, devolvemos index.html para permitir
    # que el enrutamiento del lado del cliente de React funcione
    logger.debug(f"static file not found: {static_file}")
    joined_path = os.path.join(static_file,'index.html')
    return FileResponse("static/index.html") if not os.path.isfile(joined_path) else FileResponse(joined_path)

app.mount("/", StaticFiles(directory="static", html=True), name="static")