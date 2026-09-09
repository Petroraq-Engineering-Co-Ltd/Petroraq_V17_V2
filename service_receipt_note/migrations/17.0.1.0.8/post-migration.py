def migrate(cr, version):
    """Refresh stored approvers after HR manager configuration changes."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    receipts = env["service.receipt.note"].search([])
    receipts._compute_department_manager()
