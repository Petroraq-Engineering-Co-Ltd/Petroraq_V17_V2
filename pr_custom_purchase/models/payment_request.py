from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .purchase_requisition import _open_attachment_preview_action


class PurchaseRequisitionPaymentRequest(models.Model):
    _name = "purchase.requisition.payment.request"
    _description = "Purchase Requisition Payment Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(string="Request Number", default="New", readonly=True, copy=False, tracking=True)
    purchase_requisition_id = fields.Many2one(
        "purchase.requisition",
        string="Cash PR",
        required=True,
        readonly=True,
        copy=False,
        tracking=True,
    )
    requested_user_id = fields.Many2one(
        "res.users",
        string="Requested By",
        default=lambda self: self.env.user,
        readonly=True,
        tracking=True,
    )
    request_date = fields.Date(
        string="Request Date",
        default=fields.Date.context_today,
        readonly=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True,
        readonly=True,
    )
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id", readonly=True)
    department = fields.Char(string="Department", related="purchase_requisition_id.department", readonly=True)
    vendor_id = fields.Many2one("res.partner", string="Vendor", related="purchase_requisition_id.vendor_id", readonly=True)
    expense_bucket_id = fields.Many2one(
        "crossovered.budget",
        string="Budget",
        related="purchase_requisition_id.expense_bucket_id",
        readonly=True,
    )
    transfer_type = fields.Selection(
        [("cash", "Cash"), ("bank", "Bank Transfer")],
        string="Transfer Type",
        tracking=True,
        copy=False,
    )
    pay_from_account_id = fields.Many2one(
        "account.account",
        string="Pay From Account",
        tracking=True,
        copy=False,
        help="Cash or bank account credited by the generated CPV/BPV.",
    )
    line_ids = fields.One2many(
        "purchase.requisition.payment.request.line",
        "payment_request_id",
        string="Payment Lines",
        copy=True,
    )
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "purchase_requisition_payment_request_attachment_rel",
        "payment_request_id",
        "attachment_id",
        string="Attachments",
        copy=False,
        help="Supporting documents copied to the generated CPV or BPV.",
    )
    attachment_count = fields.Integer(string="Attachments", compute="_compute_attachment_count")
    total_amount = fields.Monetary(
        string="Total Amount",
        currency_field="currency_id",
        compute="_compute_total_amount",
        store=True,
    )
    state = fields.Selection(
        [
            ("requested", "Requested"),
            ("voucher_created", "Voucher Created"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="requested",
        tracking=True,
        copy=False,
    )
    cash_payment_id = fields.Many2one(
        "pr.account.cash.payment",
        string="CPV",
        readonly=True,
        copy=False,
        tracking=True,
    )
    bank_payment_id = fields.Many2one(
        "pr.account.bank.payment",
        string="BPV",
        readonly=True,
        copy=False,
        tracking=True,
    )

    _sql_constraints = [
        (
            "purchase_requisition_payment_request_unique",
            "unique(purchase_requisition_id)",
            "A payment request already exists for this Cash PR.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("purchase.requisition.payment.request")
                    or "New"
                )
        records = super().create(vals_list)
        for record in records:
            record.purchase_requisition_id.payment_request_id = record.id
        return records

    @api.depends("line_ids.amount")
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = sum(rec.line_ids.mapped("amount"))

    @api.depends("attachment_ids", "purchase_requisition_id.attachment_ids")
    def _compute_attachment_count(self):
        for rec in self:
            rec.attachment_count = len(rec._get_supporting_attachments())

    def action_view_attachments(self):
        self.ensure_one()
        return _open_attachment_preview_action(
            self,
            self._get_supporting_attachments(),
            _("Attachments - %s") % self.display_name,
        )

    @api.onchange("transfer_type")
    def _onchange_transfer_type(self):
        for rec in self:
            rec.pay_from_account_id = rec.purchase_requisition_id._get_default_cash_pr_payment_account(
                rec.transfer_type
            )

    def _check_account_user(self):
        user = self.env.user
        if not (
            user.has_group("account.group_account_invoice")
            or user.has_group("account.group_account_user")
            or user.has_group("account.group_account_manager")
        ):
            raise UserError(_("Only Accounts users can create payment vouchers."))

    def _get_supporting_attachments(self):
        self.ensure_one()
        chatter_attachments = self.env["ir.attachment"].sudo().search([
            ("res_model", "=", self._name),
            ("res_id", "=", self.id),
        ])
        return self.attachment_ids.sudo() | chatter_attachments

    def _copy_attachments_from_record(self, source):
        """Copy explicit and chatter documents into this payment request."""
        self.ensure_one()
        source.ensure_one()
        explicit_attachments = (
            source.attachment_ids.sudo()
            if "attachment_ids" in source._fields
            else self.env["ir.attachment"]
        )
        chatter_attachments = self.env["ir.attachment"].sudo().search([
            ("res_model", "=", source._name),
            ("res_id", "=", source.id),
        ])
        source_attachments = explicit_attachments | chatter_attachments
        existing_keys = {
            (attachment.name, attachment.checksum)
            for attachment in self._get_supporting_attachments()
        }
        copied_attachments = self.env["ir.attachment"]
        for attachment in source_attachments:
            if (attachment.name, attachment.checksum) in existing_keys:
                continue
            copied_attachments |= attachment.copy({
                "res_model": self._name,
                "res_id": self.id,
                "res_field": False,
            })
            existing_keys.add((attachment.name, attachment.checksum))
        if copied_attachments:
            self.sudo().write({
                "attachment_ids": [(4, attachment.id) for attachment in copied_attachments],
            })

    def _copy_attachments_to_record(self, target):
        """Copy all request attachments to the generated voucher chatter."""
        self.ensure_one()
        target.ensure_one()
        for attachment in self._get_supporting_attachments():
            attachment.copy({
                "res_model": target._name,
                "res_id": target.id,
                "res_field": False,
            })

    def _notify_accounts(self):
        users = self.env["res.users"]
        for xmlid in ("account.group_account_invoice", "account.group_account_user", "account.group_account_manager"):
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                users |= group.users
        users = users.filtered(lambda user: user.active)
        activity_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        for rec in self:
            for user in users:
                if activity_type:
                    rec.activity_schedule(
                        activity_type_id=activity_type.id,
                        user_id=user.id,
                        summary=_("Cash PR Payment Request"),
                        note=_("Please review payment request %s and create the CPV/BPV.") % rec.display_name,
                    )

    def _check_ready_for_voucher(self):
        for rec in self:
            pr = rec.purchase_requisition_id
            if rec.state == "cancelled":
                raise UserError(_("Cancelled payment requests cannot create vouchers."))
            if rec.cash_payment_id or rec.bank_payment_id or pr.cash_payment_id or pr.bank_payment_id:
                raise UserError(_("A payment voucher already exists for requisition %s.") % pr.name)
            if pr.pr_type != "cash":
                raise UserError(_("Payment requests are only for Cash PRs."))
            if pr.approval != "approved":
                raise UserError(_("Supervisor approval is required before creating a payment voucher."))
            if not rec.transfer_type:
                raise UserError(_("Please select Transfer Type: Cash or Bank Transfer."))
            if not rec.pay_from_account_id:
                raise UserError(_("Please select the Pay From Account."))
            if not rec.line_ids:
                raise UserError(_("This payment request has no lines."))
            missing_accounts = rec.line_ids.filtered(lambda line: not line.expense_account_id)
            if missing_accounts:
                raise UserError(_("Please select an Expense Account on every payment request line."))
            invalid_lines = rec.line_ids.filtered(lambda line: line.amount <= 0.0)
            if invalid_lines:
                raise UserError(_("Payment request lines must have a positive amount."))
            pr._check_cash_pr_budget()

    def _prepare_voucher_line_vals(self):
        self.ensure_one()
        line_vals = []
        for line in self.line_ids:
            amount = line.amount or 0.0
            if amount <= 0.0:
                continue
            analytic_distribution = (
                {str(line.cost_center_id.id): 100.0}
                if line.cost_center_id
                else False
            )
            cost_center_is_project = (
                line.cost_center_id
                and getattr(line.cost_center_id, "analytic_plan_type", False) == "project"
            )
            line_vals.append({
                "account_id": line.expense_account_id.id,
                "description": (
                    (line.description or "").strip()
                    or line.product_id.with_context(display_default_code=False).display_name
                ),
                "reference_number": self.purchase_requisition_id.name,
                "budget_cost_center_id": line.cost_center_id.id,
                "cs_project_id": line.cost_center_id.id if cost_center_is_project else False,
                "partner_id": self.vendor_id.id if self.vendor_id else False,
                "amount": amount,
                "analytic_distribution": analytic_distribution,
            })
        if not line_vals:
            raise UserError(_("Payment request has no positive amount lines to create a voucher."))
        return line_vals

    def action_create_payment_voucher(self):
        self._check_account_user()
        voucher = False
        voucher_model = False
        for rec in self:
            rec._check_ready_for_voucher()
            pr = rec.purchase_requisition_id
            line_vals = rec._prepare_voucher_line_vals()
            common_vals = {
                "account_id": rec.pay_from_account_id.id,
                "description": _("Generated from Cash PR payment request %s (%s)") % (rec.name, pr.name),
                "accounting_date": fields.Date.context_today(rec),
                "purchase_requisition_id": pr.id,
            }
            if rec.transfer_type == "cash":
                voucher_model = "pr.account.cash.payment"
                voucher = self.env[voucher_model].sudo().create({
                    **common_vals,
                    "cash_payment_line_ids": [(0, 0, vals) for vals in line_vals],
                })
                rec.cash_payment_id = voucher.id
                pr.cash_payment_id = voucher.id
            else:
                voucher_model = "pr.account.bank.payment"
                voucher = self.env[voucher_model].sudo().create({
                    **common_vals,
                    "bank_payment_line_ids": [(0, 0, vals) for vals in line_vals],
                })
                rec.bank_payment_id = voucher.id
                pr.bank_payment_id = voucher.id

            rec._copy_attachments_to_record(voucher)
            pr.write({
                "cash_pr_payment_method": rec.transfer_type,
                "cash_pr_payment_account_id": rec.pay_from_account_id.id,
                "status": "payment",
            })
            for line in rec.line_ids.filtered("source_line_id"):
                line.source_line_id.expense_account_id = line.expense_account_id.id
            rec.state = "voucher_created"
            rec.message_post(
                body=_("%s %s created in Draft.")
                % ("CPV" if rec.transfer_type == "cash" else "BPV", voucher.name),
                message_type="notification",
            )
            pr.message_post(
                body=_("Payment voucher %s created from payment request %s in Draft.")
                % (voucher.name, rec.name),
                message_type="notification",
            )

        return {
            "type": "ir.actions.act_window",
            "name": _("Payment Voucher"),
            "res_model": voucher_model,
            "res_id": voucher.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_payment_voucher(self):
        self.ensure_one()
        voucher = self.cash_payment_id or self.bank_payment_id
        if not voucher:
            raise UserError(_("No payment voucher has been created yet."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Payment Voucher"),
            "res_model": voucher._name,
            "res_id": voucher.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_cancel(self):
        for rec in self:
            if rec.cash_payment_id or rec.bank_payment_id:
                raise UserError(_("Cannot cancel a request after a voucher has been created."))
            rec.state = "cancelled"


class PurchaseRequisitionPaymentRequestLine(models.Model):
    _name = "purchase.requisition.payment.request.line"
    _description = "Purchase Requisition Payment Request Line"
    _order = "id"

    payment_request_id = fields.Many2one(
        "purchase.requisition.payment.request",
        required=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(related="payment_request_id.company_id", store=True, readonly=True)
    currency_id = fields.Many2one(related="payment_request_id.currency_id", readonly=True)
    source_line_id = fields.Many2one("purchase.requisition.line", string="PR Line", readonly=True)
    product_id = fields.Many2one("product.product", string="Product", readonly=True)
    description = fields.Text(string="Description", readonly=True)
    cost_center_id = fields.Many2one("account.analytic.account", string="Cost Center", readonly=True)
    quantity = fields.Float(string="Quantity", readonly=True)
    unit = fields.Char(string="Unit", readonly=True)
    unit_price = fields.Float(string="Unit Cost", readonly=True)
    amount = fields.Monetary(string="Amount", currency_field="currency_id", readonly=True)
    expense_account_id = fields.Many2one(
        "account.account",
        string="Expense Account",
        domain="[('deprecated', '=', False)]",
    )
    remarks = fields.Char(string="Remarks")

    @api.constrains("amount")
    def _check_positive_amount(self):
        for rec in self:
            if rec.amount <= 0.0:
                raise ValidationError(_("Payment request line amount must be greater than zero."))
