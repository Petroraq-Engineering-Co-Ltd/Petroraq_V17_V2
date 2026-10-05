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

    def test_estimation_own_revision_uses_r_labels(self):
        estimation = self.env["petroraq.estimation"].create({
            "partner_id": self.partner.id,
        })
        original_name = estimation.name

        revision_1 = estimation.with_context(
            allow_estimation_write=True
        ).copy_revision_with_context()
        self.assertNotEqual(revision_1.id, estimation.id)
        self.assertEqual(revision_1.name, "%s-R1" % original_name)
        self.assertEqual(revision_1.revision_number, 1)
        self.assertFalse(estimation.active)

        revision_2 = revision_1.with_context(
            allow_estimation_write=True
        ).copy_revision_with_context()
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

    def test_direct_confirm_blocked_by_posted_invoice_bypassing_estimation_flow(self):
        """The guard in _prepare_confirmed_so_data() must independently block
        a quotation confirmed straight into the same estimation/SO chain,
        without ever going through _ensure_sale_order()."""
        so_quotation = self._prepare_confirmable_quotation()
        so_quotation.action_confirm()
        invoice = so_quotation._create_invoices()
        invoice.action_post()

        estimation = self.env["petroraq.estimation"].create({
            "partner_id": self.partner.id,
            "sale_order_id": so_quotation.id,
        })
        new_quotation = self._prepare_confirmable_quotation()
        new_quotation.write({"estimation_id": estimation.id})

        with self.assertRaises(UserError):
            new_quotation.action_confirm()

    def _revise_via_estimation(self, quotation):
        estimation = self.env["petroraq.estimation"].create({
            "partner_id": self.partner.id,
            "sale_order_id": quotation.id,
        })
        revised_estimation = estimation.with_context(
            allow_estimation_write=True
        ).copy_revision_with_context()
        revised_quotation = revised_estimation._ensure_sale_order()
        self._prepare_confirmable_quotation(revised_quotation)
        return revised_quotation

    def test_revision_blocked_by_posted_invoice(self):
        quotation = self._prepare_confirmable_quotation()
        quotation.action_confirm()
        invoice = quotation._create_invoices()
        invoice.action_post()

        # Blocked immediately when "Revise Quotation" is clicked on the
        # Estimation - before any draft quotation revision is even created.
        with self.assertRaises(UserError):
            self._revise_via_estimation(quotation)

    def test_revision_allowed_with_draft_invoice(self):
        quotation = self._prepare_confirmable_quotation()
        quotation.action_confirm()
        invoice = quotation._create_invoices()
        self.assertEqual(invoice.state, "draft")

        revised_quotation = self._revise_via_estimation(quotation)
        revised_quotation.action_confirm()
        self.assertEqual(revised_quotation.state, "sale")
        self.assertFalse(quotation.active)
        self.assertEqual(quotation.state, "cancel")

    def test_revision_allowed_with_cancelled_invoice(self):
        quotation = self._prepare_confirmable_quotation()
        quotation.action_confirm()
        invoice = quotation._create_invoices()
        invoice.button_cancel()
        self.assertEqual(invoice.state, "cancel")

        revised_quotation = self._revise_via_estimation(quotation)
        revised_quotation.action_confirm()
        self.assertEqual(revised_quotation.state, "sale")

    def test_revision_blocked_by_active_delivery(self):
        quotation = self._prepare_confirmable_quotation()
        quotation.action_confirm()
        picking_type = self.env["stock.picking.type"].search([("code", "=", "outgoing")], limit=1)
        picking = self.env["stock.picking"].create({
            "sale_id": quotation.id,
            "partner_id": self.partner.id,
            "picking_type_id": picking_type.id,
            "location_id": picking_type.default_location_src_id.id,
            "location_dest_id": picking_type.default_location_dest_id.id,
        })
        picking.write({"state": "confirmed"})

        with self.assertRaises(UserError):
            self._revise_via_estimation(quotation)

    def test_revision_allowed_with_draft_delivery(self):
        quotation = self._prepare_confirmable_quotation()
        quotation.action_confirm()
        picking_type = self.env["stock.picking.type"].search([("code", "=", "outgoing")], limit=1)
        self.env["stock.picking"].create({
            "sale_id": quotation.id,
            "partner_id": self.partner.id,
            "picking_type_id": picking_type.id,
            "location_id": picking_type.default_location_src_id.id,
            "location_dest_id": picking_type.default_location_dest_id.id,
        })

        revised_quotation = self._revise_via_estimation(quotation)
        revised_quotation.action_confirm()
        self.assertEqual(revised_quotation.state, "sale")

    def test_estimation_revision_blocked_by_posted_invoice_via_create_revision_button(self):
        """The "New Revision" button on the Estimation form (create_revision)
        must also be blocked, not just the lower-level copy_revision_with_context."""
        quotation = self._prepare_confirmable_quotation()
        quotation.action_confirm()
        invoice = quotation._create_invoices()
        invoice.action_post()

        estimation = self.env["petroraq.estimation"].create({
            "partner_id": self.partner.id,
            "sale_order_id": quotation.id,
        })
        with self.assertRaises(UserError):
            estimation.create_revision()

    def test_estimation_revision_allowed_with_draft_invoice(self):
        quotation = self._prepare_confirmable_quotation()
        quotation.action_confirm()
        quotation._create_invoices()

        estimation = self.env["petroraq.estimation"].create({
            "partner_id": self.partner.id,
            "sale_order_id": quotation.id,
        })
        revision = estimation.with_context(
            allow_estimation_write=True
        ).copy_revision_with_context()
        self.assertTrue(revision)
        self.assertFalse(estimation.active)

    def test_action_revise_so_creates_estimation_revision_only(self):
        quotation = self._prepare_confirmable_quotation()
        quotation.action_confirm()
        estimation = self.env["petroraq.estimation"].create({
            "partner_id": self.partner.id,
            "sale_order_id": quotation.id,
        })
        quotation.write({"estimation_id": estimation.id})
        original_est_name = estimation.name

        result = quotation.action_revise_so()

        self.assertEqual(result["res_model"], "petroraq.estimation")
        new_estimation = self.env["petroraq.estimation"].browse(result["res_id"])
        self.assertEqual(new_estimation.name, "%s-R1" % original_est_name)
        self.assertFalse(estimation.active)

        # The Sales Order/Quotation itself must be completely untouched.
        self.assertTrue(quotation.active)
        self.assertEqual(quotation.state, "sale")
        self.assertFalse(new_estimation.sale_order_id)

    def test_action_revise_so_requires_sale_state(self):
        quotation = self._prepare_confirmable_quotation()
        estimation = self.env["petroraq.estimation"].create({
            "partner_id": self.partner.id,
            "sale_order_id": quotation.id,
        })
        quotation.write({"estimation_id": estimation.id})
        with self.assertRaises(UserError):
            quotation.action_revise_so()

    def test_action_revise_so_requires_estimation(self):
        quotation = self._prepare_confirmable_quotation()
        quotation.action_confirm()
        with self.assertRaises(UserError):
            quotation.action_revise_so()

    def test_action_revise_so_blocked_by_posted_invoice(self):
        quotation = self._prepare_confirmable_quotation()
        quotation.action_confirm()
        estimation = self.env["petroraq.estimation"].create({
            "partner_id": self.partner.id,
            "sale_order_id": quotation.id,
        })
        quotation.write({"estimation_id": estimation.id})
        invoice = quotation._create_invoices()
        invoice.action_post()

        with self.assertRaises(UserError):
            quotation.action_revise_so()

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

    def test_revising_sale_order_cancels_draft_work_orders_and_allows_new_wo_from_revised_estimation(self):
        quotation = self._prepare_confirmable_quotation()
        quotation.action_confirm()
        self.assertEqual(quotation.state, "sale")

        estimation = self.env["petroraq.estimation"].create({
            "partner_id": self.partner.id,
            "sale_order_id": quotation.id,
        })
        self._add_estimation_line(estimation, "material", 2.0, 100.0)

        # 1. Create Work Order from estimation
        action_wo = estimation.action_create_work_order()
        wo_1 = self.env["pr.work.order"].browse(action_wo["res_id"])
        self.assertEqual(wo_1.state, "draft")
        self.assertEqual(quotation.work_order_id.id, wo_1.id)
        self.assertEqual(estimation.work_order_id.id, wo_1.id)

        # 2. Revise the Sale Order
        action_rev = quotation.action_revise_so()
        rev_est = self.env["petroraq.estimation"].browse(action_rev["res_id"])
        self.assertNotEqual(rev_est.id, estimation.id)

        # 3. Verify original draft Work Order was moved to 'cancel'
        self.assertEqual(wo_1.state, "cancel")

        # 4. Generate and confirm revised quotation
        rev_quo = rev_est._ensure_sale_order()
        self.assertFalse(rev_quo.work_order_id)
        self._prepare_confirmable_quotation(rev_quo)
        rev_quo.action_confirm()
        self.assertEqual(rev_quo.state, "sale")

        # 5. Create new Work Order from the revised estimation
        action_wo_2 = rev_est.action_create_work_order()
        wo_2 = self.env["pr.work.order"].browse(action_wo_2["res_id"])
        self.assertNotEqual(wo_2.id, wo_1.id)
        self.assertEqual(wo_2.state, "draft")
        self.assertEqual(rev_quo.work_order_id.id, wo_2.id)
        self.assertEqual(rev_est.work_order_id.id, wo_2.id)

    def test_approving_work_order_revision_cancels_other_work_orders(self):
        quotation = self._prepare_confirmable_quotation()
        quotation.action_confirm()
        self.assertEqual(quotation.state, "sale")

        estimation = self.env["petroraq.estimation"].create({
            "partner_id": self.partner.id,
            "sale_order_id": quotation.id,
        })
        self._add_estimation_line(estimation, "material", 5.0, 200.0)

        # 1. Create first Work Order from estimation and approve it
        action_wo = estimation.action_create_work_order()
        wo_0 = self.env["pr.work.order"].browse(action_wo["res_id"])
        self.assertEqual(wo_0.state, "draft")
        wo_0.write({"state": "approved"})
        self.assertEqual(wo_0.state, "approved")
        self.assertEqual(quotation.work_order_id.id, wo_0.id)

        # 2. Create revision wo_1 from wo_0
        action_rev1 = wo_0.action_new_revision()
        wo_1 = self.env["pr.work.order"].browse(action_rev1["res_id"])
        self.assertEqual(wo_1.state, "draft")
        self.assertEqual(wo_0.state, "approved")

        # 3. Approve wo_1 via write({"state": "approved"})
        wo_1.write({"state": "approved"})
        self.assertEqual(wo_1.state, "approved")
        self.assertEqual(wo_0.state, "cancel")
        self.assertEqual(quotation.work_order_id.id, wo_1.id)

        # 4. Create another revision wo_2 from wo_1
        action_rev2 = wo_1.action_new_revision()
        wo_2 = self.env["pr.work.order"].browse(action_rev2["res_id"])
        self.assertEqual(wo_2.state, "draft")
        self.assertEqual(wo_1.state, "approved")

        # 5. Approve wo_2 via action_final_approve
        wo_2.state = "final_approval"
        wo_2.action_final_approve()
        self.assertEqual(wo_2.state, "approved")
        self.assertEqual(wo_1.state, "cancel")
        self.assertEqual(wo_0.state, "cancel")
        self.assertEqual(quotation.work_order_id.id, wo_2.id)

    def test_revise_so_button_groups(self):
        view = self.env.ref("petroraq_sale_workflow.view_order_form_inherit_petroraq_workflow")
        arch = view.arch
        self.assertIn('name="action_revise_so"', arch)
        self.assertIn('groups="petroraq_sale_workflow.group_sale_approval_manager,pr_work_order.custom_group_work_order_user"', arch)






