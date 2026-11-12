from odoo import fields
from odoo.tests.common import TransactionCase


class TestPrPoPartialWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env["res.partner"].create({
            "name": "Partial PR Workflow Vendor",
            "supplier_rank": 1,
        })
        cls.uom = cls.env.ref("uom.product_uom_unit")
        cls.plan = cls.env["account.analytic.plan"].create({
            "name": "Partial PR Workflow Plan",
        })
        cls.cost_center = cls.env["account.analytic.account"].create({
            "name": "Partial PR Workflow Cost Center",
            "plan_id": cls.plan.id,
        })
        cls.products = cls.env["product.product"].create([
            {
                "name": "Partial PR Product A",
                "detailed_type": "consu",
                "uom_id": cls.uom.id,
                "uom_po_id": cls.uom.id,
                "standard_price": 100.0,
            },
            {
                "name": "Partial PR Product B",
                "detailed_type": "consu",
                "uom_id": cls.uom.id,
                "uom_po_id": cls.uom.id,
                "standard_price": 200.0,
            },
            {
                "name": "Partial PR Product C",
                "detailed_type": "consu",
                "uom_id": cls.uom.id,
                "uom_po_id": cls.uom.id,
                "standard_price": 300.0,
            },
        ])
        today = fields.Date.context_today(cls.env["purchase.requisition"])
        cls.budget = cls.env["crossovered.budget"].create({
            "name": "Partial PR Workflow Budget",
            "date_from": today.replace(month=1, day=1),
            "date_to": today.replace(month=12, day=31),
            "state": "validate",
            "user_id": cls.env.user.id,
            "expense_type": "opex",
            "scope": "department",
        })
        cls.env["crossovered.budget.lines"].create({
            "crossovered_budget_id": cls.budget.id,
            "analytic_account_id": cls.cost_center.id,
            "date_from": cls.budget.date_from,
            "date_to": cls.budget.date_to,
            "planned_amount": 100000.0,
        })
        cls.purchase_tax = cls.env["account.tax"].create({
            "name": "Partial PR VAT 15%",
            "amount": 15.0,
            "amount_type": "percent",
            "type_tax_use": "purchase",
            "company_id": cls.env.company.id,
        })

    def _create_three_line_pr(self):
        return self.env["purchase.requisition"].create({
            "name": "PR-PARTIAL-%s" % (self.env["ir.sequence"].next_by_code("purchase.order") or "TEST"),
            "pr_type": "pr",
            "approval": "approved",
            "expense_type": "opex",
            "expense_bucket_id": self.budget.id,
            "line_ids": [
                (0, 0, {
                    "description": product.id,
                    "cost_center_id": self.cost_center.id,
                    "quantity": 2.0,
                    "unit_price": product.standard_price,
                })
                for product in self.products
            ],
        })

    def _create_po_for_lines(self, pr, req_lines, state="draft", name=False):
        po_name = name or (self.env["ir.sequence"].sudo().next_by_code("purchase.order") or "PO-PARTIAL-TEST")
        po = self.env["purchase.order"].with_context(tracking_disable=True).create({
            "name": po_name,
            "partner_id": self.vendor.id,
            "requisition_id": pr.id,
            "pr_name": pr.name,
            "origin": pr.name,
            "state": state,
            "notes": "<p>Standard terms</p>",
            "pe_approved": True,
            "order_line": [
                (0, 0, {
                    "product_id": req_line.description.id,
                    "name": req_line.description.display_name,
                    "product_qty": req_line.quantity,
                    "product_uom": self.uom.id,
                    "price_unit": req_line.unit_price,
                    "date_planned": fields.Datetime.now(),
                    "taxes_id": [(6, 0, self.purchase_tax.ids)],
                    "analytic_distribution": {str(self.cost_center.id): 100.0},
                    "custom_requisition_line_id": req_line.id,
                })
                for req_line in req_lines
            ],
        })
        return po

    def test_partial_po_done_keeps_create_rfq_visible_for_remaining_lines(self):
        pr = self._create_three_line_pr()
        line_a, line_b, line_c = pr.line_ids.sorted("id")

        self.assertTrue(pr.show_create_rfq_button)

        # Create initial RFQ for all lines
        rfq_action = pr.action_create_rfq()
        rfq_1 = self.env["purchase.order"].browse(rfq_action["res_id"])
        self.assertEqual(len(rfq_1.order_line), 3)
        self.assertEqual(pr.status, "rfq")

        # Create PO for Product A only, submit, and lock/confirm -> done
        po_a = self._create_po_for_lines(pr, line_a, state="pending", name="PO-PARTIAL-A")
        po_a.button_confirm()
        self.assertEqual(po_a.state, "done")

        pr.invalidate_recordset()
        self.assertEqual(line_a.remaining_qty, 0.0)
        self.assertEqual(line_b.remaining_qty, 2.0)
        self.assertEqual(line_c.remaining_qty, 2.0)
        self.assertEqual(pr.status, "po")
        self.assertTrue(pr.show_create_rfq_button)

        # Cancelling the old RFQ must not regress status back to 'pr'
        rfq_1.button_cancel()
        pr.invalidate_recordset()
        self.assertEqual(pr.status, "po")
        self.assertTrue(pr.show_create_rfq_button)

        # Creating a second RFQ includes only remaining lines B and C
        rfq_action_2 = pr.action_create_rfq()
        rfq_2 = self.env["purchase.order"].browse(rfq_action_2["res_id"])
        self.assertEqual(rfq_2.order_line.mapped("product_id"), self.products[1:])
        self.assertEqual(pr.status, "po")

        # Draft PO for B and C must NOT hide Create RFQ yet
        po_bc = self._create_po_for_lines(pr, line_b | line_c, state="draft", name="PO-PARTIAL-BC")
        pr.invalidate_recordset()
        self.assertTrue(pr.show_create_rfq_button)

        # Submitting and locking PO for B and C completes the PR and hides Create RFQ
        po_bc.action_submit_for_approval()
        po_bc.pe_approved = True
        po_bc.button_confirm()
        self.assertEqual(po_bc.state, "done")

        pr.invalidate_recordset()
        self.assertEqual(line_b.remaining_qty, 0.0)
        self.assertEqual(line_c.remaining_qty, 0.0)
        self.assertEqual(pr.status, "completed")
        self.assertFalse(pr.show_create_rfq_button)

    def test_legacy_completed_pr_with_remaining_lines_still_shows_create_rfq(self):
        pr = self._create_three_line_pr()
        line_a = pr.line_ids.sorted("id")[0]
        self._create_po_for_lines(pr, line_a, state="done", name="PO-LEGACY-A")

        pr.sudo().write({"status": "completed"})
        pr.invalidate_recordset()

        self.assertTrue(pr.show_create_rfq_button)

    def test_unlinking_one_po_preserves_other_po_status_and_restores_create_rfq(self):
        pr = self._create_three_line_pr()
        line_a, line_b, line_c = pr.line_ids.sorted("id")

        po_a = self._create_po_for_lines(pr, line_a, state="done", name="PO-UNLINK-A")
        po_bc = self._create_po_for_lines(pr, line_b | line_c, state="draft", name="PO-UNLINK-BC")
        po_bc.action_submit_for_approval()
        po_bc.pe_approved = True
        po_bc.button_confirm()

        pr.invalidate_recordset()
        self.assertEqual(pr.status, "completed")
        self.assertFalse(pr.show_create_rfq_button)

        # Cancel and unlink PO for B & C while PO A remains done
        po_bc.button_cancel()
        po_bc.unlink()

        pr.invalidate_recordset()
        self.assertEqual(pr.status, "po")
        self.assertTrue(pr.show_create_rfq_button)
        self.assertEqual(po_a.state, "done")

