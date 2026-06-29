from datetime import timedelta

from dateutil.relativedelta import relativedelta
from odoo import api, fields, models
from odoo.tools import float_is_zero, float_round


class HrLeaveAllocation(models.Model):
    _inherit = "hr.leave.allocation"

    pr_is_carryover_allocation = fields.Boolean(
        string="PR Carryover Allocation",
        copy=False,
        index=True,
    )
    pr_carryover_origin_allocation_id = fields.Many2one(
        "hr.leave.allocation",
        string="Carryover Origin Allocation",
        copy=False,
        index=True,
    )

    def _pr_process_accrual_until(self, date_to):
        self.ensure_one()
        if (
            self.state == "validate"
            and self.accrual_plan_id
            and self.date_from
            and self.date_from <= date_to
            and (not self.nextcall or self.nextcall <= date_to)
        ):
            self._process_accrual_plans(date_to, log=False)

    def _pr_prepare_next_year_allocation_vals(self, date_from, date_to):
        self.ensure_one()
        return {
            "name": f"{self.holiday_status_id.name} Accrual {date_from.year}/{date_to.year} - {self.employee_id.name}",
            "holiday_type": "employee",
            "employee_id": self.employee_id.id,
            "employee_ids": [(6, 0, self.employee_id.ids)],
            "holiday_status_id": self.holiday_status_id.id,
            "allocation_type": "accrual",
            "date_from": date_from,
            "date_to": date_to,
            "number_of_days": 0.0,
            "accrual_plan_id": self.accrual_plan_id.id,
            "lastcall": date_from,
            "nextcall": False,
            "already_accrued": False,
        }

    def _pr_get_remaining_days_for_carryover(self, target_date):
        self.ensure_one()
        consumed_data = self.employee_id.with_context(
            default_date_from=target_date,
        )._get_consumed_leaves(
            self.holiday_status_id,
            target_date,
            ignore_future=True,
        )[0]
        allocation_data = consumed_data[self.employee_id][self.holiday_status_id][self]
        remaining = max(allocation_data.get("remaining_leaves", 0.0), 0.0)
        if self.holiday_status_id.request_unit == "hour":
            calendar = self.employee_id.sudo().resource_calendar_id or self.employee_id.company_id.resource_calendar_id
            remaining = remaining / (calendar.hours_per_day or 8.0)
        return float_round(remaining, precision_digits=5)

    def _pr_prepare_carryover_allocation_vals(self, remaining_days, date_from, date_to):
        self.ensure_one()
        return {
            "name": f"{self.holiday_status_id.name} Carryover {self.date_from.year}/{self.date_to.year} - {self.employee_id.name}",
            "holiday_type": "employee",
            "employee_id": self.employee_id.id,
            "employee_ids": [(6, 0, self.employee_id.ids)],
            "holiday_status_id": self.holiday_status_id.id,
            "allocation_type": "regular",
            "date_from": date_from,
            "date_to": date_to,
            "number_of_days": remaining_days,
            "pr_is_carryover_allocation": True,
            "pr_carryover_origin_allocation_id": self.id,
        }

    def _pr_create_carryover_allocation(self):
        self.ensure_one()
        if not self.date_to:
            return self.env["hr.leave.allocation"]

        date_from = self.date_to + timedelta(days=1)
        date_to = date_from + relativedelta(years=1) - timedelta(days=1)
        if self.employee_id.last_working_date and date_from > self.employee_id.last_working_date:
            return self.env["hr.leave.allocation"]
        existing_allocation = self.search([
            ("pr_carryover_origin_allocation_id", "=", self.id),
            ("active", "=", True),
            ("state", "!=", "refuse"),
        ], limit=1)
        if existing_allocation:
            return existing_allocation

        remaining_days = self._pr_get_remaining_days_for_carryover(self.date_to)
        if float_is_zero(remaining_days, precision_digits=5):
            return self.env["hr.leave.allocation"]

        carryover_allocation = self.sudo().create(
            self._pr_prepare_carryover_allocation_vals(remaining_days, date_from, date_to)
        )
        carryover_allocation.action_validate()
        return carryover_allocation

    def _pr_create_next_year_allocation(self):
        self.ensure_one()
        if not self.date_to:
            return self.env["hr.leave.allocation"]

        date_from = self.date_to + timedelta(days=1)
        date_to = date_from + relativedelta(years=1) - timedelta(days=1)
        if self.employee_id.last_working_date and date_from > self.employee_id.last_working_date:
            return self.env["hr.leave.allocation"]
        existing_allocation = self.search([
            ("employee_id", "=", self.employee_id.id),
            ("holiday_status_id", "=", self.holiday_status_id.id),
            ("allocation_type", "=", "accrual"),
            ("active", "=", True),
            ("date_from", "=", date_from),
            ("date_to", "=", date_to),
        ], limit=1)
        if existing_allocation:
            return existing_allocation

        next_allocation = self.sudo().create(self._pr_prepare_next_year_allocation_vals(date_from, date_to))
        next_allocation.action_validate()
        next_allocation._pr_process_accrual_until(min(fields.Date.context_today(self), date_to))
        return next_allocation

    @api.model
    def _cron_pr_create_next_year_for_ending_annual_allocations(self):
        today = fields.Date.context_today(self)
        allocations = self.sudo().search([
            ("allocation_type", "=", "accrual"),
            ("employee_id", "!=", False),
            ("holiday_status_id.leave_type", "=", "annual_leave"),
            ("accrual_plan_id", "!=", False),
            ("date_from", "!=", False),
            ("date_to", "=", today),
            ("state", "=", "validate"),
            ("active", "=", True),
        ])

        for allocation in allocations:
            allocation._pr_process_accrual_until(today)
            allocation._pr_create_carryover_allocation()
            allocation._pr_create_next_year_allocation()

    def _cron_pr_rollover_annual_leave_allocations(self):
        return self._cron_pr_create_next_year_for_ending_annual_allocations()
