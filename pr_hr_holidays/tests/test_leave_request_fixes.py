from datetime import date, datetime

from freezegun import freeze_time

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestLeaveRequestFixes(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # pr_base requires a unique VAT on company partners
        cls.company = cls.env["res.company"].create({
            "name": "Leave Request Fixes Test Company",
            "vat": "PRLEAVETESTFIXES01",
        })
        cls.env.user.sudo().write({"company_ids": [Command.link(cls.company.id)]})

        internal = cls.env.ref("base.group_user")
        employee_groups = (
            cls.env.ref("de_hr_workspace.group_hr_employee_workspace", raise_if_not_found=False)
            or cls.env.ref("hr_holidays.group_hr_holidays_user")
        )

        def _make_user(name, login, groups):
            return cls.env["res.users"].with_context(no_reset_password=True).create({
                "name": name,
                "login": login,
                "email": f"{login}@example.com",
                "company_id": cls.company.id,
                "company_ids": [Command.set(cls.company.ids)],
                "groups_id": [Command.set((internal | groups).ids)],
            })

        cls.employee_user = _make_user("Fixes Employee", "leave.fixes.employee", employee_groups)
        cls.dept_manager_user = _make_user("Fixes Dept Manager", "leave.fixes.dept.mgr", employee_groups)
        cls.hr_supervisor_user = _make_user(
            "Fixes HR Supervisor", "leave.fixes.hr.sup", cls.env.ref("pr_hr.group_hr_supervisor"),
        )
        cls.hr_manager_user = _make_user(
            "Fixes HR Manager", "leave.fixes.hr.mgr", cls.env.ref("pr_hr.group_hr_manager"),
        )

        cls.department = cls.env["hr.department"].create({
            "name": "Fixes Scoped Department",
            "company_id": cls.company.id,
        })
        cls.dept_manager_emp = cls.env["hr.employee"].create({
            "name": "Fixes Dept Manager Employee",
            "user_id": cls.dept_manager_user.id,
            "company_id": cls.company.id,
        })
        cls.employee = cls.env["hr.employee"].create({
            "name": "Fixes Employee",
            "user_id": cls.employee_user.id,
            "parent_id": cls.dept_manager_emp.id,
            "department_id": cls.department.id,
            "company_id": cls.company.id,
        })
        cls.other_employee = cls.env["hr.employee"].create({
            "name": "Fixes Other Employee",
            "company_id": cls.company.id,
        })

        cls.annual_type = cls.env["hr.leave.type"].create({
            "name": "Fixes Annual Leave",
            "time_type": "leave",
            "request_unit": "day",
            "requires_allocation": "yes",
            "allocation_validation_type": "no",
            "leave_type": "annual_leave",
            "company_id": cls.company.id,
        })
        cls.business_type = cls.env["hr.leave.type"].create({
            "name": "Fixes Business Trip",
            "time_type": "leave",
            "request_unit": "day",
            "requires_allocation": "no",
            "leave_type": "business_leave",
            "company_id": cls.company.id,
        })

    def _allocate(self, employee, leave_type, days, date_from=date(2099, 1, 1)):
        allocation = self.env["hr.leave.allocation"].create({
            "name": "Fixes Allocation",
            "holiday_type": "employee",
            "employee_id": employee.id,
            "employee_ids": [Command.set(employee.ids)],
            "holiday_status_id": leave_type.id,
            "allocation_type": "regular",
            "number_of_days": days,
            "date_from": date_from,
        })
        allocation.action_validate()
        return allocation

    def _draft(self, user, employee, date_from, date_to, leave_type=None):
        return self.env["pr.hr.leave.request"].with_user(user).sudo().create({
            "employee_id": employee.id,
            "company_id": self.company.id,
            "leave_type_id": (leave_type or self.annual_type).id,
            "date_from": date_from,
            "date_to": date_to,
        })

    # ------------------------------------------------------------------
    # Late approval / standard validation / allocation_bypassed
    # ------------------------------------------------------------------

    def test_late_approval_creates_validated_leave_with_resource_leave(self):
        # 3 calendar days requested against exactly 3 allocated days.
        self._allocate(self.employee, self.annual_type, 3)
        with freeze_time("2099-03-02"):
            request = self._draft(self.employee_user, self.employee, date(2099, 3, 10), date(2099, 3, 12))
            request.with_user(self.employee_user).action_submit()
        self.assertEqual(request.state, "employee_manager_approval")

        # HR Manager (without the override group) approves after the leave started.
        self.assertFalse(self.hr_manager_user.has_group("pr_hr_holidays.group_leave_allocation_limit_override"))
        with freeze_time("2099-03-11"):
            request.with_user(self.hr_manager_user).action_hr_manager_approve()

        self.assertEqual(request.state, "approved")
        leave = request.leave_id
        self.assertTrue(leave)
        self.assertEqual(leave.state, "validate")
        self.assertEqual(leave.number_of_days, 3)
        resource_leaves = self.env["resource.calendar.leaves"].sudo().search([("holiday_id", "=", leave.id)])
        self.assertTrue(resource_leaves, "Validation must go through hr.leave._validate_leave_request")

        # The allocation is now fully consumed by the approved leave itself.
        request.invalidate_recordset(["allocation_bypassed"])
        self.assertFalse(request.allocation_bypassed)

    # ------------------------------------------------------------------
    # hr.leave validations surface on submit
    # ------------------------------------------------------------------

    def test_submit_blocks_overlap_with_approved_time_off(self):
        self._allocate(self.employee, self.annual_type, 10)
        with freeze_time("2099-03-02"):
            first = self._draft(self.employee_user, self.employee, date(2099, 3, 10), date(2099, 3, 11))
            first.with_user(self.employee_user).action_submit()
            first.with_user(self.hr_manager_user).action_hr_manager_approve()
            self.assertEqual(first.state, "approved")

            second = self._draft(self.employee_user, self.employee, date(2099, 3, 11), date(2099, 3, 12))
            # Core hr.leave overlap error is raised on submit, not at final approval
            with self.assertRaises(ValidationError):
                second.with_user(self.employee_user).action_submit()
        self.assertEqual(second.state, "draft")

    def test_submit_blocks_overlap_with_pending_request_and_dry_run_leaves_nothing(self):
        self._allocate(self.employee, self.annual_type, 10)
        with freeze_time("2099-03-02"):
            first = self._draft(self.employee_user, self.employee, date(2099, 3, 10), date(2099, 3, 11))
            first.with_user(self.employee_user).action_submit()
            self.assertEqual(first.state, "employee_manager_approval")
            # The hr.leave dry run on submit is rolled back
            self.assertFalse(self.env["hr.leave"].sudo().search([("employee_id", "=", self.employee.id)]))

            second = self._draft(self.employee_user, self.employee, date(2099, 3, 11), date(2099, 3, 11))
            with self.assertRaisesRegex(ValidationError, "awaiting approval"):
                second.with_user(self.employee_user).action_submit()
        self.assertEqual(second.state, "draft")

    def test_create_employee_leave_handles_multiple_records(self):
        self._allocate(self.other_employee, self.annual_type, 10)
        requests = (
            self._draft(self.hr_manager_user, self.other_employee, date(2099, 4, 6), date(2099, 4, 7))
            | self._draft(self.hr_manager_user, self.other_employee, date(2099, 4, 13), date(2099, 4, 14))
        )
        requests.sudo().write({"state": "approved", "approval_state": "approved"})
        leaves = requests.sudo()._create_employee_leave()
        self.assertEqual(len(leaves), 2)
        self.assertEqual(set(leaves.mapped("state")), {"validate"})
        self.assertEqual(requests.mapped("leave_id"), leaves)

    # ------------------------------------------------------------------
    # Last working day
    # ------------------------------------------------------------------

    def test_request_beyond_last_working_day_rejected_at_submit(self):
        employee = self.env["hr.employee"].create({
            "name": "Fixes Leaving Employee",
            "company_id": self.company.id,
        })
        self._allocate(employee, self.annual_type, 10)
        request = self._draft(self.hr_manager_user, employee, date(2099, 3, 10), date(2099, 3, 12))

        contract = self.env["hr.contract"].create({
            "name": "Fixes Leaving Contract",
            "employee_id": employee.id,
            "company_id": self.company.id,
            "date_start": date(2099, 1, 1),
            "joining_date": date(2099, 1, 1),
            "wage": 3000.0,
            "structure_type_id": self.env["hr.payroll.structure.type"].create({"name": "Fixes Structure"}).id,
        })
        contract.write({"state": "open"})
        contract.write({"date_end": date(2099, 3, 11)})
        self.assertEqual(employee.last_working_date, date(2099, 3, 11))

        with self.assertRaisesRegex(ValidationError, "Last Working Day"):
            request.with_user(self.hr_manager_user).action_submit()

    # ------------------------------------------------------------------
    # Cancellation request (B1)
    # ------------------------------------------------------------------

    def test_cancel_request_only_from_approved_by_employee_or_hr(self):
        self._allocate(self.employee, self.annual_type, 10)
        request = self._draft(self.employee_user, self.employee, date(2099, 5, 4), date(2099, 5, 5))
        request.with_user(self.employee_user).action_submit()
        self.assertEqual(request.state, "employee_manager_approval")
        with self.assertRaises(UserError):
            request.with_user(self.employee_user).action_employee_cancel_request()

        request.with_user(self.hr_manager_user).action_hr_manager_approve()
        self.assertEqual(request.state, "approved")
        with self.assertRaises(UserError):
            request.with_user(self.dept_manager_user).action_employee_cancel_request()

        request.with_user(self.employee_user).action_employee_cancel_request()
        self.assertEqual(request.state, "cancel_request")

    # ------------------------------------------------------------------
    # Protected workflow fields (B6)
    # ------------------------------------------------------------------

    def test_non_hr_user_cannot_write_workflow_fields(self):
        self._allocate(self.employee, self.annual_type, 10)
        request = self.env["pr.hr.leave.request"].with_user(self.employee_user).create({
            "leave_type_id": self.annual_type.id,
            "date_from": date(2099, 6, 1),
            "date_to": date(2099, 6, 2),
            "state": "draft",
        })
        as_employee = request.with_user(self.employee_user)
        as_employee.write({"note": "Still editable"})
        for vals in (
            {"state": "approved"},
            {"approval_state": "approved"},
            {"manager_approved_user_id": self.employee_user.id},
            {"allocation_override_applied": True},
            {"reject_reason": "x"},
        ):
            with self.subTest(vals=vals), self.assertRaises(AccessError):
                as_employee.write(vals)
        with self.assertRaises(AccessError):
            self.env["pr.hr.leave.request"].with_user(self.employee_user).create({
                "leave_type_id": self.annual_type.id,
                "date_from": date(2099, 6, 8),
                "date_to": date(2099, 6, 9),
                "state": "approved",
            })

        # The model's own actions still work for the same user.
        as_employee.action_submit()
        self.assertEqual(request.state, "employee_manager_approval")
        request.with_user(self.dept_manager_user).action_manager_approve()
        self.assertEqual(request.manager_approved_user_id, self.dept_manager_user)

    def test_rejection_requires_reason(self):
        self._allocate(self.employee, self.annual_type, 10)
        request = self._draft(self.employee_user, self.employee, date(2099, 7, 6), date(2099, 7, 7))
        request.with_user(self.employee_user).action_submit()
        with self.assertRaises(UserError):
            request.with_user(self.dept_manager_user)._apply_stage_rejection("manager", "   ")
        request.with_user(self.dept_manager_user)._apply_stage_rejection("manager", "Busy period")
        self.assertEqual(request.state, "rejected")

    # ------------------------------------------------------------------
    # Public holidays (scoped)
    # ------------------------------------------------------------------

    def test_scoped_public_holiday_only_affects_scoped_employees(self):
        # Mon 2099-03-09 .. Fri 2099-03-13, holiday on Wed 2099-03-11 for one department.
        self.env["hr.public.holiday"].create({
            "name": "Fixes Department Holiday",
            "date_from": date(2099, 3, 11),
            "date_to": date(2099, 3, 11),
            "state": "active",
            "type_select": "dep",
            "dep_ids": [Command.set(self.department.ids)],
        })
        holiday_day = date(2099, 3, 11)
        self.assertIn(holiday_day, self.employee._pr_get_public_holiday_dates(date(2099, 3, 9), date(2099, 3, 13)))
        self.assertNotIn(
            holiday_day, self.other_employee._pr_get_public_holiday_dates(date(2099, 3, 9), date(2099, 3, 13)),
        )

        for employee, expected in ((self.employee, 4), (self.other_employee, 5)):
            with self.subTest(employee=employee.name):
                request = self.env["pr.hr.leave.request"].new({
                    "employee_id": employee.id,
                    "company_id": self.company.id,
                    "leave_type_id": self.business_type.id,
                    "date_from": date(2099, 3, 9),
                    "date_to": date(2099, 3, 13),
                })
                request._compute_requested_days()
                self.assertEqual(request.requested_days, expected)

                leave = self.env["hr.leave"].new({
                    "employee_id": employee.id,
                    "holiday_status_id": self.business_type.id,
                    "request_date_from": date(2099, 3, 9),
                    "request_date_to": date(2099, 3, 13),
                    "date_from": datetime(2099, 3, 9, 0, 0, 0),
                    "date_to": datetime(2099, 3, 13, 23, 59, 59),
                })
                self.assertEqual(leave._get_duration()[0], expected)

        # A single-day request on the scoped holiday is blocked only for the scoped employee.
        with self.assertRaises(ValidationError):
            self.env["pr.hr.leave.request"].sudo().create({
                "employee_id": self.employee.id,
                "company_id": self.company.id,
                "leave_type_id": self.business_type.id,
                "date_from": holiday_day,
                "date_to": holiday_day,
            })

    # ------------------------------------------------------------------
    # Sick leave pay (service year + self exclusion)
    # ------------------------------------------------------------------

    def _validated_sick_leave(self, employee, leave_type, date_from, date_to):
        leave = self.env["hr.leave"].sudo().with_context(
            tracking_disable=True,
            mail_activity_automation_skip=True,
            leave_fast_create=True,
            leave_skip_state_check=True,
        ).create({
            "name": "Fixes Sick Leave",
            "employee_id": employee.id,
            "holiday_status_id": leave_type.id,
            "request_date_from": date_from,
            "request_date_to": date_to,
            "state": "confirm",
        })
        leave.action_validate()
        return leave

    def test_sick_leave_amount_uses_current_service_year_and_excludes_itself(self):
        employee = self.env["hr.employee"].create({
            "name": "Fixes Sick Employee",
            "company_id": self.company.id,
        })
        contract = self.env["hr.contract"].create({
            "name": "Fixes Sick Contract",
            "employee_id": employee.id,
            "company_id": self.company.id,
            "date_start": date(2023, 9, 1),
            "joining_date": date(2023, 9, 1),
            "wage": 9000.0,
            "structure_type_id": self.env["hr.payroll.structure.type"].create({"name": "Fixes Sick Structure"}).id,
        })
        contract.write({"state": "open"})
        self.assertEqual(contract.gross_amount, 9000.0)
        sick_type = self.env["hr.leave.type"].create({
            "name": "Fixes Sick Leave",
            "time_type": "leave",
            "request_unit": "day",
            "requires_allocation": "no",
            "leave_type": "sick_leave",
            "is_paid": True,
            "company_id": self.company.id,
        })
        # Previous service year (2024-09-01 .. 2025-08-31): ignored.
        self._validated_sick_leave(employee, sick_type, date(2025, 6, 1), date(2025, 6, 20))
        # Current service year (2025-09-01 .. 2026-08-31): 25 prior calendar days.
        self._validated_sick_leave(employee, sick_type, date(2025, 10, 1), date(2025, 10, 25))
        # Later in the same service year: not prior to the leave being paid.
        self._validated_sick_leave(employee, sick_type, date(2026, 4, 1), date(2026, 4, 5))

        leave = self._validated_sick_leave(employee, sick_type, date(2026, 1, 28), date(2026, 2, 10))
        self.assertEqual(leave._pr_get_prior_sick_leave_days(), 25)
        # Jan 28-31: 4 full days      -> 4 * 9000 / 31               = 1161.29
        # Feb 1-10: 1 full + 9 at 75% -> (1 + 9 * 0.75) * 9000 / 28 = 2491.07
        self.assertAlmostEqual(leave.leave_amount, 3652.36, places=2)

    # ------------------------------------------------------------------
    # Emergency leave code (consumed by pr_hr_attendance)
    # ------------------------------------------------------------------

    def test_emergency_leave_code_replaces_attendance(self):
        Leave = self.env["hr.leave"]
        if not hasattr(Leave, "_pr_leave_replaces_attendance"):
            self.skipTest("pr_hr_attendance is not installed")
        family_type = self.env["hr.leave.type"].create({
            "name": "Fixes Family Matter",
            "time_type": "leave",
            "request_unit": "day",
            "requires_allocation": "no",
            "leave_type": "emergency_leave",
            "company_id": self.company.id,
        })
        leave = Leave.new({
            "employee_id": self.employee.id,
            "holiday_status_id": family_type.id,
            "request_date_from": date(2099, 3, 9),
            "request_date_to": date(2099, 3, 9),
        })
        self.assertTrue(leave._pr_leave_replaces_attendance())
