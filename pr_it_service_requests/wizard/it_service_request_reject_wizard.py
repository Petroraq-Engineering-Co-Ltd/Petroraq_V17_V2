from odoo import fields, models


class PrItServiceRequestRejectWizard(models.TransientModel):
    _name = "pr.it.service.request.reject.wizard"
    _description = "Reject IT Service Request"

    request_id = fields.Many2one("pr.it.service.request", required=True, readonly=True)
    reason = fields.Text(required=True)

    def action_reject(self):
        self.ensure_one()
        self.request_id._action_reject(self.reason)
        return {"type": "ir.actions.act_window_close"}
