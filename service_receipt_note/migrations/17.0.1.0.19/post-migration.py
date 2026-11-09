def migrate(cr, version):
    """Backfill monetary amounts on existing SRN lines and headers."""
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env["service.receipt.note.line"].search([])
    if lines:
        lines._compute_amounts()
        lines.flush_recordset(["price_unit", "price_subtotal", "price_tax", "price_total"])
    receipts = env["service.receipt.note"].search([])
    if receipts:
        receipts._compute_amounts()
        receipts.flush_recordset(["amount_untaxed", "amount_tax", "amount_total"])

