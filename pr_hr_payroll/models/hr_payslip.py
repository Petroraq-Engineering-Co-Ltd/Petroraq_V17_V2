from odoo import models, fields, tools, api, exceptions, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import date_utils


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    PAYROLL_COST_CENTER_EXCLUDED_CODES = {
        "ADVALL",
        "ADVANCE_ALLOWANCE",
        "ADVANCE_ALLOWANCES",
        "PETTY",
        "PETTYCASH",
        "PETTY_CASH",
        "DEPR",
        "DEP",
        "DEPRECIATION",
    }
    PAYROLL_COST_CENTER_EXCLUDED_TERMS = (
        "petty cash",
        "pettycash",
        "advance allowance",
        "advance allowances",
        "advanceallowance",
        "advanceallowances",
        "depreciation",
        "provision for gosi",
        "provision gosi",
        "gosi provision",
    )

    other_amount = fields.Float(string="Other Amount", default=0.0)
    salary_journal_entry_id = fields.Many2one("account.move", readonly=True)

    hold_salary = fields.Boolean(string="Hold Salary", tracking=True, copy=False)
    hold_reason = fields.Char(string="Hold Reason", tracking=True, copy=False)
    hold_date = fields.Date(string="Hold Date", tracking=True, copy=False)
    release_date = fields.Date(string="Release Date", tracking=True, copy=False)

    def action_hold_salary(self):
        for slip in self:
            if slip.state in ('paid', 'cancel'):
                raise UserError(_("You cannot hold a payslip that is already Paid/Cancelled."))
            slip.write({
                'hold_salary': True,
                'hold_date': fields.Date.today(),
            })

    def action_release_salary(self):
        for slip in self:
            if slip.state in ('paid', 'cancel'):
                continue
            slip.write({
                'hold_salary': False,
                'release_date': fields.Date.today(),
            })

    attendance_sheet_line_ids = fields.One2many(
        related='attendance_sheet_id.line_ids',
        string="Attendance Lines",
        readonly=True
    )
    no_overtime = fields.Integer(related="attendance_sheet_id.no_overtime", readonly=True)
    tot_overtime = fields.Float(related="attendance_sheet_id.tot_overtime", readonly=True)
    tot_overtime_amount = fields.Float(related="attendance_sheet_id.tot_overtime_amount", readonly=True)
    approved_overtime_hours = fields.Float(related="attendance_sheet_id.approved_overtime_hours", readonly=True)
    approved_overtime_amount = fields.Float(related="attendance_sheet_id.approved_overtime_amount", readonly=True)
    no_late = fields.Integer(related="attendance_sheet_id.no_late", readonly=True)
    tot_late_in_minutes = fields.Float(string="Total Late In Minutes", readonly=True)
    tot_late = fields.Float(related="attendance_sheet_id.tot_late", readonly=True)
    tot_late_amount = fields.Float(related="attendance_sheet_id.tot_late_amount", readonly=True)
    no_early_checkout = fields.Integer(string="No of Early Check Out", readonly=True)
    tot_early_checkout = fields.Float(string="Total Early Check Out", readonly=True)
    tot_early_checkout_amount = fields.Float(string="Total Early Check Out Amount", readonly=True)
    early_check_out_minutes = fields.Float(string="Total Early Checkout Minutes", readonly=True)
    no_absence = fields.Integer(related="attendance_sheet_id.no_absence", readonly=True)
    tot_absence = fields.Float(related="attendance_sheet_id.tot_absence", readonly=True)
    tot_absence_amount = fields.Float(related="attendance_sheet_id.tot_absence_amount", readonly=True)
    no_difftime = fields.Integer(related="attendance_sheet_id.no_difftime", readonly=True)
    tot_difftime = fields.Float(related="attendance_sheet_id.tot_difftime", readonly=True)
    tot_difftime_amount = fields.Float(related="attendance_sheet_id.tot_difftime_amount", readonly=True)
    carry_forward_absence_amount = fields.Float(related="attendance_sheet_id.carry_forward_absence_amount",
                                                readonly=True)
    carry_forward_late_amount = fields.Float(related="attendance_sheet_id.carry_forward_late_amount", readonly=True)
    carry_forward_diff_amount = fields.Float(related="attendance_sheet_id.carry_forward_diff_amount", readonly=True)
    carry_forward_overtime_amount = fields.Float(related="attendance_sheet_id.carry_forward_overtime_amount",
                                                 readonly=True)
    carry_forward_early_checkout_amount = fields.Float(
        related="attendance_sheet_id.carry_forward_early_checkout_amount", readonly=True)
    carry_forward_deduction = fields.Float(string="Carry Forward Deduction", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = []
        for incoming_vals in vals_list:
            vals = dict(incoming_vals)
            contract = self.env["hr.contract"].browse(vals.get("contract_id")).exists()
            date_from = fields.Date.to_date(vals.get("date_from"))
            date_to = fields.Date.to_date(vals.get("date_to"))
            if contract and contract.date_end and date_from:
                if date_from > contract.date_end:
                    raise ValidationError(_(
                        "A payslip cannot start after the Last Working Day (%s) for %s.",
                        contract.date_end,
                        contract.employee_id.display_name,
                    ))
                if date_to and date_to > contract.date_end:
                    vals["date_to"] = contract.date_end
            prepared_vals_list.append(vals)
        return super().create(prepared_vals_list)

    @api.constrains("contract_id", "date_from", "date_to")
    def _check_last_working_day(self):
        for payslip in self:
            cutoff = payslip.contract_id.date_end
            if cutoff and payslip.date_from and payslip.date_from > cutoff:
                raise ValidationError(_(
                    "The payslip period for %s starts after the Last Working Day (%s).",
                    payslip.employee_id.display_name,
                    cutoff,
                ))
            if cutoff and payslip.date_to and payslip.date_to > cutoff:
                raise ValidationError(_(
                    "The payslip must end on or before the Last Working Day (%s) for %s.",
                    cutoff,
                    payslip.employee_id.display_name,
                ))

    def _pr_get_last_working_day_period_bounds(self):
        self.ensure_one()
        if self.payslip_run_id:
            return self.payslip_run_id.date_start, self.payslip_run_id.date_end
        if not self.date_from:
            return False, False
        return self.date_from, self.date_from + self._get_schedule_timedelta()

    def _pr_get_last_working_day_ratio(self):
        """Return the payable share of the batch period when a contract ends mid-period."""
        self.ensure_one()
        contract = self.contract_id
        if not contract or not contract.date_end or not self.date_from or not self.date_to:
            return 1.0

        period_start, period_end = self._pr_get_last_working_day_period_bounds()
        if not period_start or not period_end or contract.date_end >= period_end:
            return 1.0

        payable_start = max(period_start, contract.date_start or period_start)
        payable_end = min(period_end, contract.date_end)
        if payable_end < payable_start:
            return 0.0
        period_days = (period_end - period_start).days + 1
        payable_days = (payable_end - payable_start).days + 1
        return payable_days / period_days if period_days else 1.0

    def _pr_get_last_working_day_missing_days(self):
        """Return the unpaid tail of the payroll period after the contract cutoff."""
        self.ensure_one()
        contract = self.contract_id
        period_start, period_end = self._pr_get_last_working_day_period_bounds()
        if not contract or not contract.date_end or not period_start or not period_end:
            return 0
        if contract.date_end >= period_end:
            return 0
        if contract.date_end < period_start:
            return (period_end - period_start).days + 1
        return max((period_end - contract.date_end).days, 0)

    def _pr_get_transportation_allowance_amount(self):
        self.ensure_one()
        contract = self.contract_id
        if not contract:
            return 0.0
        transport_rules = contract.contract_salary_rule_ids.filtered(
            lambda rule: rule.pay_in_payslip and (rule.salary_rule_id.code or "").upper() == "TRANSPORTATION"
        )
        return sum(transport_rules.mapped("amount")) if transport_rules else 0.0

    def _pr_get_attendance_deduction_salary_base(self):
        self.ensure_one()
        contract = self.contract_id
        gross_amount = contract.gross_amount if contract else 0.0
        employee = self.employee_id
        exclude_transport = (
            employee
            and "exclude_transportation_from_attendance_gross" in employee._fields
            and employee.exclude_transportation_from_attendance_gross
        )
        if not exclude_transport:
            return gross_amount
        return max(gross_amount - self._pr_get_transportation_allowance_amount(), 0.0)

    def _pr_get_last_working_day_day_amount(self):
        self.ensure_one()
        attendance_line = self.attendance_sheet_line_ids[:1]
        if attendance_line and attendance_line.day_amount:
            return attendance_line.day_amount
        salary_base = self._pr_get_attendance_deduction_salary_base()
        return salary_base / 30.0 if salary_base else 0.0

    def _pr_get_last_working_day_absence_amount(self):
        """Convert post-cutoff days into the same daily deduction used by attendance absences."""
        self.ensure_one()
        missing_days = self._pr_get_last_working_day_missing_days()
        if not missing_days:
            return 0.0
        return missing_days * self._pr_get_last_working_day_day_amount()

    def _pr_should_prorate_final_period_line(self, code, category_code):
        """Return whether a line is a recurring amount that still needs proration."""
        excluded_codes = {
            "GROSS", "NET", "OVT", "OTHER", "ADVALL", "REIMBURSEMENT199",
            "ABS", "LATE", "ECO", "DIFFT",
            # These are attendance-derived daily amounts. Their allowance and
            # deduction lines must remain equal and must not be prorated again.
            "PAID86", "PAID87", "SICKTO88", "SICKTO89", "BTA", "BTD",
        }
        gosi_codes = {"GOSI", "GOSIALLOW", "GOSI_COMP_ADD", "GOSI_EMP", "GOSI_COMP_DED"}
        return (
            code not in excluded_codes
            and (category_code in {"BASIC", "ALW"} or code in gosi_codes)
        )

    def _pr_prorate_final_period_lines(self, line_vals):
        """Prorate recurring earnings and GOSI once for a mid-period final payslip."""
        self.ensure_one()
        ratio = self._pr_get_last_working_day_ratio()
        if ratio >= 1.0:
            return

        salary_rules = self.env["hr.salary.rule"].browse(
            [vals.get("salary_rule_id") for vals in line_vals if vals.get("salary_rule_id")]
        )
        category_by_rule = {
            rule.id: rule.category_id.code
            for rule in salary_rules
        }
        for vals in line_vals:
            code = vals.get("code")
            category_code = category_by_rule.get(vals.get("salary_rule_id"))
            if not self._pr_should_prorate_final_period_line(code, category_code):
                continue
            vals["amount"] = (vals.get("amount", 0.0) or 0.0) * ratio
            vals["total"] = (vals.get("total", 0.0) or 0.0) * ratio

    @api.model
    def _compute_gross_net_amounts(self, line_vals, excluded_earning_codes=None):
        excluded_earning_codes = excluded_earning_codes or set()
        totals_by_code = {}
        for vals in line_vals:
            code = vals.get("code")
            if not code:
                continue
            totals_by_code[code] = totals_by_code.get(code, 0.0) + (vals.get("total", 0.0) or 0.0)

        gosi_company_add = totals_by_code.get("GOSI_COMP_ADD", 0.0) + totals_by_code.get("GOSIALLOW", 0.0)
        gosi_employee_ded = totals_by_code.get("GOSI_EMP", 0.0)
        gosi_company_ded = totals_by_code.get("GOSI_COMP_DED", 0.0) + totals_by_code.get("GOSI", 0.0)
        advance_allowances = totals_by_code.get("ADVALL", 0.0)
        reimbursement_amount = totals_by_code.get("REIMBURSEMENT199", 0.0)

        net_excluded = {"NET", "GROSS", "ADVALL", "GOSI_EMP", "GOSI", "GOSI_COMP_DED", "REIMBURSEMENT199"}
        gross_amount = sum(
            vals.get("total", 0.0) or 0.0
            for vals in line_vals
            if vals.get("code")
            and vals.get("code") not in net_excluded
        )
        # Keep formula explicit and in requested order
        net_amount = gross_amount + reimbursement_amount + advance_allowances + gosi_company_ded + gosi_employee_ded
        return gross_amount, net_amount, gosi_company_add

    def _sync_attendance_summary_fields(self):
        field_names = [
            "tot_late_in_minutes",
            "no_early_checkout",
            "tot_early_checkout",
            "tot_early_checkout_amount",
            "early_check_out_minutes",
        ]
        for payslip in self:
            update_vals = {}
            for field_name in field_names:
                value = 0.0
                if payslip.attendance_sheet_id and field_name in payslip.attendance_sheet_id._fields:
                    value = getattr(payslip.attendance_sheet_id, field_name, 0.0) or 0.0
                if field_name == "no_early_checkout":
                    value = int(value)
                update_vals[field_name] = value
            update_vals["carry_forward_deduction"] = (
                    (payslip.carry_forward_absence_amount or 0.0)
                    + (payslip.carry_forward_late_amount or 0.0)
                    + (payslip.carry_forward_diff_amount or 0.0)
                    + (payslip.carry_forward_early_checkout_amount or 0.0)
            )
            payslip.update(update_vals)

    def _upsert_attendance_deduction_line(self, line_vals, payslip, code, amount):
        """Ensure attendance deduction line exists and reflects latest attendance-sheet amount."""
        if abs(amount or 0.0) < 1e-6:
            return

        existing_line = None
        for vals in line_vals:
            if vals.get('code') == code:
                existing_line = vals
                break

        if existing_line:
            existing_line['amount'] = amount
            existing_line['total'] = amount
            existing_line['quantity'] = 1
            existing_line['rate'] = 100
            return

        salary_rule = self.env['hr.salary.rule'].search([
            ('code', '=', code),
            ('struct_id', '=', payslip.struct_id.id),
        ], limit=1)
        if not salary_rule:
            return

        line_vals.append({
            'sequence': salary_rule.sequence,
            'code': salary_rule.code,
            'name': salary_rule.name,
            'salary_rule_id': salary_rule.id,
            'contract_id': payslip.contract_id.id if payslip.contract_id else False,
            'employee_id': payslip.employee_id.id,
            'amount': amount,
            'quantity': 1,
            'rate': 100,
            'total': amount,
            'slip_id': payslip.id,
        })

    def _get_payslip_lines(self):
        line_vals = super()._get_payslip_lines()
        for payslip in self:
            payslip._sync_attendance_summary_fields()

            contract_id = payslip.contract_id or payslip.employee_id.contract_id
            if not contract_id:
                continue
            gosi_salary_rule = self.env.ref("pr_hr_payroll.hr_salary_rule_saudi_gosi")
            gosi_allow_salary_rule = self.env.ref("pr_hr_payroll.hr_salary_rule_saudi_gosi_allow")
            # ===============================
            # GOSI – single source of truth
            # ===============================
            company_gosi = contract_id.company_portion or 0.0
            employee_gosi = contract_id.employee_portion or 0.0

            if payslip.employee_id.country_id and payslip.employee_id.country_id.is_homeland and contract_id.is_automatic_gosi:
                start_of_month = date_utils.start_of(payslip.date_to, 'month')
                end_of_month = date_utils.end_of(payslip.date_to, 'month')
                month_days = (end_of_month - start_of_month).days + 1
                total_amount = 0
                if end_of_month > contract_id.date_start > payslip.date_from:
                    wage = contract_id.wage
                    salary_month_days = (end_of_month - contract_id.date_start).days + 1
                    total_amount = (salary_month_days * wage) / month_days
                elif payslip.date_from >= contract_id.date_start:
                    total_amount = contract_id.wage
                salary_rule_ids = contract_id.contract_salary_rule_ids
                if salary_rule_ids:
                    acc_salary_rule_id = salary_rule_ids.filtered(lambda l: l.salary_rule_id.code == "ACCOMMODATION")
                    if acc_salary_rule_id:
                        rule_total_amount = acc_salary_rule_id.amount
                        if end_of_month > contract_id.date_start > payslip.date_from:
                            salary_month_days = (end_of_month - contract_id.date_start).days + 1
                            rule_amount = (salary_month_days * rule_total_amount) / month_days
                            total_amount += rule_amount
                        elif payslip.date_from >= contract_id.date_start:
                            total_amount += rule_total_amount
                if gosi_salary_rule:
                    # line_vals.append({
                    #     'sequence': gosi_salary_rule.sequence,
                    #     'code': gosi_salary_rule.code,
                    #     'name': gosi_salary_rule.name,
                    #     'salary_rule_id': gosi_salary_rule.id,
                    #     'contract_id': payslip.employee_id.contract_id.id,
                    #     'employee_id': payslip.employee_id.id,
                    #     'amount': (total_amount * -1 * .0975) or 0,
                    #     'quantity': 1,
                    #     'rate': 100,
                    #     'total': (total_amount * -1 * .0975) or 0,
                    #     'slip_id': payslip.id,
                    # })
                    # 1) Company GOSI → ADD to GROSS
                    line_vals.append({
                        'sequence': 44,
                        'code': 'GOSI_COMP_ADD',
                        'name': 'GOSI Company Contribution',
                        'salary_rule_id': gosi_allow_salary_rule.id,
                        'contract_id': contract_id.id,
                        'employee_id': payslip.employee_id.id,
                        'amount': company_gosi,
                        'quantity': 1,
                        'rate': 100,
                        'total': company_gosi,
                        'slip_id': payslip.id,
                    })

                    # 2) Employee GOSI → DEDUCT from NET
                    line_vals.append({
                        'sequence': 45,
                        'code': 'GOSI_EMP',
                        'name': 'GOSI Employee Deduction',
                        'salary_rule_id': gosi_salary_rule.id,
                        'contract_id': contract_id.id,
                        'employee_id': payslip.employee_id.id,
                        'amount': -employee_gosi,
                        'quantity': 1,
                        'rate': 100,
                        'total': -employee_gosi,
                        'slip_id': payslip.id,
                    })

                    # 3) Company GOSI → DEDUCT from NET
                    line_vals.append({
                        'sequence': 46,
                        'code': 'GOSI_COMP_DED',
                        'name': 'GOSI Company Deduction',
                        'salary_rule_id': gosi_salary_rule.id,
                        'contract_id': contract_id.id,
                        'employee_id': payslip.employee_id.id,
                        'amount': -company_gosi,
                        'quantity': 1,
                        'rate': 100,
                        'total': -company_gosi,
                        'slip_id': payslip.id,
                    })


            else:
                start_of_month = date_utils.start_of(payslip.date_to, 'month')
                end_of_month = date_utils.end_of(payslip.date_to, 'month')
                month_days = (end_of_month - start_of_month).days + 1
                total_amount = 0
                if end_of_month > contract_id.date_start > payslip.date_from:
                    wage = contract_id.wage
                    salary_month_days = (end_of_month - contract_id.date_start).days + 1
                    total_amount = (salary_month_days * wage) / month_days
                elif payslip.date_from >= contract_id.date_start:
                    total_amount = contract_id.wage
                salary_rule_ids = contract_id.contract_salary_rule_ids
                if salary_rule_ids:
                    acc_salary_rule_id = salary_rule_ids.filtered(lambda l: l.salary_rule_id.code == "ACCOMMODATION")
                    if acc_salary_rule_id:
                        rule_total_amount = acc_salary_rule_id.amount
                        if end_of_month > contract_id.date_start > payslip.date_from:
                            salary_month_days = (end_of_month - contract_id.date_start).days + 1
                            rule_amount = (salary_month_days * rule_total_amount) / month_days
                            total_amount += rule_amount
                        elif payslip.date_from >= contract_id.date_start:
                            total_amount += rule_total_amount
                if gosi_salary_rule:
                    gosi_line_amount = total_amount * 1 * .02
                    line_vals.append({
                        'sequence': gosi_allow_salary_rule.sequence,
                        'code': gosi_allow_salary_rule.code,
                        'name': gosi_allow_salary_rule.name,
                        'salary_rule_id': gosi_allow_salary_rule.id,
                        'contract_id': contract_id.id,
                        'employee_id': payslip.employee_id.id,
                        'amount': (gosi_line_amount if gosi_line_amount <= 900 else 900) or 0,
                        'quantity': 1,
                        'rate': 100,
                        'total': (gosi_line_amount if gosi_line_amount <= 900 else 900) or 0,
                        'slip_id': payslip.id,
                    })

                    line_vals.append({
                        'sequence': gosi_salary_rule.sequence,
                        'code': gosi_salary_rule.code,
                        'name': gosi_salary_rule.name,
                        'salary_rule_id': gosi_salary_rule.id,
                        'contract_id': contract_id.id,
                        'employee_id': payslip.employee_id.id,
                        'amount': (gosi_line_amount * -1 if gosi_line_amount <= 900 else -900) or 0,
                        'quantity': 1,
                        'rate': 100,
                        'total': (gosi_line_amount * -1 if gosi_line_amount <= 900 else -900) or 0,
                        'slip_id': payslip.id,
                    })

            # Check Other Payment Like: First Payslip Days
            if contract_id.other_first_payslip and contract_id.joining_date:
                start_of_month = date_utils.start_of(contract_id.joining_date, 'month')
                end_of_month = date_utils.end_of(contract_id.joining_date, 'month')
                month_days = (end_of_month - start_of_month).days + 1
                extra_salary_days = (end_of_month - contract_id.joining_date).days + 1
                other_salary_rule = self.env.ref("pr_hr_payroll.hr_salary_rule_other_payments")
                gross_salary = contract_id.gross_amount
                extra_salary_amount = (extra_salary_days * gross_salary) / month_days
                if other_salary_rule and extra_salary_amount > 0:
                    line_vals.append({
                        'sequence': other_salary_rule.sequence,
                        'code': other_salary_rule.code,
                        'name': other_salary_rule.name,
                        'salary_rule_id': other_salary_rule.id,
                        'contract_id': contract_id.id,
                        'employee_id': payslip.employee_id.id,
                        'amount': extra_salary_amount or 0,
                        'quantity': 1,
                        'rate': 100,
                        'total': extra_salary_amount or 0,
                        'slip_id': payslip.id,
                    })

                # Check GOSI Amount For These Days If Employee Is Saudi
                if payslip.employee_id.country_id and payslip.employee_id.country_id.is_homeland and contract_id.is_automatic_gosi:
                    gosi_salary_amount = contract_id.wage
                    salary_rule_ids = contract_id.contract_salary_rule_ids
                    if salary_rule_ids:
                        acc_salary_rule_id = salary_rule_ids.filtered(
                            lambda l: l.salary_rule_id.code == "ACCOMMODATION")
                        if acc_salary_rule_id:
                            gosi_salary_amount += acc_salary_rule_id.amount
                    extra_gosi_salary_amount = (extra_salary_days * gosi_salary_amount) / month_days
                    if gosi_salary_rule and extra_gosi_salary_amount > 0:
                        line_vals.append({
                            'sequence': gosi_salary_rule.sequence,
                            'code': gosi_salary_rule.code,
                            'name': gosi_salary_rule.name,
                            'salary_rule_id': gosi_salary_rule.id,
                            'contract_id': contract_id.id,
                            'employee_id': payslip.employee_id.id,
                            'amount': (extra_gosi_salary_amount * -1 * .0975) or 0,
                            'quantity': 1,
                            'rate': 100,
                            'total': (extra_gosi_salary_amount * -1 * .0975) or 0,
                            'slip_id': payslip.id,
                        })

            # Contract Salary Rules
            if contract_id.contract_salary_rule_ids:
                for salary_rule_line_id in contract_id.contract_salary_rule_ids:
                    if salary_rule_line_id.pay_in_payslip:
                        salary_rule_id = salary_rule_line_id.sudo().salary_rule_id.sudo()
                        base_amount = salary_rule_line_id.sudo().amount or 0.0
                        eligible_amount = self._compute_attendance_eligible_amount(
                            payslip,
                            salary_rule_id,
                            base_amount,
                        )
                        line_vals.append({
                            'sequence': salary_rule_id.sequence,
                            'code': salary_rule_id.code,
                            'name': salary_rule_id.name,
                            'salary_rule_id': salary_rule_id.id,
                            'contract_id': contract_id.id,
                            'employee_id': payslip.employee_id.id,
                            'amount': eligible_amount,
                            'quantity': 1,
                            'rate': 100,
                            'total': eligible_amount,
                            'slip_id': payslip.id,
                        })

            if payslip.attendance_sheet_id and payslip.employee_id.compute_attendance:
                att_sheet = payslip.attendance_sheet_id
                final_period_absence_amount = payslip._pr_get_last_working_day_absence_amount()
                abs_amount = -((att_sheet.tot_absence_amount or 0.0) + (
                        getattr(att_sheet, 'carry_forward_absence_amount', 0.0) or 0.0)
                    + final_period_absence_amount)
                late_amount = -((att_sheet.tot_late_amount or 0.0) + (
                        getattr(att_sheet, 'carry_forward_late_amount', 0.0) or 0.0))
                eco_amount = -((getattr(att_sheet, 'tot_early_checkout_amount', 0.0) or 0.0) + (
                        getattr(att_sheet, 'carry_forward_early_checkout_amount', 0.0) or 0.0))
                diff_amount = -((att_sheet.tot_difftime_amount or 0.0) + (
                        getattr(att_sheet, 'carry_forward_diff_amount', 0.0) or 0.0))
                ovt_amount = ((att_sheet.approved_overtime_amount or 0.0) + (
                        getattr(att_sheet, 'carry_forward_overtime_amount',
                                0.0) or 0.0)) if payslip.employee_id.add_overtime else 0.0
                self._upsert_attendance_deduction_line(line_vals, payslip, 'OVT', ovt_amount)
                self._upsert_attendance_deduction_line(line_vals, payslip, 'ABS', abs_amount)
                self._upsert_attendance_deduction_line(line_vals, payslip, 'LATE', late_amount)
                self._upsert_attendance_deduction_line(line_vals, payslip, 'ECO', eco_amount)
                self._upsert_attendance_deduction_line(line_vals, payslip, 'DIFFT', diff_amount)
            elif payslip.attendance_sheet_id and not payslip.employee_id.compute_attendance:
                for vals in line_vals:
                    if vals.get('code') in ['ABS', 'LATE', 'ECO', 'DIFFT']:
                        vals['amount'] = 0.0
                        vals['total'] = 0.0

            payslip_line_vals = [
                vals for vals in line_vals
                if vals.get("slip_id") == payslip.id
            ]
            if not (payslip.attendance_sheet_id and payslip.employee_id.compute_attendance):
                payslip._pr_prorate_final_period_lines(payslip_line_vals)
            gross_amount, net_amount, _gosi_company_add = self._compute_gross_net_amounts(
                payslip_line_vals,
            )

            for val_line in payslip_line_vals:
                code = val_line.get("code")
                if code == "NET":
                    val_line["amount"] = net_amount
                    val_line["total"] = net_amount
                elif code == "GROSS":
                    val_line["amount"] = gross_amount
                    val_line["total"] = gross_amount
        return line_vals

    def _compute_attendance_eligible_amount(self, payslip, salary_rule, base_amount):
        """Prorate contract rule amount based on attendance eligibility in the payslip period."""
        if not salary_rule.attendance_based_eligibility:
            return base_amount

        att_sheet = payslip.attendance_sheet_id
        if not att_sheet:
            return 0.0

        unpaid_leave_type = self.env.ref(
            'hr_work_entry_contract.work_entry_type_unpaid_leave',
            raise_if_not_found=False,
        )
        validated_leaves = self.env['hr.leave'].sudo().search([
            ('employee_id', '=', payslip.employee_id.id),
            ('request_date_from', '<=', payslip.date_to),
            ('request_date_to', '>=', payslip.date_from),
            ('state', '=', 'validate'),
        ])
        unpaid_leaves = validated_leaves.filtered(
            lambda leave: not leave.holiday_status_id.is_paid
            or (
                unpaid_leave_type
                and leave.holiday_status_id.work_entry_type_id == unpaid_leave_type
            )
        )
        unpaid_leave_dates = {
            line.date
            for line in att_sheet.line_ids
            if line.status == 'leave'
            and any(
                leave.request_date_from <= line.date <= leave.request_date_to
                for leave in unpaid_leaves
            )
        }

        min_hours = salary_rule.attendance_min_worked_hours or 0.0
        require_presence = salary_rule.attendance_require_presence
        period_lines = att_sheet.line_ids.filtered(
            lambda attendance_line: payslip.date_from <= attendance_line.date <= payslip.date_to
        )
        working_dates = {
            line.date
            for line in period_lines
            if line.status not in ('weekend', 'ph')
        }
        deductible_dates = set()
        for line in period_lines:
            if line.date not in working_dates:
                continue
            is_absent = line.status == 'ab'
            is_unpaid_leave = line.date in unpaid_leave_dates
            if is_unpaid_leave:
                deductible_dates.add(line.date)
                continue
            if require_presence and is_absent:
                deductible_dates.add(line.date)
                continue
            if not line.status and line.worked_hours < min_hours:
                deductible_dates.add(line.date)

        return self._pr_prorate_attendance_eligible_amount(
            base_amount,
            deductible_days=len(deductible_dates),
            divisor=len(working_dates),
        )

    @api.model
    def _pr_prorate_attendance_eligible_amount(self, base_amount, deductible_days, divisor=30.0):
        if not divisor:
            return 0.0
        capped_deductible_days = min(max(deductible_days, 0.0), divisor)
        return max(base_amount * (divisor - capped_deductible_days) / divisor, 0.0)

    def check_payslip_dates(self):
        """Backward-compatible entry point: recompute from source values exactly once."""
        return self.compute_sheet()

    def _pr_payroll_line_excludes_cost_centers(self, salary_rule=False, account=False, label=False):
        """Return True for payroll JE lines that must not receive cost centers."""
        salary_rule = salary_rule.sudo() if salary_rule else self.env["hr.salary.rule"]
        account = (account or salary_rule.account_id).sudo() if (account or salary_rule) else self.env["account.account"]
        code = (salary_rule.code or "").strip().upper() if salary_rule else ""

        searchable_text = " ".join(filter(None, [
            code,
            salary_rule.name if salary_rule else "",
            account.code if account else "",
            account.name if account else "",
            label or "",
        ])).lower()
        if code in self.PAYROLL_COST_CENTER_EXCLUDED_CODES:
            return True
        if "gosi" in searchable_text and "provision" in searchable_text:
            return True
        return any(term in searchable_text for term in self.PAYROLL_COST_CENTER_EXCLUDED_TERMS)

    def _pr_employee_payroll_cost_centers(self, employee):
        employee = employee.sudo()
        return [
            employee.department_cost_center_id,
            employee.section_cost_center_id,
            employee.project_cost_center_id,
            employee.employee_cost_center_id,
        ]

    def _pr_employee_payroll_analytic_distribution(self, employee, percentage=100.0):
        distribution = {}
        for cost_center in self._pr_employee_payroll_cost_centers(employee):
            if cost_center:
                distribution[str(cost_center.id)] = distribution.get(str(cost_center.id), 0.0) + percentage
        return {
            key: round(value, 6)
            for key, value in distribution.items()
            if value
        }

    def _pr_employees_payroll_analytic_distribution(self, employees):
        employees = employees.filtered(lambda employee: employee.employee_cost_center_id)
        if not employees:
            return {}
        distribution = {}
        for employee in employees:
            employee_distribution = self._pr_employee_payroll_analytic_distribution(employee)
            for key, value in employee_distribution.items():
                distribution[key] = 100.0
        return {
            key: round(value, 6)
            for key, value in distribution.items()
            if value
        }

    def _pr_prepare_payroll_cost_center_vals(self, employee, salary_rule=False, account=False, label=False):
        if self._pr_payroll_line_excludes_cost_centers(
            salary_rule=salary_rule,
            account=account,
            label=label,
        ):
            return {}

        analytic_distribution = self._pr_employee_payroll_analytic_distribution(employee)
        if not analytic_distribution:
            return {}

        line_vals = {
            "analytic_distribution": analytic_distribution,
        }
        move_line_fields = self.env["account.move.line"]._fields
        if "cs_project_id" in move_line_fields and employee.project_cost_center_id:
            line_vals["cs_project_id"] = employee.project_cost_center_id.id
        if "cs_employee_id" in move_line_fields and employee.employee_cost_center_id:
            line_vals["cs_employee_id"] = employee.employee_cost_center_id.id
        if employee.project_cost_center_id and employee.project_cost_center_id.project_partner_id:
            line_vals["partner_id"] = employee.project_cost_center_id.project_partner_id.id
        return line_vals

    def prepare_payslip_entry_vals_lines(self):
        for rec in self:
            payslip_entry_vals_lines = []
            if rec.state != 'done':
                # raise UserError(_('Cannot mark payslip as paid if not confirmed.'))
                raise UserError(_('Cannot pay the payslip if not confirmed.'))
            if not rec.employee_id.employee_cost_center_id:
                raise ValidationError(
                    f"This employee {rec.employee_id.name} does not have cost center, please check !!")
            if not rec.employee_id.employee_account_id:
                raise ValidationError(
                    f"This employee {rec.employee_id.name} does not have account, please check !!")
            for line in rec.line_ids:
                if not line.salary_rule_id.account_id:
                    raise ValidationError(
                        f"This salary rule {line.salary_rule_id.name} does not have account, please check !!")
                payslip_entry_line_vals = self.prepare_payslip_entry_line_vals(line=line)
                if payslip_entry_line_vals:
                    payslip_entry_vals_lines.append((0, 0, payslip_entry_line_vals))
            return payslip_entry_vals_lines

    def prepare_payslip_entry_line_vals(self, line):
        if line.total and line.salary_rule_id.code not in ["GROSS", "NET"]:
            payslip_date_to = line.slip_id.date_to or self.date_to
            month_name = payslip_date_to.strftime('%B') if payslip_date_to else ""
            year_name = payslip_date_to.year if payslip_date_to else ""
            line_vals = {
                "account_id": line.salary_rule_id.account_id.id,
            }
            line_vals.update(self._pr_prepare_payroll_cost_center_vals(
                employee=self.employee_id,
                salary_rule=line.salary_rule_id,
                account=line.salary_rule_id.account_id,
                label=line.salary_rule_id.name,
            ))
            # if line.salary_rule_id.code in ["LOAN", "ADVALL"]:
            #     line_vals["account_id"] = line.slip_id.employee_id.employee_account_id.id

            category_code = (line.category_id.code or "").upper()
            if category_code in ["BASIC", "ALW"] or line.total > 0:
                line_vals.update({
                    "name": f"{line.slip_id.employee_id.code} - {line.slip_id.employee_id.name} {line.salary_rule_id.name} of Month {month_name} {year_name}",
                    "debit": abs(line.total),
                    "credit": 0.0,
                })
            elif category_code == "DED" or line.total < 0:
                line_vals.update({
                    "name": f"{line.slip_id.employee_id.code} - {line.slip_id.employee_id.name} {line.salary_rule_id.name} of Month {month_name} {year_name}",
                    "credit": abs(line.total),
                    "debit": 0.0,
                })
            return line_vals
        else:
            return False

    def action_open_salary_journal_entry(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": self.salary_journal_entry_id.id,
            "views": [[self.env.ref('account.view_move_form').id, "form"]],
            "target": "current",
            "name": self.name,
            "context": {"form_view_initial_mode": "readonly"}
        }
