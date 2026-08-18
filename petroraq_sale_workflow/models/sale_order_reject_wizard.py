from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SaleOrderRejectWizard(models.TransientModel):
    _name = "sale.order.reject.wizard"
    _description = "Reject Sale Order with Reason"

    order_id = fields.Many2one("sale.order", required=True, ondelete="cascade")
    rejection_type = fields.Selection([
        ("quotation", "Quotation"),
        ("confirmation", "Sales Order Confirmation"),
    ], required=True, default="quotation")
    reason = fields.Text(string="Rejection Reason", required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        order = self.order_id
        if self.rejection_type == "confirmation":
            if not self.env.user.has_group(
                "petroraq_sale_workflow.group_sale_confirmation_approver"
            ):
                raise UserError(_("Only a Sales Order Confirmation Approver can reject this request."))
            if order.confirmation_approval_state != "pending":
                raise UserError(_("Only a pending confirmation approval can be rejected."))
            order.with_context(skip_confirmation_approval_reset=True).write({
                "confirmation_approval_state": "rejected",
                "confirmation_rejection_reason": self.reason,
                "confirmation_approved_by_id": False,
                "confirmation_approved_date": False,
            })
            order.message_post(
                body=_("Sales Order confirmation rejected. Reason: %s") % self.reason
            )
            return {"type": "ir.actions.act_window_close"}

        # reuse existing security check
        if order.approval_state not in ("to_manager", "to_md"):
            raise UserError(_("Only waiting approvals can be rejected."))

        # record reason and reject
        order.approval_comment = self.reason
        order.approval_state = "rejected"
        order.state = "cancel"
        order.message_post(body=_("Quotation has been rejected. Reason: %s") % self.reason)
        return {"type": "ir.actions.act_window_close"}
