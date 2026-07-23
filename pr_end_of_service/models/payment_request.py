from odoo import fields, models


class EmployeePaymentRequest(models.Model):
    _inherit = "pr.employee.payment.request"

    eos_id = fields.Many2one(
        "pr.end.of.service",
        string="End of Service",
        readonly=True,
        copy=False,
        tracking=True,
    )

    def action_create_payment_voucher(self):
        result = super().action_create_payment_voucher()
        for request in self.filtered("eos_id"):
            voucher = request.cash_payment_id or request.bank_payment_id
            if not voucher:
                continue
            voucher.sudo().eos_id = request.eos_id.id
            vals = {"payment_request_id": request.id}
            if voucher._name == "pr.account.cash.payment":
                vals["cash_payment_id"] = voucher.id
            else:
                vals["bank_payment_id"] = voucher.id
            request.eos_id.sudo().write(vals)
        return result

    def _mark_source_paid_from_voucher(self, voucher):
        result = super()._mark_source_paid_from_voucher(voucher)
        for request in self.filtered("eos_id"):
            request.eos_id._mark_done_from_payment(voucher)
        return result


class AccountCashPayment(models.Model):
    _inherit = "pr.account.cash.payment"

    eos_id = fields.Many2one(
        "pr.end.of.service",
        string="End of Service",
        readonly=True,
        copy=False,
        tracking=True,
    )
