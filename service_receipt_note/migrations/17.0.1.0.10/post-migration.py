def migrate(cr, version):
    """Refresh SRN approvers using the employee's direct user link."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    receipts = env["service.receipt.note"].search([])
    receipts._compute_department_manager()
