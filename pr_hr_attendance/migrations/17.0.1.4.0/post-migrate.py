from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Assign the open shortage requests to the pr_hr approvers of their company."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    requests = env["pr.hr.shortage.request"].search([
        ("state", "not in", ("approved", "rejected")),
    ])
    for request in requests:
        vals = request._prepare_approver_vals()
        # keep the manager the request was addressed to
        vals.pop("employee_manager_id")
        request.write(vals)
