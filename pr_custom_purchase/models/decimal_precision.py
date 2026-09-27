from odoo import api, models


class DecimalPrecision(models.Model):
    _inherit = "decimal.precision"

    @api.model
    def ensure_product_uom_precision(self):
        """Keep three-decimal sale/purchase quantities exact on invoices and bills."""
        precision = self.sudo().search([
            ("name", "=", "Product Unit of Measure"),
        ], limit=1)
        if not precision:
            self.sudo().create({
                "name": "Product Unit of Measure",
                "digits": 3,
            })
        elif precision.digits < 3:
            precision.write({"digits": 3})
        return True

    @api.model
    def ensure_purchase_uom_precision(self):
        """Backward-compatible data hook used by earlier module versions."""
        return self.ensure_product_uom_precision()
