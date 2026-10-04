# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase


class TestResPartnerDefaults(TransactionCase):

    def test_customer_and_vendor_creation_default_to_company(self):
        Partner = self.env["res.partner"]

        for search_mode in ("customer", "supplier"):
            defaults = Partner.with_context(
                res_partner_search_mode=search_mode,
            ).default_get(["is_company", "company_type"])

            self.assertTrue(defaults["is_company"])
            self.assertEqual(defaults["company_type"], "company")

    def test_explicit_individual_default_is_respected(self):
        defaults = self.env["res.partner"].with_context(
            res_partner_search_mode="customer",
            default_is_company=False,
            default_company_type="person",
        ).default_get(["is_company", "company_type"])

        self.assertFalse(defaults.get("is_company", False))
        self.assertEqual(defaults.get("company_type", "person"), "person")

    def test_child_contact_keeps_individual_default(self):
        defaults = self.env["res.partner"].with_context(
            res_partner_search_mode="supplier",
            default_parent_id=self.env.company.partner_id.id,
        ).default_get(["is_company", "company_type", "parent_id"])

        self.assertFalse(defaults.get("is_company", False))
        self.assertEqual(defaults.get("company_type", "person"), "person")
