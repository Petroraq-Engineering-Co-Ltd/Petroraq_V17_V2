from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SaleAdvancePaymentInv(models.TransientModel):
    _inherit = "sale.advance.payment.inv"

    advance_payment_method = fields.Selection(
        # Added before "Down payment (percentage)" option
        selection_add=[
            ("qty_percentage", "Percentage of the quantity"),
            ("percentage",),
        ],
        ondelete={"qty_percentage": "set default"},
    )
    qty_percentage = fields.Float(
        string="Quantity percentage",
        digits=(16, 6),
        help="Fraction of the quantity to invoice, e.g. 0.5 for 50%.",
    )

    @api.constrains("advance_payment_method", "qty_percentage")
    def _check_qty_percentage(self):
        for wizard in self:
            if wizard.advance_payment_method == "qty_percentage" and not (
                0.0 < wizard.qty_percentage <= 1.0
            ):
                raise ValidationError(
                    _("The quantity percentage must be greater than 0 and at most 1 (e.g. 0.5 for 50%).")
                )

    def create_invoices(self):
        """Inject context key for later use that information to modify quantities
        and switch the invoiced method back to regular one for using the normal flow.
        """
        if self.advance_payment_method == "qty_percentage":
            self = self.with_context(qty_percentage=self.qty_percentage)
            self.advance_payment_method = "delivered"
        return super().create_invoices()
