from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user


class TestServiceReceiptWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.requester = new_test_user(cls.env, login="srn_requester",
                                     groups="service_receipt_note.group_service_receipt_user")
        cls.qc = new_test_user(cls.env, login="srn_qc",
                               groups="service_receipt_note.group_service_receipt_qc")
        cls.manager = new_test_user(cls.env, login="srn_manager",
                                   groups="service_receipt_note.group_service_receipt_manager")
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

    def _receipt(self, vendor_srn_number="VENDOR-SRN-001", with_attachment=True):
        receipt = self.env["service.receipt.note"].sudo().create({
            "purchase_id": self.order.id,
            "vendor_srn_number": vendor_srn_number,
            "line_ids": [(0, 0, {"purchase_line_id": self.order.order_line.id,
                                  "name": "Accepted service", "done_qty": 1})],
        }).sudo(False)
        if with_attachment:
            attachment = self.env["ir.attachment"].create({
                "name": "test_service_evidence.pdf",
                "datas": "dGVzdA==",
            })
            receipt.sudo().attachment_ids = [(4, attachment.id)]
        return receipt

    def test_vendor_srn_number_is_required_for_approval_and_validation(self):
        receipt = self._receipt(vendor_srn_number=False)
        with self.assertRaisesRegex(UserError, "Vendor SRN Number"):
            receipt.with_user(self.qc).action_approve()

        receipt.with_user(self.requester).vendor_srn_number = "VENDOR-SRN-002"
        receipt.with_user(self.qc).action_approve()
        receipt.with_user(self.manager).vendor_srn_number = False
        with self.assertRaisesRegex(UserError, "Vendor SRN Number"):
            receipt.with_user(self.manager).action_validate()

    def test_role_permissions_receiver_qc_manager(self):
        receipt = self._receipt()
        self.assertEqual(receipt.department_manager_id, self.manager)

        # Receiver cannot approve or validate
        with self.assertRaises(AccessError):
            receipt.with_user(self.requester).action_approve()
        with self.assertRaises(AccessError):
            receipt.with_user(self.requester).action_validate()

        # Outsider cannot approve
        with self.assertRaises(AccessError):
            receipt.with_user(self.outsider).action_approve()

        # Manager cannot approve (QC does)
        with self.assertRaises(AccessError):
            receipt.with_user(self.manager).action_approve()

        # QC approves
        receipt.with_user(self.qc).action_approve()
        self.assertEqual(receipt.approval_state, "approved")

        # QC cannot validate
        with self.assertRaises(AccessError):
            receipt.with_user(self.qc).action_validate()

        # Department Manager validates
        receipt.with_user(self.manager).action_validate()
        self.assertEqual(receipt.state, "done")

    def test_attachment_required_before_approval(self):
        receipt = self._receipt(with_attachment=False)
        with self.assertRaisesRegex(UserError, "attach supporting documents in the Attachments tab"):
            receipt.with_user(self.qc).action_approve()

        attachment = self.env["ir.attachment"].create({
            "name": "invoice_evidence.pdf",
            "datas": "dGVzdA==",
        })
        receipt.sudo().attachment_ids = [(4, attachment.id)]
        receipt.with_user(self.qc).action_approve()
        self.assertEqual(receipt.approval_state, "approved")

    def test_auto_create_srn_on_po_confirm(self):
        pr = self.env["purchase.requisition"].create({"requested_user_id": self.requester.id})
        vendor = self.env["res.partner"].create({"name": "Auto SRN Test Vendor"})
        service_product = self.env["product.product"].create({
            "name": "Auto SRN Service",
            "detailed_type": "service",
        })
        order = self.env["purchase.order"].create({
            "partner_id": vendor.id,
            "requisition_id": pr.id,
            "notes": "Terms and conditions applied",
            "order_line": [(0, 0, {
                "product_id": service_product.id,
                "name": service_product.name,
                "product_qty": 5,
                "product_uom": service_product.uom_po_id.id,
                "price_unit": 20,
            })],
        })
        self.assertEqual(order.service_receipt_note_count, 0)
        order.button_confirm()
        self.assertEqual(order.state, "purchase")
        self.assertEqual(order.service_receipt_note_count, 1)
        srn = order.service_receipt_note_ids
        self.assertEqual(srn.state, "ready")
        self.assertEqual(srn.approval_state, "pending")
        self.assertEqual(len(srn.line_ids), 1)
        self.assertEqual(srn.line_ids.done_qty, 0.0)

    def test_no_srn_created_for_non_service_po(self):
        pr = self.env["purchase.requisition"].create({"requested_user_id": self.requester.id})
        vendor = self.env["res.partner"].create({"name": "Consu Test Vendor"})
        consu_product = self.env["product.product"].create({
            "name": "Physical Consumable",
            "detailed_type": "consu",
        })
        order = self.env["purchase.order"].create({
            "partner_id": vendor.id,
            "requisition_id": pr.id,
            "notes": "Terms and conditions applied",
            "order_line": [(0, 0, {
                "product_id": consu_product.id,
                "name": consu_product.name,
                "product_qty": 2,
                "product_uom": consu_product.uom_po_id.id,
                "price_unit": 50,
            })],
        })
        order.button_confirm()
        self.assertEqual(order.state, "purchase")
        self.assertEqual(order.service_receipt_note_count, 0)

    def test_payment_request_requires_validation(self):
        receipt = self._receipt()
        with self.assertRaises(UserError):
            receipt.with_user(self.requester).action_request_payment()

        receipt.with_user(self.qc).action_approve()
        receipt.with_user(self.manager).action_validate()
        receipt.with_user(self.requester).action_request_payment()
        self.assertTrue(receipt.payment_requested)
