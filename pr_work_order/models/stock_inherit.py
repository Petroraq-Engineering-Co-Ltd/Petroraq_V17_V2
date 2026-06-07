from odoo import fields, models, api


class StockMove(models.Model):
    _inherit = "stock.move"

    work_order_id = fields.Many2one("pr.work.order", string="Work Order")
    work_order_boq_line_id = fields.Many2one("pr.work.order.boq", string="WO BOQ Line")

    def _get_work_order_material_usage_cost(self):
        self.ensure_one()

        if "stock_valuation_layer_ids" in self._fields:
            cost = sum(self.stock_valuation_layer_ids.mapped("value"))
            if cost:
                return cost

        qty = self.quantity if "quantity" in self._fields else self.product_uom_qty
        qty = self.product_uom._compute_quantity(qty or 0.0, self.product_id.uom_id)
        return (self.product_id.standard_price or 0.0) * qty

    def _action_done(self, *args, **kwargs):
        res = super()._action_done(*args, **kwargs)

        Analytic = self.env["account.analytic.line"]

        for move in self:
            wo = move.work_order_id
            if not wo:
                continue

            cost = move._get_work_order_material_usage_cost()

            if not cost or not wo.analytic_account_id:
                continue

            Analytic.create({
                "name": f"Material Usage – {move.product_id.display_name}",
                "account_id": wo.analytic_account_id.id,
                "work_order_id": wo.id,
                "date": fields.Date.today(),
                "amount": -abs(cost),
                "unit_amount": move.product_uom_qty,
                "product_id": move.product_id.id,
                "company_id": move.company_id.id,
            })

        return res


class StockPicking(models.Model):
    _inherit = "stock.picking"
    work_order_id = fields.Many2one("pr.work.order", string="Work Order")

    @api.model_create_multi
    def create(self, vals_list):
        pickings = super().create(vals_list)

        for picking in pickings:
            wo = picking.work_order_id or picking.sale_id.work_order_id
            if wo:
                if not picking.work_order_id:
                    picking.work_order_id = wo.id

                picking.move_ids_without_package.write({
                    "work_order_id": wo.id,
                })

        return pickings
