from odoo import api, fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    product_internal_reference = fields.Many2one(
        "product.internal.reference.lookup",
        string="Product Code",
        compute="_compute_product_internal_reference",
        inverse="_inverse_product_internal_reference",
        readonly=False,
    )

    @api.depends("product_id")
    def _compute_product_internal_reference(self):
        ProductRef = self.env["product.internal.reference.lookup"]
        for line in self:
            line.product_internal_reference = ProductRef.browse(line.product_id.id) if line.product_id else False

    def _inverse_product_internal_reference(self):
        for line in self:
            product = line.product_internal_reference.product_id
            if line.product_id != product:
                line.product_id = product

    @api.onchange("product_internal_reference")
    def _onchange_product_internal_reference(self):
        for line in self:
            product = line.product_internal_reference.product_id
            # The computed lookup can be sent back by the form on an imported
            # SO/PO line. Keep its negotiated price, UoM, taxes and description
            # when it still refers to the same product.
            if line.product_id == product:
                continue
            line.product_id = product
            if line.product_id and line.display_type == "product" and line.move_id.is_invoice(True):
                line._inverse_product_id()
                line._compute_account_id()
                line._compute_product_uom_id()
                line._compute_name()
                line._compute_price_unit()
                line._compute_tax_ids()
            elif not line.product_id:
                line.product_internal_reference = False
