def migrate(cr, version):
    """Backfill monetary amounts on existing PO-linked incoming/outgoing moves and pickings."""
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    moves = env["stock.move"].search([
        ("picking_id.picking_type_code", "in", ("incoming", "outgoing")),
        ("purchase_line_id", "!=", False),
    ])
    if moves:
        moves._compute_pr_currency_id()
        moves._compute_pr_amounts()
        moves.flush_recordset([
            "pr_currency_id",
            "pr_unit_price",
            "pr_price_subtotal",
            "pr_price_tax",
            "pr_price_total",
        ])
        pickings = moves.mapped("picking_id").filtered(
            lambda p: p.picking_type_code in ("incoming", "outgoing")
        )
        if pickings:
            pickings._compute_pr_currency_id()
            pickings._compute_pr_amounts()
            pickings.flush_recordset([
                "pr_currency_id",
                "pr_amount_untaxed",
                "pr_amount_tax",
                "pr_amount_total",
            ])