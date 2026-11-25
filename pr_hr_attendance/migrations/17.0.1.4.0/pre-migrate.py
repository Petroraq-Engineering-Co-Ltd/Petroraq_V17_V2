def migrate(cr, version):
    """Map the shortage request states to the leave request ones. Some old
    approved requests kept a stale approval_state: it now mirrors the state."""
    cr.execute("""
        UPDATE pr_hr_shortage_request
           SET state = CASE state
               WHEN 'draft' THEN 'employee_manager_approval'
               WHEN 'manager_approve' THEN 'hr_supervisor_approval'
               WHEN 'hr_supervisor' THEN 'hr_manager_approval'
               WHEN 'hr_approve' THEN 'approved'
               WHEN 'reject' THEN 'rejected'
               ELSE state
           END
    """)
    cr.execute("UPDATE pr_hr_shortage_request SET approval_state = state")
