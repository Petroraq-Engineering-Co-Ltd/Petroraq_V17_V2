from odoo.tests.common import TransactionCase


class TestBudgetaryPurchaseRequisition(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uom = cls.env.ref("uom.product_uom_unit")

    def _create_budgetary_pr(self, description="Budgetary Test Item"):
        return self.env["purchase.requisition"].create({
            "name": "BPR-TEST",
            "pr_type": "budgetary",
            "line_ids": [(0, 0, {
                "budgetary_description": description,
                "budgetary_product_type": "product",
                "uom_id": self.uom.id,
                "quantity": 2.0,
                "unit_price": 25.0,
            })],
        })

    def test_budgetary_pr_validates_without_budget_product_or_cost_center(self):
        requisition = self._create_budgetary_pr()

        requisition._validate_for_submission()

        self.assertFalse(requisition.expense_bucket_id)
        self.assertFalse(requisition.line_ids.description)
        self.assertFalse(requisition.line_ids.cost_center_id)

    def test_budgetary_product_is_created_from_open_line(self):
        line = self._create_budgetary_pr("New Budgetary Valve").line_ids

        product = line._get_or_create_budgetary_product()

        self.assertEqual(product.name, "New Budgetary Valve")
        self.assertEqual(product.detailed_type, "product")
        self.assertEqual(product.uom_po_id, self.uom)
        self.assertEqual(product.purchase_method, "receive")
        self.assertEqual(line.description, product)

    def test_budgetary_product_reuses_existing_inventory_product(self):
        existing = self.env["product.product"].create({
            "name": "Existing Budgetary Service",
            "detailed_type": "service",
            "uom_id": self.uom.id,
            "uom_po_id": self.uom.id,
        })
        requisition = self._create_budgetary_pr("Existing Budgetary Service")
        requisition.line_ids.budgetary_product_type = "service"

        product = requisition.line_ids._get_or_create_budgetary_product()

        self.assertEqual(product, existing)
