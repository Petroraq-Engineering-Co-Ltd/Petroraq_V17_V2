from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """The rule is noupdate (and was archived on some databases)."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    rule = env.ref(
        "de_hr_workspace_attendance.hr_shortage_request_workspace_rule_employee",
        raise_if_not_found=False,
    )
    if rule:
        rule.write({
            "active": True,
            "domain_force": (
                "['|', '|', '|', '|', ('employee_id.user_id', '=', user.id), "
                "('employee_id.parent_id.user_id', '=', user.id), "
                "('employee_manager_id.user_id', '=', user.id), "
                "('hr_supervisor_ids', 'in', user.id), ('hr_manager_ids', 'in', user.id)]"
            ),
            "groups": [(4, env.ref("de_hr_workspace.group_hr_employee_approvals").id)],
        })
