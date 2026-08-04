from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestVoucherRejectionStages(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        internal_group = cls.env.ref("base.group_user")
        first_approval_group = cls.env.ref("account.group_account_manager")
        final_approval_group = cls.env.ref("pr_account.custom_group_accounting_manager")
        cls.first_approver = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Voucher First Approver",
            "login": "voucher.first.approver.test",
            "email": "voucher.first@example.com",
            "groups_id": [(6, 0, [internal_group.id, first_approval_group.id])],
        })
        cls.final_approver = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Voucher Final Approver",
            "login": "voucher.final.approver.test",
            "email": "voucher.final@example.com",
            "groups_id": [(6, 0, [internal_group.id, final_approval_group.id])],
        })

    def _voucher(self, model_name, user, state):
        return self.env[model_name].with_user(user).new({"state": state})

    def test_first_approver_can_only_reject_submitted_bpv_and_cpv(self):
        for model_name in ("pr.account.bank.payment", "pr.account.cash.payment"):
            submitted = self._voucher(model_name, self.first_approver, "submit")
            self.assertTrue(submitted._check_reject_stage_access())
            final_stage = self._voucher(model_name, self.first_approver, "finance_approve")
            with self.assertRaises(UserError):
                final_stage._check_reject_stage_access()

    def test_accounting_manager_can_only_reject_final_stage_bpv_and_cpv(self):
        for model_name in ("pr.account.bank.payment", "pr.account.cash.payment"):
            submitted = self._voucher(model_name, self.final_approver, "submit")
            with self.assertRaises(UserError):
                submitted._check_reject_stage_access()
            final_stage = self._voucher(model_name, self.final_approver, "finance_approve")
            self.assertTrue(final_stage._check_reject_stage_access())
