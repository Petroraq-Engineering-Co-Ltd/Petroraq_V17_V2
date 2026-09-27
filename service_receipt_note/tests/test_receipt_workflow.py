from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user


class TestServiceReceiptWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.requester = new_test_user(cls.env, login="srn_requester",
                                     groups="service_receipt_note.group_service_receipt_user")
        cls.manager = new_test_user(cls.env, login="srn_manager",
                                   groups="service_receipt_note.group_service_receipt_user")
        cls.outsider = new_test_user(cls.env, login="srn_outsider",
                                    groups="purchase.group_purchase_user")
        manager_employee = cls.env["hr.employee"].create({"name": "Department Manager", "user_id": cls.manager.id})
        department = cls.env["hr.department"].create({"name": "Service Test Department", "manager_id": manager_employee.id})
        cls.env["hr.employee"].create({"name": "Requester", "user_id": cls.requester.id, "department_id": department.id})
        pr = cls.env["purchase.requisition"].create({"requested_user_id": cls.requester.id})
        vendor = cls.env["res.partner"].create({"name": "Receipt Test Vendor"})
        product = cls.env["product.product"].create({"name": "Receipt Test Service", "detailed_type": "service"})
        cls.order = cls.env["purchase.order"].create({
            "partner_id": vendor.id, "requisition_id": pr.id, "state": "purchase", "notes": "Test terms",
            "order_line": [(0, 0, {"product_id": product.id, "name": product.name,
                                  "product_qty": 3, "product_uom": product.uom_po_id.id,
                                  "price_unit": 10})],
        })

    def _receipt(self, vendor_srn_number="VENDOR-SRN-001"):
        return self.env["service.receipt.note"].sudo().create({
            "purchase_id": self.order.id,
            "vendor_srn_number": vendor_srn_number,
            "line_ids": [(0, 0, {"purchase_line_id": self.order.order_line.id,
                                  "name": "Accepted service", "done_qty": 1})],
        }).sudo(False)

    def test_vendor_srn_number_is_required_for_approval_and_validation(self):
        receipt = self._receipt(vendor_srn_number=False)
        with self.assertRaisesRegex(UserError, "Vendor SRN Number"):
            receipt.with_user(self.manager).action_approve()

        receipt.with_user(self.manager).vendor_srn_number = "VENDOR-SRN-002"
        receipt.with_user(self.manager).action_approve()
        receipt.with_user(self.manager).vendor_srn_number = False
        with self.assertRaisesRegex(UserError, "Vendor SRN Number"):
            receipt.with_user(self.manager).action_validate()

    def test_only_department_manager_approves(self):
        receipt = self._receipt()
        self.assertEqual(receipt.department_manager_id, self.manager)
        with self.assertRaises(AccessError):
            receipt.with_user(self.outsider).action_approve()
        receipt.with_user(self.manager).action_approve()
        self.assertEqual(receipt.approval_state, "approved")

    def test_payment_request_requires_validation(self):
        receipt = self._receipt()
        with self.assertRaises(UserError):
            receipt.with_user(self.requester).action_request_payment()
