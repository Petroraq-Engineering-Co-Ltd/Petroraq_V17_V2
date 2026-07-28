from odoo.tests.common import TransactionCase


class TestZatcaCustomerPrecheck(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.saudi_arabia = cls.env.ref("base.sa")
        cls.company = cls.env.company
        cls.company.country_id = cls.saudi_arabia
        cls.sales_journal = cls.env["account.journal"].search([
            ("company_id", "=", cls.company.id),
            ("type", "=", "sale"),
        ], limit=1)

    def _create_invoice(self, partner):
        return self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": partner.id,
            "journal_id": self.sales_journal.id,
        })

    def test_standard_invoice_reports_missing_customer_master_data(self):
        customer = self.env["res.partner"].create({
            "name": "Incomplete ZATCA Customer",
            "company_type": "company",
        })

        issues = self._create_invoice(customer)._pr_get_zatca_customer_issues()

        self.assertTrue(any("City" in issue for issue in issues))
        self.assertTrue(any("Country" in issue for issue in issues))

    def test_complete_saudi_standard_customer_passes_precheck(self):
        customer = self.env["res.partner"].create({
            "name": "Complete ZATCA Customer",
            "company_type": "company",
            "street": "King Fahd Road",
            "street2": "Al Olaya",
            "city": "Riyadh",
            "zip": "12345",
            "country_id": self.saudi_arabia.id,
            "l10n_sa_edi_building_number": "1234",
            "l10n_sa_edi_plot_identification": "5678",
            "vat": "311111111111113",
        })

        issues = self._create_invoice(customer)._pr_get_zatca_customer_issues()

        self.assertFalse(issues)

    def test_simplified_customer_does_not_require_b2b_address(self):
        customer = self.env["res.partner"].create({
            "name": "Walk-in Customer",
            "company_type": "person",
        })

        issues = self._create_invoice(customer)._pr_get_zatca_customer_issues()

        self.assertFalse(issues)
