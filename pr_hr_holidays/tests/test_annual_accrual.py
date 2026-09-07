from datetime import date, timedelta

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..models.annual_accrual import earned_entitlement, next_anniversary


@tagged("post_install", "-at_install")
class TestAnnualAccrual(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create({"name": "Annual accrual test"})
        cls.leave_type = cls.env["hr.leave.type"].create({
            "name": "Annual accrual test", "leave_type": "annual_leave",
            "request_unit": "day", "allocation_validation_type": "officer",
        })

    def allocation(self, entitlement=21, start=date(2030, 1, 1), gain="end"):
        plan = self.env["hr.leave.accrual.plan"].create({
            "name": "Service-year test", "pr_annual_earning_limit": True,
            "pr_annual_entitlement": entitlement, "pr_earning_days": 330,
            "accrued_gain_time": gain,
        })
        return self.env["hr.leave.allocation"].create({
            "name": "Annual test", "employee_id": self.employee.id,
            "holiday_status_id": self.leave_type.id, "allocation_type": "accrual",
            "accrual_plan_id": plan.id, "date_from": start, "number_of_days": 0,
        })

    def test_entitlements_pause_and_retry(self):
        for entitlement in (21, 26):
            allocation = self.allocation(entitlement)
            for elapsed in (0, 165, 329, 330, 350, 365):
                target = allocation.date_from + timedelta(days=elapsed)
                allocation._process_accrual_plans(target)
                self.assertAlmostEqual(allocation.number_of_days, entitlement * min(elapsed, 330) / 330)
                allocation._process_accrual_plans(target)
                self.assertLessEqual(allocation.number_of_days, entitlement)

    def test_plan_selection_keeps_no_limit(self):
        plan = self.allocation().accrual_plan_id
        draft = self.env["hr.leave.allocation"].new({
            "employee_id": self.employee.id, "employee_ids": [(6, 0, self.employee.ids)],
            "holiday_status_id": self.leave_type.id, "allocation_type": "accrual",
            "accrual_plan_id": plan.id, "date_from": date(2025, 6, 6),
            "date_to": False, "number_of_days": 0,
        })
        draft._onchange_date_from()
        self.assertFalse(draft.date_to)
        self.assertEqual(draft._get_request_unit(), "day")
        draft.date_to = date(2025, 12, 31)
        draft._onchange_date_from()
        self.assertEqual(draft.date_to, date(2025, 12, 31))

    def test_existing_draft_selection_preserves_saved_record(self):
        allocation = self.env["hr.leave.allocation"].create({
            "employee_id": self.employee.id, "holiday_status_id": self.leave_type.id,
            "allocation_type": "accrual", "date_from": date(2025, 6, 6),
            "number_of_days": 0,
        })
        draft = self.env["hr.leave.allocation"].new(origin=allocation)
        draft.accrual_plan_id = self.allocation().accrual_plan_id
        draft._onchange_date_from()
        self.assertFalse(draft.date_to)
        self.assertFalse(allocation.date_to)
        self.assertEqual(allocation.number_of_days, 0)

    def test_leave_taken_does_not_reopen_cap(self):
        allocation = self.allocation()
        allocation.action_validate()
        allocation._process_accrual_plans(date(2030, 11, 30))
        leave = self.env["hr.leave"].create({
            "name": "Consume earned leave", "employee_id": self.employee.id,
            "holiday_status_id": self.leave_type.id,
            "request_date_from": date(2030, 12, 2), "request_date_to": date(2030, 12, 6),
        })
        if leave.state == "draft":
            leave.action_confirm()
        if leave.state == "confirm":
            leave.action_approve()
        if leave.state == "validate1":
            leave.action_validate()
        self.assertEqual(leave.state, "validate")
        allocation._process_accrual_plans(date(2030, 12, 20))
        self.assertEqual(allocation.number_of_days, 21)
        consumed = self.employee._get_consumed_leaves(
            self.leave_type, date(2030, 12, 20), ignore_future=True,
        )[0]
        self.assertGreater(consumed[self.employee][self.leave_type][allocation]["leaves_taken"], 0)

    def test_same_allocation_restarts_each_year(self):
        allocation = self.allocation()
        allocation.action_validate()
        allocation._process_accrual_plans(date(2031, 1, 1))
        self.assertFalse(allocation.date_to)
        self.assertFalse(allocation._pr_create_next_year_allocation())
        self.assertFalse(allocation._pr_create_carryover_allocation())
        allocation._process_accrual_plans(date(2031, 1, 2))
        self.assertAlmostEqual(allocation.number_of_days, 21 + 21 / 330)
        allocation._process_accrual_plans(date(2033, 1, 1))
        self.assertEqual(allocation.number_of_days, 63)

    def test_leap_year_and_gain_timing(self):
        anchor = date(2024, 2, 29)
        self.assertEqual(next_anniversary(date(2027, 2, 28), anchor), date(2028, 2, 29))
        start, end = date(2024, 1, 1), date(2024, 12, 31)
        self.assertEqual(earned_entitlement(start, end, start, 21, 330, "end"), 0)
        self.assertAlmostEqual(earned_entitlement(start, end, start, 21, 330, "start"), 21 / 330)
        self.assertEqual(earned_entitlement(start, end, end, 21, 330, "end"), 21)

    def test_invalid_policy_and_replacement_allocation(self):
        allocation = self.allocation()
        allocation.action_validate()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            allocation.accrual_plan_id.pr_annual_entitlement = 26
        replacement = self.allocation()
        replacement.action_validate()
        self.assertEqual(replacement.state, "validate")
        self.assertEqual(allocation.state, "validate")
        with self.assertRaises(ValidationError), self.cr.savepoint():
            allocation.number_of_days = -1

    def test_standard_plan_is_unchanged(self):
        plan = self.env["hr.leave.accrual.plan"].create({"name": "Standard empty plan"})
        allocation = self.env["hr.leave.allocation"].create({
            "employee_id": self.employee.id, "holiday_status_id": self.leave_type.id,
            "allocation_type": "accrual", "accrual_plan_id": plan.id,
            "date_from": date(2030, 1, 1), "number_of_days": 0,
        })
        allocation._process_accrual_plans(date(2030, 12, 31))
        self.assertFalse(allocation.date_to)
        self.assertEqual(allocation.number_of_days, 0)

    def test_early_closure_does_not_reset_entitlement(self):
        allocation = self.allocation()
        allocation.date_to = date(2030, 6, 30)
        allocation._process_accrual_plans(date(2031, 1, 1))
        self.assertAlmostEqual(allocation.number_of_days, 21 * 181 / 330)
        self.assertFalse(allocation._pr_create_next_year_allocation())
        self.assertFalse(allocation._pr_create_carryover_allocation())

    def test_later_year_termination_stays_capped(self):
        allocation = self.allocation(26)
        allocation.date_to = date(2031, 6, 30)
        for target in (date(2031, 7, 1), date(2032, 1, 1), date(2035, 1, 1)):
            allocation._process_accrual_plans(target)
            self.assertAlmostEqual(allocation.number_of_days, 26 + 26 * 181 / 330)
        self.assertFalse(allocation._pr_create_next_year_allocation())
        self.assertFalse(allocation._pr_create_carryover_allocation())

    def test_onboarding_uses_no_limit_for_custom_plan(self):
        allocation = self.allocation()
        contract = self.env["hr.contract"].new({
            "employee_id": self.employee.id, "date_start": date(2030, 1, 1),
        })
        vals = contract._pr_prepare_onboarding_allocation_vals(
            self.leave_type, {"allocation_type": "accrual"}, allocation.accrual_plan_id,
        )
        self.assertFalse(vals["date_to"])

    def test_retrospective_cutoff_recalculates_final_entitlement(self):
        allocation = self.allocation()
        allocation._process_accrual_plans(date(2032, 1, 1))
        allocation.date_to = date(2030, 6, 30)
        allocation._process_accrual_plans(date(2030, 7, 1))
        self.assertAlmostEqual(allocation.number_of_days, 21 * 181 / 330)
