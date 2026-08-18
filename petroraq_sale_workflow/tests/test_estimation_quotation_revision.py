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

    def test_estimation_revision_context_uses_r_labels(self):
        quotation = self._create_quotation()
        original_name = quotation.name

        revision_1 = quotation.with_context(
            revision_from_estimation=True
        ).copy_revision_with_context()
        self.assertEqual(revision_1.name, "%s-R1" % original_name)
        self.assertEqual(revision_1.revision_number, 1)
        self.assertFalse(quotation.active)
        self.assertEqual(quotation.state, "cancel")

        revision_2 = revision_1.with_context(
            revision_from_estimation=True
        ).copy_revision_with_context()
        self.assertEqual(revision_2.name, "%s-R2" % original_name)
        self.assertEqual(revision_2.revision_number, 2)

