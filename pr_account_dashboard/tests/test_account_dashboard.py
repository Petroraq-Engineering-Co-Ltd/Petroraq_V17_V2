from types import SimpleNamespace

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestAccountDashboard(TransactionCase):
    def test_posted_payment_voucher_uses_approved_journal_amount(self):
        voucher = SimpleNamespace(
            _name="pr.account.bank.payment",
            _fields={"approved_amount": True, "total_amount": True},
            state="posted",
            approved_amount=80.0,
            total_amount=100.0,
        )

        self.assertEqual(
            self.env["pr.account.dashboard"]._voucher_amount(voucher),
            80.0,
        )

    def test_parent_scope_includes_allowed_same_currency_branch(self):
        parent = self.env.company
        branch = self.env["res.company"].create({
            "name": "Accounting Dashboard Scope Branch",
            "parent_id": parent.id,
            "currency_id": parent.currency_id.id,
        })
        dashboard = self.env["pr.account.dashboard"].with_context(
            allowed_company_ids=[parent.id, branch.id],
        )

        self.assertEqual(
            set(dashboard._scope_companies(parent).ids),
            {parent.id, branch.id},
        )
        company_domain = dashboard._company_domain(parent)
        self.assertEqual(company_domain[0][:2], ("company_id", "in"))
        self.assertEqual(set(company_domain[0][2]), {parent.id, branch.id})
        self.assertIn(parent, dashboard._journal_companies(branch))

    def test_dashboard_contract_contains_custom_accounting_sections(self):
        today = fields.Date.context_today(self.env["pr.account.dashboard"])
        data = self.env["pr.account.dashboard"].get_dashboard_data({
            "company_id": self.env.company.id,
            "date_from": today.replace(month=1, day=1),
            "date_to": today,
        })

        self.assertEqual(data["filters"]["company_id"], self.env.company.id)
        self.assertTrue({
            "summary",
            "monthly",
            "aging",
            "vouchers",
            "approval_queue",
            "journals",
            "gl",
            "main_heads",
            "analytics",
            "vat",
            "top_customers",
            "top_vendors",
            "data_quality",
            "close_checklist",
            "exceptions",
            "cash_forecast",
            "voucher_sla",
            "vat_audit",
            "bank_health",
            "profitability",
            "recent_activity",
        }.issubset(data))
        self.assertEqual(
            {voucher["code"] for voucher in data["vouchers"]},
            {"BPV", "CPV", "BRV", "CRV"},
        )
        self.assertEqual(
            {dimension["key"] for dimension in data["analytics"]["dimensions"]},
            {"project", "department", "section", "employee", "asset"},
        )
        self.assertIn("projected_30", data["cash_forecast"])
        self.assertIn("checks", data["vat_audit"])
        self.assertIn("top_profit", data["profitability"])

    def test_invalid_date_range_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["pr.account.dashboard"].get_dashboard_data({
                "company_id": self.env.company.id,
                "date_from": "2026-07-31",
                "date_to": "2026-07-01",
            })
