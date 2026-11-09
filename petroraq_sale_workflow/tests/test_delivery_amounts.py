from datetime import date

from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "pr_picking_amounts")
class TestDeliveryAmounts(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.customer = cls.env["res.partner"].create({
            "name": "Delivery Amount Test Customer",
            "customer_rank": 1,
        })
        cls.inventory_user = cls.env["res.users"].create({
            "name": "Delivery Inventory User",
            "login": "delivery_amount_wh_user",
            "email": "delivery_amount_wh_user@example.com",
            "groups_id": [Command.set([cls.env.ref("stock.group_stock_user").id])],
        })
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.uom_dozen = cls.env.ref("uom.product_uom_dozen")
        cls.product_a = cls.env["product.product"].create({
            "name": "Delivery Storable A",
            "detailed_type": "product",
            "uom_id": cls.uom_unit.id,
            "uom_po_id": cls.uom_unit.id,
            "standard_price": 15.0,
            "list_price": 100.0,
        })
        cls.product_b = cls.env["product.product"].create({
            "name": "Delivery Storable B Dozen",
            "detailed_type": "product",
            "uom_id": cls.uom_unit.id,
            "uom_po_id": cls.uom_dozen.id,
            "standard_price": 2.0,
            "list_price": 240.0,
        })
        cls.tax_excl_15 = cls.env["account.tax"].create({
            "name": "Delivery Sale VAT 15%",
            "amount": 15.0,
            "amount_type": "percent",
            "type_tax_use": "sale",
            "price_include": False,
            "company_id": cls.company.id,
        })
        cls.tax_incl_15 = cls.env["account.tax"].create({
            "name": "Delivery Sale Incl 15%",
            "amount": 15.0,
            "amount_type": "percent",
            "type_tax_use": "sale",
            "price_include": True,
            "company_id": cls.company.id,
        })

    def _create_and_confirm_so(self, line_vals):
        order = self.env["sale.order"].create({
            "partner_id": self.customer.id,
            "payment_term_id": False,
            "approval_state": "approved",
            "confirmation_approval_state": "approved",
            "po_number": "CUST-PO-001",
            "po_date": date.today(),
            "note": "<p>Standard delivery terms and conditions.</p>",
            "order_line": [Command.create(vals) for vals in line_vals],
        })
        attachment = self.env["ir.attachment"].create({
            "name": "customer-po-delivery-test.pdf",
            "type": "binary",
            "datas": "VGVzdCBDdXN0b21lciBQTz0=",
            "res_model": "sale.order",
            "res_id": order.id,
        })
        order.with_context(skip_confirmation_approval_reset=True).write({
            "customer_po_attachment_ids": [Command.set(attachment.ids)],
        })
        order.action_confirm()
        return order

    def test_delivery_uses_so_price_partial_uom_backorder_recompute_and_access(self):
        self.company.tax_calculation_rounding_method = "round_per_line"
        order = self._create_and_confirm_so([
            {
                "product_id": self.product_a.id,
                "name": "Delivery Product A",
                "product_uom_qty": 10.0,
                "product_uom": self.uom_unit.id,
                "price_unit": 100.0,
                "discount": 10.0,
                "tax_id": [Command.set(self.tax_excl_15.ids)],
            },
            {
                "product_id": self.product_b.id,
                "name": "Delivery Product B Dozen",
                "product_uom_qty": 2.0,
                "product_uom": self.uom_dozen.id,
                "price_unit": 240.0,
                "discount": 0.0,
                "tax_id": [Command.set(self.tax_incl_15.ids)],
            },
        ])
        picking = order.picking_ids.filtered(lambda p: p.picking_type_code == "outgoing")[:1]
        self.assertEqual(len(picking), 1)
        move_a = picking.move_ids.filtered(lambda m: m.product_id == self.product_a)
        move_b = picking.move_ids.filtered(lambda m: m.product_id == self.product_b)

        # Uses SO net discounted sales price (NOT product cost 15.0 / 2.0) and converts Dozen -> Unit (240 / 12 = 20.0).
        self.assertAlmostEqual(move_a.pr_unit_price, 90.0)
        self.assertAlmostEqual(move_b.pr_unit_price, 20.0)
        self.assertEqual(move_a.pr_price_subtotal, 0.0)
        self.assertEqual(picking.pr_amount_untaxed, 0.0)
        self.assertEqual(picking.pr_amount_total, 0.0)

        # Partial delivery: 3 units of A (270 + 40.50 = 310.50) + 6 units of B (120 incl VAT: 104.35 + 15.65 = 120) -> 430.50.
        move_a.quantity = 3.0
        move_b.quantity = 6.0
        move_a.picked = True
        move_b.picked = True
        self.assertAlmostEqual(move_a.pr_price_subtotal, 270.0)
        self.assertAlmostEqual(move_a.pr_price_tax, 40.5)
        self.assertAlmostEqual(move_a.pr_price_total, 310.5)
        self.assertAlmostEqual(move_b.pr_price_total, 120.0)
        self.assertAlmostEqual(picking.pr_amount_untaxed, 374.35)
        self.assertAlmostEqual(picking.pr_amount_tax, 56.15)
        self.assertAlmostEqual(picking.pr_amount_total, 430.5)

        # Non-sales Inventory user can read delivery amounts cleanly without AccessError.
        wh_picking = picking.with_user(self.inventory_user)
        self.assertAlmostEqual(wh_picking.pr_amount_total, 430.5)
        self.assertAlmostEqual(
            wh_picking.move_ids_without_package.filtered(lambda m: m.id == move_a.id).pr_price_total,
            310.5,
        )

        # Validate partial delivery and create backorder.
        res = picking.button_validate()
        if isinstance(res, dict) and res.get("res_model") == "stock.backorder.confirmation":
            self.env["stock.backorder.confirmation"].with_context(res["context"]).create({}).process()
        self.assertEqual(picking.state, "done")
        self.assertAlmostEqual(picking.pr_amount_total, 430.5)

        backorder = order.picking_ids.filtered(lambda p: p.backorder_id == picking)
        self.assertEqual(len(backorder), 1)
        self.assertEqual(backorder.pr_amount_total, 0.0)
        bo_move_a = backorder.move_ids.filtered(lambda m: m.product_id == self.product_a)
        bo_move_b = backorder.move_ids.filtered(lambda m: m.product_id == self.product_b)
        bo_move_a.quantity = 7.0
        bo_move_b.quantity = 18.0
        # 7 * 90 = 630 + 94.5 = 724.50; 18 * 20 = 360 tax-incl -> 1084.50 total.
        self.assertAlmostEqual(backorder.pr_amount_total, 1084.5)

        # Updating SO line price triggers stored recomputation on open delivery/backorder moves and picking.
        sol_a = bo_move_a.sale_line_id
        sol_a.with_context(skip_confirmation_approval_reset=True).price_unit = 120.0
        # Net price becomes 120 * 0.9 = 108; 7 * 108 = 756 + 113.4 VAT = 869.40; + 360 = 1229.40.
        self.assertAlmostEqual(bo_move_a.pr_unit_price, 108.0)
        self.assertAlmostEqual(bo_move_a.pr_price_total, 869.4)
        self.assertAlmostEqual(backorder.pr_amount_total, 1229.4)

    def test_delivery_packages_customer_return_and_two_step_internal(self):
        warehouse = self.env["stock.warehouse"].search([("company_id", "=", self.company.id)], limit=1)
        prev_steps = warehouse.delivery_steps
        prev_entire_packs = warehouse.out_type_id.show_entire_packs
        warehouse.delivery_steps = "pick_ship"
        warehouse.out_type_id.show_entire_packs = True
        try:
            order = self._create_and_confirm_so([
                {
                    "product_id": self.product_a.id,
                    "name": "Two Step Product A",
                    "product_uom_qty": 4.0,
                    "product_uom": self.uom_unit.id,
                    "price_unit": 50.0,
                    "discount": 0.0,
                    "tax_id": [Command.set(self.tax_excl_15.ids)],
                },
            ])
            pick_internal = order.picking_ids.filtered(lambda p: p.picking_type_code == "internal")
            out_delivery = order.picking_ids.filtered(lambda p: p.picking_type_code == "outgoing")
            self.assertEqual(len(pick_internal), 1)
            self.assertEqual(len(out_delivery), 1)

            # Two-step internal Pick transfer must yield 0.0 even with quantity filled and SO line present.
            pick_internal.move_ids.quantity = 4.0
            self.assertEqual(pick_internal.move_ids.pr_unit_price, 0.0)
            self.assertEqual(pick_internal.move_ids.pr_price_total, 0.0)
            self.assertEqual(pick_internal.pr_amount_total, 0.0)

            # Outgoing delivery calculates SO value even when move is grouped inside a package_level_id.
            out_move = out_delivery.move_ids
            out_move.quantity = 4.0
            pack = self.env["stock.quant.package"].create({"name": "TEST-PKG-001"})
            pkg_level = self.env["stock.package_level"].create({
                "package_id": pack.id,
                "picking_id": out_delivery.id,
                "location_dest_id": out_delivery.location_dest_id.id,
                "company_id": self.company.id,
                "move_ids": [Command.set(out_move.ids)],
            })
            self.assertTrue(out_move.package_level_id == pkg_level)
            self.assertFalse(out_delivery.move_ids_without_package)
            self.assertAlmostEqual(out_delivery.pr_amount_untaxed, 200.0)
            self.assertAlmostEqual(out_delivery.pr_amount_tax, 30.0)
            self.assertAlmostEqual(out_delivery.pr_amount_total, 230.0)

            # Incoming Customer Return referencing sale_line_id computes positive return value.
            customer_return = self.env["stock.picking"].create({
                "partner_id": self.customer.id,
                "picking_type_id": warehouse.in_type_id.id,
                "location_id": self.env.ref("stock.stock_location_customers").id,
                "location_dest_id": warehouse.lot_stock_id.id,
                "move_ids": [
                    Command.create({
                        "name": "Customer return move",
                        "product_id": self.product_a.id,
                        "product_uom_qty": 2.0,
                        "quantity": 2.0,
                        "product_uom": self.uom_unit.id,
                        "sale_line_id": order.order_line[0].id,
                        "location_id": self.env.ref("stock.stock_location_customers").id,
                        "location_dest_id": warehouse.lot_stock_id.id,
                    }),
                ],
            })
            self.assertAlmostEqual(customer_return.move_ids.pr_unit_price, 50.0)
            self.assertAlmostEqual(customer_return.move_ids.pr_price_subtotal, 100.0)
            self.assertAlmostEqual(customer_return.pr_amount_tax, 15.0)
            self.assertAlmostEqual(customer_return.pr_amount_total, 115.0)
        finally:
            warehouse.delivery_steps = prev_steps
            warehouse.out_type_id.show_entire_packs = prev_entire_packs