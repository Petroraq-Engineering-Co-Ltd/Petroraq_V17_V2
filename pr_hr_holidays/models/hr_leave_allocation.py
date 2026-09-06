from datetime import timedelta

from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import float_is_zero, float_round

from .annual_accrual import lifetime_entitlement


class HrLeaveAllocation(models.Model):
    _inherit = "hr.leave.allocation"

    pr_service_year_anchor = fields.Date(copy=False, string="Service anniversary anchor")

    def _get_request_unit(self):
        self.ensure_one()
        if self.allocation_type == "accrual" and self.accrual_plan_id.pr_annual_earning_limit:
            # These plans have no milestone from which Odoo can infer the unit.
            return "day"
        return super()._get_request_unit()

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            plan = self.env["hr.leave.accrual.plan"].browse(vals.get("accrual_plan_id"))
            if vals.get("allocation_type") == "accrual" and plan.pr_annual_earning_limit:
                start = fields.Date.to_date(vals.get("date_from")) or fields.Date.context_today(self)
                if not vals.get("pr_service_year_anchor"):
                    vals["pr_service_year_anchor"] = start
                vals.setdefault("number_of_days", 0.0)
        return super().create(vals_list)

    @api.constrains("accrual_plan_id", "allocation_type", "date_from", "date_to",
                    "holiday_status_id", "number_of_days", "pr_service_year_anchor")
    def _check_pr_service_year(self):
        for allocation in self:
            plan = allocation.accrual_plan_id
            if allocation.allocation_type != "accrual" or not plan.pr_annual_earning_limit:
                continue
            if (allocation.holiday_status_id.leave_type != "annual_leave" or
                    allocation.holiday_status_id.request_unit == "hour"):
                raise ValidationError(_("Service-year plans require an Annual Leave type measured in days or half days."))
            if allocation.number_of_days < 0:
                raise ValidationError(_("Earned days cannot be negative."))

    def _process_accrual_plans(self, date_to=False, force_period=False, log=True):
        custom = self.filtered(lambda a: a.allocation_type == "accrual" and a.accrual_plan_id.pr_annual_earning_limit)
        result = super(HrLeaveAllocation, self - custom)._process_accrual_plans(date_to, force_period, log)
        target = fields.Date.to_date(date_to) if date_to else fields.Date.context_today(self)
        for allocation in custom:
            allocation._check_pr_service_year()
            cutoffs = [d for d in (allocation.date_to, allocation.employee_id.last_working_date) if d]
            cutoff = min(cutoffs) if cutoffs else False
            final_credit = bool(cutoff and target > cutoff)
            if target < allocation.date_from or (not final_credit and allocation.nextcall and allocation.nextcall > target):
                continue
            plan = allocation.accrual_plan_id
            earned = lifetime_entitlement(
                allocation.date_from, cutoff, target,
                plan.pr_annual_entitlement, plan.pr_earning_days, plan.accrued_gain_time,
            )
            # number_of_days is gross granted leave; taking leave never reduces it.
            # A cumulative target makes retries and missed cron runs idempotent.
            allocation.update({
                "number_of_days": earned if final_credit else max(allocation.number_of_days, earned),
                "lastcall": min(target, cutoff + timedelta(days=1)) if cutoff else target,
                "nextcall": target + timedelta(days=1),
                "already_accrued": False,
            })
        return result

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
            "pr_service_year_anchor": self.pr_service_year_anchor or self.date_from,
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
        if self.accrual_plan_id.pr_annual_earning_limit:
            return self.env["hr.leave.allocation"]
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
        if self.accrual_plan_id.pr_annual_earning_limit:
            return self.env["hr.leave.allocation"]
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
            ("allocation_type", "in", ["accrual", "regular"]),
            ("employee_id", "!=", False),
            ("holiday_status_id.leave_type", "=", "annual_leave"),
            ("date_from", "!=", False),
            ("date_to", "<", today),
            ("state", "=", "validate"),
            ("active", "=", True),
        ])

        for allocation in allocations:
            if allocation.allocation_type == "accrual":
                end = allocation.date_to
                if allocation.accrual_plan_id.pr_annual_earning_limit:
                    end += timedelta(days=1)
                allocation._pr_process_accrual_until(end)
            allocation._pr_create_carryover_allocation()
            if allocation.allocation_type == "accrual" and allocation.accrual_plan_id:
                allocation._pr_create_next_year_allocation()

    def _cron_pr_rollover_annual_leave_allocations(self):
        return self._cron_pr_create_next_year_for_ending_annual_allocations()
