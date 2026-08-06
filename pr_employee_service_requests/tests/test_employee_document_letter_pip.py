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
        md_group = cls.env.ref("pr_custom_purchase.managing_director")
        cls.managing_director = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Letter Managing Director",
            "login": "letter.managing.director.test",
            "email": "letter.md@example.com",
            "groups_id": [(6, 0, [internal.id, md_group.id])],
        })
        cls.manager_employee = cls.env["hr.employee"].create({
            "name": "PIP Department Manager",
            "user_id": cls.department_manager.id,
        })
        cls.employee = cls.env["hr.employee"].create({
            "name": "PIP Employee",
            "parent_id": cls.manager_employee.id,
        })
        cls.hr_manager_employee = cls.env["hr.employee"].create({
            "name": "PIP HR Manager",
            "user_id": cls.hr_manager.id,
        })
        cls.hr_managed_employee = cls.env["hr.employee"].create({
            "name": "HR Manager Direct Report",
            "parent_id": cls.hr_manager_employee.id,
        })
        cls.md_employee = cls.env["hr.employee"].create({
            "name": "Letter Managing Director",
            "user_id": cls.managing_director.id,
        })
        cls.md_managed_employee = cls.env["hr.employee"].create({
            "name": "Managing Director Direct Report",
            "parent_id": cls.md_employee.id,
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

    def test_final_approval_does_not_automatically_send_notice(self):
        self.employee.private_email = "employee.private@example.com"
        notice = self._create_notice()
        notice.write({
            "state": "hr_manager_approval",
            "department_manager_approved_by_id": self.department_manager.id,
        })
        model_class = type(notice)
        with patch.object(
            model_class,
            "_generate_letter_pdf_attachment",
            autospec=True,
            return_value=self.attachment,
        ):
            notice.with_user(self.hr_manager).action_hr_manager_approve()
        self.assertEqual(notice.state, "approved")
        self.assertFalse(notice.sent_date)
        self.assertFalse(notice.sent_email_to)
        notice.with_user(self.hr_manager)._compute_action_flags()
        self.assertTrue(notice.can_send)
        wizard_values = self.env["pr.employee.letter.send.wizard"].with_user(
            self.hr_manager
        ).with_context(
            default_letter_id=notice.id,
            active_model=notice._name,
            active_id=notice.id,
        ).default_get(["letter_id", "recipient_mode", "email_to"])
        self.assertEqual(wizard_values["recipient_mode"], "private")
        self.assertEqual(wizard_values["email_to"], "employee.private@example.com")

    def test_all_letter_types_follow_department_manager_then_hr_manager(self):
        letter = self.env["pr.employee.document.letter"].create({
            "letter_type": "warning",
            "employee_id": self.employee.id,
            "subject": "Warning Letter",
            "body_html": "<p>Warning details.</p>",
        })
        model_class = type(letter)
        with patch.object(
            model_class,
            "_generate_letter_pdf_attachment",
            autospec=True,
            return_value=self.attachment,
        ):
            letter.action_submit()
            self.assertEqual(letter.state, "department_manager_approval")
            letter.with_user(self.department_manager).action_department_manager_approve()
            self.assertEqual(letter.state, "hr_manager_approval")
            letter.with_user(self.hr_manager).action_hr_manager_approve()
        self.assertEqual(letter.state, "approved")

    def test_hr_manager_department_manager_approves_only_once(self):
        letter = self.env["pr.employee.document.letter"].create({
            "letter_type": "experience",
            "employee_id": self.hr_managed_employee.id,
            "subject": "Experience Letter",
            "body_html": "<p>Experience details.</p>",
        })
        model_class = type(letter)
        with patch.object(
            model_class,
            "_generate_letter_pdf_attachment",
            autospec=True,
            return_value=self.attachment,
        ):
            letter.action_submit()
            letter.with_user(self.hr_manager).action_department_manager_approve()
        self.assertEqual(letter.state, "approved")
        self.assertEqual(letter.department_manager_approved_by_id, self.hr_manager)
        self.assertEqual(letter.hr_manager_approved_by_id, self.hr_manager)

    def test_md_department_manager_approves_only_once(self):
        letter = self.env["pr.employee.document.letter"].create({
            "letter_type": "appraisal",
            "employee_id": self.md_managed_employee.id,
            "subject": "Appraisal Letter",
            "body_html": "<p>Appraisal details.</p>",
        })
        model_class = type(letter)
        with patch.object(
            model_class,
            "_generate_letter_pdf_attachment",
            autospec=True,
            return_value=self.attachment,
        ):
            letter.action_submit()
            letter.with_user(self.managing_director).action_department_manager_approve()
        self.assertEqual(letter.state, "approved")
        self.assertEqual(letter.department_manager_approved_by_id, self.managing_director)
        self.assertEqual(letter.hr_manager_approved_by_id, self.managing_director)
