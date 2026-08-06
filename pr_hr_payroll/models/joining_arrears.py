import calendar
from datetime import date, datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class PayrollJoiningArrears(models.Model):
    _name = "payroll.joining.arrears"
    _description = "Payroll Joining Arrears"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_from desc, id desc"

    name = fields.Char(default=lambda self: _("New"), readonly=True, copy=False)
    employee_id = fields.Many2one("hr.employee", required=True, index=True, tracking=True)
    contract_id = fields.Many2one("hr.contract", required=True, index=True, tracking=True)
    company_id = fields.Many2one(related="contract_id.company_id", store=True, readonly=True)
    currency_id = fields.Many2one(related="company_id.currency_id", readonly=True)
    date_from = fields.Date(required=True, tracking=True)
    date_to = fields.Date(required=True, tracking=True)
    paid_through_date = fields.Date(
        string="Previously Paid Through",
        help="Inclusive date assumed to have already been covered before these arrears.",
    )
    calendar_days = fields.Integer(string="Payable Days", compute="_compute_amounts", store=True)
    attendance_day_count = fields.Integer(
        string="Attended Days",
        default=0,
        readonly=True,
        help="Distinct actual attendance dates paid when the employee was absent from the previous payroll.",
    )
    attendance_based = fields.Boolean(default=False, readonly=True)
    gross_amount = fields.Monetary(compute="_compute_amounts", store=True)
    attendance_deduction = fields.Monetary(compute="_compute_amounts", store=True)
    overtime_amount = fields.Monetary(compute="_compute_amounts", store=True)
    gosi_employee_deduction = fields.Monetary(
        string="Employee GOSI Deduction", compute="_compute_amounts", store=True
    )
    net_amount = fields.Monetary(compute="_compute_amounts", store=True)
    attendance_sheet_id = fields.Many2one(
        "attendance.sheet", readonly=True, copy=False, ondelete="restrict"
    )
    payslip_id = fields.Many2one("hr.payslip", readonly=True, copy=False, index=True)
    state = fields.Selection(
        [("draft", "Draft"), ("attached", "Attached to Payslip"), ("paid", "Paid"), ("cancel", "Cancelled")],
        default="draft",
        required=True,
        tracking=True,
        copy=False,
    )

    _sql_constraints = [
        (
            "joining_arrears_contract_period_unique",
            "unique(contract_id, date_from, date_to)",
            "Joining arrears already exist for this contract and date range.",
        )
    ]

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for record in self:
            if record.date_from and record.date_to and record.date_from > record.date_to:
                raise ValidationError(_("Joining arrears start date cannot be after the end date."))

    @api.depends(
        "date_from",
        "date_to",
        "attendance_day_count",
        "attendance_based",
        "contract_id.gross_amount",
        "contract_id.employee_portion",
        "contract_id.is_automatic_gosi",
        "employee_id.country_id.is_homeland",
        "attendance_sheet_id.tot_absence_amount",
        "attendance_sheet_id.tot_late_amount",
        "attendance_sheet_id.tot_difftime_amount",
        "attendance_sheet_id.tot_early_checkout_amount",
        "attendance_sheet_id.total_unpaid_leave",
        "attendance_sheet_id.approved_overtime_amount",
    )
    def _compute_amounts(self):
        for record in self:
            period_days = (
                (record.date_to - record.date_from).days + 1
                if record.date_from and record.date_to
                else 0
            )
            days = record.attendance_day_count if record.attendance_based else period_days
            sheet = record.attendance_sheet_id
            gross = (record.contract_id.gross_amount or 0.0) / 30.0 * days
            deduction = 0.0
            overtime = 0.0
            gosi_deduction = 0.0
            if sheet:
                deduction_parts = [
                    sheet.tot_late_amount or 0.0,
                    sheet.tot_difftime_amount or 0.0,
                    getattr(sheet, "tot_early_checkout_amount", 0.0) or 0.0,
                ]
                if not record.attendance_based:
                    deduction_parts.extend([
                        sheet.tot_absence_amount or 0.0,
                        getattr(sheet, "total_unpaid_leave", 0.0) or 0.0,
                    ])
                deduction = sum(deduction_parts)
                overtime = sheet.approved_overtime_amount or 0.0
            if (
                not record.attendance_based
                and record.contract_id.is_automatic_gosi
                and record.employee_id.country_id
                and record.employee_id.country_id.is_homeland
            ):
                gosi_deduction = (record.contract_id.employee_portion or 0.0) / 30.0 * days
            record.calendar_days = days
            record.gross_amount = gross
            record.attendance_deduction = deduction
            record.overtime_amount = overtime
            record.gosi_employee_deduction = gosi_deduction
            record.net_amount = gross - deduction + overtime - gosi_deduction

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.name == _("New"):
                record.name = self.env["ir.sequence"].next_by_code("payroll.joining.arrears") or _("New")
        return records

    @api.model
    def _previous_month_cutoff(self, period_start, cutoff_day):
        previous_month_end = period_start.replace(day=1) - timedelta(days=1)
        day = min(cutoff_day, calendar.monthrange(previous_month_end.year, previous_month_end.month)[1])
        return date(previous_month_end.year, previous_month_end.month, day)

    @api.model
    def _get_arrears_period(self, joining_date, period_start, cutoff_day=26, paid_through=False):
        # A cutoff controls prediction; it is not proof that salary was paid.
        # With no completed prior slip or explicit paid-through date, a new
        # joiner's unpaid window begins on the joining date itself.
        paid_through = paid_through or (joining_date - timedelta(days=1))
        date_from = max(joining_date, paid_through + timedelta(days=1))
        date_to = period_start - timedelta(days=1)
        return (date_from, date_to, paid_through) if date_from <= date_to else (False, False, paid_through)

    @api.model
    def _actual_attendance_dates(self, employee, date_from, date_to):
        """Return distinct local dates with an actual check-in in the window."""
        if not employee or not date_from or not date_to or date_from > date_to:
            return []
        timezone_name = employee.resource_calendar_id.tz or self.env.user.tz or "UTC"
        timezone = pytz.timezone(timezone_name)
        utc = pytz.UTC
        start = timezone.localize(datetime.combine(date_from, time.min)).astimezone(utc)
        end = timezone.localize(
            datetime.combine(date_to + timedelta(days=1), time.min)
        ).astimezone(utc)
        attendances = self.env["hr.attendance"].sudo().search([
            ("employee_id", "=", employee.id),
            ("check_in", ">=", start.replace(tzinfo=None)),
            ("check_in", "<", end.replace(tzinfo=None)),
        ])
        attended_dates = set()
        for attendance in attendances.filtered("check_in"):
            check_in = fields.Datetime.to_datetime(attendance.check_in)
            check_in_utc = check_in.astimezone(utc) if check_in.tzinfo else utc.localize(check_in)
            attended_dates.add(check_in_utc.astimezone(timezone).date())
        return sorted(attended_dates)

    @api.model
    def _prepare_for_payslip(self, payslip):
        """Create or attach the one-time unpaid pre-period joining window."""
        if not payslip.id or not payslip.contract_id or not payslip.date_from:
            return self.browse()
        linked_arrears = payslip.joining_arrears_id
        if linked_arrears and linked_arrears.state == "paid":
            return linked_arrears

        contract = payslip.contract_id
        joining_date = contract.joining_date or contract.date_start
        period_start = fields.Date.to_date(payslip.date_from)
        if not joining_date or joining_date >= period_start:
            return self.browse()

        prior_slip = self.env["hr.payslip"].sudo().search([
            ("id", "!=", payslip.id),
            ("contract_id", "=", contract.id),
            ("state", "in", ("done", "paid")),
            ("date_to", "<", period_start),
        ], order="date_to desc, id desc", limit=1)

        cutoff_day = 26
        attendance_sheet = payslip.attendance_sheet_id
        if attendance_sheet and attendance_sheet.predictive_cutoff_date:
            cutoff_day = attendance_sheet.predictive_cutoff_date.day

        attendance_dates = []
        attendance_based = not prior_slip and not contract.salary_paid_through_date
        if attendance_based:
            previous_cutoff = self._previous_month_cutoff(period_start, cutoff_day)
            attendance_from = max(joining_date, previous_cutoff + timedelta(days=1))
            attendance_to = period_start - timedelta(days=1)
            attendance_dates = self._actual_attendance_dates(
                payslip.employee_id, attendance_from, attendance_to
            )
            if not attendance_dates:
                return self.browse()

        # When a previous payroll exists, only its actual paid-through boundary
        # is used. Otherwise the exact attended dates after cutoff are paid.
        paid_candidates = []
        if contract.salary_paid_through_date:
            paid_candidates.append(contract.salary_paid_through_date)
        if prior_slip and prior_slip.date_to:
            paid_candidates.append(prior_slip.date_to)
        paid_through = max(paid_candidates) if paid_candidates else False

        if attendance_based:
            arrears_from = attendance_dates[0]
            arrears_to = attendance_dates[-1]
            assumed_paid_through = arrears_from - timedelta(days=1)
        else:
            arrears_from, arrears_to, assumed_paid_through = self._get_arrears_period(
                joining_date,
                period_start,
                cutoff_day=cutoff_day,
                paid_through=paid_through,
            )
        if not arrears_from:
            return self.browse()

        # Recomputing an existing draft payslip must refresh an arrears record
        # created by an earlier version of the calculation.
        if linked_arrears:
            arrears_sheet = linked_arrears.attendance_sheet_id
            if arrears_sheet:
                arrears_sheet.write({
                    "date_from": arrears_from,
                    "date_to": arrears_to,
                    "predictive_mode": False,
                    "predictive_cutoff_date": False,
                    "is_joining_arrears_sheet": True,
                })
                arrears_sheet.with_context(force_actual_attendance=True).get_attendances()
            linked_arrears.write({
                "date_from": arrears_from,
                "date_to": arrears_to,
                "paid_through_date": assumed_paid_through,
                "attendance_day_count": len(attendance_dates),
                "attendance_based": attendance_based,
                "state": "attached",
            })
            return linked_arrears

        existing = self.sudo().search([
            ("contract_id", "=", contract.id),
            ("date_from", "=", arrears_from),
            ("date_to", "=", arrears_to),
            ("state", "!=", "cancel"),
        ], limit=1)
        if existing:
            if existing.state == "draft" and not existing.payslip_id:
                existing.write({"payslip_id": payslip.id, "state": "attached"})
                payslip.joining_arrears_id = existing
            return existing if existing.payslip_id == payslip else self.browse()

        arrears_sheet = self.env["attendance.sheet"].new({
            "employee_id": payslip.employee_id.id,
            "date_from": arrears_from,
            "date_to": arrears_to,
            "predictive_mode": False,
            "predictive_cutoff_date": False,
            "is_joining_arrears_sheet": True,
        })
        arrears_sheet.onchange_employee()
        sheet_values = self.env["attendance.sheet"]._convert_to_write(arrears_sheet._cache)
        arrears_sheet = self.env["attendance.sheet"].create(sheet_values)
        arrears_sheet.with_context(force_actual_attendance=True).get_attendances()

        record = self.create({
            "employee_id": payslip.employee_id.id,
            "contract_id": contract.id,
            "date_from": arrears_from,
            "date_to": arrears_to,
            "paid_through_date": assumed_paid_through,
            "attendance_day_count": len(attendance_dates),
            "attendance_based": attendance_based,
            "attendance_sheet_id": arrears_sheet.id,
            "payslip_id": payslip.id,
            "state": "attached",
        })
        payslip.joining_arrears_id = record
        return record


class AttendanceSheet(models.Model):
    _inherit = "attendance.sheet"

    is_joining_arrears_sheet = fields.Boolean(default=False, copy=False, index=True)

    def action_create_payslip(self):
        if self.filtered("is_joining_arrears_sheet"):
            raise UserError(_(
                "A joining-arrears attendance sheet cannot create a separate payslip. "
                "Its net adjustment is attached to the employee's regular payslip."
            ))
        return super().action_create_payslip()
