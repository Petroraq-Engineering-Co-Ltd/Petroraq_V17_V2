import logging

from odoo import api, fields, models


_logger = logging.getLogger(__name__)


class HrContract(models.Model):
    _inherit = "hr.contract"

    def _pr_onboarding_allocation_specs(self):
        self.ensure_one()
        specs = [
            {
                "name": "Marriage Leave",
                "days": 3.0,
                "allocation_type": "regular",
            },
            {
                "name": "Emergency Leave",
                "days": 5.0,
                "allocation_type": "regular",
            },
            {
                "name": "Hajj Leave",
                "days": 15.0,
                "allocation_type": "regular",
            },
            {
                "name": "Annual Leave",
                "days": 0.0,
                "allocation_type": "accrual",
                "leave_type_code": "annual_leave",
                "accrual_plan_name": "Annual Leave",
            },
        ]
        if self.employee_id.gender == "female":
            specs.append({
                "name": "Maternity Leave",
                "days": 90.0,
                "allocation_type": "regular",
            })
        return specs

    def _pr_find_leave_type(self, spec):
        self.ensure_one()
        LeaveType = self.env["hr.leave.type"].sudo()
        company = self.company_id or self.employee_id.company_id or self.env.company
        company_domain = ["|", ("company_id", "=", company.id), ("company_id", "=", False)]

        leave_type = LeaveType
        leave_type_code = spec.get("leave_type_code")
        if leave_type_code:
            leave_type = LeaveType.search(
                company_domain + [("active", "=", True), ("leave_type", "=", leave_type_code)],
                limit=1,
            )
        if not leave_type:
            leave_type = LeaveType.search(
                company_domain + [("active", "=", True), ("name", "=ilike", spec["name"])],
                limit=1,
            )
        return leave_type

    def _pr_find_accrual_plan(self, leave_type, plan_name):
        self.ensure_one()
        AccrualPlan = self.env["hr.leave.accrual.plan"].sudo()
        company = self.company_id or self.employee_id.company_id or self.env.company
        return AccrualPlan.search([
            ("name", "=ilike", plan_name),
            "|", ("company_id", "=", company.id), ("company_id", "=", False),
            "|", ("time_off_type_id", "=", leave_type.id), ("time_off_type_id", "=", False),
        ], order="time_off_type_id desc, id", limit=1)

    def _pr_has_active_allocation(self, leave_type, allocation_type=False):
        self.ensure_one()
        domain = [
            ("employee_id", "=", self.employee_id.id),
            ("holiday_status_id", "=", leave_type.id),
            ("state", "in", ["draft", "confirm", "validate"]),
            ("active", "=", True),
        ]
        if allocation_type:
            domain.append(("allocation_type", "=", allocation_type))
        return bool(self.env["hr.leave.allocation"].sudo().search_count(domain))

    def _pr_prepare_onboarding_allocation_vals(self, leave_type, spec, accrual_plan=False):
        self.ensure_one()
        vals = {
            "name": f"{leave_type.name} Allocation - {self.employee_id.name}",
            "holiday_type": "employee",
            "employee_id": self.employee_id.id,
            "employee_ids": [(6, 0, self.employee_id.ids)],
            "holiday_status_id": leave_type.id,
            "allocation_type": spec["allocation_type"],
            "date_from": self.date_start,
        }
        if spec["allocation_type"] == "accrual":
            vals.update({
                "name": f"{leave_type.name} Accrual Allocation - {self.employee_id.name}",
                "number_of_days": 0.0,
                "accrual_plan_id": accrual_plan.id,
            })
        else:
            vals.update({
                "number_of_days": spec["days"],
            })
        return vals

    def _pr_sync_onboarding_timeoff_allocations(self):
        Allocation = self.env["hr.leave.allocation"].sudo()
        today = fields.Date.context_today(self)
        for contract in self.sudo():
            if not contract.employee_id or not contract.date_start:
                continue

            for spec in contract._pr_onboarding_allocation_specs():
                leave_type = contract._pr_find_leave_type(spec)
                if not leave_type:
                    _logger.warning(
                        "Skipping onboarding allocation for %s: leave type %s was not found.",
                        contract.employee_id.display_name,
                        spec["name"],
                    )
                    continue

                if contract._pr_has_active_allocation(leave_type):
                    continue

                accrual_plan = False
                if spec["allocation_type"] == "accrual":
                    accrual_plan = contract._pr_find_accrual_plan(leave_type, spec["accrual_plan_name"])
                    if not accrual_plan:
                        _logger.warning(
                            "Skipping annual accrual allocation for %s: accrual plan %s was not found.",
                            contract.employee_id.display_name,
                            spec["accrual_plan_name"],
                        )
                        continue

                allocation = Allocation.create(
                    contract._pr_prepare_onboarding_allocation_vals(leave_type, spec, accrual_plan)
                )
                if allocation.allocation_type == "accrual":
                    allocation.write({
                        "lastcall": contract.date_start,
                        "nextcall": False,
                        "number_of_days": 0.0,
                        "already_accrued": False,
                    })
                    if contract.date_start <= today:
                        allocation._process_accrual_plans(today, log=False)
                allocation.action_validate()

    @api.model_create_multi
    def create(self, vals_list):
        contracts = super().create(vals_list)
        contracts._pr_sync_onboarding_timeoff_allocations()
        return contracts

    def write(self, vals):
        result = super().write(vals)
        if {"employee_id", "date_start", "company_id"}.intersection(vals):
            self._pr_sync_onboarding_timeoff_allocations()
        return result

    def action_running(self):
        result = super().action_running()
        self._pr_sync_onboarding_timeoff_allocations()
        return result
