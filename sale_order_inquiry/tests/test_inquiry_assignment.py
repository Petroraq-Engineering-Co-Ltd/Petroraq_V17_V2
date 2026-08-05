from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestInquiryAssignment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        internal = cls.env.ref("base.group_user")
        sales_user_group = cls.env.ref("sales_team.group_sale_salesman")
        sales_manager_group = cls.env.ref("sales_team.group_sale_manager")

        cls.sales_manager = cls.env["res.users"].create({
            "name": "Inquiry Sales Manager",
            "login": "inquiry.sales.manager",
            "company_id": cls.env.company.id,
            "company_ids": [Command.set(cls.env.company.ids)],
            "groups_id": [Command.set((internal | sales_manager_group).ids)],
        })
        cls.salesperson = cls.env["res.users"].create({
            "name": "Assigned Inquiry Salesperson",
            "login": "assigned.inquiry.salesperson",
            "company_id": cls.env.company.id,
            "company_ids": [Command.set(cls.env.company.ids)],
            "groups_id": [Command.set((internal | sales_user_group).ids)],
        })
        cls.other_salesperson = cls.env["res.users"].create({
            "name": "Other Inquiry Salesperson",
            "login": "other.inquiry.salesperson",
            "company_id": cls.env.company.id,
            "company_ids": [Command.set(cls.env.company.ids)],
            "groups_id": [Command.set((internal | sales_user_group).ids)],
        })

        cls.customer = cls.env["res.partner"].create({
            "name": "Inquiry Assignment Customer",
            "company_type": "company",
        })
        cls.contact = cls.env["res.partner"].create({
            "name": "Inquiry Contact",
            "parent_id": cls.customer.id,
            "type": "contact",
            "email": "contact@example.com",
            "phone": "+966500000001",
        })
        cls.attachment = cls.env["ir.attachment"].create({
            "name": "inquiry-requirement.txt",
            "datas": "VGVzdCByZXF1aXJlbWVudA==",
            "res_model": "order.inq",
            "res_id": 0,
        })

    def _create_submitted_inquiry(self):
        return self.env["order.inq"].create({
            "description": "Assignment workflow inquiry",
            "user_id": self.sales_manager.id,
            "partner_id": self.customer.id,
            "contact_partner_id": self.contact.id,
            "contact_person_email": self.contact.email,
            "contact_person_phone": self.contact.phone,
            "deadline_submission": fields.Date.today() + timedelta(days=10),
            "required_attachment_ids": [Command.set(self.attachment.ids)],
            "state": "confirm",
        })

    def test_manager_assigns_and_assigned_salesperson_accepts(self):
        inquiry = self._create_submitted_inquiry()
        inquiry.with_user(self.sales_manager).write({
            "assigned_salesperson_id": self.salesperson.id,
        })

        inquiry.with_user(self.sales_manager).action_assign_salesperson()
        self.assertEqual(inquiry.state, "assigned")
        self.assertEqual(inquiry.assigned_by_id, self.sales_manager)
        self.assertTrue(inquiry.assigned_at)

        inquiry.with_user(self.salesperson).action_accept()
        self.assertEqual(inquiry.state, "accept")

    def test_manager_can_choose_salesperson_before_submit(self):
        inquiry = self.env["order.inq"].with_user(self.sales_manager).create({
            "description": "Manager delegates before submission",
            "user_id": self.sales_manager.id,
            "partner_id": self.customer.id,
            "contact_partner_id": self.contact.id,
            "contact_person_email": self.contact.email,
            "contact_person_phone": self.contact.phone,
            "deadline_submission": fields.Date.today() + timedelta(days=10),
            "required_attachment_ids": [Command.set(self.attachment.ids)],
        })

        inquiry.with_user(self.sales_manager).write({
            "assigned_salesperson_id": self.salesperson.id,
        })
        inquiry.with_user(self.sales_manager).button_confirm()

        self.assertEqual(inquiry.assigned_salesperson_id, self.salesperson)
        self.assertEqual(inquiry.state, "confirm")
        inquiry.with_user(self.sales_manager).action_assign_salesperson()
        self.assertEqual(inquiry.state, "assigned")

    def test_creator_is_default_assigned_salesperson(self):
        inquiry = self.env["order.inq"].with_user(self.salesperson).create({
            "description": "Creator defaults as salesperson",
            "user_id": self.salesperson.id,
            "partner_id": self.customer.id,
            "contact_partner_id": self.contact.id,
            "contact_person_email": self.contact.email,
            "contact_person_phone": self.contact.phone,
            "deadline_submission": fields.Date.today() + timedelta(days=10),
            "required_attachment_ids": [Command.set(self.attachment.ids)],
        })

        self.assertEqual(inquiry.assigned_salesperson_id, self.salesperson)

    def test_creator_self_assignment_skips_manager_assignment(self):
        inquiry = self.env["order.inq"].with_user(self.salesperson).create({
            "description": "Creator accepts own inquiry",
            "user_id": self.salesperson.id,
            "assigned_salesperson_id": self.salesperson.id,
            "partner_id": self.customer.id,
            "contact_partner_id": self.contact.id,
            "contact_person_email": self.contact.email,
            "contact_person_phone": self.contact.phone,
            "deadline_submission": fields.Date.today() + timedelta(days=10),
            "required_attachment_ids": [Command.set(self.attachment.ids)],
        })

        inquiry.with_user(self.salesperson).button_confirm()

        self.assertEqual(inquiry.state, "assigned")
        self.assertEqual(inquiry.assigned_salesperson_id, self.salesperson)
        self.assertEqual(inquiry.assigned_by_id, self.salesperson)
        self.assertTrue(inquiry.assigned_at)
        inquiry.with_user(self.salesperson).action_accept()
        self.assertEqual(inquiry.state, "accept")

    def test_other_salesperson_still_requires_manager_assignment(self):
        inquiry = self.env["order.inq"].with_user(self.salesperson).create({
            "description": "Manager assignment remains required",
            "user_id": self.salesperson.id,
            "partner_id": self.customer.id,
            "contact_partner_id": self.contact.id,
            "contact_person_email": self.contact.email,
            "contact_person_phone": self.contact.phone,
            "deadline_submission": fields.Date.today() + timedelta(days=10),
            "required_attachment_ids": [Command.set(self.attachment.ids)],
        })
        inquiry.sudo().write({"assigned_salesperson_id": self.other_salesperson.id})

        inquiry.with_user(self.salesperson).button_confirm()

        self.assertEqual(inquiry.state, "confirm")
        self.assertFalse(inquiry.assigned_by_id)

    def test_unassigned_salesperson_cannot_accept(self):
        inquiry = self._create_submitted_inquiry()
        inquiry.with_user(self.sales_manager).write({
            "assigned_salesperson_id": self.salesperson.id,
        })
        inquiry.with_user(self.sales_manager).action_assign_salesperson()

        with self.assertRaises(UserError):
            inquiry.with_user(self.other_salesperson).action_accept()
