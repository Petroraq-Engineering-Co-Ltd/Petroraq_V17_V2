from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "pr_picking_amounts")
class TestGrnAmounts(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.requester = cls.env["res.users"].create({
            "name": "GRN Test Requester",
            "login": "grn_amount_requester",
            "email": "grn_amount_requester@example.com",
            "groups_id": [Command.set([cls.env.ref("base.group_user").id])],
        })
        cls.warehouse_user = cls.env["res.users"].create({
            "name": "GRN Warehouse User",
            "login": "grn_warehouse_user",
            "email": "grn_warehouse_user@example.com",
            "groups_id": [Command.set([cls.env.ref("stock.group_stock_user").id])],
        })
        cls.vendor = cls.env["res.partner"].create({
            "name": "GRN Amount Vendor",
            "supplier_rank": 1,
        })
        cls.pr = cls.env["purchase.requisition"].create({
            "requested_user_id": cls.requester.id,
        })
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.uom_dozen = cls.env.ref("uom.product_uom_dozen")
        cls.product_a = cls.env["product.product"].create({
            "name": "GRN Storable A",
            "detailed_type": "product",
            "uom_id": cls.uom_unit.id,
            "uom_po_id": cls.uom_unit.id,
        })
        cls.product_b = cls.env["product.product"].create({
            "name": "GRN Storable B Dozen",
            "detailed_type": "product",
            "uom_id": cls.uom_unit.id,
            "uom_po_id": cls.uom_dozen.id,
        })
        cls.tax_excl_15 = cls.env["account.tax"].create({
            "name": "GRN Purchase VAT 15%",
            "amount": 15.0,
            "amount_type": "percent",
            "type_tax_use": "purchase",
            "price_include": False,
            "company_id": cls.company.id,
        })
        cls.tax_incl_15 = cls.env["account.tax"].create({
            "name": "GRN Purchase Incl 15%",
            "amount": 15.0,
            "amount_type": "percent",
            "type_tax_use": "purchase",
            "price_include": True,
            "company_id": cls.company.id,
        })

    def test_grn_partial_discount_tax_uom_cancel_and_access(self):
        self.company.tax_calculation_rounding_method = "round_per_line"
        order = self.env["purchase.order"].create({
            "partner_id": self.vendor.id,
            "requisition_id": self.pr.id,
            "notes": "Test GRN amounts",
            "order_line": [
                Command.create({
                    "product_id": self.product_a.id,
                    "name": "Storable A",
                    "product_qty": 10.0,
                    "product_uom": self.uom_unit.id,
                    "price_unit": 100.0,
                    "discount": 10.0,
                    "taxes_id": [Command.set(self.tax_excl_15.ids)],
                }),
                Command.create({
                    "product_id": self.product_b.id,
                    "name": "Storable B Dozen",
                    "product_qty": 2.0,
                    "product_uom": self.uom_dozen.id,
                    "price_unit": 120.0,
                    "discount": 0.0,
                    "taxes_id": [Command.set(self.tax_incl_15.ids)],
                }),
            ],
        })
        order.button_confirm()
        picking = order.picking_ids.filtered(lambda p: p.picking_type_code == "incoming")[:1]
        self.assertEqual(len(picking), 1)
        move_a = picking.move_ids.filtered(lambda m: m.product_id == self.product_a)
        move_b = picking.move_ids.filtered(lambda m: m.product_id == self.product_b)

        # Unit price reflects PO discounted price (and Dozen->Unit UoM conversion = 10.0/unit).
        # Subtotal/Total remain 0.0 until done quantity is entered.
        self.assertAlmostEqual(move_a.pr_unit_price, 90.0)
        self.assertAlmostEqual(move_b.pr_unit_price, 10.0)
        self.assertEqual(move_a.pr_price_subtotal, 0.0)
        self.assertEqual(picking.pr_amount_untaxed, 0.0)
        self.assertEqual(picking.pr_amount_total, 0.0)

        # Enter partial quantities: 4 units of A (4*90=360 + 54 VAT = 414) + 12 units of B (tax-included 120: 104.35 + 15.65 VAT = 120).
        move_a.quantity = 4.0
        move_b.quantity = 12.0
        self.assertAlmostEqual(move_a.pr_price_subtotal, 360.0)
        self.assertAlmostEqual(move_a.pr_price_tax, 54.0)
        self.assertAlmostEqual(move_a.pr_price_total, 414.0)
        self.assertAlmostEqual(move_b.pr_price_total, 120.0)
        self.assertAlmostEqual(picking.pr_amount_total, 534.0)

        # Warehouse user without purchase group can read picking/move values cleanly.
        wh_picking = picking.with_user(self.warehouse_user)
        self.assertAlmostEqual(wh_picking.pr_amount_total, 534.0)
        self.assertAlmostEqual(wh_picking.move_ids_without_package.filtered(lambda m: m.id == move_a.id).pr_price_total, 414.0)

        # Cancelling move_b removes its contribution from picking totals cleanly.
        move_b._action_cancel()
        self.assertEqual(move_b.pr_price_subtotal, 0.0)
        self.assertEqual(move_b.pr_price_total, 0.0)
        self.assertAlmostEqual(picking.pr_amount_untaxed, 360.0)
        self.assertAlmostEqual(picking.pr_amount_tax, 54.0)
        self.assertAlmostEqual(picking.pr_amount_total, 414.0)

    def test_vendor_return_internal_transfer_and_unlinked_picking(self):
        warehouse = self.env["stock.warehouse"].search([("company_id", "=", self.company.id)], limit=1)
        order = self.env["purchase.order"].create({
            "partner_id": self.vendor.id,
            "requisition_id": self.pr.id,
            "notes": "Test return and internal transfer",
            "order_line": [
                Command.create({
                    "product_id": self.product_a.id,
                    "name": "Returnable A",
                    "product_qty": 5.0,
                    "product_uom": self.uom_unit.id,
                    "price_unit": 50.0,
                    "taxes_id": [Command.set(self.tax_excl_15.ids)],
                }),
            ],
        })
        order.button_confirm()
        po_line = order.order_line[0]

        # Outgoing Vendor Return referencing purchase_line_id computes positive value.
        vendor_return = self.env["stock.picking"].create({
            "partner_id": self.vendor.id,
            "picking_type_id": warehouse.out_type_id.id,
            "location_id": warehouse.lot_stock_id.id,
            "location_dest_id": self.env.ref("stock.stock_location_suppliers").id,
            "move_ids": [
                Command.create({
                    "name": "Return move",
                    "product_id": self.product_a.id,
                    "product_uom_qty": 2.0,
                    "quantity": 2.0,
                    "product_uom": self.uom_unit.id,
                    "purchase_line_id": po_line.id,
                    "location_id": warehouse.lot_stock_id.id,
                    "location_dest_id": self.env.ref("stock.stock_location_suppliers").id,
                }),
            ],
        })
        self.assertAlmostEqual(vendor_return.move_ids.pr_unit_price, 50.0)
        self.assertAlmostEqual(vendor_return.move_ids.pr_price_subtotal, 100.0)
        self.assertAlmostEqual(vendor_return.pr_amount_tax, 15.0)
        self.assertAlmostEqual(vendor_return.pr_amount_total, 115.0)

        # Internal transfer must always yield 0.0 even if move has a purchase_line_id.
        internal_picking = self.env["stock.picking"].create({
            "picking_type_id": warehouse.int_type_id.id,
            "location_id": warehouse.lot_stock_id.id,
            "location_dest_id": warehouse.lot_stock_id.id,
            "move_ids": [
                Command.create({
                    "name": "Internal move",
                    "product_id": self.product_a.id,
                    "product_uom_qty": 2.0,
                    "quantity": 2.0,
                    "product_uom": self.uom_unit.id,
                    "purchase_line_id": po_line.id,
                    "location_id": warehouse.lot_stock_id.id,
                    "location_dest_id": warehouse.lot_stock_id.id,
                }),
            ],
        })
        self.assertEqual(internal_picking.move_ids.pr_unit_price, 0.0)
        self.assertEqual(internal_picking.move_ids.pr_price_total, 0.0)
        self.assertEqual(internal_picking.pr_amount_total, 0.0)

        # Unlinked manual incoming picking yields 0.0 without falling back to product cost.
        self.product_a.standard_price = 999.0
        manual_receipt = self.env["stock.picking"].create({
            "partner_id": self.vendor.id,
            "picking_type_id": warehouse.in_type_id.id,
            "location_id": self.env.ref("stock.stock_location_suppliers").id,
            "location_dest_id": warehouse.lot_stock_id.id,
            "move_ids": [
                Command.create({
                    "name": "Manual receipt",
                    "product_id": self.product_a.id,
                    "product_uom_qty": 3.0,
                    "quantity": 3.0,
                    "product_uom": self.uom_unit.id,
                    "location_id": self.env.ref("stock.stock_location_suppliers").id,
                    "location_dest_id": warehouse.lot_stock_id.id,
                }),
            ],
        })
        self.assertEqual(manual_receipt.move_ids.pr_unit_price, 0.0)
        self.assertEqual(manual_receipt.pr_amount_total, 0.0)

