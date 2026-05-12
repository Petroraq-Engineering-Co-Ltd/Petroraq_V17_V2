from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


class ProjectMilestone(models.Model):
    _inherit = "project.milestone"

    quantity_percentage = fields.Float(digits=(16, 10))
    product_uom_qty = fields.Float(digits=(16, 10))
    petroraq_currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_petroraq_currency_id",
        readonly=True,
    )
    petroraq_invoice_amount = fields.Monetary(
        string="Invoice Amount",
        compute="_compute_petroraq_invoice_amount",
        inverse="_inverse_petroraq_invoice_amount",
        currency_field="petroraq_currency_id",
        readonly=False,
        store=True,
        copy=False,
        help="Untaxed milestone amount. When entered, the milestone quantity and percentage are calculated from the sales order line subtotal.",
    )

    def _get_petroraq_sale_line(self):
        self.ensure_one()
        return self.sale_line_id if "sale_line_id" in self._fields else self.env["sale.order.line"]

    def _compute_petroraq_currency_id(self):
        for milestone in self:
            sale_line = milestone._get_petroraq_sale_line()
            milestone.petroraq_currency_id = sale_line.currency_id if sale_line else False

    @api.depends("sale_line_id.price_subtotal", "quantity_percentage")
    def _compute_petroraq_invoice_amount(self):
        for milestone in self:
            sale_line = milestone._get_petroraq_sale_line()
            sale_line_amount = sale_line.price_subtotal if sale_line else 0.0
            amount = (sale_line_amount or 0.0) * (milestone.quantity_percentage or 0.0)
            currency = milestone.petroraq_currency_id
            milestone.petroraq_invoice_amount = currency.round(amount) if currency else amount

    def _inverse_petroraq_invoice_amount(self):
        self._set_progress_from_invoice_amount(raise_if_invalid=True)

    @api.onchange("petroraq_invoice_amount", "sale_line_id")
    def _onchange_petroraq_invoice_amount(self):
        self._set_progress_from_invoice_amount(raise_if_invalid=False)

    def _set_progress_from_invoice_amount(self, raise_if_invalid=False):
        for milestone in self:
            amount = milestone.petroraq_invoice_amount or 0.0
            sale_line = milestone._get_petroraq_sale_line()

            if amount < 0.0:
                if raise_if_invalid:
                    raise ValidationError(_("Milestone invoice amount cannot be negative."))
                continue

            if not sale_line:
                if amount and raise_if_invalid:
                    raise ValidationError(_("Please select a sales order item before entering a milestone invoice amount."))
                continue

            sale_line_amount = sale_line.price_subtotal or 0.0
            sale_line_qty = sale_line.product_uom_qty or 0.0
            if not sale_line_amount:
                if amount and raise_if_invalid:
                    raise ValidationError(_("The selected sales order item has no subtotal to calculate a milestone percentage from."))
                milestone.quantity_percentage = 0.0
                milestone.product_uom_qty = 0.0
                continue

            ratio = amount / sale_line_amount
            milestone.quantity_percentage = ratio
            milestone.product_uom_qty = sale_line_qty * ratio

    @api.constrains("sale_line_id", "product_uom_qty", "quantity_percentage")
    def _check_sale_line_milestone_percentage(self):
        """
        Enforce that the sum of milestone % for the same Sale Order Line
        never exceeds 100%.

        NOTE:
        - In standard Odoo, quantity_percentage is a ratio (0..1), not 0..100.
        """
        for milestone in self:
            sale_line = milestone.sale_line_id
            if not sale_line:
                continue

            milestones = self.search([("sale_line_id", "=", sale_line.id)])
            total_ratio = sum(milestones.mapped("quantity_percentage"))  # 0..1

            # total_ratio > 1.0 means > 100%
            if float_compare(total_ratio, 1.0, precision_digits=10) > 0:
                raise ValidationError(_(
                    "The total milestone percentage for the sales order item '%(line)s' "
                    "cannot exceed 100%%. Current total: %(total).6f%%."
                ) % {
                    "line": sale_line.display_name,
                    "total": total_ratio * 100.0,
                })
