from odoo import models, _
from odoo.exceptions import UserError


class SaleAdvancePaymentInv(models.TransientModel):
    _inherit = "sale.advance.payment.inv"

    def create_invoices(self):
        orders = self.env["sale.order"].browse(self._context.get("active_ids", []))
        if self.advance_payment_method in ("percentage", "fixed"):
            orders_with_downpayment = orders.filtered(
                lambda order: order.order_line.filtered(
                    lambda line: not line.display_type and line.is_downpayment
                )
            )
            if orders_with_downpayment:
                raise UserError(
                    _(
                        "Only one down payment is allowed per sales order. "
                        "Remove the existing down payment before creating another."
                    )
                )

        res = super().create_invoices()

        if self.advance_payment_method == "percentage":
            for order in orders:
                order.dp_percent = self.amount / 100.0
        elif self.advance_payment_method == "fixed":
            for order in orders:
                base = order.amount_untaxed or 0.0
                order.dp_percent = (self.amount / base) if base else 0.0

        return res
