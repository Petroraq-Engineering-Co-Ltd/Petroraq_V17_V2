from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    requisition_lines = env["purchase.requisition.line"].with_context(
        active_test=False
    ).search([
        ("description", "!=", False),
        "|",
        ("type", "=", False),
        ("unit", "=", False),
    ])
    for line in requisition_lines:
        defaults = line._get_product_purchase_defaults(line.description)
        line.write({
            "type": defaults["type"],
            "unit": defaults["unit"],
        })

    legacy_lines = env["custom.pr.line"].with_context(active_test=False).search([
        ("description", "!=", False),
        ("unit", "=", False),
    ])
    for line in legacy_lines:
        line.unit = line.description.uom_po_id or line.description.uom_id
