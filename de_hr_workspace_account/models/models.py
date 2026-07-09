# -*- coding: utf-8 -*-

from odoo import models


def _workspace_approval_domain(env):
    user = env.user
    if user.has_group("pr_account.custom_group_accounting_manager"):
        return [("state", "=", "finance_approve")]
    if (
        user.has_group("account.group_account_manager")
        or user.has_group("pr_account.custom_group_account_supervisor")
    ):
        return [("state", "=", "submit")]
    if user.has_group("base.group_system"):
        return [("state", "in", ["submit", "finance_approve"])]
    return [("id", "=", 0)]


def _workspace_action(env, xmlid):
    action = env["ir.actions.actions"]._for_xml_id(xmlid)
    action["domain"] = _workspace_approval_domain(env)
    return action


class PrAccountCashPayment(models.Model):
    _inherit = "pr.account.cash.payment"

    def action_workspace_cash_payment_approvals(self):
        return _workspace_action(
            self.env,
            "de_hr_workspace_account.pr_account_cash_payment_approvals_view_action",
        )


class PrAccountBankPayment(models.Model):
    _inherit = "pr.account.bank.payment"

    def action_workspace_bank_payment_approvals(self):
        return _workspace_action(
            self.env,
            "de_hr_workspace_account.pr_account_bank_payment_approvals_view_action",
        )
