from markupsafe import Markup, escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountPayment(models.Model):
    _inherit = "account.payment"

    received_bank_account_id = fields.Many2one(
        "res.partner.bank",
        string="Received In Bank Account",
        help="Company bank account where this payment was received.",
        index=True,
        copy=False,
    )

    pr_requires_vendor_payment_approval = fields.Boolean(
        string="Requires Vendor Payment Approval",
        copy=False,
        tracking=True,
        readonly=True,
    )
    pr_payment_approval_state = fields.Selection([
        ("draft", "Draft"),
        ("submit", "Submitted"),
        ("finance_approve", "Accounts Approval"),
        ("posted", "Finance Approval"),
        ("reject", "Rejected"),
        ("cancel", "Cancelled"),
    ], string="Payment Approval Status", default="draft", copy=False, tracking=True)
    pr_vendor_payment_reject_reason = fields.Text(
        string="Rejection Reason",
        copy=False,
        tracking=True,
        readonly=True,
    )
    pr_vendor_payment_source_line_ids = fields.Many2many(
        "account.move.line",
        "pr_account_vendor_payment_source_line_rel",
        "payment_id",
        "line_id",
        string="Vendor Bill Lines",
        copy=False,
        readonly=True,
    )
    pr_vendor_bill_ids = fields.Many2many(
        "account.move",
        string="Vendor Bills",
        compute="_compute_pr_vendor_bills",
    )
    pr_vendor_bill_count = fields.Integer(
        string="Vendor Bill Count",
        compute="_compute_pr_vendor_bills",
    )
    pr_is_current_vendor_payment_approver = fields.Boolean(
        string="Visible in My Vendor Payment Approvals",
        compute="_compute_pr_vendor_payment_current_user_flags",
        search="_search_pr_is_current_vendor_payment_approver",
    )
    pr_can_current_user_approve_vendor_payment_accounts = fields.Boolean(
        string="Can Approve Vendor Payment",
        compute="_compute_pr_vendor_payment_current_user_flags",
    )
    pr_can_current_user_final_approve_vendor_payment = fields.Boolean(
        string="Can Final Approve Vendor Payment",
        compute="_compute_pr_vendor_payment_current_user_flags",
    )
    pr_can_current_user_reject_vendor_payment = fields.Boolean(
        string="Can Reject Vendor Payment",
        compute="_compute_pr_vendor_payment_current_user_flags",
    )

    @api.depends("pr_vendor_payment_source_line_ids.move_id")
    def _compute_pr_vendor_bills(self):
        for payment in self:
            bills = payment.pr_vendor_payment_source_line_ids.mapped("move_id")
            payment.pr_vendor_bill_ids = bills
            payment.pr_vendor_bill_count = len(bills)

    def _pr_is_vendor_payment_approval_payment(self):
        self.ensure_one()
        return (
                self.pr_requires_vendor_payment_approval
                and self.payment_type == "outbound"
                and self.partner_type == "supplier"
        )

    def _pr_get_current_vendor_payment_approval_domain(self):
        base_domain = [
            ("pr_requires_vendor_payment_approval", "=", True),
            ("payment_type", "=", "outbound"),
            ("partner_type", "=", "supplier"),
            ("state", "=", "draft"),
        ]
        if self.env.user.has_group("pr_account.custom_group_accounting_manager"):
            return base_domain + [("pr_payment_approval_state", "=", "finance_approve")]
        if self.env.user.has_group("account.group_account_manager"):
            return base_domain + [("pr_payment_approval_state", "=", "submit")]
        return [("id", "=", 0)]

    def _search_pr_is_current_vendor_payment_approver(self, operator, value):
        if (operator in ("=", "==") and value) or (operator in ("!=", "<>") and not value):
            return self._pr_get_current_vendor_payment_approval_domain()
        return [("id", "=", 0)]

    @api.depends(
        "pr_requires_vendor_payment_approval",
        "payment_type",
        "partner_type",
        "state",
        "pr_payment_approval_state",
    )
    @api.depends_context("uid")
    def _compute_pr_vendor_payment_current_user_flags(self):
        is_final_approver = self.env.user.has_group("pr_account.custom_group_accounting_manager")
        is_accounts_approver = (
                self.env.user.has_group("account.group_account_manager")
                and not is_final_approver
        )

        for payment in self:
            is_approval_payment = (
                    payment.pr_requires_vendor_payment_approval
                    and payment.payment_type == "outbound"
                    and payment.partner_type == "supplier"
                    and payment.state == "draft"
            )
            can_accounts_approve = (
                    is_approval_payment
                    and is_accounts_approver
                    and payment.pr_payment_approval_state == "submit"
            )
            can_final_approve = (
                    is_approval_payment
                    and is_final_approver
                    and payment.pr_payment_approval_state == "finance_approve"
            )
            payment.pr_can_current_user_approve_vendor_payment_accounts = can_accounts_approve
            payment.pr_can_current_user_final_approve_vendor_payment = can_final_approve
            payment.pr_can_current_user_reject_vendor_payment = (
                    can_accounts_approve or can_final_approve
            )
            payment.pr_is_current_vendor_payment_approver = (
                    can_accounts_approve or can_final_approve
            )

    def action_pr_vendor_payment_submit(self):
        for payment in self:
            if not payment._pr_is_vendor_payment_approval_payment():
                continue
            if payment.state != "draft":
                raise UserError(_("Only draft payments can be submitted for approval."))
            payment.write({
                "pr_payment_approval_state": "submit",
                "pr_vendor_payment_reject_reason": False,
            })
            payment.message_post(body=_("Vendor payment submitted for approval."))
        return True

    def action_pr_vendor_payment_finance_approve(self):
        for payment in self:
            if not payment._pr_is_vendor_payment_approval_payment():
                continue
            if not payment.pr_can_current_user_approve_vendor_payment_accounts:
                raise UserError(_("You are not allowed to approve this vendor payment at the Accounts Approval step."))
            if payment.pr_payment_approval_state != "submit":
                raise UserError(_("Only submitted vendor payments can be approved."))
            payment.pr_payment_approval_state = "finance_approve"
            payment.message_post(body=_("Vendor payment approved by Accounts."))
        return True

    def action_pr_vendor_payment_reset_to_draft(self):
        for payment in self:
            if not payment._pr_is_vendor_payment_approval_payment():
                continue
            if payment.state != "draft":
                raise UserError(_("Only unposted vendor payments can be reset to draft."))
            payment.write({
                "pr_payment_approval_state": "draft",
                "pr_vendor_payment_reject_reason": False,
            })
            payment.message_post(body=_("Vendor payment approval reset to draft."))
        return True

    def action_pr_vendor_payment_reject(self):
        self.ensure_one()
        if not self._pr_is_vendor_payment_approval_payment():
            raise UserError(_("Only vendor payment approvals can be rejected."))
        if self.state != "draft":
            raise UserError(_("Only unposted vendor payments can be rejected."))
        if not self.pr_can_current_user_reject_vendor_payment:
            raise UserError(_("You are not allowed to reject this vendor payment at its current approval step."))
        if self.pr_payment_approval_state not in ("submit", "finance_approve"):
            raise UserError(_("Only submitted vendor payment approvals can be rejected."))

        return {
            "name": _("Reject Vendor Payment"),
            "type": "ir.actions.act_window",
            "res_model": "account.vendor.payment.reject.reason.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_payment_id": self.id,
            },
        }

    def action_pr_vendor_payment_final_approve(self):
        for payment in self:
            if not payment._pr_is_vendor_payment_approval_payment():
                continue
            if not payment.pr_can_current_user_final_approve_vendor_payment:
                raise UserError(_("You are not allowed to final approve this vendor payment."))
            if payment.state != "draft":
                raise UserError(_("Only draft vendor payments can be finally approved."))
            if payment.pr_payment_approval_state != "finance_approve":
                raise UserError(_("Vendor payment must be approved by Accounts before final approval."))
            if payment.pr_vendor_payment_source_line_ids and not payment.pr_vendor_payment_source_line_ids.filtered(
                    lambda line: not line.reconciled):
                raise UserError(_("The linked vendor bill lines are already reconciled."))

            payment.with_context(pr_vendor_payment_approval_post=True).action_post()
            payment._pr_reconcile_vendor_payment_source_lines()
            payment.pr_payment_approval_state = "posted"
            payment.message_post(body=_("Vendor payment finally approved, posted, and reconciled."))
        return True

    def _pr_reconcile_vendor_payment_source_lines(self):
        valid_account_types = self._get_valid_payment_account_types()
        for payment in self:
            if not payment.pr_vendor_payment_source_line_ids:
                continue

            source_lines = payment.pr_vendor_payment_source_line_ids.filtered(lambda line: not line.reconciled)
            payment_lines = payment.line_ids.filtered_domain([
                ("parent_state", "=", "posted"),
                ("account_type", "in", valid_account_types),
                ("reconciled", "=", False),
            ])
            for account in payment_lines.account_id:
                lines_to_reconcile = (payment_lines + source_lines).filtered_domain([
                    ("account_id", "=", account.id),
                    ("reconciled", "=", False),
                ])
                if len(lines_to_reconcile) > 1:
                    lines_to_reconcile.reconcile()

    def action_post(self):
        blocked_payments = self.filtered(
            lambda payment: payment._pr_is_vendor_payment_approval_payment()
                            and not self.env.context.get("pr_vendor_payment_approval_post")
        )
        if blocked_payments:
            raise UserError(_("Vendor payments registered from bills must be approved before posting."))
        return super().action_post()

    def action_cancel(self):
        result = super().action_cancel()
        self.filtered("pr_requires_vendor_payment_approval").write({
            "pr_payment_approval_state": "cancel",
        })
        return result

    def button_open_pr_vendor_bills(self):
        self.ensure_one()
        action = {
            "name": _("Vendor Bills"),
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "context": {"create": False},
        }
        if len(self.pr_vendor_bill_ids) == 1:
            action.update({
                "view_mode": "form",
                "res_id": self.pr_vendor_bill_ids.id,
            })
        else:
            action.update({
                "view_mode": "tree,form",
                "domain": [("id", "in", self.pr_vendor_bill_ids.ids)],
            })
        return action


class AccountVendorPaymentRejectReasonWizard(models.TransientModel):
    _name = "account.vendor.payment.reject.reason.wizard"
    _description = "Vendor Payment Rejection Reason"

    payment_id = fields.Many2one(
        "account.payment",
        string="Payment",
        required=True,
        readonly=True,
    )
    reason = fields.Text(
        string="Reason",
        required=True,
    )

    def action_confirm(self):
        self.ensure_one()
        payment = self.payment_id
        if not payment._pr_is_vendor_payment_approval_payment():
            raise UserError(_("Only vendor payment approvals can be rejected."))
        if payment.state != "draft":
            raise UserError(_("Only unposted vendor payments can be rejected."))
        if not payment.pr_can_current_user_reject_vendor_payment:
            raise UserError(_("You are not allowed to reject this vendor payment at its current approval step."))
        if payment.pr_payment_approval_state not in ("submit", "finance_approve"):
            raise UserError(_("Only submitted vendor payment approvals can be rejected."))

        payment.write({
            "pr_payment_approval_state": "reject",
            "pr_vendor_payment_reject_reason": self.reason,
        })
        payment.message_post(body=Markup(
            "<p>%s</p><p><strong>%s</strong> %s</p>"
        ) % (
                                      escape(_("Vendor payment rejected.")),
                                      escape(_("Reason:")),
                                      escape(self.reason),
                                  ))
        return {"type": "ir.actions.act_window_close"}
