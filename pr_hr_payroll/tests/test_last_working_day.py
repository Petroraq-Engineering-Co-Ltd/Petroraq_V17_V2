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

    def test_final_payslip_is_capped_and_prorated(self):
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
