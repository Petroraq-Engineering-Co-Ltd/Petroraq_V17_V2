from uuid import uuid4

from odoo.tests.common import TransactionCase


class TestAnalyticDisplayName(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plan = cls.env["account.analytic.plan"].create({
            "name": "Accounting Display Test Plan",
            "analytic_plan_type": "project",
        })
        cls.code = "TEST-%s" % uuid4().hex[:10].upper()
        cls.analytic = cls.env["account.analytic.account"].create({
            "name": "Operations Cost Center",
            "code": cls.code,
            "plan_id": cls.plan.id,
        })

    def test_default_display_remains_code_only(self):
        self.assertEqual(self.analytic.display_name, self.code)
        self.assertEqual(self.analytic.name_get(), [(self.analytic.id, self.code)])

    def test_accounting_context_displays_code_and_name(self):
        analytic = self.analytic.with_context(show_analytic_name=True)
        expected = "%s - Operations Cost Center" % self.code

        self.assertEqual(analytic.display_name, expected)
        self.assertEqual(analytic.name_get(), [(analytic.id, expected)])

    def test_accounting_name_search_returns_code_and_name(self):
        result = self.env["account.analytic.account"].with_context(
            show_analytic_name=True
        ).name_search(
            name="Operations Cost Center",
            args=[("id", "=", self.analytic.id)],
            limit=1,
        )

        self.assertEqual(
            result,
            [(self.analytic.id, "%s - Operations Cost Center" % self.code)],
        )

    def test_project_name_fields_show_raw_analytic_name(self):
        project_name_fields = (
            ("account.move.line", "cs_project_id", "cs_project_name"),
            (
                "pr.account.bank.payment.line",
                "cs_project_id",
                "cs_project_name",
            ),
            (
                "pr.account.cash.payment.line",
                "cs_project_id",
                "cs_project_name",
            ),
            (
                "pr.account.bank.receipt.line",
                "cs_project_id",
                "cs_project_name",
            ),
            (
                "pr.account.cash.receipt.line",
                "cs_project_id",
                "cs_project_name",
            ),
            (
                "pr.payment.receipt",
                "debit_cs_project_id",
                "debit_cs_project_name",
            ),
            (
                "pr.payment.receipt",
                "credit_cs_project_id",
                "credit_cs_project_name",
            ),
            (
                "pr.transaction.payment",
                "debit_cs_project_id",
                "debit_cs_project_name",
            ),
            (
                "pr.transaction.payment",
                "credit_cs_project_id",
                "credit_cs_project_name",
            ),
        )

        for model_name, project_field, name_field in project_name_fields:
            with self.subTest(model=model_name, field=name_field):
                field = self.env[model_name]._fields[name_field]
                related = (
                    tuple(field.related.split("."))
                    if isinstance(field.related, str)
                    else tuple(field.related)
                )
                self.assertEqual(related, (project_field, "name"))

                record = self.env[model_name].new({
                    project_field: self.analytic.id,
                })
                self.assertEqual(record[name_field], self.analytic.name)
