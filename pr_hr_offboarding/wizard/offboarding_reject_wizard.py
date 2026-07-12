from odoo import _, fields, models
from odoo.exceptions import UserError


class PrHrOffboardingRejectWizard(models.TransientModel):
    _name = "pr.hr.offboarding.reject.wizard"
    _description = "Reject Offboarding Request"

    request_id = fields.Many2one(
        "pr.hr.offboarding.request",
        string="Request",
        required=True,
        readonly=True,
    )
    rejection_reason = fields.Text(
        string="Rejection Reason",
        required=True,
    )

    def action_reject(self):
        self.ensure_one()
        reason = (self.rejection_reason or "").strip()
        if not reason:
            raise UserError(_("A rejection reason is required."))
        self.request_id._action_reject(reason)
        return {"type": "ir.actions.act_window_close"}
