from odoo.tools import sql


STATE_MAP_SQL = """
    CASE {col}
        WHEN 'draft' THEN 'employee_manager_approval'
        WHEN 'manager_approve' THEN 'hr_supervisor_approval'
        WHEN 'hr_supervisor' THEN 'hr_manager_approval'
        WHEN 'hr_approve' THEN 'approved'
        WHEN 'reject' THEN 'rejected'
        ELSE {col}
    END
"""

OLD_STATES = ('draft', 'manager_approve', 'hr_supervisor', 'hr_approve', 'reject')


def migrate(cr, version):
    if not version:
        return
    cr.execute(f"""
        UPDATE pr_hr_leave_request
           SET state = {STATE_MAP_SQL.format(col='state')},
               approval_state = {STATE_MAP_SQL.format(col='approval_state')}
         WHERE state IN %(old)s OR approval_state IN %(old)s
    """, {'old': OLD_STATES})
    # rejected_from_state was introduced later; older databases don't have it yet
    # (the ORM creates it after this pre-migration), so only remap it when present.
    if sql.column_exists(cr, 'pr_hr_leave_request', 'rejected_from_state'):
        cr.execute(f"""
            UPDATE pr_hr_leave_request
               SET rejected_from_state = {STATE_MAP_SQL.format(col='rejected_from_state')}
             WHERE rejected_from_state IN %(old)s
        """, {'old': ('draft', 'manager_approve', 'hr_supervisor')})
