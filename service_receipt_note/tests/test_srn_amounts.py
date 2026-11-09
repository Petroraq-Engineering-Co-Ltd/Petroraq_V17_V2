from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "pr_picking_amounts")
class TestSrnAmounts(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.requester = cls.env["res.users"].create({
            "name": "SRN Amount Requester",
            "login": "srn_amount_requester",
            "email": "srn_amount_requester@example.com",
            "groups_id": [Command.set([
                cls.env.ref("service_receipt_note.group_service_receipt_user").id,
            ])],
        })
        cls.qc = cls.env["res.users"].create({
            "name": "SRN Amount QC",
            "login": "srn_amount_qc",
            "email": "srn_amount_qc@example.com",
            "groups_id": [Command.set([
                cls.env.ref("service_receipt_note.group_service_receipt_qc").id,
            ])],
        })
        cls.vendor = cls.env["res.partner"].create({
            "name": "SRN Amount Vendor",
            "supplier_rank": 1,
        })
        cls.pr = cls.env["purchase.requisition"].create({
            "requested_user_id": cls.requester.id,
        })
        cls.service_a = cls.env["product.product"].create({
            "name": "Service Alpha",
            "detailed_type": "service",
        })
        cls.service_b = cls.env["product.product"].create({
            "name": "Service Beta",
            "detailed_type": "service",
        })
        cls.vat_15 = cls.env["account.tax"].create({
            "name": "SRN Test VAT 15%",
            "amount": 15.0,
            "amount_type": "percent",
            "type_tax_use": "purchase",
            "company_id": cls.company.id,
        })

    def test_srn_amounts_discount_tax_partial_and_po_price_update(self):
        order = self.env["purchase.order"].create({
            "partner_id": self.vendor.id,
            "requisition_id": self.pr.id,
            "notes": "Test SRN amount calculation",
            "order_line": [
                Command.create({
                    "product_id": self.service_a.id,
                    "name": "Service Alpha Line",
                    "product_qty": 10.0,
                    "product_uom": self.service_a.uom_po_id.id,
                    "price_unit": 100.0,
                    "discount": 10.0,
                    "taxes_id": [Command.set(self.vat_15.ids)],
                }),
                Command.create({
                    "product_id": self.service_b.id,
                    "name": "Service Beta Line",
                    "product_qty": 5.0,
                    "product_uom": self.service_b.uom_po_id.id,
                    "price_unit": 200.0,
                    "discount": 0.0,
                    "taxes_id": [Command.set(self.vat_15.ids)],
                }),
            ],
        })
        order.button_confirm()
        srn = order.service_receipt_note_ids
        self.assertEqual(len(srn), 1)
        line_a = srn.line_ids.filtered(lambda l: l.product_id == self.service_a)
        line_b = srn.line_ids.filtered(lambda l: l.product_id == self.service_b)

        # Unit price shows net discounted rate even before done_qty is entered; totals start at 0.0.
        self.assertAlmostEqual(line_a.price_unit, 90.0)
        self.assertAlmostEqual(line_b.price_unit, 200.0)
        self.assertEqual(line_a.price_subtotal, 0.0)
        self.assertEqual(line_a.price_total, 0.0)
        self.assertEqual(srn.amount_untaxed, 0.0)
        self.assertEqual(srn.amount_tax, 0.0)
        self.assertEqual(srn.amount_total, 0.0)

        # Partial done_qty: 2 * 90 = 180 + 27 VAT = 207; 1 * 200 = 200 + 30 VAT = 230 -> 380 / 57 / 437.
        line_a.with_user(self.requester).done_qty = 2.0
        line_b.with_user(self.requester).done_qty = 1.0
        self.assertAlmostEqual(line_a.price_subtotal, 180.0)
        self.assertAlmostEqual(line_a.price_tax, 27.0)
        self.assertAlmostEqual(line_a.price_total, 207.0)
        self.assertAlmostEqual(line_b.price_subtotal, 200.0)
        self.assertAlmostEqual(line_b.price_tax, 30.0)
        self.assertAlmostEqual(line_b.price_total, 230.0)
        self.assertAlmostEqual(srn.amount_untaxed, 380.0)
        self.assertAlmostEqual(srn.amount_tax, 57.0)
        self.assertAlmostEqual(srn.amount_total, 437.0)

        # Non-PO QC user can read computed totals cleanly without AccessError.
        qc_srn = srn.with_user(self.qc)
        self.assertAlmostEqual(qc_srn.amount_total, 437.0)
        self.assertAlmostEqual(qc_srn.line_ids[0].price_total, line_a.price_total if qc_srn.line_ids[0] == line_a else line_b.price_total)

        # Updating PO price triggers stored SRN recomputation.
        line_a.purchase_line_id.price_unit = 150.0
        self.assertAlmostEqual(line_a.price_unit, 135.0)
        self.assertAlmostEqual(line_a.price_subtotal, 270.0)
        self.assertAlmostEqual(line_a.price_tax, 40.5)
        self.assertAlmostEqual(line_a.price_total, 310.5)
        self.assertAlmostEqual(srn.amount_untaxed, 470.0)
        self.assertAlmostEqual(srn.amount_tax, 70.5)
        self.assertAlmostEqual(srn.amount_total, 540.5)

    def test_srn_global_rounding_and_foreign_currency(self):
        usd = self.env.ref("base.USD")
        usd.active = True
        self.company.tax_calculation_rounding_method = "round_globally"
        order = self.env["purchase.order"].create({
            "partner_id": self.vendor.id,
            "requisition_id": self.pr.id,
            "currency_id": usd.id,
            "notes": "Foreign currency global rounding",
            "order_line": [
                Command.create({
                    "product_id": self.service_a.id,
                    "name": "Rounding A",
                    "product_qty": 2.0,
                    "product_uom": self.service_a.uom_po_id.id,
                    "price_unit": 10.03,
                    "taxes_id": [Command.set(self.vat_15.ids)],
                }),
                Command.create({
                    "product_id": self.service_b.id,
                    "name": "Rounding B",
                    "product_qty": 2.0,
                    "product_uom": self.service_b.uom_po_id.id,
                    "price_unit": 10.03,
                    "taxes_id": [Command.set(self.vat_15.ids)],
                }),
            ],
        })
        order.button_confirm()
        srn = order.service_receipt_note_ids
        self.assertEqual(srn.currency_id, usd)
        for line in srn.line_ids:
            line.done_qty = 1.0
        # Two lines of 10.03 each: untaxed=20.06, global tax=20.06*0.15=3.009->3.01 (per-line would round 1.5045->1.50 * 2 = 3.00).
        self.assertAlmostEqual(srn.amount_untaxed, 20.06)
        self.assertAlmostEqual(srn.amount_tax, 3.01)
        self.assertAlmostEqual(srn.amount_total, 23.07)

