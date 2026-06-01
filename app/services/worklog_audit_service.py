"""
Worklog Audit Service for tracking modifications to worklogs and worklog lines.
Provides comprehensive audit trail functionality for the TimeShift application.
"""

import datetime
import json
from typing import Dict, Any, List, Optional, Tuple
from sqlmodel import Session
from SQLModels.WorkLogs import (
    WorkLogs, WorkLogLines, WorkLogAudit, WorkLogLineAudit, 
    AuditActionType, WorkLogTotals
)
from SQLModels.UserShifts import Shifts
import logging

log = logging.getLogger(__name__)

class WorkLogAuditService:
    """Service for managing worklog audit trails"""
    
    @staticmethod
    def capture_worklog_changes(
        db: Session,
        worklog_id: int,
        modified_by_user_id: int,
        old_worklog: WorkLogs,
        new_data: Dict[str, Any],
        reason: str = ""
    ) -> List[WorkLogAudit]:
        """
        Capture changes to a worklog by comparing old and new values.
        
        Args:
            db: Database session
            worklog_id: ID of the worklog being modified
            modified_by_user_id: ID of user making the changes
            old_worklog: Current worklog state before changes
            new_data: Dictionary of new values to be applied
            reason: Optional reason for the changes
            
        Returns:
            List of created audit records
        """
        audit_records = []
        
        # Calculate old start/end times and totals
        old_start_time = None
        old_end_time = None
        old_worked_hours = 0
        old_pause_hours = 0
        old_dept_id = None
        
        if old_worklog.lines:
            old_start_time = min(line.StartTime for line in old_worklog.lines if not line.IsPause)
            old_end_time = max(line.EndTime for line in old_worklog.lines if line.EndTime and not line.IsPause) if old_worklog.lines and old_worklog.lines[-1].EndTime else None
            
            for line in old_worklog.lines:
                if line.LoggedHours:
                    if line.IsPause:
                        old_pause_hours += line.LoggedHours
                    else:
                        old_worked_hours += line.LoggedHours
        
        if old_worklog.shift:
            old_dept_id = old_worklog.shift.DepartmentID
        
        # Calculate new values from new_data
        new_start_time = new_data.get('start_datetime').time() if new_data.get('start_datetime') else None
        new_end_time = new_data.get('end_datetime').time() if new_data.get('end_datetime') else None
        new_dept_id = new_data.get('dept_id')
        
        # Calculate new worked/pause hours from pauses
        new_worked_hours = 0
        new_pause_hours = 0
        
        if new_start_time and new_end_time:
            # Calculate total time
            start_dt = datetime.datetime.combine(datetime.date.today(), new_start_time)
            end_dt = datetime.datetime.combine(datetime.date.today(), new_end_time)
            total_hours = (end_dt - start_dt).total_seconds() / 3600
            
            # Subtract pause hours
            for pause in new_data.get('pauses', []):
                pause_start = datetime.datetime.combine(datetime.date.today(), pause.start_time)
                pause_end = datetime.datetime.combine(datetime.date.today(), pause.end_time)
                pause_duration = (pause_end - pause_start).total_seconds() / 3600
                new_pause_hours += pause_duration
            
            new_worked_hours = total_hours - new_pause_hours
        
        # Track all changes
        changes_to_track = [
            ('StartTime', old_start_time, new_start_time),
            ('EndTime', old_end_time, new_end_time),
            ('DepartmentID', old_dept_id, new_dept_id),
            ('WorkedHours', old_worked_hours, new_worked_hours),
            ('PauseHours', old_pause_hours, new_pause_hours)
        ]
        
        # Add traditional worklog fields
        trackable_fields = {
            'ShiftID': 'shift_id',
            'IsFinished': 'is_finished', 
            'IsApproved': 'is_approved',
            'LogDate': 'log_date'
        }
        
        for db_field, api_field in trackable_fields.items():
            if api_field in new_data:
                old_value = getattr(old_worklog, db_field)
                new_value = new_data[api_field]
                changes_to_track.append((db_field, old_value, new_value))
        
        # Create audit records for all changes
        for field_name, old_value, new_value in changes_to_track:
            if old_value != new_value:
                audit = WorkLogAudit.create_audit_record(
                    db=db,
                    worklog_id=worklog_id,
                    modified_by_user_id=modified_by_user_id,
                    action_type=AuditActionType.UPDATE,
                    field_name=field_name,
                    old_value=old_value,
                    new_value=new_value,
                    reason=reason
                )
                audit_records.append(audit)
        
        return audit_records
    
    @staticmethod
    def capture_line_changes(
        db: Session,
        worklog_id: int,
        modified_by_user_id: int,
        old_lines: List[WorkLogLines],
        new_lines_data: List[Dict[str, Any]],
        reason: str = ""
    ) -> List[WorkLogLineAudit]:
        """
        Capture changes to worklog lines by comparing old and new line data.
        
        Args:
            db: Database session
            worklog_id: ID of the worklog
            modified_by_user_id: ID of user making changes
            old_lines: Current worklog lines before changes
            new_lines_data: List of new line data
            reason: Optional reason for changes
            
        Returns:
            List of created audit records
        """
        audit_records = []
        
        # Create lookup for old lines by line ID
        old_lines_dict = {line.WorkLogLineID: line for line in old_lines}
        
        # Track which old lines are being updated
        updated_line_ids = set()
        
        # Process new/updated lines
        for line_data in new_lines_data:
            line_id = line_data.get('WorkLogLineID')
            
            if line_id and line_id in old_lines_dict:
                # This is an update to existing line
                updated_line_ids.add(line_id)
                old_line = old_lines_dict[line_id]
                
                # Track changes to line fields
                trackable_fields = {
                    'StartTime': 'start_time',
                    'EndTime': 'end_time',
                    'IsPause': 'is_pause',
                    'AbsenceType': 'absence_type'
                }
                
                for db_field, api_field in trackable_fields.items():
                    if api_field in line_data:
                        old_value = getattr(old_line, db_field)
                        new_value = line_data[api_field]
                        
                        # Handle time field conversion
                        if api_field in ['start_time', 'end_time'] and isinstance(new_value, str):
                            try:
                                new_value = datetime.time.fromisoformat(new_value)
                            except ValueError:
                                continue
                        
                        if old_value != new_value:
                            audit = WorkLogLineAudit.create_audit_record(
                                db=db,
                                worklog_id=worklog_id,
                                worklog_line_id=line_id,
                                modified_by_user_id=modified_by_user_id,
                                action_type=AuditActionType.UPDATE,
                                field_name=db_field,
                                old_value=old_value,
                                new_value=new_value,
                                reason=reason
                            )
                            audit_records.append(audit)
            else:
                # This is a new line
                audit = WorkLogLineAudit.create_audit_record(
                    db=db,
                    worklog_id=worklog_id,
                    worklog_line_id=line_data.get('WorkLogLineID'),
                    modified_by_user_id=modified_by_user_id,
                    action_type=AuditActionType.ADD_LINE,
                    field_name="NEW_LINE",
                    old_value=None,
                    new_value=line_data,
                    reason=reason
                )
                audit_records.append(audit)
        
        # Check for deleted lines
        new_line_ids = {line_data.get('WorkLogLineID') for line_data in new_lines_data if line_data.get('WorkLogLineID')}
        
        for old_line in old_lines:
            if old_line.WorkLogLineID not in new_line_ids:
                # This line was deleted
                audit = WorkLogLineAudit.create_audit_record(
                    db=db,
                    worklog_id=worklog_id,
                    worklog_line_id=old_line.WorkLogLineID,
                    modified_by_user_id=modified_by_user_id,
                    action_type=AuditActionType.REMOVE_LINE,
                    field_name="DELETED_LINE",
                    old_value={
                        'WorkLogLineID': old_line.WorkLogLineID,
                        'StartTime': str(old_line.StartTime),
                        'EndTime': str(old_line.EndTime) if old_line.EndTime else None,
                        'IsPause': old_line.IsPause,
                        'AbsenceType': old_line.AbsenceType,
                        'LoggedHours': old_line.LoggedHours
                    },
                    new_value=None,
                    reason=reason
                )
                audit_records.append(audit)
        
        return audit_records
    
    @staticmethod
    def capture_totals_recalculation(
        db: Session,
        worklog_id: int,
        modified_by_user_id: int,
        old_totals: Optional[WorkLogTotals],
        new_totals: WorkLogTotals,
        reason: str = "Automatic recalculation due to worklog changes"
    ) -> List[WorkLogAudit]:
        """
        Capture changes to worklog totals when they are recalculated.
        
        Args:
            db: Database session
            worklog_id: ID of the worklog
            modified_by_user_id: ID of user who triggered the change
            old_totals: Previous totals (if any)
            new_totals: New calculated totals
            reason: Reason for recalculation
            
        Returns:
            List of created audit records
        """
        audit_records = []
        
        trackable_fields = [
            'TotalWorkedHours',
            'TotalPauseCountedHours', 
            'TotalPauseUncountedHours',
            'BalanceScheduleHours'
        ]
        
        for field in trackable_fields:
            old_value = getattr(old_totals, field) if old_totals else 0
            new_value = getattr(new_totals, field)
            
            if old_value != new_value:
                audit = WorkLogAudit.create_audit_record(
                    db=db,
                    worklog_id=worklog_id,
                    modified_by_user_id=modified_by_user_id,
                    action_type=AuditActionType.UPDATE,
                    field_name=field,
                    old_value=old_value,
                    new_value=new_value,
                    reason=reason
                )
                audit_records.append(audit)
        
        return audit_records
    
    @staticmethod
    def get_worklog_modification_summary(
        db: Session,
        worklog_id: int,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Get a comprehensive summary of all modifications to a worklog.
        
        Args:
            db: Database session
            worklog_id: ID of the worklog
            limit: Maximum number of records to return
            
        Returns:
            Dictionary containing modification history summary
        """
        worklog_audits = WorkLogAudit.get_worklog_history(db, worklog_id)[:limit]
        line_audits = WorkLogLineAudit.get_line_history(db, worklog_id)[:limit]
        
        # Combine and sort by modification date
        all_audits = []
        
        for audit in worklog_audits:
            all_audits.append({
                'type': 'worklog',
                'audit_id': audit.AuditID,
                'modification_date': audit.ModificationDate,
                'modified_by_user_id': audit.ModifiedByUserID,
                'action_type': audit.ActionType,
                'field_name': audit.FieldName,
                'old_value': json.loads(audit.OldValue) if audit.OldValue else None,
                'new_value': json.loads(audit.NewValue) if audit.NewValue else None,
                'reason': audit.Reason
            })
        
        for audit in line_audits:
            all_audits.append({
                'type': 'worklog_line',
                'audit_id': audit.AuditID,
                'worklog_line_id': audit.WorkLogLineID,
                'modification_date': audit.ModificationDate,
                'modified_by_user_id': audit.ModifiedByUserID,
                'action_type': audit.ActionType,
                'field_name': audit.FieldName,
                'old_value': json.loads(audit.OldValue) if audit.OldValue else None,
                'new_value': json.loads(audit.NewValue) if audit.NewValue else None,
                'reason': audit.Reason
            })
        
        # Sort by modification date (newest first)
        all_audits.sort(key=lambda x: x['modification_date'], reverse=True)
        
        return {
            'worklog_id': worklog_id,
            'total_modifications': len(all_audits),
            'modifications': all_audits[:limit]
        }
