from datetime import date

from odoo.tests.common import TransactionCase


class TestLastWorkingDayTimeOff(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create({
            "name": "Time Off Cutoff Test Employee",
        })
        cls.structure_type = cls.env["hr.payroll.structure.type"].create({
            "name": "Time Off Cutoff Test Structure",
        })
        cls.contract = cls.env["hr.contract"].create({
            "name": "Time Off Cutoff Test Contract",
            "employee_id": cls.employee.id,
            "date_start": date(2099, 1, 1),
            "joining_date": date(2099, 1, 1),
            "wage": 3000.0,
            "structure_type_id": cls.structure_type.id,
        })
        cls.contract.write({"state": "open"})
        cls.leave_type = cls.env["hr.leave.type"].create({
            "name": "Cutoff Test Leave",
            "time_type": "leave",
            "requires_allocation": "yes",
            "allocation_validation_type": "no",
        })

    def _create_allocation(self, date_from, date_to):
        allocation = self.env["hr.leave.allocation"].create({
            "name": "Cutoff Test Allocation",
            "holiday_type": "employee",
            "employee_id": self.employee.id,
            "employee_ids": [(6, 0, self.employee.ids)],
            "holiday_status_id": self.leave_type.id,
            "allocation_type": "regular",
            "number_of_days": 10.0,
            "date_from": date_from,
            "date_to": date_to,
        })
        allocation.action_validate()
        return allocation

    def test_allocations_close_at_last_working_day(self):
        current_allocation = self._create_allocation(
            date(2099, 1, 1),
            date(2099, 12, 31),
        )
        future_allocation = self._create_allocation(
            date(2099, 7, 1),
            date(2099, 12, 31),
        )

        self.contract.write({"date_end": date(2099, 6, 15)})

        self.assertEqual(current_allocation.date_to, date(2099, 6, 15))
        self.assertFalse(future_allocation.active)
