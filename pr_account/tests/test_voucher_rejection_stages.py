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
        cls.supervisor = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Voucher Account Supervisor",
            "login": "voucher.supervisor.test",
            "groups_id": [(6, 0, [
                internal_group.id,
                cls.env.ref("pr_account.custom_group_account_supervisor").id,
            ])],
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

    def test_accounting_manager_can_only_reject_final_stage_for_all_vouchers(self):
        self.assertTrue(self.final_approver.has_group("account.group_account_manager"))
        for model_name in (
            "pr.account.bank.payment",
            "pr.account.cash.payment",
            "pr.account.bank.receipt",
            "pr.account.cash.receipt",
        ):
            submitted = self._voucher(model_name, self.final_approver, "submit")
            with self.assertRaises(UserError):
                submitted._check_reject_stage_access()
            final_stage = self._voucher(model_name, self.final_approver, "finance_approve")
            self.assertTrue(final_stage._check_reject_stage_access())

    def test_inherited_groups_do_not_merge_voucher_approval_queues(self):
        routing = self.env["pr.account.voucher.approval.mixin"]
        for user, expected in (
            (self.first_approver, [("state", "=", "submit")]),
            (self.supervisor, [("state", "=", "submit")]),
            (self.final_approver, [("state", "=", "finance_approve")]),
            (self.accountant, [("id", "=", 0)]),
            (self.non_accountant, [("id", "=", 0)]),
        ):
            with self.subTest(user=user.login):
                self.assertEqual(routing.with_user(user)._voucher_approval_domain(), expected)
                if "de.hr.approval.dashboard.service" in self.env:
                    dashboard = self.env["de.hr.approval.dashboard.service"].with_user(user)
                    self.assertEqual(dashboard._account_payment_approval_domain(), expected)
                for kind in ("bank.payment", "cash.payment", "bank.receipt", "cash.receipt"):
                    model = self.env["pr.account." + kind].with_user(user)
                    action_name = "action_workspace_" + kind.replace(".", "_") + "_approvals"
                    if hasattr(model, action_name):
                        self.assertEqual(getattr(model, action_name)()["domain"], expected)

    def test_voucher_approvals_require_separate_stages(self):
        for kind in ("bank.payment", "cash.payment", "bank.receipt", "cash.receipt"):
            model_name = "pr.account." + kind
            with self.subTest(model=model_name):
                submitted = self._voucher(model_name, self.first_approver, "submit")
                submitted.action_finance_approve()
                self.assertEqual(submitted.state, "finance_approve")
                self.assertEqual(submitted.accounting_manager_state, "finance_approve")
                with self.assertRaises(UserError):
                    submitted.action_finance_approve()
                with self.assertRaises(UserError):
                    submitted.action_post()
                final_user_submitted = self._voucher(model_name, self.final_approver, "submit")
                with self.assertRaises(UserError):
                    final_user_submitted.action_finance_approve()
                with self.assertRaises(UserError):
                    final_user_submitted.action_post()
                final_stage = self._voucher(model_name, self.final_approver, "finance_approve")
                self.assertTrue(final_stage._check_voucher_approval_stage("finance_approve"))
                for state in ("draft", "posted", "reject", "cancel"):
                    voucher = self._voucher(model_name, self.final_approver, state)
                    with self.assertRaises(UserError):
                        voucher.action_post()

    def test_final_approver_cannot_process_first_stage_payment_lines(self):
        for kind in ("bank", "cash"):
            model_name = "pr.account.%s.payment" % kind
            voucher = self._voucher(model_name, self.final_approver, "submit")
            for action_name in ("action_approve_remaining_lines", "action_reject_remaining_lines"):
                with self.subTest(model=model_name, action=action_name), self.assertRaises(UserError):
                    getattr(voucher, action_name)()
            line = self.env[model_name + ".line"].with_user(self.final_approver).new({
                "%s_payment_id" % kind: voucher,
                "state": "submit",
            })
            with self.assertRaises(UserError):
                line.action_line_approve()
            with self.assertRaises(UserError):
                line.action_line_reject()

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
