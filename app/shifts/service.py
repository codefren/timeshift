import logging
import traceback
from datetime import datetime, date, timedelta, time as datetime_time
from typing import List, Optional
from calendar import monthrange
import calendar

from sqlmodel import Session, select, and_, or_
from sqlalchemy import func, extract

from SQLModels import Shifts, ShiftStatus, Users
from dependencies import ShiftsFilters, Pagination


class ShiftsService:
    """Service class for handling shift operations"""

    _log = logging.getLogger(__name__)
    
    @staticmethod
    def apply_permission_filters(query, current_user: Users):
        """
        Apply permission-based filters to the shifts query.
        
        Args:
            query: SQLAlchemy query object
            current_user: The current authenticated user
            
        Returns:
            Modified query with permission-based filters applied
        """
        # Check permissions in order of precedence
        if current_user.has_permission("view:All") or current_user.has_permission("read:Shifts"):
            # Can view all shifts - no additional filtering needed
            return query
        
        elif current_user.has_permission("read:DepartmentShifts"):
            # Can view shifts from their primary department
            if current_user.departments:
                # Get user's primary department
                primary_dept = next(
                    (d for d in current_user.departments 
                     if d.IsPrimary and (d.DeAssignedDate is None or date.today() < d.DeAssignedDate)), 
                    None
                )
                if primary_dept:
                    query = query.where(Shifts.DepartmentID == primary_dept.DepartmentID)
                else:
                    # User has no primary department, can only see own shifts
                    query = query.where(Shifts.UserID == current_user.UserID)
            else:
                # User has no departments, can only see own shifts
                query = query.where(Shifts.UserID == current_user.UserID)
        
        elif current_user.has_permission("read:OwnShifts"):
            # Can only view their own shifts
            query = query.where(Shifts.UserID == current_user.UserID)
        
        else:
            # No valid permission, return empty result set
            query = query.where(Shifts.UserID == -1)  # This will return no results
        
        return query
    
    @staticmethod
    def get_week_date_range(year: int, week: int) -> tuple[date, date]:
        """Get the start and end date of a given week"""
        monday = date.fromisocalendar(year, week, 1)  # 1 = Lunes
        sunday = date.fromisocalendar(year, week, 7)  # 7 = Domingo
        return monday, sunday
    
    @classmethod
    def get_shifts(
        cls,
        db: Session,
        filters: ShiftsFilters,
        pagination: Pagination,
        current_user: Users
    ) -> tuple[List[Shifts], int]:
        """Get shifts with filters and pagination"""
        
        query = select(Shifts)
        
        # Apply permission-based filters first
        query = cls.apply_permission_filters(query, current_user)
        
        conditions = []
        
        # Basic filters
        exitt = False
        while exitt is False:
            if filters.shift_id:
                conditions.append(Shifts.ShiftID == filters.shift_id)
                exitt = True
                continue

            if filters.user_id:
                conditions.append(Shifts.UserID == filters.user_id)

            if filters.department_id:
                conditions.append(Shifts.DepartmentID == filters.department_id)

            if filters.location_id:
                conditions.append(Shifts.LocationID == filters.location_id)

            if filters.status:
                conditions.append(Shifts.Status == filters.status)

            if filters.is_published is not None:
                conditions.append(Shifts.IsPublished == filters.is_published)

            if filters.show_canceled is not None:
                if filters.show_canceled is True:
                    conditions.append(Shifts.Status == ShiftStatus.Canceled)
                else:
                    conditions.append(Shifts.Status != ShiftStatus.Canceled)

            # Date range filters
            if filters.date_from:
                conditions.append(Shifts.Date >= filters.date_from)

            if filters.date_to:
                conditions.append(Shifts.Date <= filters.date_to)

            # Week-based filters
            if filters.week_number and filters.year_number:
                week_start, week_end = cls.get_week_date_range(filters.year_number, filters.week_number)
                conditions.append(and_(
                    Shifts.Date >= week_start,
                    Shifts.Date <= week_end
                ))

            # Week range filters
            if filters.start_week and filters.end_week:
                start_year = filters.start_year or filters.year_number or datetime.now().year
                end_year = filters.end_year or filters.year_number or datetime.now().year

                start_week_start, _ = cls.get_week_date_range(start_year, filters.start_week)
                _, end_week_end = cls.get_week_date_range(end_year, filters.end_week)

                conditions.append(and_(
                    Shifts.Date >= start_week_start,
                    Shifts.Date <= end_week_end
                ))
            exitt = True
        # Apply conditions
        if conditions:
            query = query.where(and_(*conditions))
        
        # Get total count for pagination
        count_query = select(func.count()).select_from(Shifts)
        if conditions:
            count_query = count_query.where(and_(*conditions))
        total_count = db.exec(count_query).first()
        
        # Apply sorting
        sort_column = getattr(Shifts, filters.sort_by, Shifts.Date)
        if pagination.order.upper() == 'DESC':
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())
        
        # Apply pagination
        offset = (pagination.page - 1) * pagination.size
        query = query.offset(offset).limit(pagination.size)
        
        shifts = db.exec(query).all()
        return shifts, total_count
    
    @staticmethod
    def get_shift_by_id(db: Session, shift_id: int, current_user: Users = None) -> Optional[Shifts]:
        """Get a single shift by ID with permission checking"""
        query = select(Shifts).where(Shifts.ShiftID == shift_id)
        
        # Apply permission filters if current_user is provided
        if current_user:
            query = ShiftsService.apply_permission_filters(query, current_user)
        
        return db.exec(query).first()
    
    @staticmethod
    def update_shift(
        db: Session,
        shift_id: int,
        current_user: Users,
        **update_data
    ) -> Optional[Shifts]:
        """Update a shift"""
        shift = ShiftsService.get_shift_by_id(db, shift_id, current_user)
        if not shift:
            return None
        
        # Filter out None values
        update_data = {k: v for k, v in update_data.items() if v is not None}
        
        if update_data:
            return shift.update(db, **update_data)
        
        return shift
    
    @staticmethod
    def cancel_shift(db: Session, shift_id: int, current_user: Users) -> Optional[Shifts]:
        """Cancel a shift (soft delete)"""
        shift = ShiftsService.get_shift_by_id(db, shift_id, current_user)
        if not shift:
            return None
        
        return shift.soft_delete(db)

    @staticmethod
    def cancel_shifts_batch(
        db: Session,
        shift_ids: List[int],
        current_user: Users
    ) -> List[Optional[Shifts]]:
        """Cancel multiple shifts"""
        cancelled_shifts = []
        for shift_id in shift_ids:
            cancelled_shift = ShiftsService.get_shift_by_id(db, shift_id, current_user)
            if cancelled_shift:
                cancelled_shifts.append(cancelled_shift.soft_delete(db))

        return cancelled_shifts
        
    @classmethod
    def duplicate_shifts_by_week(
        cls,
        db: Session,
        department_id: int,
        source_week: int,
        source_year: int,
        target_week: int,
        target_year: int,
        current_user: Users
    ) -> List[Shifts]:
        """
        Duplicate shifts from a source week to a target week for a specific department.
        
        Args:
            db: Database session
            department_id: Department ID to filter shifts
            source_week: Source week number
            source_year: Source year
            target_week: Target week number
            target_year: Target year
            current_user: Current authenticated user
            
        Returns:
            List of newly created shifts
        """
        # Get start and end dates of source week
        source_start, source_end = cls.get_week_date_range(source_year, source_week)
        
        # Get start and end dates of target week
        target_start, target_end = cls.get_week_date_range(target_year, target_week)
        
        # Calculate the day difference between source and target weeks
        day_diff = (target_start - source_start).days
        
        # Get all shifts from source week for the specified department
        filters = ShiftsFilters(
            department_id=department_id,
            week_number=source_week,
            year_number=source_year,
            status=None,  # Include all statuses except canceled
            show_canceled=False  # Don't include canceled shifts
        )
        pagination = Pagination(page=1, size=1000)  # Use a large size to get all shifts
        
        source_shifts, _ = cls.get_shifts(db, filters, pagination, current_user)
        
        # Create new shifts for the target week
        new_shifts = []
        for source_shift in source_shifts:
            # Calculate new date by adding the day difference
            new_date = source_shift.Date + timedelta(days=day_diff)
            
            # Skip if the new date is outside the target week
            if not (target_start <= new_date <= target_end):
                continue
            
            # Create a new shift with the same properties but new dates
            try:
                new_shift = Shifts.create(
                    db=db,
                    UserID=source_shift.UserID,
                    DepartmentID=source_shift.DepartmentID,
                    LocationID=source_shift.LocationID,
                    ScheduleID=source_shift.ScheduleID,
                    Date=new_date,
                    StartTime=source_shift.StartTime,
                    EndTime=source_shift.EndTime,
                    BreakTime=source_shift.BreakTime,
                    IsPublished=True,
                    Status=ShiftStatus.Planned,
                    CreatedBy=current_user.UserID
                )
                new_shifts.append(new_shift)
            except ValueError as e:
                # Skip this shift if there's a conflict
                cls._log.error(f"Error duplicating shift {source_shift.ShiftID}: {str(e)}, traceback: {traceback.format_exc()}")
                continue
        
        return new_shifts