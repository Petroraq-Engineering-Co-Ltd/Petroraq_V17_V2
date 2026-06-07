from datetime import datetime

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from hijri_converter import Gregorian
from datetime import date


class HREmployeeMedicalInsuranceLineAddWizard(models.Model):
    """
    """

    # region [Initial]
    _inherit = 'hr.employee.medical.insurance.line.add.wizard'
    # endregion [Initial]

    # region [Fields]

    # endregion [Fields]

    def action_renew(self):
        insurance_line_id = super().action_renew()
        if "pr.employee.payment.request" in self.env and "expense_bucket_id" in self._fields:
            if not self.expense_bucket_id:
                raise UserError(_("Please select the approved Budget for this medical insurance request."))
            if not self.cost_center_id:
                raise UserError(_("Please select the Cost Center for this medical insurance request."))

            payment_request = self.env["pr.employee.payment.request"].sudo().create({
                "insurance_line_id": insurance_line_id.id,
                "requested_user_id": self.env.user.id,
                "employee_id": self.employee_id.id,
                "company_id": (self.employee_id.company_id or self.env.company).id,
                "expense_bucket_id": self.expense_bucket_id.id,
                "cost_center_id": self.cost_center_id.id,
                "line_ids": [(0, 0, {
                    "description": _("Medical insurance renewal - %s") % self.employee_id.name,
                    "amount": self.amount,
                })],
            })
            payment_request._check_selected_budget_or_raise(self.amount)
            payment_request._notify_accounts()
            if "payment_request_id" in insurance_line_id._fields:
                insurance_line_id.payment_request_id = payment_request.id
            insurance_line_id.state = "in_progress"
            return insurance_line_id

        bank_account_id = self.env["account.account"].sudo().search([("code", "=", "1001.02.00.07")], limit=1)
        account_id = bank_account_id if bank_account_id else self.env["account.account"].sudo().browse(749)
        bank_payment_id = self.env["pr.account.bank.payment"].sudo().create({
            "account_id": account_id.id,
            "description": f"Payment For Medical Insurance of  {self.employee_id.name}",
        })
        if bank_payment_id:
            insurance_line_id.bank_payment_id = bank_payment_id.id
            bank_payment_id.insurance_line_id = insurance_line_id.id
        if insurance_line_id and bank_payment_id:
            insurance_line_id.state = "in_progress"
        return insurance_line_id





