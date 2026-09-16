from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    # Sequence XML is noupdate: move existing installations to the new range
    # without renumbering partners or rewinding an already advanced sequence.
    partners = env["res.partner"].with_context(active_test=False).search([
        ("partner_code", "=like", "7%"),
    ])
    used = [int(code) for code in partners.mapped("partner_code") if code and code.isascii() and code.isdigit()]
    floor = max([7000] + used) + 1
    for sequence in env["ir.sequence"].search([("code", "=", "res.partner.vendor.code")]):
        sequence.number_next_actual = max(sequence.number_next_actual, floor)
