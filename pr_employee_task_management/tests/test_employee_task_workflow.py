from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase


class TestEmployeeTaskWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        employee_group = cls.env.ref(
            "pr_employee_task_management.group_task_employee"
        )
        manager_group = cls.env.ref(
            "pr_employee_task_management.group_task_manager"
        )
        cls.employee_user = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create({
            "name": "Task Employee",
            "login": "task.employee.workflow@test.invalid",
            "email": "task.employee.workflow@test.invalid",
            "groups_id": [Command.link(employee_group.id)],
        })
        cls.manager_user = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create({
            "name": "Task Manager",
            "login": "task.manager.workflow@test.invalid",
            "email": "task.manager.workflow@test.invalid",
            "groups_id": [Command.link(manager_group.id)],
        })
        cls.other_user = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create({
            "name": "Other Task Employee",
            "login": "task.other.workflow@test.invalid",
            "email": "task.other.workflow@test.invalid",
            "groups_id": [Command.link(employee_group.id)],
        })
        cls.manager_employee = cls.env["hr.employee"].create({
            "name": "Task Manager",
            "user_id": cls.manager_user.id,
            "company_id": cls.env.company.id,
        })
        cls.employee = cls.env["hr.employee"].create({
            "name": "Task Employee",
            "user_id": cls.employee_user.id,
            "parent_id": cls.manager_employee.id,
            "company_id": cls.env.company.id,
        })
        cls.other_employee = cls.env["hr.employee"].create({
            "name": "Other Task Employee",
            "user_id": cls.other_user.id,
            "company_id": cls.env.company.id,
        })

    def _create_task(self):
        return self.env["employee.task.list"].with_user(self.employee_user).create({
            "employee_id": self.employee.id,
            "assign_date": fields.Date.today(),
            "task_line_ids": [Command.create({
                "sequence": 10,
                "description": "Prepare the assigned technical deliverable.",
                "assign_date": fields.Date.today(),
                "end_date": fields.Date.add(fields.Date.today(), days=2),
            })],
        })

    def test_complete_employee_manager_workflow(self):
        task = self._create_task()

        task.with_user(self.employee_user).action_submit_to_manager()
        self.assertEqual(task.state, "submitted_manager")

        task.with_user(self.manager_user).action_manager_approve()
        self.assertEqual(task.state, "manager_approved")

        task.with_user(self.employee_user).action_start_work()
        task.task_line_ids.with_user(self.employee_user).write({
            "activities": "Prepared and checked the deliverable.",
            "progress": 100.0,
        })
        task.with_user(self.employee_user).action_mark_completed()
        self.assertEqual(task.state, "completed")

        task.with_user(self.manager_user).action_close()
        self.assertEqual(task.state, "closed")
        self.assertEqual(task.task_line_ids.task_status, "closed")
        self.assertTrue(task.history_ids)

    def test_return_requires_manager_remarks(self):
        task = self._create_task()
        task.with_user(self.employee_user).action_submit_to_manager()

        with self.assertRaises(ValidationError):
            task.with_user(self.manager_user).action_manager_return()

        task.with_user(self.manager_user).manager_remarks = "Add measurable output."
        task.with_user(self.manager_user).action_manager_return()
        self.assertEqual(task.state, "returned_manager")

    def test_unrelated_employee_cannot_approve(self):
        task = self._create_task()
        task.with_user(self.employee_user).action_submit_to_manager()

        with self.assertRaises(AccessError):
            task.with_user(self.other_user).action_manager_approve()

    def test_cannot_complete_with_incomplete_line(self):
        task = self._create_task()
        task.with_user(self.employee_user).action_submit_to_manager()
        task.with_user(self.manager_user).action_manager_approve()
        task.with_user(self.employee_user).action_start_work()

        with self.assertRaises(ValidationError):
            task.with_user(self.employee_user).action_mark_completed()
