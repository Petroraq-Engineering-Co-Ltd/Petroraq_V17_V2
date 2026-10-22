import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Seed the explicit toggle once from the access roles used previously."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    role_groups = env["res.groups"].browse([
        env.ref("employee_task_management.group_task_employee").id,
        env.ref("employee_task_management.group_task_manager").id,
        env.ref("employee_task_management.group_task_admin").id,
    ])
    employees = env["hr.employee"].with_context(active_test=False).sudo().search([
        ("user_id", "!=", False),
        ("etm_attendance_policy_enabled", "=", False),
    ])
    enabled = employees.filtered(
        lambda employee: bool(employee.user_id.sudo().groups_id & role_groups)
    )
    if enabled:
        enabled.write({"etm_attendance_policy_enabled": True})
    _logger.info("Enabled the ETM attendance toggle for %s existing employee(s).", len(enabled))
