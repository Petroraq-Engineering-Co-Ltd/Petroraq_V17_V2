from datetime import date

from lxml import etree

from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "pr_delivery_descriptions")
class TestDeliveryDescriptions(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
        cls.customer = cls.env["res.partner"].create({
            "name": "Delivery Description Test Customer",
            "customer_rank": 1,
        })
        cls.vendor = cls.env["res.partner"].create({
            "name": "Delivery Description Test Vendor",
            "supplier_rank": 1,
        })
        cls.sales_user = cls.env["res.users"].create({
            "name": "Delivery Description Salesperson",
            "login": "delivery_desc_sales_user",
            "email": "delivery_desc_sales_user@example.com",
            "groups_id": [
                Command.set([cls.env.ref("sales_team.group_sale_salesman").id])
            ],
        })
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.product = cls.env["product.product"].create({
            "name": "Industrial Control Valve",
            "default_code": "ICV-100",
            "detailed_type": "product",
            "uom_id": cls.uom_unit.id,
            "uom_po_id": cls.uom_unit.id,
            "standard_price": 50.0,
            "list_price": 120.0,
            "description_pickingout": "Default Warehouse Picking Out Description",
            "description_picking": "Default Warehouse Internal Description",
            "description_pickingin": "Default Warehouse Incoming Description",
        })
        cls.product_plain = cls.env["product.product"].create({
            "name": "Plain Flange Gasket",
            "default_code": "PFG-200",
            "detailed_type": "product",
            "uom_id": cls.uom_unit.id,
            "uom_po_id": cls.uom_unit.id,
            "standard_price": 10.0,
            "list_price": 25.0,
        })

    def _create_and_confirm_so(self, line_vals, salesperson=None):
        order = self.env["sale.order"].create({
            "partner_id": self.customer.id,
            "user_id": (salesperson or self.env.user).id,
            "warehouse_id": self.warehouse.id,
            "payment_term_id": False,
            "approval_state": "approved",
            "confirmation_approval_state": "approved",
            "po_number": "PO-DESC-001",
            "po_date": date.today(),
            "note": "<p>Delivery description test terms.</p>",
            "order_line": [Command.create(vals) for vals in line_vals],
        })
        attachment = self.env["ir.attachment"].create({
            "name": "customer-po-desc-test.pdf",
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

    def _validate_picking_with_backorder(self, picking):
        res = picking.button_validate()
        if isinstance(res, dict) and res.get("res_model") == "stock.backorder.confirmation":
            self.env["stock.backorder.confirmation"].with_context(
                res["context"]
            ).create({}).process()

    def test_single_step_description_precedence_pdf_and_remaining_delivery(self):
        custom_desc = "[ICV-100] Industrial Control Valve\nSS316 Body PN40\nClient Tag V-101"
        order = self._create_and_confirm_so([
            {
                "product_id": self.product.id,
                "name": custom_desc,
                "product_uom_qty": 5.0,
                "product_uom": self.uom_unit.id,
                "price_unit": 120.0,
            },
            {
                "product_id": self.product.id,
                "name": "   \n  ",
                "product_uom_qty": 2.0,
                "product_uom": self.uom_unit.id,
                "price_unit": 120.0,
            },
            {
                "product_id": self.product_plain.id,
                "name": "",
                "product_uom_qty": 1.0,
                "product_uom": self.uom_unit.id,
                "price_unit": 25.0,
            },
        ])
        picking = order.picking_ids.filtered(lambda p: p.picking_type_code == "outgoing")[:1]
        self.assertEqual(len(picking), 1)
        sol_custom, sol_blank, sol_plain = order.order_line

        move_custom = picking.move_ids.filtered(lambda m: m.sale_line_id == sol_custom)
        move_blank = picking.move_ids.filtered(lambda m: m.sale_line_id == sol_blank)
        move_plain = picking.move_ids.filtered(lambda m: m.sale_line_id == sol_plain)

        # SO line description beats product.description_pickingout when non-empty.
        self.assertEqual(move_custom.description_picking, custom_desc)
        # Blank/whitespace SO line falls back to standard product delivery description.
        self.assertEqual(
            move_blank.description_picking,
            "Default Warehouse Picking Out Description",
        )
        self.assertEqual(move_plain.description_picking, "Plain Flange Gasket")

        # Delivery Note PDF helper strips redundant product heading while keeping SO details.
        self.assertEqual(
            move_custom._pr_get_delivery_line_description(),
            "SS316 Body PN40\nClient Tag V-101",
        )
        html_bytes, _fmt = self.env["ir.actions.report"]._render_qweb_html(
            "stock.report_deliveryslip", [picking.id]
        )
        html = html_bytes.decode("utf-8")
        self.assertIn("SS316 Body PN40", html)
        self.assertIn("Client Tag V-101", html)

        # Manual warehouse edit on open move overrides PDF output until SO line changes.
        move_custom.description_picking = "Manual Warehouse Override Note"
        self.assertEqual(
            move_custom._pr_get_delivery_line_description(),
            "Manual Warehouse Override Note",
        )

        # Custom "Create Remaining Delivery" also populates description_picking from SO line.
        order_rem = self._create_and_confirm_so([
            {
                "product_id": self.product.id,
                "name": "Remaining Delivery Special Spec",
                "product_uom_qty": 4.0,
                "product_uom": self.uom_unit.id,
                "price_unit": 120.0,
            },
        ])
        first_picking = order_rem.picking_ids.filtered(lambda p: p.picking_type_code == "outgoing")[:1]
        first_picking.action_cancel()
        action = order_rem.action_create_remaining_delivery()
        rem_picking = self.env["stock.picking"].browse(action["res_id"])
        rem_move = rem_picking.move_ids
        self.assertEqual(len(rem_move), 1)
        self.assertEqual(rem_move.description_picking, "Remaining Delivery Special Spec")

        # Empty SO line description with no_variant attributes falls back to description_pickingout + variants.
        attr = self.env["product.attribute"].create({
            "name": "Coating",
            "create_variant": "no_variant",
        })
        val_red = self.env["product.attribute.value"].create({
            "name": "Epoxy",
            "attribute_id": attr.id,
        })
        val_blue = self.env["product.attribute.value"].create({
            "name": "Zinc",
            "attribute_id": attr.id,
        })
        attr_tmpl = self.env["product.template"].create({
            "name": "Coated Valve Body",
            "detailed_type": "product",
            "uom_id": self.uom_unit.id,
            "uom_po_id": self.uom_unit.id,
            "description_pickingout": "Coated Valve Out Note",
            "attribute_line_ids": [
                Command.create({
                    "attribute_id": attr.id,
                    "value_ids": [Command.set([val_red.id, val_blue.id])],
                })
            ],
        })
        ptav_epoxy = attr_tmpl.attribute_line_ids.product_template_value_ids.filtered(
            lambda v: v.product_attribute_value_id == val_red
        )[:1]
        order_var = self._create_and_confirm_so([
            {
                "product_id": attr_tmpl.product_variant_id.id,
                "name": "",
                "product_uom_qty": 1.0,
                "product_uom": self.uom_unit.id,
                "price_unit": 50.0,
                "product_no_variant_attribute_value_ids": [Command.set(ptav_epoxy.ids)],
            },
        ])
        var_move = order_var.picking_ids.move_ids
        self.assertIn("Coated Valve Out Note", var_move.description_picking)
        self.assertIn("Epoxy", var_move.description_picking)

    def test_post_confirmation_edit_syncs_open_moves_only_and_skips_done_cancel_returns(self):
        order = self._create_and_confirm_so([
            {
                "product_id": self.product.id,
                "name": "Initial Spec V1",
                "product_uom_qty": 6.0,
                "product_uom": self.uom_unit.id,
                "price_unit": 120.0,
            },
        ], salesperson=self.sales_user)
        sol = order.order_line[0]
        picking_done = order.picking_ids.filtered(lambda p: p.picking_type_code == "outgoing")[:1]
        move_done = picking_done.move_ids
        self.assertEqual(move_done.description_picking, "Initial Spec V1")

        # Deliver 2 out of 6 to create a Done picking + Open Backorder picking.
        move_done.quantity = 2.0
        move_done.picked = True
        self._validate_picking_with_backorder(picking_done)
        self.assertEqual(picking_done.state, "done")

        backorder = order.picking_ids.filtered(lambda p: p.backorder_id == picking_done)
        self.assertEqual(len(backorder), 1)
        move_bo = backorder.move_ids
        self.assertEqual(move_bo.description_picking, "Initial Spec V1")

        # Create a cancelled move linked to the same SO line.
        cancelled_move = self.env["stock.move"].create({
            "name": "Cancelled Move",
            "description_picking": "Cancelled Historical Desc",
            "product_id": self.product.id,
            "product_uom_qty": 1.0,
            "product_uom": self.uom_unit.id,
            "location_id": picking_done.location_id.id,
            "location_dest_id": picking_done.location_dest_id.id,
            "picking_type_id": self.warehouse.out_type_id.id,
            "sale_line_id": sol.id,
        })
        cancelled_move._action_cancel()
        self.assertEqual(cancelled_move.state, "cancel")

        # Create a Customer Return from the validated delivery via stock.return.picking.
        return_wizard = self.env["stock.return.picking"].with_context(
            active_id=picking_done.id, active_ids=picking_done.ids, active_model="stock.picking"
        ).create({})
        res_ret = return_wizard.create_returns()
        return_picking = self.env["stock.picking"].browse(res_ret["res_id"])
        return_move = return_picking.move_ids
        self.assertEqual(return_move.description_picking, "Initial Spec V1")

        # Salesperson updates SO line description after confirmation.
        sol.with_user(self.sales_user).with_context(skip_confirmation_approval_reset=True).write({
            "name": "Updated Spec V2\nExtra Certification",
        })

        self.assertEqual(
            move_bo.description_picking, "Updated Spec V2\nExtra Certification"
        )
        self.assertEqual(move_done.description_picking, "Initial Spec V1")
        self.assertEqual(cancelled_move.description_picking, "Cancelled Historical Desc")
        self.assertEqual(return_move.description_picking, "Initial Spec V1")

        # Clearing SO line description back to whitespace reverts open move to fallback.
        sol.with_user(self.sales_user).with_context(skip_confirmation_approval_reset=True).write({
            "name": "   ",
        })
        self.assertEqual(
            move_bo.description_picking, "Default Warehouse Picking Out Description"
        )
        self.assertEqual(move_done.description_picking, "Initial Spec V1")

    def test_multistep_delivery_propagation_sync_and_mto_purchase_isolation(self):
        prev_steps = self.warehouse.delivery_steps
        mto_route = self.warehouse.with_context(active_test=False).mto_pull_id.route_id
        if not mto_route:
            mto_route = self.env.ref("stock.route_warehouse0_mto", raise_if_not_found=False)
        if not mto_route:
            mto_route = self.env["stock.warehouse"]._find_global_route(
                "stock.route_warehouse0_mto", "Replenish on Order (MTO)"
            )
        prev_mto_active = mto_route.active
        mto_route.active = True
        buy_route = self.env.ref("purchase_stock.route_warehouse0_buy")
        supplierinfo = self.env["product.supplierinfo"].create({
            "partner_id": self.vendor.id,
            "product_tmpl_id": self.product.product_tmpl_id.id,
            "price": 45.0,
        })
        prev_routes = self.product.route_ids
        self.warehouse.delivery_steps = "pick_pack_ship"
        try:
            # 1) Non-MTO multi-step with same product on two SO lines having distinct descriptions.
            order = self._create_and_confirm_so([
                {
                    "product_id": self.product.id,
                    "name": "Alpha Line Desc",
                    "product_uom_qty": 3.0,
                    "product_uom": self.uom_unit.id,
                    "price_unit": 120.0,
                },
                {
                    "product_id": self.product.id,
                    "name": "Beta Line Desc",
                    "product_uom_qty": 4.0,
                    "product_uom": self.uom_unit.id,
                    "price_unit": 120.0,
                },
            ])
            sol_alpha, sol_beta = order.order_line
            pick_picking = order.picking_ids.filtered(
                lambda p: p.picking_type_id == self.warehouse.pick_type_id
            )
            pack_picking = order.picking_ids.filtered(
                lambda p: p.picking_type_id == self.warehouse.pack_type_id
            )
            ship_picking = order.picking_ids.filtered(
                lambda p: p.picking_type_id == self.warehouse.out_type_id
            )
            self.assertEqual(len(pick_picking), 1)
            self.assertEqual(len(pack_picking), 1)
            self.assertEqual(len(ship_picking), 1)

            # Two distinct moves per step (not merged) carrying exact SO line descriptions.
            self.assertEqual(len(pick_picking.move_ids), 2)
            self.assertEqual(len(pack_picking.move_ids), 2)
            self.assertEqual(len(ship_picking.move_ids), 2)

            ship_alpha = ship_picking.move_ids.filtered(lambda m: m.sale_line_id == sol_alpha)
            ship_beta = ship_picking.move_ids.filtered(lambda m: m.sale_line_id == sol_beta)
            pack_alpha = ship_alpha.move_orig_ids
            pack_beta = ship_beta.move_orig_ids
            pick_alpha = pack_alpha.move_orig_ids
            pick_beta = pack_beta.move_orig_ids

            self.assertEqual(pick_alpha.description_picking, "Alpha Line Desc")
            self.assertEqual(pack_alpha.description_picking, "Alpha Line Desc")
            self.assertEqual(ship_alpha.description_picking, "Alpha Line Desc")
            self.assertEqual(pick_beta.description_picking, "Beta Line Desc")
            self.assertEqual(pack_beta.description_picking, "Beta Line Desc")
            self.assertEqual(ship_beta.description_picking, "Beta Line Desc")

            # Editing sol_alpha syncs Pick + Pack + Ship for alpha only, leaving beta untouched.
            sol_alpha.with_context(skip_confirmation_approval_reset=True).write({
                "name": "Alpha Line Updated",
            })
            self.assertEqual(pick_alpha.description_picking, "Alpha Line Updated")
            self.assertEqual(pack_alpha.description_picking, "Alpha Line Updated")
            self.assertEqual(ship_alpha.description_picking, "Alpha Line Updated")
            self.assertEqual(pick_beta.description_picking, "Beta Line Desc")
            self.assertEqual(pack_beta.description_picking, "Beta Line Desc")
            self.assertEqual(ship_beta.description_picking, "Beta Line Desc")

            # Complete Pick transfer; subsequent SO line edit must leave done Pick unchanged
            # while still syncing open Pack + Ship.
            for move in pick_picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            self._validate_picking_with_backorder(pick_picking)
            self.assertEqual(pick_picking.state, "done")

            sol_alpha.with_context(skip_confirmation_approval_reset=True).write({
                "name": "Alpha Line Final",
            })
            self.assertEqual(pick_alpha.description_picking, "Alpha Line Updated")
            self.assertEqual(pack_alpha.description_picking, "Alpha Line Final")
            self.assertEqual(ship_alpha.description_picking, "Alpha Line Final")

            # 2) MTO + Buy isolation: PO line & incoming receipt must NOT copy SO description.
            self.product.route_ids = (mto_route | buy_route)
            mto_order = self._create_and_confirm_so([
                {
                    "product_id": self.product.id,
                    "name": "Secret Client SO Line Text",
                    "product_uom_qty": 2.0,
                    "product_uom": self.uom_unit.id,
                    "price_unit": 120.0,
                },
            ])
            mto_sol = mto_order.order_line[0]
            mto_ship = mto_order.picking_ids.filtered(
                lambda p: p.picking_type_id == self.warehouse.out_type_id
            ).move_ids
            mto_pack = mto_ship.move_orig_ids
            mto_pick = mto_pack.move_orig_ids
            self.assertEqual(mto_pick.description_picking, "Secret Client SO Line Text")
            self.assertEqual(mto_pack.description_picking, "Secret Client SO Line Text")
            self.assertEqual(mto_ship.description_picking, "Secret Client SO Line Text")

            po_line = self.env["purchase.order.line"].search([
                ("move_dest_ids", "in", mto_pick.ids),
            ])
            self.assertEqual(len(po_line), 1)
            self.assertNotIn("Secret Client SO Line Text", po_line.name or "")
            po_line.order_id.button_confirm()
            receipt_move = po_line.move_ids
            self.assertEqual(len(receipt_move), 1)
            self.assertEqual(
                receipt_move.description_picking, "Default Warehouse Incoming Description"
            )

            mto_sol.with_context(skip_confirmation_approval_reset=True).write({
                "name": "Updated Secret Client Text",
            })
            self.assertEqual(mto_pick.description_picking, "Updated Secret Client Text")
            self.assertEqual(mto_pack.description_picking, "Updated Secret Client Text")
            self.assertEqual(mto_ship.description_picking, "Updated Secret Client Text")
            self.assertEqual(
                receipt_move.description_picking, "Default Warehouse Incoming Description"
            )
        finally:
            self.product.route_ids = prev_routes
            supplierinfo.unlink()
            self.warehouse.delivery_steps = prev_steps
            mto_route.active = prev_mto_active

    def test_picking_form_shows_description_picking_by_default(self):
        view_info = self.env["stock.picking"].get_view(
            view_id=self.env.ref("stock.view_picking_form").id,
            view_type="form",
        )
        doc = etree.fromstring(view_info["arch"])
        desc_fields = doc.xpath(
            "//field[@name='move_ids_without_package']/tree//field[@name='description_picking']"
        )
        self.assertTrue(desc_fields)
        self.assertEqual(desc_fields[0].get("optional"), "show")