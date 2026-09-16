from contextlib import contextmanager
from unittest.mock import patch

from odoo import Command
from odoo.tests.common import TransactionCase, tagged


REPORT_FIELDS = (
    "budget_remaining_amount", "approval_status",
    "workflow_billing_status", "workflow_payment_status",
)


@tagged("post_install", "-at_install")
class TestPurchaseOrderReporting(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Purchase = cls.env["purchase.order"]
        vendor = cls.env["res.partner"].create({"name": "PO Reporting Vendor", "supplier_rank": 1})
        cls.orders = cls.Purchase.create([
            {"name": "PO-REPORT-%s" % index, "partner_id": vendor.id}
            for index in range(4)
        ])

    @contextmanager
    def _live_values(self):
        rows = (
            (120.5, "approved", "billed", "paid"),
            (0.0, "pending_pm", "waiting", "no_bill"),
            (-10.0, "rejected", "partial", "partial"),
            (120.5, "approved", "billed", "not_paid"),
        )
        values = {order.id: dict(zip(REPORT_FIELDS, row)) for order, row in zip(self.orders, rows)}

        def budget(records):
            for rec in records:
                rec.budget_remaining_amount = values.get(rec.id, {}).get("budget_remaining_amount", 0.0)
                rec.budget_consumed_amount = 0.0
                rec.budget_count = 0

        def approval(records):
            for rec in records:
                rec.approval_status = values.get(rec.id, {}).get("approval_status", "not_submitted")

        def billing(records):
            for rec in records:
                rec.workflow_billing_status = values.get(rec.id, {}).get("workflow_billing_status", "nothing")
                rec.workflow_payment_status = values.get(rec.id, {}).get("workflow_payment_status", "no_bill")

        with patch.object(type(self.Purchase), "_compute_po_budget_info", budget), \
             patch.object(type(self.Purchase), "_compute_approval_status", approval), \
             patch.object(type(self.Purchase), "_compute_workflow_billing_status", billing):
            self.Purchase.invalidate_model(list(REPORT_FIELDS))
            yield values
            self.Purchase.invalidate_model(list(REPORT_FIELDS))

    def test_fields_are_searchable_and_sortable(self):
        metadata = self.Purchase.fields_get(list(REPORT_FIELDS), ["searchable", "sortable"])
        for name in REPORT_FIELDS:
            self.assertTrue(metadata[name]["searchable"], name)
            self.assertTrue(metadata[name]["sortable"], name)

    def test_live_sorting_applies_before_pagination_and_keeps_tie_breaks(self):
        with self._live_values() as values:
            for name in REPORT_FIELDS:
                for direction in ("asc", "desc"):
                    with self.subTest(field=name, direction=direction):
                        expected = sorted(
                            sorted(self.orders.ids, reverse=True),
                            key=lambda record_id: values[record_id][name],
                            reverse=direction == "desc",
                        )
                        actual = self.Purchase.search(
                            [("id", "in", self.orders.ids)],
                            order="%s %s, id desc" % (name, direction), offset=1, limit=2,
                        )
                        self.assertEqual(actual.ids, expected[1:3])

    def test_all_columns_filter_by_live_values(self):
        with self._live_values() as values:
            for name in REPORT_FIELDS:
                wanted = values[self.orders[0].id][name]
                for operator, argument in (("=", wanted), ("in", [wanted])):
                    actual = self.Purchase.search([
                        ("id", "in", self.orders.ids), (name, operator, argument),
                    ])
                    self.assertEqual(set(actual.ids), {record_id for record_id, row in values.items() if row[name] == wanted})
            exhausted = self.Purchase.search([
                ("id", "in", self.orders.ids), ("budget_remaining_amount", "<=", 0),
            ])
            self.assertEqual(set(exhausted.ids), set(self.orders[1:3].ids))
            unpaid = self.Purchase.search([
                ("id", "in", self.orders.ids), ("workflow_payment_status", "!=", "paid"),
            ])
            self.assertNotIn(self.orders[0], unpaid)

    def test_filters_and_sorting_pick_up_changed_computed_values(self):
        with self._live_values() as values:
            values[self.orders[1].id]["budget_remaining_amount"] = 500.0
            self.orders.invalidate_recordset(list(REPORT_FIELDS))
            result = self.Purchase.search([
                ("id", "in", self.orders.ids), ("budget_remaining_amount", ">", 200),
            ], order="budget_remaining_amount desc")
            self.assertEqual(result, self.orders[1])

    def test_report_operations_obey_record_rules(self):
        user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "PO Report Reader", "login": "po.report.reader.test",
            "groups_id": [Command.set(self.env.ref("purchase.group_purchase_manager").ids)],
            "company_id": self.env.company.id, "company_ids": [Command.set(self.env.company.ids)],
        })
        hidden = self.orders[0]
        self.env["ir.rule"].create({
            "name": "PO reporting test restriction",
            "model_id": self.env.ref("purchase.model_purchase_order").id,
            "domain_force": "[('id', '!=', %s)]" % hidden.id,
        })
        with self._live_values():
            accessible = self.Purchase.with_user(user)
            result = accessible.search([
                ("id", "in", self.orders.ids), ("budget_remaining_amount", ">", 0),
            ], order="budget_remaining_amount desc")
            self.assertNotIn(hidden.id, result.ids)
            self.assertIn(self.orders[3].id, result.ids)

    def test_empty_sorted_result_is_valid(self):
        self.assertFalse(self.Purchase.search([("id", "=", 0)], order="workflow_payment_status asc"))
