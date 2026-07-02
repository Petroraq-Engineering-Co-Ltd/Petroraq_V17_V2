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
