from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPrCycle(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pr = cls.env["purchase.requisition"].create({"name": "PR-CYCLE-TEST"})
        cls.vendors = cls.env["res.partner"].create([
            {"name": "Cycle Supplier A"}, {"name": "Cycle Supplier B"},
        ])

    def _order(self, name, state="draft", **values):
        return self.env["purchase.order"].with_context(tracking_disable=True).create({
            "name": name, "partner_id": self.vendors[0].id,
            "requisition_id": self.pr.id, "state": state, **values,
        })

    def test_sent_count_includes_cancelled_history_once_and_excludes_drafts(self):
        self._order("RFQ-CYCLE-SENT", "sent", vendor_ids=[Command.set(self.vendors.ids)])
        cancelled = self._order("RFQ-CYCLE-CANCELLED", "cancel")
        self._order("RFQ-CYCLE-DRAFT")
        self._order("RFQ-CYCLE-UNSENT-CANCELLED", "cancel")
        # Repeated sends are still one RFQ document in the cycle.
        for _ in range(2):
            self.env["mail.message"].create({
                "model": "purchase.order", "res_id": cancelled.id,
                "subtype_id": self.env.ref("purchase.mt_rfq_sent").id,
                "message_type": "notification", "body": "RFQ sent",
            })
        self.pr._compute_linked_purchase_statuses()
        self.assertEqual(self.pr.rfq_sent_count, 2)
        self.assertEqual(self.pr.rfq_sent_to, "Cycle Supplier A, Cycle Supplier B")

    def test_po_supplier_shown_at_creation_and_legacy_pr_link_supported(self):
        self._order("PO-CYCLE-CREATED")
        self._order("PO-CYCLE-LEGACY", requisition_id=False, pr_name=self.pr.name,
                    partner_id=self.vendors[1].id)
        self.pr._compute_linked_purchase_statuses()
        self.assertEqual(self.pr.po_issued_to, "Cycle Supplier A, Cycle Supplier B")
        self.assertEqual(self.pr.linked_po_status, "draft")
        self.assertEqual(self.pr.rfq_sent_count, 0)

    def test_rejected_po_supplier_excluded_and_unregistered_rfq_supported(self):
        self.pr.pr_type = "budgetary"
        self._order("RFQ-CYCLE-BUDGET", "sent", partner_id=False,
                    rfq_vendor_name="Unregistered Supplier", rfq_vendor_email="vendor@example.com")
        self._order("PO-CYCLE-REJECTED", "rejected")
        self.pr._compute_linked_purchase_statuses()
        self.assertEqual(self.pr.rfq_sent_to, "Unregistered Supplier")
        self.assertEqual(self.pr.rfq_sent_count, 1)
        self.assertFalse(self.pr.po_issued_to)
