from datetime import date

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

    def _prepare_confirmable_quotation(self, quotation=None):
        self.env.company.keep_name_so = False
        if not quotation:
            quotation = self._create_quotation()
        product = self.env["product.product"].create({
            "name": "Revision Test Product",
            "type": "consu",
            "list_price": 100.0,
        })
        attachment = self.env["ir.attachment"].create({
            "name": "customer-po.pdf",
            "type": "binary",
            "datas": "VGVzdCBDdXN0b21lciBQTw==",
            "res_model": "sale.order",
            "res_id": quotation.id,
        })
        quotation.write({
            "order_line": [(0, 0, {
                "product_id": product.id,
                "product_uom_qty": 1.0,
                "price_unit": 100.0,
            })],
            "approval_state": "approved",
            "confirmation_approval_state": "approved",
            "po_number": "PO-REV-001",
            "po_date": date.today(),
            "customer_po_attachment_ids": [(6, 0, attachment.ids)],
            "note": "<p>Test terms and conditions</p>",
        })
        return quotation

    def test_revised_estimation_creates_quotation_revision_when_so_already_confirmed(self):
        quotation = self._prepare_confirmable_quotation()
        quotation.action_confirm()
        self.assertEqual(quotation.state, "sale")
        original_so_name = quotation.name
        self.assertIn("-SO-", original_so_name)

        estimation = self.env["petroraq.estimation"].create({
            "partner_id": self.partner.id,
            "sale_order_id": quotation.id,
        })
        revised_estimation = estimation.with_context(
            allow_estimation_write=True
        ).copy_revision_with_context()

        # Creating quotation revision from estimation revision must succeed
        revised_quotation = revised_estimation._ensure_sale_order()

        self.assertNotEqual(revised_quotation, quotation)
        self.assertEqual(revised_quotation.state, "draft")
        self.assertIn("-SQ-", revised_quotation.name)
        # Original SO must remain active in the meantime
        self.assertTrue(quotation.active)
        self.assertEqual(quotation.state, "sale")

    def test_confirming_quotation_revision_creates_so_revision_of_existing_so(self):
        quotation = self._prepare_confirmable_quotation()
        quotation.action_confirm()
        original_so_name = quotation.name
        self.assertIn("-SO-", original_so_name)

        estimation = self.env["petroraq.estimation"].create({
            "partner_id": self.partner.id,
            "sale_order_id": quotation.id,
        })
        revised_estimation = estimation.with_context(
            allow_estimation_write=True
        ).copy_revision_with_context()

        revised_quotation = revised_estimation._ensure_sale_order()
        self._prepare_confirmable_quotation(revised_quotation)
        revised_quotation.action_confirm()

        self.assertEqual(revised_quotation.state, "sale")
        self.assertEqual(revised_quotation.name, "%s-R1" % original_so_name)
        self.assertEqual(revised_quotation.revision_number, 1)
        self.assertEqual(revised_quotation.unrevisioned_name, original_so_name)
        self.assertFalse(quotation.active)
        self.assertEqual(quotation.state, "cancel")
        self.assertEqual(quotation.current_revision_id, revised_quotation)

    def test_confirming_new_quotation_without_revision_creates_so_revision_if_so_exists(self):
        so_quotation = self._prepare_confirmable_quotation()
        so_quotation.action_confirm()
        original_so_name = so_quotation.name

        estimation = self.env["petroraq.estimation"].create({
            "partner_id": self.partner.id,
            "sale_order_id": so_quotation.id,
        })

        # Directly created quotation linked to this estimation (no revision chain on quotation itself)
        new_quotation = self._prepare_confirmable_quotation()
        new_quotation.write({"estimation_id": estimation.id})

        new_quotation.action_confirm()

        self.assertEqual(new_quotation.state, "sale")
        self.assertEqual(new_quotation.name, "%s-R1" % original_so_name)
        self.assertEqual(new_quotation.revision_number, 1)
        self.assertFalse(so_quotation.active)
        self.assertEqual(so_quotation.state, "cancel")

    def test_quotation_and_sale_order_revision_sequences_are_independent(self):
        quotation = self._prepare_confirmable_quotation()
        original_sq_name = quotation.name
        self.assertIn("-SQ-", original_sq_name)

        quotation.action_confirm()
        original_so_name = quotation.name
        self.assertIn("-SO-", original_so_name)

        estimation = self.env["petroraq.estimation"].create({
            "partner_id": self.partner.id,
            "sale_order_id": quotation.id,
        })

        # Revise estimation -> Quotation Revision 1
        rev_est_1 = estimation.with_context(
            allow_estimation_write=True
        ).copy_revision_with_context()
        rev_quo_1 = rev_est_1._ensure_sale_order()
        self.assertEqual(rev_quo_1.name, "%s-R1" % original_sq_name)

        # Confirm Quotation Revision 1 -> Must become Sale Order Revision 1 (not R2!)
        self._prepare_confirmable_quotation(rev_quo_1)
        rev_quo_1.action_confirm()
        self.assertEqual(rev_quo_1.name, "%s-R1" % original_so_name)
        self.assertEqual(rev_quo_1.revision_number, 1)
        self.assertFalse(quotation.active)
        self.assertEqual(quotation.state, "cancel")

        # Revise estimation again -> Quotation Revision 2
        rev_est_2 = rev_est_1.with_context(
            allow_estimation_write=True
        ).copy_revision_with_context()
        rev_quo_2 = rev_est_2._ensure_sale_order()
        self.assertEqual(rev_quo_2.name, "%s-R2" % original_sq_name)

        # Confirm Quotation Revision 2 -> Must become Sale Order Revision 2
        self._prepare_confirmable_quotation(rev_quo_2)
        rev_quo_2.action_confirm()
        self.assertEqual(rev_quo_2.name, "%s-R2" % original_so_name)
        self.assertEqual(rev_quo_2.revision_number, 2)
        self.assertFalse(rev_quo_1.active)
        self.assertEqual(rev_quo_1.state, "cancel")

    def test_work_order_revision_sequence_in_sale_order_chain(self):
        quotation = self._prepare_confirmable_quotation()
        quotation.action_confirm()
        original_so_name = quotation.name
        self.assertIn("-SO-", original_so_name)

        estimation = self.env["petroraq.estimation"].create({
            "partner_id": self.partner.id,
            "sale_order_id": quotation.id,
        })

        # 1. Create first Work Order for the original Sale Order
        wo_original = self.env["pr.work.order"].create({
            "sale_order_id": quotation.id,
            "partner_id": self.partner.id,
        })
        quotation.write({"work_order_id": wo_original.id})
        estimation.with_context(allow_estimation_write=True).write({"work_order_id": wo_original.id})
        original_wo_name = wo_original.name
        self.assertNotIn("-R", original_wo_name)
        self.assertEqual(wo_original.revision_number, 0)
        self.assertEqual(wo_original.unrevisioned_name, original_wo_name)

        # 2. Revise estimation -> Quotation Revision 1 -> Confirm to Sale Order Revision 1
        rev_est_1 = estimation.with_context(allow_estimation_write=True).copy_revision_with_context()
        rev_quo_1 = rev_est_1._ensure_sale_order()
        self._prepare_confirmable_quotation(rev_quo_1)
        rev_quo_1.action_confirm()
        self.assertEqual(rev_quo_1.name, "%s-R1" % original_so_name)
        # Verify the new SO revision starts with work_order_id = False
        self.assertFalse(rev_quo_1.work_order_id)

        # 3. Create Work Order for revised Sale Order -> Must be Work Order Revision 1
        wo_rev_1 = self.env["pr.work.order"].create({
            "sale_order_id": rev_quo_1.id,
            "partner_id": self.partner.id,
        })
        rev_quo_1.write({"work_order_id": wo_rev_1.id})
        rev_est_1.with_context(allow_estimation_write=True).write({"work_order_id": wo_rev_1.id})

        self.assertEqual(wo_rev_1.name, "%s-R1" % original_wo_name)
        self.assertEqual(wo_rev_1.revision_number, 1)
        self.assertEqual(wo_rev_1.unrevisioned_name, original_wo_name)

        # 4. Revise estimation again -> Quotation Revision 2 -> Confirm to Sale Order Revision 2
        rev_est_2 = rev_est_1.with_context(allow_estimation_write=True).copy_revision_with_context()
        rev_quo_2 = rev_est_2._ensure_sale_order()
        self._prepare_confirmable_quotation(rev_quo_2)
        rev_quo_2.action_confirm()
        self.assertEqual(rev_quo_2.name, "%s-R2" % original_so_name)

        # 5. Create Work Order for second revision -> Must be Work Order Revision 2
        wo_rev_2 = self.env["pr.work.order"].create({
            "sale_order_id": rev_quo_2.id,
            "partner_id": self.partner.id,
        })
        rev_quo_2.write({"work_order_id": wo_rev_2.id})
        rev_est_2.with_context(allow_estimation_write=True).write({"work_order_id": wo_rev_2.id})

        self.assertEqual(wo_rev_2.name, "%s-R2" % original_wo_name)
        self.assertEqual(wo_rev_2.revision_number, 2)
        self.assertEqual(wo_rev_2.unrevisioned_name, original_wo_name)

        # 6. Further Work Order creation in the same chain continues incrementing
        wo_rev_3 = self.env["pr.work.order"].create({
            "sale_order_id": rev_quo_2.id,
            "partner_id": self.partner.id,
        })
        self.assertEqual(wo_rev_3.name, "%s-R3" % original_wo_name)
        self.assertEqual(wo_rev_3.revision_number, 3)
        self.assertEqual(wo_rev_3.unrevisioned_name, original_wo_name)

    def test_work_order_new_revision_action(self):
        quotation = self._prepare_confirmable_quotation()
        quotation.action_confirm()

        # 1. Create original Work Order
        wo_0 = self.env["pr.work.order"].create({
            "sale_order_id": quotation.id,
            "partner_id": self.partner.id,
        })
        base_name = wo_0.name
        self.assertNotIn("-R", base_name)
        self.assertEqual(wo_0.revision_number, 0)
        self.assertEqual(wo_0.state, "draft")

        # 2. Click "New Revision" on wo_0 -> creates R1
        action_1 = wo_0.action_new_revision()
        self.assertEqual(action_1.get("res_model"), "pr.work.order")
        wo_1 = self.env["pr.work.order"].browse(action_1["res_id"])

        self.assertEqual(wo_1.name, "%s-R1" % base_name)
        self.assertEqual(wo_1.revision_number, 1)
        self.assertEqual(wo_1.unrevisioned_name, base_name)
        self.assertEqual(wo_1.previous_revision_id.id, wo_0.id)
        self.assertEqual(wo_1.sale_order_id.id, quotation.id)
        self.assertEqual(wo_1.state, "draft")
        # Ensure original wo_0 is unchanged
        self.assertEqual(wo_0.name, base_name)
        self.assertEqual(wo_0.state, "draft")

        # 3. Click "New Revision" on wo_1 -> creates R2
        action_2 = wo_1.action_new_revision()
        wo_2 = self.env["pr.work.order"].browse(action_2["res_id"])

        self.assertEqual(wo_2.name, "%s-R2" % base_name)
        self.assertEqual(wo_2.revision_number, 2)
        self.assertEqual(wo_2.unrevisioned_name, base_name)
        self.assertEqual(wo_2.previous_revision_id.id, wo_1.id)
        self.assertEqual(wo_2.sale_order_id.id, quotation.id)
        # Ensure wo_1 is unchanged
        self.assertEqual(wo_1.name, "%s-R1" % base_name)

        # 4. Click "New Revision" on wo_2 -> creates R3
        action_3 = wo_2.action_new_revision()
        wo_3 = self.env["pr.work.order"].browse(action_3["res_id"])

        self.assertEqual(wo_3.name, "%s-R3" % base_name)
        self.assertEqual(wo_3.revision_number, 3)
        self.assertEqual(wo_3.unrevisioned_name, base_name)
        self.assertEqual(wo_3.previous_revision_id.id, wo_2.id)

        # 5. Check revision count and action_view_revisions
        self.assertEqual(wo_0.revision_count, 4)
        self.assertEqual(wo_3.revision_count, 4)

        view_action = wo_3.action_view_revisions()
        self.assertEqual(view_action["res_model"], "pr.work.order")
        all_revisions = self.env["pr.work.order"].search(view_action["domain"])
        self.assertEqual(len(all_revisions), 4)
        self.assertSetEqual(set(all_revisions.ids), {wo_0.id, wo_1.id, wo_2.id, wo_3.id})




