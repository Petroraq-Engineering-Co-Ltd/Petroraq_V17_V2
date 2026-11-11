from unittest.mock import patch

from lxml import etree

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase


class TestPerformanceImprovementNotice(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        internal = cls.env.ref("base.group_user")
        hr_user_group = cls.env.ref("hr.group_hr_user")
        legacy_hr_manager_group = cls.env.ref("hr.group_hr_manager")
        hr_supervisor_group = cls.env.ref("pr_hr.group_hr_supervisor")
        hr_manager_group = cls.env.ref("pr_hr.group_hr_manager")
        hr_md_group = cls.env.ref("pr_hr.group_hr_md")
        system_group = cls.env.ref("base.group_system")
        cls.hr_user = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "PIP HR User",
            "login": "pip.hr.user.test",
            "email": "pip.hr@example.com",
            "groups_id": [(6, 0, [internal.id, hr_user_group.id])],
        })
        cls.hr_supervisor = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Letter HR Supervisor",
            "login": "letter.hr.supervisor.test",
            "email": "letter.hrsup@example.com",
            "groups_id": [(6, 0, [internal.id, hr_supervisor_group.id])],
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
        cls.managing_director = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Letter Managing Director",
            "login": "letter.managing.director.test",
            "email": "letter.md@example.com",
            "groups_id": [(6, 0, [internal.id, hr_md_group.id])],
        })
        cls.legacy_hr_manager = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Legacy HR Manager Only",
            "login": "letter.legacy.hrm.test",
            "email": "letter.legacy.hrm@example.com",
            "groups_id": [(6, 0, [internal.id, legacy_hr_manager_group.id])],
        })
        cls.admin_user = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "System Admin Without HR Groups",
            "login": "letter.admin.nogroup.test",
            "email": "letter.admin@example.com",
            "groups_id": [(6, 0, [internal.id, system_group.id])],
        })
        cls.employee_user = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "PIP Employee User",
            "login": "pip.employee.user.test",
            "email": "pip.employee@example.com",
            "groups_id": [(6, 0, [internal.id])],
        })
        cls.manager_employee = cls.env["hr.employee"].create({
            "name": "PIP Department Manager",
            "user_id": cls.department_manager.id,
        })
        cls.employee = cls.env["hr.employee"].create({
            "name": "PIP Employee",
            "user_id": cls.employee_user.id,
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
        self.employee.private_email = "employee.private@example.com"
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
            notice.with_user(self.hr_manager).action_hr_manager_approve()
        self.assertEqual(notice.state, "approved")
        self.assertEqual(notice.hr_manager_approved_by_id, self.hr_manager)

    def test_personal_email_required_before_final_approval(self):
        self.employee.private_email = False
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
        self.assertTrue(notice.with_user(self.hr_manager).can_send)
        self.assertTrue(notice.with_user(self.hr_supervisor).can_send)
        self.assertFalse(notice.with_user(self.managing_director).can_send)
        wizard_model = self.env["pr.employee.letter.send.wizard"].with_user(self.hr_supervisor)
        wizard_action = notice.with_user(self.hr_supervisor).action_open_send_wizard()
        self.assertEqual(wizard_action["res_model"], "pr.employee.letter.send.wizard")
        wizard_values = wizard_model.with_context(
            default_letter_id=notice.id,
            active_model=notice._name,
            active_id=notice.id,
        ).default_get(["letter_id", "recipient_mode", "email_to", "email_from", "subject", "body_html"])
        self.assertEqual(wizard_values["recipient_mode"], "private")
        self.assertEqual(wizard_values["email_to"], "employee.private@example.com")
        wizard = wizard_model.create({
            "letter_id": notice.id,
            "recipient_mode": wizard_values["recipient_mode"],
            "email_from": wizard_values.get("email_from") or "hr@example.com",
            "email_to": wizard_values["email_to"],
            "subject": wizard_values.get("subject") or notice.subject,
            "body_html": wizard_values.get("body_html") or notice.body_html,
        })
        mail_model = type(self.env["mail.mail"])
        with patch.object(
            model_class,
            "_generate_letter_pdf_attachment",
            autospec=True,
            return_value=self.attachment,
        ), patch.object(mail_model, "send", autospec=True, return_value=True):
            wizard.action_send()
        self.assertEqual(notice.state, "sent")
        self.assertEqual(notice.sent_by_id, self.hr_supervisor)
        self.assertEqual(notice.sent_email_to, "employee.private@example.com")
        # HR Supervisor can also re-send an already sent letter.
        self.assertTrue(notice.with_user(self.hr_supervisor).can_send)
        resend_wizard = wizard_model.create({
            "letter_id": notice.id,
            "recipient_mode": "private",
            "email_from": "hr@example.com",
            "email_to": "employee.private@example.com",
            "subject": notice.subject,
            "body_html": notice.body_html,
        })
        with patch.object(
            model_class,
            "_generate_letter_pdf_attachment",
            autospec=True,
            return_value=self.attachment,
        ), patch.object(mail_model, "send", autospec=True, return_value=True):
            resend_wizard.action_send()
        self.assertEqual(notice.state, "sent")

    def test_all_letter_types_follow_department_manager_and_hr_manager(self):
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
        self.assertEqual(letter.department_manager_approved_by_id, self.department_manager)
        self.assertEqual(letter.hr_manager_approved_by_id, self.hr_manager)

    def test_manager_with_hr_manager_group_does_not_auto_finalize_on_department_approve(self):
        hr_letter = self.env["pr.employee.document.letter"].create({
            "letter_type": "experience",
            "employee_id": self.hr_managed_employee.id,
            "subject": "Experience Letter",
            "body_html": "<p>Experience details.</p>",
        })
        model_class = type(hr_letter)
        with patch.object(
            model_class,
            "_generate_letter_pdf_attachment",
            autospec=True,
            return_value=self.attachment,
        ):
            hr_letter.action_submit()
            hr_letter.with_user(self.hr_manager).action_department_manager_approve()
            self.assertEqual(hr_letter.state, "hr_manager_approval")
            self.assertEqual(hr_letter.department_manager_approved_by_id, self.hr_manager)
            self.assertFalse(hr_letter.hr_manager_approved_by_id)
            hr_letter.with_user(self.hr_manager).action_hr_manager_approve()
        self.assertEqual(hr_letter.state, "approved")
        self.assertEqual(hr_letter.hr_manager_approved_by_id, self.hr_manager)

    def test_skip_level_hr_manager_approval(self):
        letter_hr_skip = self.env["pr.employee.document.letter"].create({
            "letter_type": "salary_certificate",
            "employee_id": self.employee.id,
            "subject": "Salary Certificate",
            "body_html": "<p>Salary details.</p>",
        })
        model_class = type(letter_hr_skip)
        with patch.object(
            model_class,
            "_generate_letter_pdf_attachment",
            autospec=True,
            return_value=self.attachment,
        ):
            letter_hr_skip.action_submit()
            self.assertEqual(letter_hr_skip.state, "department_manager_approval")
            letter_hr_skip.with_user(self.hr_manager).action_hr_manager_approve()
        self.assertEqual(letter_hr_skip.state, "approved")
        self.assertFalse(letter_hr_skip.department_manager_approved_by_id)
        self.assertEqual(letter_hr_skip.hr_manager_approved_by_id, self.hr_manager)

    def test_strict_permissions_block_unauthorized_roles_and_limit_hr_supervisor(self):
        letter = self.env["pr.employee.document.letter"].with_user(self.employee_user).create({
            "letter_type": "experience",
            "employee_id": self.employee.id,
            "subject": "Experience Letter",
            "body_html": "<p>Experience details.</p>",
        })
        self.assertFalse(hasattr(letter, "action_md_approve"))
        self.assertNotIn("md_approval", dict(letter._fields["state"].selection))
        self.assertNotIn("md_approved_by_id", letter._fields)
        self.assertNotIn("can_md_approve", letter._fields)

        model_class = type(letter)
        with patch.object(
            model_class,
            "_generate_letter_pdf_attachment",
            autospec=True,
            return_value=self.attachment,
        ):
            letter.with_user(self.employee_user).action_submit()

        for unauthorized_user in (self.admin_user, self.legacy_hr_manager, self.managing_director):
            self.assertFalse(
                self.env["pr.employee.document.letter"]
                .with_user(unauthorized_user)
                .search([("id", "=", letter.id)])
            )
            own_letter = self.env["pr.employee.document.letter"].with_user(unauthorized_user).create({
                "letter_type": "experience",
                "employee_id": self.employee.id,
                "subject": f"Own Letter - {unauthorized_user.login}",
                "body_html": "<p>Experience details.</p>",
            })
            with patch.object(
                model_class,
                "_generate_letter_pdf_attachment",
                autospec=True,
                return_value=self.attachment,
            ):
                own_letter.with_user(unauthorized_user).action_submit()

            own_as_user = own_letter.with_user(unauthorized_user)
            self.assertFalse(own_as_user.can_department_manager_approve)
            self.assertFalse(own_as_user.can_hr_manager_approve)
            self.assertFalse(own_as_user.can_reject)
            with self.assertRaises(AccessError):
                own_as_user.action_department_manager_approve()
            with self.assertRaises(AccessError):
                own_as_user.action_hr_manager_approve()
            with self.assertRaises(AccessError):
                own_as_user.action_reject()

            own_letter.sudo().write({"state": "approved"})
            self.assertFalse(own_as_user.can_send)
            with self.assertRaises(AccessError):
                own_as_user.action_open_send_wizard()

        # HR Supervisor sees all letters and can send approved ones, but cannot approve,
        # reject, reset to draft, cancel others' letters, or author PIP notices without hr_user/manager.
        self.assertEqual(
            self.env["pr.employee.document.letter"]
            .with_user(self.hr_supervisor)
            .search([("id", "=", letter.id)]),
            letter,
        )
        letter_as_sup = letter.with_user(self.hr_supervisor)
        self.assertFalse(letter_as_sup.can_department_manager_approve)
        self.assertFalse(letter_as_sup.can_hr_manager_approve)
        self.assertFalse(letter_as_sup.can_reject)
        self.assertFalse(letter_as_sup.can_reset_to_draft)
        self.assertFalse(letter_as_sup.can_cancel)
        with self.assertRaises(AccessError):
            letter_as_sup.action_department_manager_approve()
        with self.assertRaises(AccessError):
            letter_as_sup.action_hr_manager_approve()
        with self.assertRaises(AccessError):
            letter_as_sup.action_reject()
        with self.assertRaises(AccessError):
            letter_as_sup.action_reset_to_draft()
        with self.assertRaises(AccessError):
            letter_as_sup.action_cancel()
        with self.assertRaises(UserError):
            self.env["pr.employee.document.letter"].with_user(self.hr_supervisor).create({
                "letter_type": "performance_improvement",
                "employee_id": self.employee.id,
                "subject": "Supervisor PIP Test",
                "body_html": "<p>PIP details.</p>",
            })

        letter.sudo().write({"state": "approved"})
        self.assertTrue(letter_as_sup.can_send)
        with patch.object(
            model_class,
            "_generate_letter_pdf_attachment",
            autospec=True,
            return_value=self.attachment,
        ):
            sup_wizard_action = letter_as_sup.action_open_send_wizard()
        self.assertEqual(sup_wizard_action["res_model"], "pr.employee.letter.send.wizard")

    def test_reject_reset_to_draft_and_cancel_clear_approvals(self):
        letter = self.env["pr.employee.document.letter"].with_user(self.hr_user).create({
            "letter_type": "experience",
            "employee_id": self.employee.id,
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
            letter.with_user(self.hr_user).action_submit()
            # Dept. manager cannot reject after advancing to HR Manager; HR Manager can reject.
            letter.with_user(self.department_manager).action_department_manager_approve()
            self.assertEqual(letter.state, "hr_manager_approval")
            with self.assertRaises(AccessError):
                letter.with_user(self.department_manager).action_reject()
            letter.with_user(self.hr_manager).action_reject()

        self.assertEqual(letter.state, "rejected")
        # Both requester and target employee user (plus HR Manager) can reset to draft and clear approvals.
        letter.with_user(self.employee_user).action_reset_to_draft()
        self.assertEqual(letter.state, "draft")
        self.assertFalse(letter.department_manager_approved_by_id)
        self.assertFalse(letter.hr_manager_approved_by_id)

        with patch.object(
            model_class,
            "_generate_letter_pdf_attachment",
            autospec=True,
            return_value=self.attachment,
        ):
            letter.with_user(self.hr_user).action_submit()
            letter.with_user(self.department_manager).action_department_manager_approve()
        self.assertEqual(letter.state, "hr_manager_approval")
        letter.with_user(self.hr_manager).action_cancel()
        self.assertEqual(letter.state, "cancelled")
        self.assertFalse(letter.department_manager_approved_by_id)
        self.assertFalse(letter.hr_manager_approved_by_id)

    def test_letter_form_view_editability_and_buttons(self):
        form_view = self.env.ref("pr_employee_service_requests.view_pr_employee_document_letter_form")
        doc = etree.fromstring(form_view.arch)
        for field_name in (
            "appraisal_increment_amount",
            "appraisal_effective_date",
            "issue_date",
            "subject",
            "body_html",
        ):
            node = doc.xpath(f"//field[@name='{field_name}']")
            self.assertTrue(node, f"Field {field_name} must exist in form view.")
            self.assertEqual(
                node[0].get("readonly"),
                "state not in ('draft', 'hr_manager_approval')",
            )

        hr_btn = doc.xpath("//button[@name='action_hr_manager_approve']")
        self.assertEqual(hr_btn[0].get("groups"), "pr_hr.group_hr_manager")
        self.assertEqual(
            hr_btn[0].get("invisible"),
            "state not in ('department_manager_approval', 'hr_manager_approval')",
        )
        self.assertFalse(doc.xpath("//button[@name='action_md_approve']"))
        send_btn = doc.xpath("//button[@name='action_open_send_wizard']")
        self.assertEqual(send_btn[0].get("groups"), "pr_hr.group_hr_supervisor,pr_hr.group_hr_manager")

        action = self.env.ref("pr_employee_service_requests.action_pr_employee_document_letter_hr_approvals")
        self.assertEqual(action.domain, "[('is_current_user_document_letter_approver', '=', True)]")
