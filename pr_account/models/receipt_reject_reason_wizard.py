from odoo import _, fields, models
from odoo.exceptions import ValidationError


class ReceiptRejectReasonWizard(models.TransientModel):
    _name = "receipt.reject.reason.wizard"
    _description = "Receipt Voucher Reject Reason"

    bank_receipt_id = fields.Many2one("pr.account.bank.receipt")
    cash_receipt_id = fields.Many2one("pr.account.cash.receipt")
    reason = fields.Text(string="Reason", required=True)

    def action_confirm(self):
        self.ensure_one()
        reason = (self.reason or "").strip()
        if not reason:
            raise ValidationError(_("Reject Reason is mandatory."))
        receipt = self.bank_receipt_id or self.cash_receipt_id
        if not receipt:
            raise ValidationError(_("Select a receipt voucher to reject."))
        receipt._reject_with_reason(reason)
        return True
