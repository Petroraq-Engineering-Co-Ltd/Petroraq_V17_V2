from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class AccountPaymentRegister(models.TransientModel):
    _inherit = "account.payment.register"

    received_bank_account_id = fields.Many2one(
        "res.partner.bank",
        string="Received In Bank Account",
        domain="[('company_id', '=', company_id)]",
        help="Company bank account where the payment was received.",
    )

    @api.onchange("journal_id")
    def _onchange_journal_id_default_received_bank(self):
        for wiz in self:
            if wiz.journal_id and wiz.journal_id.type == "bank":
                wiz.received_bank_account_id = wiz.journal_id.bank_account_id
            else:
                wiz.received_bank_account_id = False

    # def _create_payment_vals_from_wizard(self, batch_result, **kwargs):
    #     vals = super()._create_payment_vals_from_wizard(batch_result, **kwargs)
    #
    #     # only set when bank journal (optional rule)
    #     if self.journal_id.type == "bank":
    #         vals["received_bank_account_id"] = self.received_bank_account_id.id or False
    #     else:
    #         vals["received_bank_account_id"] = False
    #
    #     return vals

    # def action_create_payments(self):
    #     for wiz in self:
    #         if wiz.journal_id.type == "bank" and not wiz.received_bank_account_id:
    #             raise ValidationError(_("Please select the bank account where payment was received."))
    #     return super().action_create_payments()

    def _pr_requires_vendor_payment_approval(self, process_vals):
        payment_vals = process_vals.get("create_vals", {})
        source_lines = process_vals.get("to_reconcile", self.env["account.move.line"])
        source_moves = source_lines.move_id
        return (
            payment_vals.get("payment_type") == "outbound"
            and payment_vals.get("partner_type") == "supplier"
            and source_moves
            and all(move.move_type in ("in_invoice", "in_receipt") for move in source_moves)
        )

    def _init_payments(self, to_process, edit_mode=False):
        payments = super()._init_payments(to_process, edit_mode=edit_mode)
        for process_vals in to_process:
            payment = process_vals.get("payment")
            if not payment or not self._pr_requires_vendor_payment_approval(process_vals):
                continue

            source_lines = process_vals.get("to_reconcile", self.env["account.move.line"])
            payment.write({
                "pr_requires_vendor_payment_approval": True,
                "pr_payment_approval_state": "submit",
                "pr_vendor_payment_source_line_ids": [(6, 0, source_lines.ids)],
            })
            payment.message_post(body=_("Vendor payment submitted for approval from Register Payment."))
        return payments

    def _post_payments(self, to_process, edit_mode=False):
        immediate_process = [
            process_vals
            for process_vals in to_process
            if not process_vals.get("payment").pr_requires_vendor_payment_approval
        ]
        if immediate_process:
            return super()._post_payments(immediate_process, edit_mode=edit_mode)
        return None

    def _reconcile_payments(self, to_process, edit_mode=False):
        immediate_process = [
            process_vals
            for process_vals in to_process
            if not process_vals.get("payment").pr_requires_vendor_payment_approval
        ]
        if immediate_process:
            return super()._reconcile_payments(immediate_process, edit_mode=edit_mode)
        return None
