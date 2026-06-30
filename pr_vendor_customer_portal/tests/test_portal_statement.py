from datetime import date

from odoo.tests.common import TransactionCase


class TestPortalStatement(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.journal = cls.env["account.journal"].search([
            ("company_id", "=", cls.company.id),
            ("type", "=", "general"),
        ], limit=1)
        if not cls.journal:
            cls.journal = cls.env["account.journal"].create({
                "name": "Portal Statement Test",
                "code": "PST",
                "type": "general",
                "company_id": cls.company.id,
            })

        cls.legacy_account = cls.env["account.account"].create({
            "name": "Shared Customer Legacy Ledger",
            "code": "PST10001",
            "account_type": "asset_current",
            "company_id": cls.company.id,
        })
        cls.unique_legacy_account = cls.env["account.account"].create({
            "name": "Unique Customer Legacy Ledger",
            "code": "PST10002",
            "account_type": "asset_current",
            "company_id": cls.company.id,
        })
        cls.receivable_account = cls.env["account.account"].create({
            "name": "Portal Statement Receivable",
            "code": "PST12001",
            "account_type": "asset_receivable",
            "reconcile": True,
            "company_id": cls.company.id,
        })
        cls.counterpart_account = cls.env["account.account"].create({
            "name": "Portal Statement Counterpart",
            "code": "PST49001",
            "account_type": "income",
            "company_id": cls.company.id,
        })
        cls.partner_a = cls.env["res.partner"].create({
            "name": "Portal Statement Partner A",
            "company_id": cls.company.id,
            "pr_ledger_account_id": cls.legacy_account.id,
        })
        cls.partner_b = cls.env["res.partner"].create({
            "name": "Portal Statement Partner B",
            "company_id": cls.company.id,
            "pr_ledger_account_id": cls.legacy_account.id,
        })
        cls.partner_unique = cls.env["res.partner"].create({
            "name": "Portal Statement Unique Partner",
            "company_id": cls.company.id,
            "pr_ledger_account_id": cls.unique_legacy_account.id,
        })

    def _post_move(self, account, amount, partner=False):
        move = self.env["account.move"].create({
            "date": date(2026, 1, 15),
            "journal_id": self.journal.id,
            "line_ids": [
                (0, 0, {
                    "name": "Statement test debit",
                    "account_id": account.id,
                    "partner_id": partner.id if partner else False,
                    "debit": amount,
                    "credit": 0.0,
                }),
                (0, 0, {
                    "name": "Statement test credit",
                    "account_id": self.counterpart_account.id,
                    "debit": 0.0,
                    "credit": amount,
                }),
            ],
        })
        move.action_post()
        return move

    def test_shared_mapped_account_never_exposes_other_partner(self):
        self._post_move(self.legacy_account, 100.0, self.partner_a)
        self._post_move(self.legacy_account, 200.0, self.partner_b)
        self._post_move(self.receivable_account, 50.0, self.partner_a)

        statement = self.partner_a._pr_get_portal_statement_data(
            self.company,
            date(2026, 1, 1),
            date(2026, 1, 31),
        )

        self.assertTrue(statement["shared_ledger_account"])
        self.assertEqual(statement["entry_count"], 2)
        self.assertEqual(statement["amount_receivable"], 150.0)
        self.assertEqual(len(statement["accounts"]), 1)
        self.assertEqual(statement["accounts"][0]["id"], self.legacy_account.id)
        self.assertNotIn(200.0, [
            entry["debit"]
            for account in statement["accounts"]
            for entry in account["entries"]
        ])

    def test_unique_mapped_account_includes_unpartnered_legacy_entry(self):
        self._post_move(self.unique_legacy_account, 75.0)

        statement = self.partner_unique._pr_get_portal_statement_data(
            self.company,
            date(2026, 1, 1),
            date(2026, 1, 31),
        )

        self.assertFalse(statement["shared_ledger_account"])
        self.assertEqual(statement["entry_count"], 1)
        self.assertEqual(statement["amount_receivable"], 75.0)
        self.assertEqual(len(statement["accounts"]), 1)
        self.assertEqual(statement["accounts"][0]["id"], self.unique_legacy_account.id)

    def test_parent_company_mapped_account_is_recognized(self):
        parent_company = self.env["res.company"].create({
            "name": "Portal Statement Parent Company",
        })
        self.company.parent_id = parent_company.id
        parent_account = self.env["account.account"].create({
            "name": "Parent Company Customer Ledger",
            "code": "PST10003",
            "account_type": "asset_current",
            "company_id": parent_company.id,
        })
        partner = self.env["res.partner"].create({
            "name": "Portal Statement Parent Account Partner",
            "company_id": self.company.id,
            "pr_ledger_account_id": parent_account.id,
        })

        statement = partner._pr_get_portal_statement_data(
            self.company,
            date(2026, 1, 1),
            date(2026, 1, 31),
        )

        self.assertEqual(statement["mapped_account_id"], parent_account.id)
        self.assertEqual(len(statement["accounts"]), 1)
        self.assertEqual(statement["accounts"][0]["id"], parent_account.id)
