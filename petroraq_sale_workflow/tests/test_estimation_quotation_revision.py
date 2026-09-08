from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestEstimationQuotationRevision(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({
            "name": "Quotation Revision Test Customer",
        })

    def _create_quotation(self):
        return self.env["sale.order"].create({
            "partner_id": self.partner.id,
        })

    def test_direct_quotation_revision_is_blocked(self):
        quotation = self._create_quotation()
        with self.assertRaises(UserError):
            quotation.copy_revision_with_context()

    def test_estimation_revision_creates_new_record_and_uses_r_labels(self):
        self.env.company.keep_name_so = False
        quotation = self._create_quotation()
        original_name = quotation.name

        revision_1 = quotation.with_context(
            revision_from_estimation=True
        ).copy_revision_with_context()
        self.assertNotEqual(revision_1.id, quotation.id)
        self.assertEqual(revision_1.name, "%s-R1" % original_name)
        self.assertEqual(revision_1.revision_number, 1)
        self.assertFalse(quotation.active)
        self.assertEqual(quotation.state, "cancel")

        revision_2 = revision_1.with_context(
            revision_from_estimation=True
        ).copy_revision_with_context()
        self.assertNotEqual(revision_2.id, revision_1.id)
        self.assertEqual(revision_2.name, "%s-R2" % original_name)
        self.assertEqual(revision_2.revision_number, 2)

    def test_revision_uses_next_available_number_when_r1_already_exists(self):
        self.env.company.keep_name_so = False
        quotation = self._create_quotation()
        original_name = quotation.name
        self.env["sale.order"].with_context(
            preserve_quotation_revision_name=True
        ).create({
            "partner_id": self.partner.id,
            "company_id": quotation.company_id.id,
            "name": "%s-R1" % original_name,
            "unrevisioned_name": original_name,
            "revision_number": 1,
            "active": False,
            "state": "cancel",
        })

        revision = quotation.with_context(
            revision_from_estimation=True
        ).copy_revision_with_context()
        self.assertEqual(revision.name, "%s-R2" % original_name)
        self.assertEqual(revision.revision_number, 2)

    def test_revised_estimation_opens_an_empty_quotation_revision(self):
        quotation = self._create_quotation()
        quotation.write({
            "overhead_percent": 10.0,
            "risk_percent": 5.0,
            "profit_percent": 20.0,
            "order_line": [(0, 0, {
                "display_type": "line_note",
                "name": "Previous quotation content",
            })],
        })
        estimation = self.env["petroraq.estimation"].create({
            "partner_id": self.partner.id,
            "sale_order_id": quotation.id,
        })
        revised_estimation = estimation.with_context(
            allow_estimation_write=True
        ).copy_revision_with_context()

        revised_quotation = revised_estimation._ensure_sale_order()

        self.assertNotEqual(revised_quotation, quotation)
        self.assertEqual(revised_quotation.estimation_id, revised_estimation)
        self.assertFalse(revised_quotation.order_line)
        self.assertEqual(revised_quotation.overhead_percent, 0.0)
        self.assertEqual(revised_quotation.risk_percent, 0.0)
        self.assertEqual(revised_quotation.profit_percent, 0.0)
