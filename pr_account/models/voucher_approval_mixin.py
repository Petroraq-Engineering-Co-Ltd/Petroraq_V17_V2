from odoo import _, api, models
from odoo.exceptions import UserError


class VoucherApprovalMixin(models.AbstractModel):
    _name = "pr.account.voucher.approval.mixin"
    _description = "Voucher approval stage routing"

    @api.model
    def _voucher_approval_states(self):
        user = self.env.user
        # Final approvers inherit the first-stage group for accounting access.
        # Give their explicit final role precedence for these four vouchers.
        if user.has_group("pr_account.custom_group_accounting_manager"):
            return ["finance_approve"]
        if (
            user.has_group("account.group_account_manager")
            or user.has_group("pr_account.custom_group_account_supervisor")
        ):
            return ["submit"]
        if user.has_group("base.group_system"):
            return ["submit", "finance_approve"]
        return []

    @api.model
    def _voucher_approval_domain(self):
        states = self._voucher_approval_states()
        if len(states) == 1:
            return [("state", "=", states[0])]
        return [("state", "in", states)] if states else [("id", "=", 0)]

    def _check_voucher_approval_stage(self, stage):
        if stage not in ("submit", "finance_approve") or any(
            voucher.state != stage for voucher in self
        ):
            raise UserError(_("The voucher is not awaiting this approval stage."))
        if not self.env.su and stage not in self._voucher_approval_states():
            raise UserError(_("You are not an approver for this voucher stage."))
        return True
