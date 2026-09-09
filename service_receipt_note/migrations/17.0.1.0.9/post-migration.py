def migrate(cr, version):
    """Refresh stored approvers from each requester's department manager."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    receipts = env["service.receipt.note"].search([])
    receipts._compute_department_manager()
