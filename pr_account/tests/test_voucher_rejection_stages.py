from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestVoucherRejectionStages(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        internal_group = cls.env.ref("base.group_user")
        first_approval_group = cls.env.ref("account.group_account_manager")
        accountant_group = cls.env.ref("account.group_account_user")
        final_approval_group = cls.env.ref("pr_account.custom_group_accounting_manager")
        cls.accountant = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Voucher Accountant",
            "login": "voucher.accountant.test",
            "email": "voucher.accountant@example.com",
            "groups_id": [(6, 0, [internal_group.id, accountant_group.id])],
        })
        cls.non_accountant = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Voucher Non Accountant",
            "login": "voucher.non.accountant.test",
            "email": "voucher.non.accountant@example.com",
            "groups_id": [(6, 0, [internal_group.id])],
        })
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

    def test_first_approver_can_only_reject_submitted_vouchers(self):
        for model_name in (
            "pr.account.bank.payment",
            "pr.account.cash.payment",
            "pr.account.bank.receipt",
            "pr.account.cash.receipt",
        ):
            submitted = self._voucher(model_name, self.first_approver, "submit")
            self.assertTrue(submitted._check_reject_stage_access())
            final_stage = self._voucher(model_name, self.first_approver, "finance_approve")
            with self.assertRaises(UserError):
                final_stage._check_reject_stage_access()

    def test_accounting_manager_can_reject_both_stages_for_all_vouchers(self):
        for model_name in (
            "pr.account.bank.payment",
            "pr.account.cash.payment",
            "pr.account.bank.receipt",
            "pr.account.cash.receipt",
        ):
            submitted = self._voucher(model_name, self.final_approver, "submit")
            self.assertTrue(submitted._check_reject_stage_access())
            final_stage = self._voucher(model_name, self.final_approver, "finance_approve")
            self.assertTrue(final_stage._check_reject_stage_access())

    def test_accountant_can_reset_all_rejected_vouchers(self):
        for model_name in (
            "pr.account.bank.payment",
            "pr.account.cash.payment",
            "pr.account.bank.receipt",
            "pr.account.cash.receipt",
        ):
            voucher = self._voucher(model_name, self.accountant, "reject")
            voucher.action_reset_rejected_to_draft()
            self.assertEqual(voucher.state, "draft")

    def test_non_accountant_cannot_reset_vouchers(self):
        for model_name in (
            "pr.account.bank.payment",
            "pr.account.cash.payment",
            "pr.account.bank.receipt",
            "pr.account.cash.receipt",
        ):
            voucher = self._voucher(model_name, self.non_accountant, "reject")
            with self.assertRaises(UserError):
                voucher.action_reset_rejected_to_draft()
