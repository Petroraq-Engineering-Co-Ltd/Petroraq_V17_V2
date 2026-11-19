from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import random
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import calendar
from odoo.tools import date_utils
from collections import defaultdict  # make sure this import exists at top

from .annual_accrual import overlap_days, service_year_bounds


class HrHolidays(models.Model):
    # region [Initial]
    _inherit = "hr.leave"
    # endregion [Initial]

    # region [Fields]

    is_paid = fields.Boolean(string="Is Paid ?",
                             related="holiday_status_id.is_paid",
                             store=True)
    holiday_status_id = fields.Many2one(
        "hr.leave.type",
        domain="""[
                ('company_id', 'in', [employee_company_id, False]),
                    ('has_valid_allocation', '=', True),
            ]""",
        tracking=True)
    leave_amount = fields.Float(string="Amount", compute="compute_leave_amount", store=True)
    leave_request_id = fields.Many2one("pr.hr.leave.request", string="Leave Request", readonly=True)
    allocation_override_applied = fields.Boolean(
        string="Allocation Override Applied",
        default=False,
        readonly=True,
        help="Checked when this leave was approved using allocation-limit override.",
    )
    allocation_override_note = fields.Text(
        string="Allocation Override Note",
        readonly=True,
    )

    # leave_amount = fields.Float(string="Amount")

    # endregion [Fields]

    @api.constrains("employee_id", "request_date_from", "request_date_to", "state")
    def _check_last_working_day(self):
        for leave in self:
            cutoff = leave.employee_id.last_working_date
            if (
                cutoff
                and leave.state not in ("cancel", "refuse")
                and leave.request_date_to
                and leave.request_date_to > cutoff
            ):
                raise ValidationError(_(
                    "Time off for %(employee)s cannot extend beyond the Last Working Day (%(date)s).",
                    employee=leave.employee_id.display_name,
                    date=cutoff,
                ))

    # region [Compute Methods]

    def _get_duration(self, check_leave_type=True, resource_calendar=None):
        """Charge full-day annual leave by inclusive calendar days.

        Odoo normally derives the duration from the employee's resource
        calendar, which excludes weekends and calendar leaves.  The company
        policy for annual leave is different: every date in the selected
        period consumes the allocation, including weekends and public
        holidays.  Hours remain based on Odoo's normal work-calendar result so
        work entries are not generated for non-working dates.
        """
        days, hours = super()._get_duration(
            check_leave_type=check_leave_type,
            resource_calendar=resource_calendar,
        )
        self.ensure_one()
        is_full_day_leave = (
            check_leave_type
            and self.leave_type_request_unit == "day"
            and not self.request_unit_half
            and not self.request_unit_hours
        )
        if not is_full_day_leave:
            return days, hours

        date_from = self.request_date_from or (self.date_from and self.date_from.date())
        date_to = self.request_date_to or (self.date_to and self.date_to.date())
        if not date_from or not date_to or date_to < date_from:
            return days, hours
        if self.holiday_status_id.leave_type == "annual_leave":
            return (date_to - date_from).days + 1, hours
        return self._pr_exclude_public_holidays_from_duration(
            days, hours, date_from, date_to, resource_calendar=resource_calendar,
        )

    def _pr_exclude_public_holidays_from_duration(self, days, hours, date_from, date_to, resource_calendar=None):
        """Drop hr.public.holiday dates from a working-day duration.

        hr.public.holiday is not a resource.calendar.leaves model, so the core
        computation still counts those dates as work days. Recompute the per-day
        work time with the same domain as core and drop the employee's public
        holidays, so non-annual leave consumes what pr.hr.leave.request shows in
        requested_days, and hours only cover the remaining working dates.
        """
        self.ensure_one()
        resource_calendar = resource_calendar or self.resource_calendar_id
        if not self.employee_id or not resource_calendar or not self.date_from or not self.date_to:
            return days, hours
        holiday_dates = self.employee_id._pr_get_public_holiday_dates(date_from, date_to)
        if not holiday_dates:
            return days, hours
        domain = [
            ('time_type', '=', 'leave'),
            ('company_id', 'in', self.env.companies.ids + self.env.context.get('allowed_company_ids', [])),
            '|', ('holiday_id', '=', False), ('holiday_id', '!=', self.id),
        ]
        work_time_per_day = [
            (day, day_hours)
            for day, day_hours in self.employee_id.list_work_time_per_day(
                self.date_from, self.date_to, calendar=resource_calendar, domain=domain,
            )
            if day not in holiday_dates
        ]
        return len(work_time_per_day), sum(day_hours for _day, day_hours in work_time_per_day)

    @api.depends("holiday_status_id",
                 "request_date_from",
                 "request_date_to",
                 "state",
                 "holiday_status_id.is_paid",
                 "holiday_status_id.leave_type",
                 "number_of_days",
                 "employee_id",
                 "employee_id.contract_id",
                 "employee_id.contract_id.date_start",
                 "employee_id.contract_id.gross_amount",
                 )
    def compute_leave_amount(self):
        for leave in self:
            if leave.holiday_status_id and leave.holiday_status_id.is_paid:
                employee_net_salary = leave.employee_id.contract_id.gross_amount if (
                        leave.employee_id and leave.employee_id.contract_id) else 0
                if leave.holiday_status_id.leave_type != "sick_leave":
                    leave.leave_amount = leave._calculate_leave_amount()
                elif leave.holiday_status_id.leave_type == "sick_leave":
                    if not leave.request_date_from or not leave.request_date_to:
                        leave.leave_amount = 0
                        continue
                    sick_leave_days = leave._pr_get_prior_sick_leave_days()
                    days_dict = leave.split_dates(start_date=leave.request_date_from, end_date=leave.request_date_to)
                    leave.leave_amount = leave._calculate_sick_leave_amount(days_dict=days_dict,
                                                                            sick_leave_days=sick_leave_days,
                                                                            employee_net_salary=employee_net_salary)
            else:
                leave.leave_amount = 0

    def _pr_get_sick_leave_service_year_anchor(self):
        """Contract start date used as the sick-leave service-year anchor.

        Same anchor as the annual accrual (allocation date_from = contract
        date_start): the contract running on the leave start date, falling back
        to the employee's current contract.
        """
        self.ensure_one()
        contract = self.env["hr.contract"].sudo().search([
            ("employee_id", "=", self.employee_id.id),
            ("state", "not in", ("draft", "cancel")),
            ("date_start", "<=", self.request_date_from),
            "|", ("date_end", "=", False), ("date_end", ">=", self.request_date_from),
        ], order="date_start desc", limit=1) or self.employee_id.sudo().contract_id
        return contract.date_start

    def _pr_get_prior_sick_leave_days(self):
        """Calendar days of the employee's other validated sick leaves taken in the
        current contract-anniversary service year before this leave starts."""
        self.ensure_one()
        anchor = self._pr_get_sick_leave_service_year_anchor()
        if not self.employee_id or not anchor:
            return 0
        year_start, _next_year_start = service_year_bounds(anchor, self.request_date_from)
        window_end = self.request_date_from - timedelta(days=1)
        if window_end < year_start:
            return 0
        domain = [
            ("holiday_status_id.leave_type", "=", "sick_leave"),
            ("employee_id", "=", self.employee_id.id),
            ("state", "=", "validate"),
            ("request_date_from", "<=", window_end),
            ("request_date_to", ">=", year_start),
        ]
        if self._origin.id:
            domain.append(("id", "!=", self._origin.id))
        other_leaves = self.sudo().search(domain)
        return sum(
            overlap_days(leave.request_date_from, leave.request_date_to, year_start, window_end)
            for leave in other_leaves
        )

    def _calculate_sick_leave_amount(self, days_dict, sick_leave_days, employee_net_salary):
        for leave in self:
            leave_amount = 0

            for month_key, month_values in days_dict.items():
                start_of_month = date_utils.start_of(month_key, 'month')
                end_of_month = date_utils.end_of(month_key, 'month')
                month_days = (end_of_month - start_of_month).days + 1

                # Calculate leave days for the current month
                leave_days = (month_values.get("to_date") - month_values.get("from_date")).days + 1

                # Calculate the overlap with each paid band directly. The old
                # loop made no progress at exactly 30/60 days, between the
                # integer bands, or above 90 days, blocking stored recomputes.
                # Preserve the configured rates: 100%, 75%, then unpaid.
                period_end = sick_leave_days + leave_days
                full_pay_days = max(0.0, min(period_end, 30.0) - max(sick_leave_days, 0.0))
                reduced_pay_days = max(0.0, min(period_end, 60.0) - max(sick_leave_days, 30.0))
                if employee_net_salary > 0:
                    leave_amount += (full_pay_days + reduced_pay_days * 0.75) * employee_net_salary / month_days
                sick_leave_days = period_end

            return leave_amount

    def _calculate_leave_amount(self):
        for leave in self:
            employee_net_salary = leave.employee_id.contract_id.gross_amount if (
                    leave.employee_id and leave.employee_id.contract_id) else 0
            if leave.holiday_status_id.request_unit == "day":
                days = (leave.request_date_to - leave.request_date_from).days + 1
                days_dict = leave.split_dates(start_date=leave.request_date_from, end_date=leave.request_date_to)
                leave_amount = 0
                for month_key, month_values in days_dict.items():
                    start_of_month = date_utils.start_of(month_key, 'month')
                    end_of_month = date_utils.end_of(month_key, 'month')
                    month_days = (end_of_month - start_of_month).days + 1
                    leave_days = (month_values.get("to_date") - month_values.get("from_date")).days + 1
                    leave_amount += ((leave_days * employee_net_salary) / month_days) if employee_net_salary > 0 else 0
                return leave_amount
            elif leave.holiday_status_id.request_unit == "hour":
                average_hours_per_day = leave.employee_id.resource_calendar_id.hours_per_day if leave.employee_id.resource_calendar_id else 0
                start_of_month = date_utils.start_of(leave.request_date_from, 'month')
                end_of_month = date_utils.end_of(leave.request_date_from, 'month')
                month_days = (end_of_month - start_of_month).days + 1
                day_amount = (1 * employee_net_salary) / month_days
                leave_amount = 0
                if leave.request_unit_half:
                    leave_amount = day_amount / 2
                elif leave.request_unit_hours:
                    hours = leave.number_of_days_display
                    leave_amount = (hours * day_amount) / average_hours_per_day
                return leave_amount
            return 0

    # Function to generate the date splits
    def split_dates(self, start_date, end_date):
        for leave in self:
            # Dictionary to hold the results
            date_dict = {}

            # Start iterating from the start month to the end month
            current_date = start_date

            while current_date <= end_date:
                month = current_date.month
                year = current_date.year

                # Get the first and last days of the current month
                first_day_of_month = datetime(year, month, 1).date()
                last_day_of_month = datetime(year, month, calendar.monthrange(year, month)[1]).date()

                # Ensure both are datetime objects for comparison
                from_date = max(first_day_of_month, current_date)
                to_date = min(last_day_of_month, end_date)

                # Add the data to the dictionary if 'from_date' is before or equal to 'to_date'
                if from_date <= to_date:
                    # Key is "YYYY-MM"
                    key = f"{year}-{month:02d}"
                    # date_dict[key] = {
                    #     "from_date": from_date.strftime("%d/%m/%Y"),
                    #     "to_date": to_date.strftime("%d/%m/%Y")
                    # }

                    date_dict[first_day_of_month] = {
                        "from_date": from_date,
                        "to_date": to_date
                    }

                # Move to the first day of the next month, adjusting for year transition
                if current_date.month == 12:
                    current_date = datetime(current_date.year + 1, 1, 1).date()
                else:
                    current_date = datetime(current_date.year, current_date.month + 1, 1).date()

            return date_dict

    # endregion [Compute Methods]

    # region [Onchange Methods]

    @api.onchange("employee_id")
    def _onchange_employee_id_set_employee_ids(self):
        self.ensure_one()
        if self.employee_id:
            self.employee_ids = self.employee_id.ids

    def _is_allocation_override_enabled(self):
        return (
                self.env.context.get("pr_leave_allocation_override")
                or self.env.context.get("pr_leave_request_allocation_checked")
                or self.env.user.has_group('pr_hr_holidays.group_leave_allocation_limit_override')
        )

    # endregion [Onchange Methods]

    def _is_request_for_current_user_employee(self):
        self.ensure_one()
        return bool(
            self.employee_id
            and self.employee_id.user_id
            and self.employee_id.user_id == self.env.user
        )

    def _can_bypass_annual_leave_start_date(self):
        self.ensure_one()
        return (
            self.env.user.has_group("pr_hr_holidays.group_leave_allocation_limit_override")
            and not self._is_request_for_current_user_employee()
        )

    @api.constrains('holiday_status_id', 'request_date_from', 'employee_id')
    def _check_annual_leave_start_date(self):
        today = fields.Date.context_today(self)
        for leave in self:
            if not leave.holiday_status_id or not leave.request_date_from:
                continue
            if leave._can_bypass_annual_leave_start_date():
                continue
            # The tomorrow-onward rule is enforced when the pr.hr.leave.request is
            # submitted; the leave generated by its final approval may be validated
            # on or after the start date.
            if leave.sudo().leave_request_id.state in ("approved", "cancel_request", "cancelled"):
                continue
            if leave.holiday_status_id.leave_type == 'annual_leave' and leave.request_date_from <= today:
                raise ValidationError(_("Annual Leave requests must start from tomorrow onward."))

    def _check_validity(self):
        if not self._is_allocation_override_enabled():
            return super()._check_validity()

        # Allocation override flow:
        # Keep all standard validations from parent _check_holidays (date/order/overlap/etc.)
        # but bypass allocation-cap checks only.
        sorted_leaves = defaultdict(lambda: self.env['hr.leave'])
        for leave in self:
            sorted_leaves[(leave.holiday_status_id, leave.date_from.date())] |= leave

        for (leave_type, date_from), leaves in sorted_leaves.items():
            if leave_type.requires_allocation == 'no':
                continue

            employees = self.env['hr.employee']
            for leave in leaves:
                employees |= leave._get_employees_from_holiday_type()

            leave_data = leave_type.get_allocation_data(employees, date_from)

            # Community/Enterprise variants:
            # - one variant raises when not leave_data[employee]
            # - another variant skips that raise.
            # For this override group/context, both "missing allocation" and
            # "insufficient remaining allocation" checks are intentionally bypassed.
            if leave_type.allows_negative:
                continue

            previous_leave_data = leave_type.with_context(
                ignored_leave_ids=leaves.ids
            ).get_allocation_data(employees, date_from)

            for employee in employees:
                previous_emp_data = previous_leave_data[employee] and previous_leave_data[employee][0][1].get(
                    'virtual_excess_data')
                emp_data = leave_data[employee] and leave_data[employee][0][1].get('virtual_excess_data')

                if not previous_emp_data and not emp_data:
                    continue

                # Standard behavior would raise "There is no valid allocation..."
                # Skip for the dedicated override group/context only.
                if previous_emp_data != emp_data and len(emp_data or []) >= len(previous_emp_data or []):
                    continue

        return
