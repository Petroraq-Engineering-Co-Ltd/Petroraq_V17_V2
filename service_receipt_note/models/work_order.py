from odoo import fields, models, _


class PRWorkOrder(models.Model):
    _inherit = "pr.work.order"

    service_receipt_note_count = fields.Integer(
        string="Service Receipts",
        compute="_compute_service_receipt_note_count",
    )

    def _compute_service_receipt_note_count(self):
        grouped = self.env["service.receipt.note"].read_group(
            [("work_order_id", "in", self.ids)],
            ["work_order_id"],
            ["work_order_id"],
        )
        count_map = {item["work_order_id"][0]: item["work_order_id_count"] for item in grouped if item["work_order_id"]}
        for order in self:
            order.service_receipt_note_count = count_map.get(order.id, 0)

    def action_view_service_receipt_notes(self):
        self.ensure_one()
        action = {
            "type": "ir.actions.act_window",
            "name": _("Service Receipt Notes"),
            "res_model": "service.receipt.note",
            "view_mode": "tree,form",
            "domain": [("work_order_id", "=", self.id)],
            "target": "current",
        }
        if self.service_receipt_note_count == 1:
            receipt = self.env["service.receipt.note"].search([("work_order_id", "=", self.id)], limit=1)
            action["view_mode"] = "form"
            action["res_id"] = receipt.id
        return action
