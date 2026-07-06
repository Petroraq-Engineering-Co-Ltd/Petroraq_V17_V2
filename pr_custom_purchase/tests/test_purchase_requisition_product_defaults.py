from odoo.tests.common import TransactionCase


class TestPurchaseRequisitionProductDefaults(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock_uom = cls.env.ref("uom.product_uom_unit")
        cls.purchase_uom = cls.env.ref(
            "uom.product_uom_dozen",
            raise_if_not_found=False,
        ) or cls.stock_uom
        cls.analytic_plan = cls.env["account.analytic.plan"].create({
            "name": "PR Product Defaults Test Plan",
        })
        cls.cost_center = cls.env["account.analytic.account"].create({
            "name": "PR Product Defaults Test Cost Center",
            "plan_id": cls.analytic_plan.id,
        })
        cls.material_product = cls.env["product.product"].create({
            "name": "Configured PR Material",
            "detailed_type": "consu",
            "uom_id": cls.stock_uom.id,
            "uom_po_id": cls.purchase_uom.id,
            "standard_price": 24.0,
        })
        cls.service_product = cls.env["product.product"].create({
            "name": "Configured PR Service",
            "detailed_type": "service",
            "uom_id": cls.stock_uom.id,
            "uom_po_id": cls.stock_uom.id,
            "standard_price": 50.0,
        })

    def test_onchange_uses_product_type_and_purchase_uom(self):
        line = self.env["purchase.requisition.line"].new({
            "description": self.material_product.id,
        })

        line._onchange_description()

        self.assertEqual(line.type, "material")
        self.assertEqual(line.unit, self.purchase_uom.name)

    def test_server_create_populates_readonly_type_and_unit(self):
        line = self.env["purchase.requisition.line"].create({
            "description": self.material_product.id,
            "cost_center_id": self.cost_center.id,
            "quantity": 2.0,
        })

        self.assertEqual(line.type, "material")
        self.assertEqual(line.unit, self.purchase_uom.name)

    def test_service_product_maps_to_service_type(self):
        line = self.env["purchase.requisition.line"].create({
            "description": self.service_product.id,
            "cost_center_id": self.cost_center.id,
            "quantity": 1.0,
        })

        self.assertEqual(line.type, "service")
        self.assertEqual(line.unit, self.stock_uom.name)

    def test_same_product_inverse_does_not_reset_manual_unit_cost(self):
        line = self.env["purchase.requisition.line"].create({
            "description": self.material_product.id,
            "cost_center_id": self.cost_center.id,
            "quantity": 1.0,
            "unit_price": 2000.0,
        })

        line.write({"description": self.material_product.id})
        line._inverse_product_internal_reference()

        self.assertEqual(line.unit_price, 2000.0)

    def test_actual_product_change_uses_new_product_default_cost(self):
        line = self.env["purchase.requisition.line"].create({
            "description": self.material_product.id,
            "cost_center_id": self.cost_center.id,
            "quantity": 1.0,
            "unit_price": 2000.0,
        })

        line.write({"description": self.service_product.id})

        self.assertEqual(line.unit_price, self.service_product.standard_price)

    def test_explicit_cost_is_kept_when_product_changes(self):
        line = self.env["purchase.requisition.line"].create({
            "description": self.material_product.id,
            "cost_center_id": self.cost_center.id,
            "quantity": 1.0,
            "unit_price": 2000.0,
        })

        line.write({
            "description": self.service_product.id,
            "unit_price": 75.0,
        })

        self.assertEqual(line.unit_price, 75.0)
