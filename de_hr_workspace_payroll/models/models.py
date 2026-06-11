# -*- coding: utf-8 -*-

from odoo import _, models, fields, api
from odoo.exceptions import AccessError


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    line_ids_filtered = fields.One2many("hr.payslip.line", "slip_id", compute="_compute_line_ids_filtered")

    def _pr_get_payslip_currency(self):
        self.ensure_one()
        if "currency_id" in self._fields and self.currency_id:
            return self.currency_id
        return self.company_id.currency_id

    def _pr_payslip_amount_is_zero(self, amount):
        self.ensure_one()
        currency = self._pr_get_payslip_currency()
        if currency:
            return currency.is_zero(amount or 0.0)
        return abs(amount or 0.0) < 0.005

    def _pr_add_payslip_summary_line(self, target, name, amount, code):
        amount = abs(amount or 0.0)
        if self._pr_payslip_amount_is_zero(amount):
            return
        for item in target:
            if item["name"] == name and item["code"] == code:
                item["amount"] += amount
                return
        target.append({
            "name": name,
            "amount": amount,
            "code": code,
        })

    def _pr_payslip_report_pair_base(self, name):
        name = (name or "").strip()
        name_upper = name.upper()
        for suffix in (" DEDUCTION", " DED"):
            if name_upper.endswith(suffix):
                name = name[:-len(suffix)].strip()
                break
        return name.casefold()

    def _pr_net_payslip_offset_pairs(self, payments, deductions):
        payments = [dict(payment) for payment in payments]
        deductions = [dict(deduction) for deduction in deductions]

        for payment in payments:
            if self._pr_payslip_amount_is_zero(payment.get("amount")):
                continue

            payment_base = self._pr_payslip_report_pair_base(payment.get("name"))
            for deduction in deductions:
                if self._pr_payslip_amount_is_zero(deduction.get("amount")):
                    continue
                if payment_base != self._pr_payslip_report_pair_base(deduction.get("name")):
                    continue

                payment_amount = payment.get("amount") or 0.0
                deduction_amount = deduction.get("amount") or 0.0
                offset_amount = min(payment_amount, deduction_amount)
                payment["amount"] = payment_amount - offset_amount
                deduction["amount"] = deduction_amount - offset_amount

                if self._pr_payslip_amount_is_zero(payment.get("amount")):
                    break

        payments = [
            payment
            for payment in payments
            if not self._pr_payslip_amount_is_zero(payment.get("amount"))
        ]
        deductions = [
            deduction
            for deduction in deductions
            if not self._pr_payslip_amount_is_zero(deduction.get("amount"))
        ]
        return payments, deductions

    def _pr_format_payslip_report_date(self, value):
        if not value:
            return ""
        return value.strftime("%d-%B-%Y")

    def _pr_get_payslip_report_values(self):
        """Return the compact company payslip values used by the PDF and portal."""
        self.ensure_one()
        payslip = self.sudo()
        employee = payslip.employee_id.sudo()
        payslip_contract = payslip.contract_id if "contract_id" in payslip._fields else False
        contract = (payslip_contract or employee.contract_id).sudo()

        hidden_codes = {
            "GROSS",
            "NET",
            "GOSI_COMP_ADD",
            "GOSI_COMP_DED",
            "GOSIALLOW",
        }
        gosi_allow_balance = sum(
            (line.total or 0.0)
            for line in payslip.line_ids
            if ((line.code or line.salary_rule_id.code or "").upper() == "GOSIALLOW")
            and (line.total or 0.0) > 0
        )
        payments = []
        deductions = []
        net_line = payslip.line_ids.filtered(
            lambda line: (line.code or line.salary_rule_id.code or "").upper() == "NET"
        )[:1]

        for line in payslip.line_ids.sorted(lambda line: (line.sequence, line.id)):
            code = (line.code or line.salary_rule_id.code or "").upper()
            amount = line.total or 0.0
            if self._pr_payslip_amount_is_zero(amount):
                continue
            if code in hidden_codes:
                continue
            if code == "GOSI" and amount < 0 and gosi_allow_balance:
                matched_amount = min(abs(amount), gosi_allow_balance)
                gosi_allow_balance -= matched_amount
                amount = -(abs(amount) - matched_amount)
                if self._pr_payslip_amount_is_zero(amount):
                    continue

            name = line.name or line.salary_rule_id.name or code or _("Payslip Line")
            category_code = (line.category_id.code or "").upper()
            if amount < 0 or category_code == "DED":
                self._pr_add_payslip_summary_line(deductions, name, amount, code)
            else:
                self._pr_add_payslip_summary_line(payments, name, amount, code)

        payments, deductions = payslip._pr_net_payslip_offset_pairs(payments, deductions)
        payment_total = sum(item["amount"] for item in payments)
        deduction_total = sum(item["amount"] for item in deductions)
        net_amount = (
            net_line.total
            if net_line
            else (payslip.net_wage if "net_wage" in payslip._fields else payment_total - deduction_total)
        )

        salary_period = ""
        if payslip.date_to:
            salary_period = payslip.date_to.strftime("%B %Y")
        elif payslip.date_from:
            salary_period = payslip.date_from.strftime("%B %Y")

        period_parts = [
            payslip._pr_format_payslip_report_date(payslip.date_from),
            payslip._pr_format_payslip_report_date(payslip.date_to),
        ]
        payslip_period = " to ".join(part for part in period_parts if part)

        cost_center = ""
        for field_name in (
            "employee_cost_center_id",
            "department_cost_center_id",
            "section_cost_center_id",
            "project_cost_center_id",
        ):
            if field_name in employee._fields and employee[field_name]:
                cost_center = employee[field_name].display_name
                break

        bank_account = ""
        if "bank_account_id" in employee._fields and employee.bank_account_id:
            bank_account = employee.bank_account_id.acc_number or employee.bank_account_id.display_name

        absence_days = payslip.no_absence if "no_absence" in payslip._fields else 0.0
        employee_no = (employee.code if "code" in employee._fields else False) or employee.identification_id or ""

        return {
            "employee": employee,
            "contract": contract,
            "salary_period": salary_period,
            "payslip_period": payslip_period,
            "employee_no": employee_no,
            "bank_account": bank_account,
            "cost_center": cost_center or (employee.department_id.display_name if employee.department_id else ""),
            "payments": payments,
            "deductions": deductions,
            "payment_total": payment_total,
            "deduction_total": deduction_total,
            "net_amount": net_amount or 0.0,
            "absence_days": absence_days or 0.0,
            "currency_symbol": payslip._pr_get_payslip_currency().symbol or "",
        }

    @api.depends("line_ids", "line_ids.total")
    def _compute_line_ids_filtered(self):
        for rec in self:
            if rec.line_ids:
                line_ids_filtered = rec.line_ids.filtered(lambda l: l.total != 0)
                if line_ids_filtered:
                    rec.line_ids_filtered = line_ids_filtered.ids
                else:
                    rec.line_ids_filtered = False
            else:
                rec.line_ids_filtered = False

    def action_print_payslip(self):
        if not self.env.user.has_group("hr_payroll.group_hr_payroll_user") and any(
            payslip.employee_id.user_id != self.env.user for payslip in self
        ):
            raise AccessError(_("You can only print your own payslips."))

        self.env["ir.actions.report"]._pr_configure_payslip_paperformat()
        return {
            "name": _("Payslip"),
            "type": "ir.actions.act_url",
            "url": "/print/payslips/inline?list_ids=%s" % ",".join(str(payslip.id) for payslip in self),
            "target": "new",
        }
