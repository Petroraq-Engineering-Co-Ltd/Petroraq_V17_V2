import base64

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestWorkOrderBOQEstimationLimit(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({
            "name": "BOQ Estimation Limit Test Customer",
        })
        cls.product = cls.env["product.product"].create({
            "name": "BOQ Limit Test Product",
            "type": "consu",
        })
        cls.dummy_attachment = cls.env["ir.attachment"].create({
            "name": "dummy.txt",
            "datas": base64.b64encode(b"dummy"),
        })

    def _create_estimation_line(self, quantity=10.0, unit_cost=5.0):
        estimation = self.env["petroraq.estimation"].create({
            "partner_id": self.partner.id,
        })
        return estimation.line_ids.create({
            "estimation_id": estimation.id,
            "section_type": "material",
            "product_id": self.product.id,
            "quantity": quantity,
            "unit_cost": unit_cost,
        })

    def _create_work_order(self):
        return self.env["pr.work.order"].create({
            "scope_attachment_ids": [(6, 0, [self.dummy_attachment.id])],
            "boq_attachment_ids": [(6, 0, [self.dummy_attachment.id])],
        })

    def test_boq_line_can_match_estimation_line_exactly(self):
        estimation_line = self._create_estimation_line(quantity=10.0, unit_cost=5.0)
        work_order = self._create_work_order()
        boq_line = self.env["pr.work.order.boq"].create({
            "work_order_id": work_order.id,
            "name": "Test line",
            "estimation_line_id": estimation_line.id,
            "qty": 10.0,
            "unit_cost": 5.0,
        })
        self.assertEqual(boq_line.qty, 10.0)

    def test_boq_line_can_be_reduced_below_estimation_line(self):
        estimation_line = self._create_estimation_line(quantity=10.0, unit_cost=5.0)
        work_order = self._create_work_order()
        boq_line = self.env["pr.work.order.boq"].create({
            "work_order_id": work_order.id,
            "name": "Test line",
            "estimation_line_id": estimation_line.id,
            "qty": 10.0,
            "unit_cost": 5.0,
        })
        boq_line.write({"qty": 5.0, "unit_cost": 3.0})
        self.assertEqual(boq_line.qty, 5.0)
        self.assertEqual(boq_line.unit_cost, 3.0)

    def test_boq_line_qty_cannot_exceed_estimation_line(self):
        estimation_line = self._create_estimation_line(quantity=10.0, unit_cost=5.0)
        work_order = self._create_work_order()
        boq_line = self.env["pr.work.order.boq"].create({
            "work_order_id": work_order.id,
            "name": "Test line",
            "estimation_line_id": estimation_line.id,
            "qty": 10.0,
            "unit_cost": 5.0,
        })
        with self.assertRaises(ValidationError):
            boq_line.write({"qty": 11.0})

    def test_boq_line_unit_cost_cannot_exceed_estimation_line(self):
        estimation_line = self._create_estimation_line(quantity=10.0, unit_cost=5.0)
        work_order = self._create_work_order()
        boq_line = self.env["pr.work.order.boq"].create({
            "work_order_id": work_order.id,
            "name": "Test line",
            "estimation_line_id": estimation_line.id,
            "qty": 10.0,
            "unit_cost": 5.0,
        })
        with self.assertRaises(ValidationError):
            boq_line.write({"unit_cost": 6.0})

    def test_boq_line_without_estimation_line_is_unrestricted(self):
        work_order = self._create_work_order()
        boq_line = self.env["pr.work.order.boq"].create({
            "work_order_id": work_order.id,
            "name": "Test line",
            "qty": 100.0,
            "unit_cost": 999.0,
        })
        boq_line.write({"qty": 500.0, "unit_cost": 1500.0})
        self.assertEqual(boq_line.qty, 500.0)

    def test_boq_line_labor_section_compares_against_quantity_hours(self):
        estimation = self.env["petroraq.estimation"].create({
            "partner_id": self.partner.id,
        })
        estimation_line = estimation.line_ids.create({
            "estimation_id": estimation.id,
            "section_type": "labor",
            "product_id": self.product.id,
            "resource_count": 2.0,
            "days": 1.0,
            "hours_per_day": 8.0,
            "unit_cost": 5.0,
        })
        self.assertEqual(estimation_line.quantity_hours, 16.0)

        work_order = self._create_work_order()
        boq_line = self.env["pr.work.order.boq"].create({
            "work_order_id": work_order.id,
            "name": "Labor line",
            "estimation_line_id": estimation_line.id,
            "qty": 16.0,
            "unit_cost": 5.0,
        })
        with self.assertRaises(ValidationError):
            boq_line.write({"qty": 20.0})
