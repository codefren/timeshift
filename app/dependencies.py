import random
import re
import string
import time, sys
from collections import defaultdict
from fastapi import Depends, HTTPException, status, Request, Response, Query, Security
from fastapi.security import OAuth2PasswordBearer, SecurityScopes
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic.types import datetime as datetype
from sqlalchemy import Enum
from sqlmodel import select, Session
from starlette.middleware.base import BaseHTTPMiddleware
from utils import CONFIG
from jose import jwt, JWTError
from datetime import datetime, timedelta, UTC, time as dttime
from typing import Optional, Annotated, Dict, List
from SQLModels import Users
from db.session import get_session
import logging, sys

# Configuración de JWT
SECRET_KEY = CONFIG.SECRET_KEY
ALGORITHM = CONFIG.SECURITY_ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = CONFIG.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = 7  # Default refresh token expiration
REFRESH_TOKEN_SECRET_KEY = CONFIG.SECRET_KEY + "_refresh"  # Use a different secret for refresh tokens

# OAuth2 scheme para obtener el token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


# Print background
async def log_back(message, logger, level='info'):
    if level == 'info':
        logger.info(message)
    elif level == 'debug':
        logger.debug(message)
    elif level == 'error':
        logger.error(message)
    elif level == 'warning':
        logger.warning(message)
    elif level == 'critical':
        logger.critical(message)
    else:
        logger.info(message)


# Dependencia para obtener la sesión de la base de datos
get_db = get_session

SessionDep = Annotated[Session, Depends(get_db)]


def random_string(length: int) -> str:
    # Create a random string of alphanumeric characters of length
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


# Método para autenticar al usuario
def authenticate_user(db: Session, username: str, password: str):
    user: Users = db.exec(select(Users).where(Users.Email == username, Users.IsInactive == False)).first()
    if not user or not user.verify_password(password):
        return None
    return user


# Crear el token de acceso
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# Crear el token de refresco
def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    
    # Add a type claim to distinguish refresh tokens from access tokens
    to_encode.update({"exp": expire, "token_type": "refresh"})
    
    # Use a different secret key for refresh tokens
    encoded_jwt = jwt.encode(to_encode, REFRESH_TOKEN_SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# Verificar el token de refresco
def verify_refresh_token(refresh_token: str):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # Decode the refresh token using the refresh token secret
        payload = jwt.decode(refresh_token, REFRESH_TOKEN_SECRET_KEY, algorithms=[ALGORITHM])
        
        # Check if this is a refresh token
        token_type = payload.get("token_type")
        if token_type != "refresh":
            raise credentials_exception
        
        # Extract the user ID
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
            
        return user_id
    except JWTError:
        raise credentials_exception


# Dependencia para obtener el usuario actual usando el token
def verify_token(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    return token_data


def get_current_user(db: SessionDep, token: str = Depends(oauth2_scheme)):
    token_data = verify_token(token)
    user = db.exec(select(Users).where(Users.UserID == token_data.username)).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Users not found")
    if user.IsInactive:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


def get_current_user_with_scopes(
        security_scopes: SecurityScopes,
        token: str = Depends(oauth2_scheme),
        db: Session = Depends(get_db)
) -> Users:
    """
    Enhanced version of get_current_user that also checks for required scopes
    """
    if security_scopes.scopes:
        authenticate_value = f'Bearer scope="{security_scopes.scope_str}"'
    else:
        authenticate_value = "Bearer"

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": authenticate_value},
    )

    token_data = verify_token(token)
    user: Users = db.exec(select(Users).where(Users.UserID == token_data.username)).first()
    if user is None:
        raise credentials_exception

    # Check scopes
    for scope in security_scopes.scopes:
        if not user.has_permission(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Not enough permissions. Required scope: {scope}",
                headers={"WWW-Authenticate": authenticate_value},
            )

    return user


def require_scopes(scopes: List[str]):
    """
    Dependency creator for requiring specific scopes
    Usage: @app.get("/endpoint", dependencies=[Depends(require_scopes(["scope1", "scope2"]))])
    """

    async def scope_dependency(
            current_user: Users = Security(get_current_user_with_scopes, scopes=scopes)
    ):
        return current_user

    return scope_dependency


def require_permission(permission: str):
    """Create dependency that checks if current user has the given permission.
    
    Args:
        permission: The permission name to check for
        
    Returns:
        A dependency function that will check if the current user has the specified permission
    
    Example:
        @app.get("/admin/users")
        async def get_users(user = Depends(require_permission("view_users"))):
            # Your code here
            return {"message": "List of users"}
    """

    async def permission_dependency(
        current_user: Users = Depends(get_current_user),
    ):
        if not current_user.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission {permission} required",
            )
        return current_user

    return permission_dependency

def require_any_permission(permissions: List[str]):
    """Create dependency that checks if current user has any of the given permissions.
    
    Args:
        permissions: List of permission names to check for
        
    Returns:
        A dependency function that will check if the current user has any of the specified permissions
    
    Example:
        @app.get("/admin/users")
        async def get_users(user = Depends(require_permission("view_users"))):
            # Your code here
            return {"message": "List of users"}
    """

    async def permission_dependency(
        current_user: Users = Depends(get_current_user),
    ):
        if not current_user.has_any_permission(permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Some permission in {permissions} required",
            )
        return current_user

    return permission_dependency


def scope_router(router_name: str):
    """
    Creates a dependency that checks for appropriate scope based on request method.
    GET requests require read:{router} scope
    POST/PUT/DELETE requests require write:{router} scope
    """
    log = logging.getLogger(__name__)

    async def scope_dependency(
            request: Request,
            current_user: Users = Security(get_current_user_with_scopes),
            db: Session = Depends(get_db)
    ):
        router = router_name.lower()
        method = request.method.upper()

        if method == "GET":
            required_scope = f"read:{router}"
        elif method in ["POST", "PUT", "DELETE", "PATCH"]:
            required_scope = f"write:{router}"
        else:
            raise HTTPException(
                status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
                detail=f"Method {method} not allowed"
            )

        # Check if user has any of the required scopes
        log.debug(f"Checking for scope {required_scope}")
        if not current_user.has_scope(db, required_scope):
            log.warning(f"User {current_user.fldIdUsuario} does not have required scope {required_scope}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Not enough permissions. Required scope: {required_scope}"
            )

        return current_user

    return scope_dependency


# Modelo para autenticación del usuario
class TokenData(BaseModel):
    username: Optional[str | int] = None

    @field_validator('username', mode="before")
    def correct_username_syntax(cls, value) -> str:
        if not value:
            return value
        return value


# Rate Limiter Middleware
class RateLimiterMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.rate_limit_records: Dict[str, List[datetime]] = defaultdict(list)

    def log_message(self, request, message: str, level: str = "info"):
        ip = request.client.host if request.client else "unknown"
        logger = logging.getLogger(__name__)
        log_method = getattr(logger, level, logger.info)
        log_method(f"[{ip}] - {message}")

    async def dispatch(self, request: Request, call_next):
        # Get the client IP
        ip = request.client.host if request.client else "unknown"
        path = request.url.path
        method = request.method

        # Skip rate limiting for certain paths
        skip_paths = ['/docs', '/openapi.json', '/favicon.ico']
        if any(path.startswith(skip_path) for skip_path in skip_paths):
            return await call_next(request)

        # Define rate limits
        time_window = 60  # 1 minute
        max_requests = 120  # Maximum requests per minute

        # Check if IP exceeded rate limit
        current_time = datetime.now(UTC)
        self.rate_limit_records[ip] = [t for t in self.rate_limit_records[ip]
                                       if (current_time - t).total_seconds() < time_window]

        if len(self.rate_limit_records[ip]) >= max_requests:
            self.log_message(request, f"Rate limit exceeded: {ip} - {path} - {method}", "warning")
            return Response(
                content="Too Many Requests",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS
            )

        # Record the request
        self.rate_limit_records[ip].append(current_time)
        self.log_message(request, f"Request: {method} {path} (Remaining: {max_requests - len(self.rate_limit_records[ip])})", "debug")

        # Process the request
        return await call_next(request)


class SortEnum(str, Enum):
    ASC: str = "asc"
    DESC: str = "desc"


class Pagination(BaseModel):
    size: int
    page: int
    order: str = Field(default_factory=lambda: SortEnum.ASC)
    model_config = {
        'arbitrary_types_allowed': True,
    }

    @field_validator('order', mode="before")
    def correct_order_syntax(cls, value):
        if value is None:
            return SortEnum.ASC
        try:
            return SortEnum(value.lower())
        except:
            return SortEnum.ASC


def pagination_params(
        page: int = Query(1, ge=1, required=False, le=50000),
        size: int = Query(100, ge=1, required=False, le=250),
        order: str = Query('ASC', required=False)
):
    return Pagination(page=page, size=size, order=order)


PaginationDep = Annotated[Pagination, Depends(pagination_params)]


class UsersFilters(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    IDNumber: Optional[str] = None
    hired_before: Optional[datetype] = None
    hired_after: Optional[datetype] = None
    job_title: Optional[str] = None
    role: Optional[int] = None
    department: Optional[int] = None
    updated_before: Optional[datetype] = None
    updated_after: Optional[datetype] = None
    create_before: Optional[datetype] = None
    create_after: Optional[datetype] = None
    active: Optional[bool] = None
    has_picture: Optional[bool] = None
    subordinate_of: Optional[int] = None
    supervisor_of: Optional[int] = None
    owes_hours: Optional[bool] = None

    @field_validator('hired_before', mode="before")
    def correct_hired_before(cls, value):
        if not value:
            return value
        try:
            if isinstance(value, str):
                return datetime.fromisoformat(value)
            return value
        except:
            return None

    @field_validator('hired_after', mode="before")
    def correct_hired_after(cls, value):
        if not value:
            return value
        try:
            if isinstance(value, str):
                return datetime.fromisoformat(value)
            return value
        except:
            return None


def users_filters_model(
        name: Optional[str] = Query(None, required=False),
        phone: Optional[str] = Query(None, required=False),
        IDNumber: Optional[str] = Query(None, required=False),
        hired_before: Optional[datetype] = Query(None, required=False),
        hired_after: Optional[datetype] = Query(None, required=False),
        job_title: Optional[str] = Query(None, required=False),
        role: Optional[int] = Query(None, required=False),
        department: Optional[int] = Query(None, required=False),
        updated_before: Optional[datetype] = Query(None, required=False),
        updated_after: Optional[datetype] = Query(None, required=False),
        create_before: Optional[datetype] = Query(None, required=False),
        create_after: Optional[datetype] = Query(None, required=False),
        active: Optional[bool] = Query(None, required=False),
        #schedule: Optional[int] = Query(None, required=False),
        #has_schedule: Optional[bool] = Query(None, required=False),
        has_picture: Optional[bool] = Query(None, required=False),
        subordinate_of: Optional[int] = Query(None, required=False),
        supervisor_of: Optional[int] = Query(None, required=False),
        owes_hours: Optional[bool] = Query(None, required=False)
):
    return UsersFilters(
        name=name,
        phone=phone,
        IDNumber=IDNumber,
        hired_before=hired_before,
        hired_after=hired_after,
        job_title=job_title,
        role=role,
        department=department,
        updated_before=updated_before,
        updated_after=updated_after,
        create_before=create_before,
        create_after=create_after,
        active=active,
        #schedule=schedule,
        #has_schedule=has_schedule,
        has_picture=has_picture,
        subordinate_of=subordinate_of,
        supervisor_of=supervisor_of,
        owes_hours=owes_hours
    )


UsersFiltersDep = Annotated[UsersFilters, Depends(users_filters_model)]


class LocationFilters(BaseModel):
    location_name: Optional[str] = None
    address: Optional[str] = None
    zip_code: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    active: Optional[bool] = None

    @field_validator('location_name', mode="before")
    def correct_location_name(cls, value):
        if not value:
            return value
        return value


def location_filters_model(
        location_name: Optional[str] = Query(None, required=False),
        address: Optional[str] = Query(None, required=False),
        zip_code: Optional[str] = Query(None, required=False),
        city: Optional[str] = Query(None, required=False),
        state: Optional[str] = Query(None, required=False),
        country: Optional[str] = Query(None, required=False),
        active: Optional[bool] = Query(None, required=False)
):
    return LocationFilters(
        location_name=location_name,
        address=address,
        zip_code=zip_code,
        city=city,
        state=state,
        country=country,
        active=active
    )


LocationFiltersDep = Annotated[LocationFilters, Depends(location_filters_model)]


class CompanyFilters(BaseModel):
    tax_id: Optional[str] = None
    social_name: Optional[str] = None
    fiscal_name: Optional[str] = None
    address: Optional[str] = None
    zip_code: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    active: Optional[bool] = None

    @field_validator('social_name', mode="before")
    def correct_name(cls, value):
        if not value:
            return value
        return value


def company_filters_model(
        tax_id: Optional[str] = Query(None, required=False),
        social_name: Optional[str] = Query(None, required=False),
        fiscal_name: Optional[str] = Query(None, required=False),
        address: Optional[str] = Query(None, required=False),
        zip_code: Optional[str] = Query(None, required=False),
        city: Optional[str] = Query(None, required=False),
        state: Optional[str] = Query(None, required=False),
        country: Optional[str] = Query(None, required=False),
        active: Optional[bool] = Query(None, required=False)
):
    return CompanyFilters(
        tax_id=tax_id,
        social_name=social_name,
        fiscal_name=fiscal_name,
        address=address,
        zip_code=zip_code,
        city=city,
        state=state,
        country=country,
        active=active
    )


CompanyFiltersDep = Annotated[CompanyFilters, Depends(company_filters_model)]


class DepartmentFilters(BaseModel):
    dept_name: Optional[str] = None
    location_name: Optional[str] = None
    active: Optional[bool] = None
    subdepartment_of: Optional[int] = None
    parentdepartment_of: Optional[int] = None
    user_is_in: Optional[int] = None

    @field_validator('dept_name', mode="before")
    def correct_name(cls, value):
        if not value:
            return value
        return value


def department_filters_model(
        dept_name: Optional[str] = Query(None, required=False),
        location_name: Optional[str] = Query(None, required=False),
        active: Optional[bool] = Query(None, required=False),
        subdepartment_of: Optional[int] = Query(None, required=False),
        parentdepartment_of: Optional[int] = Query(None, required=False),
        user_is_in: Optional[int] = Query(None, required=False)
):
    return DepartmentFilters(
        dept_name=dept_name,
        location_name=location_name,
        active=active,
        subdepartment_of=subdepartment_of,
        parentdepartment_of=parentdepartment_of,
        user_is_in=user_is_in
    )


DepartmentFiltersDep = Annotated[DepartmentFilters, Depends(department_filters_model)]


class WorkLogFilters(BaseModel):
    user_id: Optional[int] = None
    log_date: Optional[datetype] = None
    log_before: Optional[datetype] = None
    log_after: Optional[datetype] = None
    sort_by: Optional[str] = "WorkLogID"
    is_finished: Optional[bool] = None
    is_approved: Optional[bool] = None
    start_time_before: Optional[dttime] = None
    start_time_after: Optional[dttime] = None
    final_time_before: Optional[dttime] = None
    final_time_after: Optional[dttime] = None
    department_id: Optional[int] = None
    has_shift: Optional[bool] = None
    show_aggregated: Optional[bool] = None

    @field_validator('log_date', 'log_before', 'log_after', mode="before")
    def correct_log_date(cls, value):
        if not value:
            return value
        try:
            if isinstance(value, str):
                return datetime.fromisoformat(value)
            return value
        except:
            raise HTTPException(status_code=400, detail="Invalid date format")

    @field_validator('start_time_before', 'start_time_after','final_time_before','final_time_after', mode="before")
    def correct_hour(cls, value):
        if not value:
            return value
        try:
            if isinstance(value, str):
                return dttime.fromisoformat(value)
            return value
        except:
            return None

    @model_validator(mode="after")
    def model_validate(self):
        #Aggregated parameter must be accompanied with user_id and log_before and log_after or log_date
        if self.show_aggregated and not self.user_id:
            raise ValueError("Can only show aggregated when specifying a user_id")
        if self.show_aggregated and not ((self.log_before and self.log_after) or self.log_date):
            raise ValueError("Can only show aggregated when specifying a valid date period or specific date")
        if self.log_before < self.log_after:
            raise ValueError("End date before start date")
        return self

def worklog_filters_model(
        user_id: Optional[int] = Query(None, required=False),
        log_date: Optional[datetype] = Query(None, required=False),
        log_before: Optional[datetype] = Query(None, required=False),
        log_after: Optional[datetype] = Query(None, required=False),
        sort_by: Optional[str] = Query("WorkLogID", required=False),
        is_finished: Optional[bool] = Query(None, required=False),
        is_approved: Optional[bool] = Query(None, required=False),
        start_time_before: Optional[dttime] = Query(None, required=False),
        start_time_after: Optional[dttime] = Query(None, required=False),
        final_time_before: Optional[dttime] = Query(None, required=False),
        final_time_after: Optional[dttime] = Query(None, required=False),
        department_id: Optional[int] = Query(None, required=False),
        has_shift: Optional[bool] = Query(None, required=False),
        show_aggregated: Optional[bool] = Query(None, required=False),

):
    return WorkLogFilters(
        user_id=user_id,
        log_date=log_date,
        log_before=log_before,
        log_after=log_after,
        sort_by=sort_by,
        is_finished=is_finished,
        is_approved=is_approved,
        start_time_before=start_time_before,
        start_time_after=start_time_after,
        final_time_before=final_time_before,
        final_time_after=final_time_after,
        department_id=department_id,
        has_shift=has_shift,
        show_aggregated=show_aggregated,
    )


WorkLogFiltersDep = Annotated[WorkLogFilters, Depends(worklog_filters_model)]


class ShiftsFilters(BaseModel):
    """Filters for retrieving shifts"""
    shift_id: Optional[int] = None
    user_id: Optional[int] = None
    department_id: Optional[int] = None
    location_id: Optional[int] = None
    status: Optional[str] = None
    is_published: Optional[bool] = None
    show_canceled: Optional[bool] = None
    show_canceled: Optional[bool] = None
    # Date range filters
    date_from: Optional[datetype] = None
    date_to: Optional[datetype] = None
    # Week filters
    week_number: Optional[int] = Field(None, ge=1, le=53)
    year_number: Optional[int] = Field(None, ge=2020, le=2030)
    # Start/End week filters
    start_week: Optional[int] = Field(None, ge=1, le=53)
    end_week: Optional[int] = Field(None, ge=1, le=53)
    start_year: Optional[int] = Field(None, ge=2020, le=2030)
    end_year: Optional[int] = Field(None, ge=2020, le=2030)
    # Sort options
    sort_by: Optional[str] = "Date"
    
    @field_validator('date_from', 'date_to')
    def validate_dates(cls, v):
        """Convert string dates to datetime objects"""
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v).date()
            except ValueError:
                raise ValueError("Date format must be ISO (YYYY-MM-DD)")
        return v.date() if isinstance(v, datetime) else v
    
    @field_validator('status')
    def validate_status(cls, v):
        """Validate shift status"""
        if v is not None:
            valid_statuses = ['Planned', 'Confirmed', 'Canceled', 'Completed', 'Approved', 'Rejected']
            if v not in valid_statuses:
                raise ValueError(f"Status must be one of: {', '.join(valid_statuses)}")
        return v
    
    @model_validator(mode='after')
    def validate_exclusive_date_filters(self):
        """Ensure that only one type of date filtering is used at a time"""
        # Count how many different filter types are being used
        filter_types_used = 0
        
        # Check for date range filters
        has_date_range = bool(self.date_from or self.date_to)
        if has_date_range:
            filter_types_used += 1
        
        # Check for single week filter
        has_single_week = bool(self.week_number or self.year_number)
        if has_single_week:
            filter_types_used += 1
        
        # Check for week range filters
        has_week_range = bool(self.start_week or self.end_week or self.start_year or self.end_year)
        if has_week_range:
            filter_types_used += 1
        
        # Ensure only one type of date filtering is used
        if filter_types_used > 1:
            raise ValueError(
                "Only one type of date filtering can be used at a time: "
                "either date range (date_from/date_to), "
                "single week (week_number/year_number), "
                "or week range (start_week/end_week with start_year/end_year)"
            )
        
        # Validate date range
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be before or equal to date_to")
        
        # Validate week ranges
        if self.start_week and self.end_week:
            start_year = self.start_year or datetime.now().year
            end_year = self.end_year or datetime.now().year
            
            if start_year > end_year:
                raise ValueError("start_year must be before or equal to end_year")
            elif start_year == end_year and self.start_week > self.end_week:
                raise ValueError("start_week must be before or equal to end_week when in the same year")
        
        # Ensure week range has both start and end components
        if has_week_range:
            if (self.start_week or self.end_week) and not (self.start_week and self.end_week):
                raise ValueError("Both start_week and end_week must be provided for week range filtering")

        if self.week_number and not self.year_number:
            self.year_number = datetime.now().year
        
        return self


def shifts_filters_model(
        shift_id: Optional[int] = Query(None, required=False),
        user_id: Optional[int] = Query(None, required=False),
        department_id: Optional[int] = Query(None, required=False),
        location_id: Optional[int] = Query(None, required=False),
        status: Optional[str] = Query(None, required=False),
        is_published: Optional[bool] = Query(None, required=False),
        show_canceled: Optional[bool] = Query(None, required=False),
        date_from: Optional[datetype] = Query(None, required=False),
        date_to: Optional[datetype] = Query(None, required=False),
        week_number: Optional[int] = Query(None, required=False, ge=1, le=53),
        year_number: Optional[int] = Query(None, required=False, ge=2020, le=2030),
        start_week: Optional[int] = Query(None, required=False, ge=1, le=53),
        end_week: Optional[int] = Query(None, required=False, ge=1, le=53),
        start_year: Optional[int] = Query(None, required=False, ge=2020, le=2030),
        end_year: Optional[int] = Query(None, required=False, ge=2020, le=2030),
        sort_by: Optional[str] = Query("Date", required=False)
):
    """Create shifts filters from query parameters"""
    return ShiftsFilters(
        shift_id=shift_id,
        user_id=user_id,
        department_id=department_id,
        location_id=location_id,
        status=status,
        is_published=is_published,
        show_canceled=show_canceled,
        date_from=date_from,
        date_to=date_to,
        week_number=week_number,
        year_number=year_number,
        start_week=start_week,
        end_week=end_week,
        start_year=start_year,
        end_year=end_year,
        sort_by=sort_by
    )


ShiftsFiltersDep = Annotated[ShiftsFilters, Depends(shifts_filters_model)]