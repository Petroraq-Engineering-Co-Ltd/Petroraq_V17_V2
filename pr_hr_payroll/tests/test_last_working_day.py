from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestLastWorkingDay(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create({
            "name": "Last Working Day Test Employee",
        })
        cls.structure_type = cls.env["hr.payroll.structure.type"].create({
            "name": "Last Working Day Test Structure",
        })
        cls.contract = cls.env["hr.contract"].create({
            "name": "Last Working Day Test Contract",
            "employee_id": cls.employee.id,
            "date_start": date(2099, 1, 1),
            "joining_date": date(2099, 1, 1),
            "date_end": date(2099, 6, 15),
            "wage": 3000.0,
            "structure_type_id": cls.structure_type.id,
        })
        cls.contract.write({"state": "open"})

    def test_final_payslip_is_capped_and_ratio_is_computable(self):
        payroll_run = self.env["hr.payslip.run"].create({
            "name": "June 2099",
            "date_start": date(2099, 6, 1),
            "date_end": date(2099, 6, 30),
        })
        payslip = self.env["hr.payslip"].create({
            "name": "Final Payslip",
            "employee_id": self.employee.id,
            "contract_id": self.contract.id,
            "payslip_run_id": payroll_run.id,
            "date_from": payroll_run.date_start,
            "date_to": payroll_run.date_end,
        })

        self.assertEqual(payslip.date_to, date(2099, 6, 15))
        self.assertAlmostEqual(payslip._pr_get_last_working_day_ratio(), 0.5)
        self.assertTrue(self.employee.active)
        self.assertEqual(self.employee.last_working_date, date(2099, 6, 15))

    def test_last_working_day_shortfall_becomes_absence_amount(self):
        payroll_run = self.env["hr.payslip.run"].create({
            "name": "June 2099",
            "date_start": date(2099, 6, 1),
            "date_end": date(2099, 6, 30),
        })
        payslip = self.env["hr.payslip"].create({
            "name": "Final Payslip",
            "employee_id": self.employee.id,
            "contract_id": self.contract.id,
            "payslip_run_id": payroll_run.id,
            "date_from": payroll_run.date_start,
            "date_to": payroll_run.date_end,
        })

        self.assertEqual(payslip._pr_get_last_working_day_missing_days(), 15)
        self.assertAlmostEqual(
            payslip._pr_get_last_working_day_absence_amount(),
            1500.0,
        )

    def test_terminal_absence_amount_excludes_transport_when_configured(self):
        if "exclude_transportation_from_attendance_gross" not in self.employee._fields:
            self.skipTest("transport exclusion field is not available in this test environment")

        transport_rule = self.env["hr.salary.rule"].search([
            ("code", "=", "TRANSPORTATION"),
        ], limit=1)
        extra_rule = self.env["hr.salary.rule"].search([
            ("code", "!=", "BASIC"),
            ("code", "!=", "TRANSPORTATION"),
        ], limit=1)
        if not transport_rule or not extra_rule:
            self.skipTest("salary rules for transport exclusion are not available")

        employee = self.env["hr.employee"].create({
            "name": "Transport Exclusion Final Day Employee",
            "exclude_transportation_from_attendance_gross": True,
        })
        contract = self.env["hr.contract"].create({
            "name": "Transport Exclusion Final Day Contract",
            "employee_id": employee.id,
            "date_start": date(2099, 1, 1),
            "joining_date": date(2099, 1, 1),
            "date_end": date(2099, 6, 24),
            "wage": 5000.0,
            "structure_type_id": self.structure_type.id,
        })
        self.env["hr.contract.salary.rule"].create({
            "contract_id": contract.id,
            "salary_rule_id": extra_rule.id,
            "pay_in_payslip": True,
            "amount_type": "fixed",
            "amount_value": 1250.0,
        })
        self.env["hr.contract.salary.rule"].create({
            "contract_id": contract.id,
            "salary_rule_id": transport_rule.id,
            "pay_in_payslip": True,
            "amount_type": "fixed",
            "amount_value": 3875.45,
        })
        contract._compute_amount()
        contract.write({"state": "open"})

        payroll_run = self.env["hr.payslip.run"].create({
            "name": "June 2099 - Transport Exclusion",
            "date_start": date(2099, 6, 1),
            "date_end": date(2099, 6, 30),
        })
        payslip = self.env["hr.payslip"].create({
            "name": "Transport Exclusion Final Payslip",
            "employee_id": employee.id,
            "contract_id": contract.id,
            "payslip_run_id": payroll_run.id,
            "date_from": payroll_run.date_start,
            "date_to": payroll_run.date_end,
        })

        self.assertEqual(payslip._pr_get_last_working_day_missing_days(), 6)
        self.assertAlmostEqual(contract.gross_amount, 10125.45, places=2)
        self.assertAlmostEqual(payslip._pr_get_attendance_deduction_salary_base(), 6250.0, places=2)
        self.assertAlmostEqual(payslip._pr_get_last_working_day_absence_amount(), 1250.0, places=2)

    def test_employee_is_excluded_after_cutoff(self):
        july_run = self.env["hr.payslip.run"].create({
            "name": "July 2099",
            "date_start": date(2099, 7, 1),
            "date_end": date(2099, 7, 31),
        })
        wizard_model = self.env["hr.payslip.employees"].with_context(
            active_model="hr.payslip.run",
            active_id=july_run.id,
        )
        eligible_employees = wizard_model._pr_filter_employees_for_period(self.employee)
        self.assertFalse(eligible_employees)

        with self.assertRaises(ValidationError):
            self.env["hr.payslip"].create({
                "name": "Invalid Future Payslip",
                "employee_id": self.employee.id,
                "contract_id": self.contract.id,
                "date_from": july_run.date_start,
                "date_to": july_run.date_end,
            })

    def test_time_off_pairs_are_not_prorated_again(self):
        payslip_model = self.env["hr.payslip"]

        for code in ("PAID86", "PAID87", "SICKTO88", "SICKTO89", "BTA", "BTD"):
            self.assertFalse(
                payslip_model._pr_should_prorate_final_period_line(code, "ALW"),
                "%s is attendance-derived and must retain its full daily amount" % code,
            )

        self.assertTrue(
            payslip_model._pr_should_prorate_final_period_line("BASIC", "BASIC")
        )
        self.assertTrue(
            payslip_model._pr_should_prorate_final_period_line("TRANSPORTATION", "ALW")
        )
