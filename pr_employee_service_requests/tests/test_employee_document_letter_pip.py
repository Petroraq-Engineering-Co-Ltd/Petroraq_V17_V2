from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestPerformanceImprovementNotice(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        internal = cls.env.ref("base.group_user")
        hr_user_group = cls.env.ref("hr.group_hr_user")
        hr_manager_group = cls.env.ref("hr.group_hr_manager")
        cls.hr_user = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "PIP HR User",
            "login": "pip.hr.user.test",
            "email": "pip.hr@example.com",
            "groups_id": [(6, 0, [internal.id, hr_user_group.id])],
        })
        cls.department_manager = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "PIP Department Manager",
            "login": "pip.department.manager.test",
            "email": "pip.manager@example.com",
            "groups_id": [(6, 0, [internal.id])],
        })
        cls.hr_manager = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "PIP HR Manager",
            "login": "pip.hr.manager.test",
            "email": "pip.hrm@example.com",
            "groups_id": [(6, 0, [internal.id, hr_manager_group.id])],
        })
        cls.manager_employee = cls.env["hr.employee"].create({
            "name": "PIP Department Manager",
            "user_id": cls.department_manager.id,
        })
        cls.employee = cls.env["hr.employee"].create({
            "name": "PIP Employee",
            "parent_id": cls.manager_employee.id,
        })
        cls.attachment = cls.env["ir.attachment"].create({
            "name": "PIP.pdf",
            "type": "binary",
            "datas": b"VGVzdA==",
            "res_model": "pr.employee.document.letter",
        })

    def _create_notice(self):
        return self.env["pr.employee.document.letter"].with_user(self.hr_user).create({
            "letter_type": "performance_improvement",
            "employee_id": self.employee.id,
            "subject": "Performance Improvement Notice",
            "body_html": "<p>Improvement plan details.</p>",
        })

    def test_hr_to_department_manager_to_hr_manager(self):
        notice = self._create_notice()
        model_class = type(notice)
        with patch.object(
            model_class,
            "_generate_letter_pdf_attachment",
            autospec=True,
            return_value=self.attachment,
        ):
            notice.with_user(self.hr_user).action_submit()
            self.assertEqual(notice.state, "department_manager_approval")
            self.assertEqual(notice.department_manager_user_id, self.department_manager)
            notice.with_user(self.department_manager).action_department_manager_approve()
        self.assertEqual(notice.state, "hr_manager_approval")
        self.assertEqual(notice.department_manager_approved_by_id, self.department_manager)

    def test_personal_email_required_before_final_approval(self):
        notice = self._create_notice()
        notice.write({
            "state": "hr_manager_approval",
            "department_manager_approved_by_id": self.department_manager.id,
        })
        with self.assertRaises(UserError):
            notice.with_user(self.hr_manager).action_hr_manager_approve()
