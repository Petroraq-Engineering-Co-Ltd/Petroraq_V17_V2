import logging
from odoo import _, models, fields, api
from odoo.exceptions import ValidationError
from odoo.exceptions import UserError
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)


class PurchaseRequisition(models.Model):
    _name = "purchase.requisition"
    _description = "Purchase Requisition"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name desc"

    name = fields.Char(
        string="PR Number", required=True, copy=False, readonly=True, default="New"
    )
    date_request = fields.Date(
        string="Date of Request", default=fields.Date.context_today
    )
    requested_by = fields.Char(string="Requested By")
    requested_user_id = fields.Many2one("res.users", string="Requested User", readonly=True)
    department = fields.Char(string="Department")
    supervisor = fields.Char(string="Supervisor")
    supervisor_partner_id = fields.Char(string="supervisor_partner_id")
    required_date = fields.Date(string="Required Date")
    priority = fields.Selection(
        [("low", "Low"), ("medium", "Medium"), ("high", "High"), ("urgent", "Urgent")],
        string="Priority",
        required=True,
        default="low",
    )
    budget_type = fields.Selection(
        [("opex", "Opex"), ("capex", "Capex")], string="Budget Type"
    )
    budget_details = fields.Char(string="Cost Center Code")
    cost_center_id = fields.Many2one("account.analytic.account", string="Cost Center")
    notes = fields.Text(string="Notes")
    approval = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending", "Pending Approval"),
            ("rejected", "Rejected"),
            ("approved", "Approved"),
        ],
        default="draft",
        string="Approval",
        tracking=True,
    )
    wo_variance_requires_approval = fields.Boolean(
        string="WO Variance Requires Approval",
        compute="_compute_wo_variance_requires_approval",
        store=False,
        help="Quantity/unit cost exceeds WO baseline but total requested amount remains within allowed WO amount.",
    )
    comments = fields.Text(string="Comments")
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "purchase_requisition_attachment_rel",
        "purchase_requisition_id",
        "attachment_id",
        string="Attachments",
        copy=False,
        help="Optional supporting documents copied to Cash PR payment requests and their CPV/BPV.",
    )
    vendor_id = fields.Many2one("res.partner", string="Preferred Vendor")
    total_excl_vat = fields.Float(
        string="Total Amount",
        compute="_compute_totals",
        store=True,
        currency_field="currency_id",
    )
    vat_amount = fields.Float(
        string="VAT (15%)",
        compute="_compute_totals",
        store=True,
        currency_field="currency_id",
    )
    total_incl_vat = fields.Float(
        string="Total Incl. VAT",
        compute="_compute_totals",
        store=True,
        currency_field="currency_id",
    )
    pr_type = fields.Selection(
        [
            ("pr", "PR"),
            ("cash", "Cash PR"),
        ],
        string="Type",
        default="pr",
    )
    is_supervisor = fields.Boolean(
        string="Can Approve",
        compute="_compute_is_supervisor",
    )
    status = fields.Selection(
        [
            ("pr", "PR"),
            ("rfq", "RFQ"),
            ("po", "PO"),
            ("payment", "Payment"),
            ("completed", "Completed"),
        ],
        default="pr",
        string="PR Status",
    )
    cash_pr_payment_method = fields.Selection(
        [("cash", "Cash"), ("bank", "Bank Transfer")],
        string="Transfer Type",
        tracking=True,
        copy=False,
    )
    cash_pr_payment_account_id = fields.Many2one(
        "account.account",
        string="Pay From Account",
        tracking=True,
        copy=False,
        help="Cash or bank account credited by the generated CPV/BPV.",
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
    payment_request_id = fields.Many2one(
        "purchase.requisition.payment.request",
        string="Payment Request",
        readonly=True,
        copy=False,
        tracking=True,
    )
    legacy_custom_pr_id = fields.Many2one(
        "custom.pr",
        string="Legacy Custom PR",
        readonly=True,
        copy=False,
        index=True,
        help="Original custom.pr record kept for audit after migrating to the unified requisition workflow.",
    )
    payment_request_state = fields.Selection(
        [
            ("not_requested", "Not Requested"),
            ("requested", "Requested"),
            ("voucher_created", "Voucher Created"),
            ("cancelled", "Cancelled"),
        ],
        string="Payment Request Status",
        compute="_compute_payment_request_state",
    )
    cash_pr_voucher_state = fields.Selection(
        [
            ("not_created", "Not Created"),
            ("draft", "Draft"),
            ("submit", "Submitted"),
            ("finance_approve", "Accounts Approval"),
            ("posted", "Posted"),
            ("cancel", "Cancelled"),
        ],
        string="Voucher Status",
        compute="_compute_cash_pr_voucher_state",
    )
    show_create_payment_voucher_button = fields.Boolean(
        compute="_compute_button_visibility",
        store=False,
    )
    show_request_payment_button = fields.Boolean(
        compute="_compute_button_visibility",
        store=False,
    )
    line_ids = fields.One2many(
        "purchase.requisition.line", "requisition_id", string="Line Items"
    )
    rfq_ids = fields.One2many("purchase.order", "requisition_id", string="RFQs")
    rfq_count = fields.Integer(string="RFQ Count", compute="_compute_rfq_metrics")
    rfq_sent_count = fields.Integer(string="RFQ Sent Count", compute="_compute_rfq_metrics")

    # Computed fields for button visibility logic
    show_create_rfq_button = fields.Boolean(
        compute="_compute_button_visibility", store=False
    )
    show_create_po_button = fields.Boolean(
        compute="_compute_button_visibility", store=False
    )
    show_request_budget_increase_button = fields.Boolean(
        compute="_compute_show_request_budget_increase_button", store=False
    )
    project_id = fields.Many2one("project.project", string="Project")
    expense_bucket_id = fields.Many2one(
        "crossovered.budget",
        string="Expense",
        domain="[('expense_type', '=', expense_type), ('state', 'in', ['validate', 'done']), ('pr_under_revision', '=', False)]",
    )
    allowed_cost_center_ids = fields.Many2many(
        "account.analytic.account",
        compute="_compute_allowed_cost_center_ids",
        store=False,
    )
    expense_scope = fields.Selection(
        [("department", "Department"), ("project", "Project"),("trading", "Trading")],
        string="Expense Scope",
    )
    expense_type = fields.Selection(
        [("opex", "Opex"), ("capex", "Capex")],
        string="Expense Type",
    )

    @api.depends("expense_bucket_id", "expense_bucket_id.crossovered_budget_line",
                 "expense_bucket_id.crossovered_budget_line.analytic_account_id")
    def _compute_allowed_cost_center_ids(self):
        for rec in self:
            rec.allowed_cost_center_ids = rec.expense_bucket_id.crossovered_budget_line.mapped("analytic_account_id")

    def _required_date_from_priority(self, priority):
        today = fields.Date.context_today(self)
        offsets = {
            "low": 30,
            "medium": 10,
            "high": 3,
            "urgent": 0,
        }
        return today + relativedelta(days=offsets.get(priority, 0))

    @api.onchange("priority")
    def _onchange_priority_set_required_date(self):
        for rec in self:
            if rec.priority:
                rec.required_date = rec._required_date_from_priority(rec.priority)

    @api.model
    def create(self, vals):
        if vals.get("priority"):
            vals["required_date"] = self._required_date_from_priority(vals["priority"])

        if not vals.get("requested_user_id"):
            vals["requested_user_id"] = self.env.user.id

        requester = self.env["res.users"].sudo().browse(vals.get("requested_user_id")) if vals.get(
            "requested_user_id") else self.env.user

        employee = self.env["hr.employee"].sudo().search([
            ("user_id", "=", requester.id)
        ], limit=1) if requester else False

        if not vals.get("requested_by"):
            vals["requested_by"] = employee.name if employee else (requester.name if requester else self.env.user.name)

        if not vals.get("department") and employee and employee.department_id:
            vals["department"] = employee.department_id.name

        supervisor_user = requester.supervisor_user_id if requester else False
        if supervisor_user:
            vals["supervisor"] = vals.get("supervisor") or supervisor_user.name
            vals["supervisor_partner_id"] = vals.get("supervisor_partner_id") or str(supervisor_user.partner_id.id)

        record = super().create(vals)
        if record.name == "New":
            if record.pr_type == "cash":
                record.name = (
                        self.env["ir.sequence"]
                        .sudo()
                        .next_by_code("cash.purchase.requisition")
                        or "CPR0001"
                )
            else:
                record.name = (
                        self.env["ir.sequence"].sudo().next_by_code("purchase.requisition")
                        or "PR0001"
                )
        return record

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        user = self.env.user
        employee = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)
        supervisor_user = user.supervisor_user_id

        if employee:
            res.update({
                "requested_by": employee.name,
                "requested_user_id": user.id,
                "department": employee.department_id.name if employee.department_id else False,
                "supervisor": supervisor_user.name if supervisor_user else (
                    employee.parent_id.name if employee.parent_id else False
                ),
                "supervisor_partner_id": (
                    str(supervisor_user.partner_id.id)
                    if supervisor_user and supervisor_user.partner_id
                    else (
                        str(employee.parent_id.user_id.partner_id.id)
                        if employee.parent_id and employee.parent_id.user_id and employee.parent_id.user_id.partner_id
                        else False
                    )
                ),
            })
        else:
            res.update({
                "requested_by": user.name,
                "requested_user_id": user.id,
                "supervisor": supervisor_user.name if supervisor_user else False,
                "supervisor_partner_id": (
                    str(supervisor_user.partner_id.id)
                    if supervisor_user and supervisor_user.partner_id
                    else False
                ),
            })

        return res

    # Checking when PR is approved
    def write(self, vals):
        if vals.get("priority"):
            vals["required_date"] = self._required_date_from_priority(vals["priority"])

        approval_changed = "approval" in vals
        res = super().write(vals)

        if approval_changed:
            for requisition in self:
                new_approval = vals.get("approval", requisition.approval)
                custom_pr = requisition.legacy_custom_pr_id or (
                    self.env["custom.pr"]
                    .sudo()
                    .search([("name", "=", requisition.name)], limit=1)
                )

                if custom_pr:
                    if not custom_pr.purchase_requisition_id:
                        custom_pr.sudo().purchase_requisition_id = requisition.id
                    # Sync approval → state
                    if new_approval == "approved" and custom_pr.approval != "approved":
                        custom_pr.write(
                            {"approval": "approved"}
                        )
                        self._notify_procurement_admins()

                    elif (
                            new_approval == "rejected" and custom_pr.approval != "rejected"
                    ):
                        custom_pr.write(
                            {"approval": "rejected"}
                        )

                    elif new_approval in ("draft", "pending") and custom_pr.approval != "pending":
                        custom_pr.write({"approval": "pending"})

        return res

    @api.depends("line_ids.total_price")
    def _compute_totals(self):
        for rec in self:
            total = sum(line.total_price for line in rec.line_ids)
            rec.total_excl_vat = total
            rec.vat_amount = total * 0.15
            rec.total_incl_vat = total + rec.vat_amount

    @api.depends("rfq_ids", "rfq_ids.state")
    def _compute_rfq_metrics(self):
        for rec in self:
            rec.rfq_count = len(rec.rfq_ids)
            rec.rfq_sent_count = len(rec.rfq_ids.filtered(lambda r: r.state == "sent"))

    @api.onchange("expense_type")
    def _onchange_expense_type(self):
        for rec in self:
            if rec.expense_bucket_id and rec.expense_bucket_id.expense_type != rec.expense_type:
                rec.expense_bucket_id = False

    @api.onchange("expense_bucket_id")
    def _onchange_expense_bucket_id(self):
        for rec in self:
            bucket = rec.expense_bucket_id
            if not bucket:
                continue
            rec.expense_scope = bucket.scope
            rec.expense_type = bucket.expense_type
            allowed = bucket.crossovered_budget_line.mapped("analytic_account_id")
            for line in rec.line_ids:
                if line.cost_center_id and line.cost_center_id not in allowed:
                    line.cost_center_id = False

    @api.depends(
        "pr_type",
        "approval",
        "status",
        "line_ids.quantity",
        "line_ids.description",
        "rfq_ids",
        "rfq_ids.state",
        "rfq_ids.order_line.product_qty",
        "cash_payment_id",
        "bank_payment_id",
        "payment_request_id",
        "payment_request_id.state",
    )
    def _compute_button_visibility(self):
        """Compute button visibility from approval state and remaining purchasable quantities."""
        for rec in self:
            has_remaining_qty = rec._has_remaining_product_quantities()
            rec.show_create_rfq_button = (
                    rec.pr_type != "cash"
                    and rec.approval == "approved"
                    and rec.status in ["pr", "rfq", "po"]
                    and has_remaining_qty
            )

            rec.show_create_po_button = False
            rec.show_create_payment_voucher_button = False
            rec.show_request_payment_button = (
                rec.pr_type == "cash"
                and rec.approval == "approved"
                and rec.status in ["pr", "rfq", "po", "payment"]
                and not rec.cash_payment_id
                and not rec.bank_payment_id
                and not rec.payment_request_id
                and has_remaining_qty
            )

    @api.depends("payment_request_id.state")
    def _compute_payment_request_state(self):
        for rec in self:
            rec.payment_request_state = rec.payment_request_id.state if rec.payment_request_id else "not_requested"

    @api.depends("cash_payment_id.state", "bank_payment_id.state")
    def _compute_cash_pr_voucher_state(self):
        for rec in self:
            voucher = rec.cash_payment_id or rec.bank_payment_id
            rec.cash_pr_voucher_state = voucher.sudo().state if voucher else "not_created"

    @api.depends(
        "line_ids.quantity",
        "line_ids.unit_price",
        "line_ids.cost_center_id",
        "line_ids.description",
    )
    def _compute_wo_variance_requires_approval(self):
        for rec in self:
            variance_found = False
            for line in rec.line_ids:
                caps = line._get_wo_product_caps()
                if not caps:
                    continue
                if line.quantity > caps["allowed_qty"] or line.unit_price > caps["allowed_unit_price"]:
                    variance_found = True
                    break
            rec.wo_variance_requires_approval = variance_found

    @api.depends(
        "line_ids.total_price",
        "line_ids.cost_center_id",
        "expense_bucket_id",
        "expense_bucket_id.budget_remaining_amount",
    )
    def _compute_show_request_budget_increase_button(self):
        for rec in self:
            remaining_by_cost_center = rec._get_selected_budget_remaining_by_cost_center()
            rec.show_request_budget_increase_button = any(
                item["amount"] > remaining_by_cost_center.get(item["cc"].id, item["cc"].budget_left)
                for item in rec._amount_by_cost_center().values()
            ) and bool(rec._get_selected_budget_requisition())

    def _budget_usage_date(self):
        self.ensure_one()
        return self.date_request or fields.Date.context_today(self)

    def _check_selected_budget_active(self):
        for rec in self.filtered("expense_bucket_id"):
            rec.expense_bucket_id.sudo()._check_active_for_date(rec._budget_usage_date())

    def _amount_by_cost_center(self, remaining_quantities=False):
        self.ensure_one()
        amount_by_cost_center = {}
        for line in self.line_ids:
            quantity = line.quantity
            if remaining_quantities is not False:
                quantity = remaining_quantities.get(line.id, 0.0)
                if quantity <= 1e-6:
                    continue
            line_cc = line.cost_center_id.sudo()
            if not line_cc:
                continue
            amount_by_cost_center.setdefault(line_cc.id, {"cc": line_cc, "amount": 0.0})
            amount_by_cost_center[line_cc.id]["amount"] += quantity * (line.unit_price or 0.0)
        return amount_by_cost_center

    def _current_budget_reservation_by_cost_center(self):
        """Return the approved PR amount still reserved before downstream spend takes over."""
        self.ensure_one()
        if self.approval != "approved":
            return {}

        voucher = self.cash_payment_id or self.bank_payment_id
        if self.pr_type == "cash" and voucher and voucher.sudo().state in ("submit", "finance_approve", "posted"):
            return {}

        if self.pr_type == "cash":
            return self._amount_by_cost_center()

        return self._amount_by_cost_center(
            remaining_quantities=self._get_remaining_requisition_line_quantities()
        )

    def _get_selected_budget_remaining_by_cost_center(self):
        self.ensure_one()
        if self.expense_bucket_id:
            remaining_by_cost_center = dict(self.expense_bucket_id.sudo()._get_remaining_by_cost_center())
            for item in self._current_budget_reservation_by_cost_center().values():
                cc = item["cc"]
                remaining_by_cost_center[cc.id] = remaining_by_cost_center.get(cc.id, cc.budget_left) + item["amount"]
            return remaining_by_cost_center
        return {}

    def _get_selected_budget_requisition(self):
        self.ensure_one()
        if not self.expense_bucket_id or "pr.budget.requisition" not in self.env:
            return False
        return self.env["pr.budget.requisition"].sudo().search([
            ("generated_budget_id", "=", self.expense_bucket_id.id),
        ], order="revision_number desc, id desc", limit=1)

    def _prepare_source_product_line_values(self):
        self.ensure_one()
        bucket = self.expense_bucket_id.sudo()
        if not bucket:
            return []

        def _remaining_quantity(cost_center, product, allowed_qty):
            if not cost_center or not product:
                return 0.0
            domain = [
                ("id", "not in", self.line_ids.ids),
                ("requisition_id.expense_bucket_id", "=", bucket.id),
                ("requisition_id.approval", "in", ("pending", "approved")),
                ("cost_center_id", "=", cost_center.id),
                ("description", "=", product.id),
            ]
            if isinstance(self.id, int):
                domain.append(("requisition_id", "!=", self.id))
            other_lines = self.env["purchase.requisition.line"].sudo().search(domain)
            remaining = (allowed_qty or 0.0) - sum(other_lines.mapped("quantity"))
            return remaining if remaining > 0.0 else 0.0

        grouped = {}

        def _add_line(cost_center, product, quantity, unit, unit_price):
            if not cost_center or not product or quantity <= 0.0:
                return
            unit_name = unit.name if unit else product.uom_id.name
            key = (cost_center.id, product.id, unit_name)
            data = grouped.setdefault(key, {
                "cost_center_id": cost_center.id,
                "description": product.id,
                "quantity": 0.0,
                "unit": unit_name,
                "unit_price": unit_price or product.standard_price or 0.0,
            })
            data["quantity"] += quantity
            if unit_price:
                data["unit_price"] = unit_price

        work_order = bucket.work_order_id.sudo() if "work_order_id" in bucket._fields else False
        sale_order = bucket.sale_order_id.sudo() if "sale_order_id" in bucket._fields else False

        if work_order:
            cost_centers_by_section = {
                cc.section_name: cc.analytic_account_id
                for cc in work_order.cost_center_ids.filtered("analytic_account_id")
            }
            for boq_line in work_order.boq_line_ids.sorted(key=lambda line: (line.sequence, line.id)):
                if boq_line.display_type in ("line_section", "line_note") or not boq_line.product_id:
                    continue
                cost_center = cost_centers_by_section.get(boq_line.section_name)
                remaining_qty = _remaining_quantity(cost_center, boq_line.product_id, boq_line.qty or 0.0)
                _add_line(
                    cost_center,
                    boq_line.product_id,
                    remaining_qty,
                    boq_line.uom_id or boq_line.product_id.uom_id,
                    boq_line.unit_cost or boq_line.product_id.standard_price,
                )
        elif sale_order:
            budget_cost_centers = bucket.crossovered_budget_line.mapped("analytic_account_id")
            default_cost_center = budget_cost_centers[:1]
            for sale_line in sale_order.order_line.sorted(key=lambda line: (line.sequence, line.id)):
                if sale_line.display_type or not sale_line.product_id:
                    continue
                distribution = sale_line.analytic_distribution or {}
                line_cc_ids = {int(key) for key in distribution.keys() if str(key).isdigit()}
                if line_cc_ids:
                    cost_centers = budget_cost_centers.filtered(lambda cc: cc.id in line_cc_ids)
                else:
                    cost_centers = default_cost_center if len(budget_cost_centers) == 1 else self.env["account.analytic.account"]
                for cost_center in cost_centers:
                    remaining_qty = _remaining_quantity(cost_center, sale_line.product_id, sale_line.product_uom_qty or 0.0)
                    unit_price = sale_line.price_unit or sale_line.product_id.standard_price
                    if "cost_price_unit" in sale_line._fields and sale_line.cost_price_unit:
                        unit_price = sale_line.cost_price_unit
                    _add_line(
                        cost_center,
                        sale_line.product_id,
                        remaining_qty,
                        sale_line.product_uom or sale_line.product_id.uom_id,
                        unit_price,
                    )

        existing_keys = {
            (line.cost_center_id.id, line.description.id, line.unit)
            for line in self.line_ids
        }
        return [vals for key, vals in grouped.items() if key not in existing_keys and vals["quantity"] > 0.0]

    def action_get_all_products(self):
        self.ensure_one()
        if not self.expense_bucket_id:
            raise ValidationError(_("Please select a budget before getting products."))
        if self.expense_bucket_id.state not in ("validate", "done"):
            raise ValidationError(_("Only validated budgets can be used."))
        self.expense_bucket_id._check_active_for_date(self._budget_usage_date())

        line_values = self._prepare_source_product_line_values()
        if not line_values:
            raise ValidationError(_("No remaining source product lines were found for the selected budget."))

        self.write({"line_ids": [(0, 0, vals) for vals in line_values]})
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }

    def _check_amounts_against_selected_budget(self, amount_by_cost_center, exception_cls=UserError):
        self.ensure_one()
        self._check_selected_budget_active()
        remaining_by_cost_center = self._get_selected_budget_remaining_by_cost_center()
        for item in amount_by_cost_center.values():
            cc = item["cc"]
            amount = item["amount"]
            remaining = remaining_by_cost_center.get(cc.id, cc.budget_left)
            if remaining < amount:
                raise exception_cls(
                    _("Insufficient budget for cost center %s. Remaining: %s, Required: %s")
                    % (cc.display_name, remaining, amount)
                )

    def _resolve_voucher_budget_cost_center(self, voucher_line, raise_if_missing=True):
        """Return the PR cost center that owns a generated voucher line's budget.

        Voucher analytic distributions can also contain project, employee,
        asset, department, and section dimensions. Those dimensions are valid
        for accounting analysis, but they must not each be treated as a budget
        cost center.
        """
        self.ensure_one()
        explicit_cost_center = (
            voucher_line.budget_cost_center_id
            if "budget_cost_center_id" in voucher_line._fields
            else False
        )
        if explicit_cost_center:
            return explicit_cost_center

        # Compatibility for vouchers generated before budget_cost_center_id
        # existed: identify the one selected-budget PR cost center present in
        # the analytic distribution.
        pr_cost_centers = self.line_ids.mapped("cost_center_id")
        if self.expense_bucket_id:
            allowed_cost_centers = self.expense_bucket_id.crossovered_budget_line.mapped(
                "analytic_account_id"
            )
            pr_cost_centers &= allowed_cost_centers

        distribution_ids = set()
        for analytic_key in (voucher_line.analytic_distribution or {}):
            for key_part in str(analytic_key).split(","):
                if key_part.strip().isdigit():
                    distribution_ids.add(int(key_part))
        matching_cost_centers = pr_cost_centers.filtered(
            lambda cost_center: cost_center.id in distribution_ids
        )
        if len(matching_cost_centers) == 1:
            return matching_cost_centers
        if len(pr_cost_centers) == 1:
            return pr_cost_centers

        if raise_if_missing:
            raise UserError(_(
                "Unable to identify the original PR budget cost center for voucher line '%s'. "
                "Please recreate the payment voucher from its payment request."
            ) % (voucher_line.description or _("Unnamed line")))
        return self.env["account.analytic.account"]

    def _get_voucher_budget_amounts(self, voucher_lines):
        """Group voucher amounts only by their originating PR cost centers."""
        self.ensure_one()
        amount_by_cost_center = {}
        for line in voucher_lines:
            cost_center = self._resolve_voucher_budget_cost_center(line)
            amount_by_cost_center.setdefault(cost_center.id, {
                "cc": cost_center,
                "amount": 0.0,
            })
            amount_by_cost_center[cost_center.id]["amount"] += line.amount or 0.0
        return amount_by_cost_center

    @api.constrains("expense_type", "expense_bucket_id", "date_request")
    def _check_expense_bucket_period(self):
        for rec in self:
            if rec.expense_bucket_id and rec.expense_type and rec.expense_bucket_id.expense_type != rec.expense_type:
                raise ValidationError(_("Expense bucket must match selected expense type."))
            if rec.expense_bucket_id:
                rec.expense_bucket_id.sudo()._check_active_for_date(rec._budget_usage_date())

    def action_request_budget_increase(self):
        self.ensure_one()
        line_amounts = self._amount_by_cost_center()
        remaining_by_cost_center = self._get_selected_budget_remaining_by_cost_center()

        exceeded_cost_centers = [
            item for item in line_amounts.values()
            if item["amount"] > remaining_by_cost_center.get(item["cc"].id, item["cc"].budget_left)
        ]

        if not exceeded_cost_centers:
            raise ValidationError(
                _("All cost center lines are within budget. Budget revision is not required.")
            )

        requisition = self._get_selected_budget_requisition()
        if not requisition:
            raise UserError(
                _("Selected budget was not created from Budget Requisition, so it cannot be revised here.")
            )

        if requisition.state == "approved":
            if not requisition._can_user_request_revision(self.env.user):
                raise UserError(
                    _("Budget is exceeded. Ask the budget requester, department manager, or procurement/admin "
                      "to revise Budget Requisition %s.")
                    % requisition.display_name
                )
            return requisition.with_user(self.env.user).action_request_revision()

        return {
            "type": "ir.actions.act_window",
            "name": _("Budget Revision"),
            "res_model": "pr.budget.requisition",
            "res_id": requisition.id,
            "view_mode": "form",
            "target": "current",
        }

    def _validate_for_submission(self):
        for rec in self:
            rec._check_selected_budget_active()
            if not rec.line_ids:
                raise UserError(_("You must add at least one line before submitting the Purchase Requisition."))
            if rec.total_excl_vat <= 0.0:
                raise UserError(_("Total requested amount must be greater than zero."))
            for line in rec.line_ids:
                if not line.cost_center_id:
                    raise UserError(_("Please set a cost center on every PR line."))
            rec.line_ids._check_work_order_product_limits()
            rec.line_ids._check_trading_sale_order_product_limits()
            rec._check_amounts_against_selected_budget(rec._amount_by_cost_center())

    def action_submit(self):
        for rec in self:
            if rec.approval != "draft":
                raise UserError(_("Only draft Purchase Requisitions can be submitted."))
            rec._validate_for_submission()
            rec.write({
                "approval": "pending",
                "rejection_reason": False,
            })
            rec._notify_supervisor()
            rec.message_post(body=_("Purchase Requisition submitted for approval."))
        return True

    def action_reset_to_draft(self):
        self.ensure_one()
        impact = self._get_reset_to_draft_impact()
        return {
            "type": "ir.actions.act_window",
            "name": _("Reset Purchase Requisition to Draft"),
            "res_model": "purchase.requisition.reset.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_requisition_id": self.id,
                "default_warning_message": impact["warning_message"],
            },
        }

    def _get_reset_to_draft_impact(self):
        """Validate reset eligibility and return records that may be deleted."""
        self.ensure_one()
        if self.approval not in ("rejected", "approved"):
            raise UserError(_(
                "Only rejected or approved Purchase Requisitions can be reset to draft."
            ))

        if self.pr_type == "cash":
            payment_requests = self.env[
                "purchase.requisition.payment.request"
            ].sudo().search([
                ("purchase_requisition_id", "=", self.id),
            ])
            cash_vouchers = self.env["pr.account.cash.payment"].sudo().search([
                ("purchase_requisition_id", "=", self.id),
            ])
            bank_vouchers = self.env["pr.account.bank.payment"].sudo().search([
                ("purchase_requisition_id", "=", self.id),
            ])
            cash_vouchers |= self.cash_payment_id.sudo().exists()
            bank_vouchers |= self.bank_payment_id.sudo().exists()
            cash_vouchers |= payment_requests.mapped("cash_payment_id").sudo().exists()
            bank_vouchers |= payment_requests.mapped("bank_payment_id").sudo().exists()

            if cash_vouchers or bank_vouchers:
                voucher_names = ", ".join(
                    cash_vouchers.mapped("display_name")
                    + bank_vouchers.mapped("display_name")
                )
                raise UserError(_(
                    "This Cash PR cannot be reset because CPV/BPV record(s) already exist: %s. "
                    "Cancel or reverse the downstream voucher process first."
                ) % (voucher_names or _("Unnamed voucher")))

            advanced_requests = payment_requests.filtered(
                lambda request: request.state != "requested"
            )
            if advanced_requests:
                request_states = ", ".join(
                    "%s (%s)" % (
                        request.display_name,
                        dict(request._fields["state"].selection).get(
                            request.state,
                            request.state,
                        ),
                    )
                    for request in advanced_requests
                )
                raise UserError(_(
                    "This Cash PR cannot be reset because its Payment Request is no longer "
                    "in the draft/requested stage: %s."
                ) % request_states)

            if payment_requests:
                warning_message = _(
                    "Payment Request %(requests)s is still in the draft/requested stage. "
                    "Confirming will permanently delete the Payment Request and its owned "
                    "attachments, then reset this Cash PR to Draft."
                ) % {"requests": ", ".join(payment_requests.mapped("display_name"))}
            else:
                warning_message = _(
                    "No Payment Request, CPV, or BPV exists. Confirming will reset this "
                    "Cash PR to Draft."
                )
            return {
                "payment_requests": payment_requests,
                "rfqs": self.env["purchase.order"],
                "warning_message": warning_message,
            }

        rfqs = self.env["purchase.order"].sudo().search([
            ("requisition_id", "=", self.id),
        ])
        non_draft_rfqs = rfqs.filtered(lambda order: order.state != "draft")
        if non_draft_rfqs:
            rfq_states = ", ".join(
                "%s (%s)" % (
                    order.display_name,
                    dict(order._fields["state"].selection).get(
                        order.state,
                        order.state,
                    ),
                )
                for order in non_draft_rfqs
            )
            raise UserError(_(
                "This Purchase Requisition cannot be reset because these RFQ/PO records "
                "are no longer in Draft: %s."
            ) % rfq_states)

        if rfqs:
            warning_message = _(
                "Draft RFQ record(s) %(rfqs)s will be permanently deleted before this "
                "Purchase Requisition is reset to Draft."
            ) % {"rfqs": ", ".join(rfqs.mapped("display_name"))}
        else:
            warning_message = _(
                "No RFQ or Purchase Order exists. Confirming will reset this Purchase "
                "Requisition to Draft."
            )
        return {
            "payment_requests": self.env["purchase.requisition.payment.request"],
            "rfqs": rfqs,
            "warning_message": warning_message,
        }

    def _confirm_reset_to_draft(self):
        self.ensure_one()
        impact = self._get_reset_to_draft_impact()
        deleted_documents = []

        for payment_request in impact["payment_requests"]:
            deleted_documents.append(payment_request.display_name)
            owned_attachments = payment_request._get_supporting_attachments().filtered(
                lambda attachment: (
                    attachment.res_model == payment_request._name
                    and attachment.res_id == payment_request.id
                )
            )
            payment_request.sudo().unlink()
            owned_attachments.sudo().exists().unlink()

        if impact["rfqs"]:
            deleted_documents.extend(impact["rfqs"].mapped("display_name"))
            impact["rfqs"].sudo().unlink()

        self.sudo().write({
            "approval": "draft",
            "status": "pr",
            "rejection_reason": False,
            "payment_request_id": False,
            "cash_payment_id": False,
            "bank_payment_id": False,
            "cash_pr_payment_method": False,
            "cash_pr_payment_account_id": False,
        })
        if deleted_documents:
            self.message_post(
                body=_(
                    "Purchase Requisition reset to Draft. Deleted draft downstream "
                    "record(s): %s"
                ) % ", ".join(deleted_documents)
            )
        else:
            self.message_post(body=_("Purchase Requisition reset to Draft."))
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_supervisor_approve(self):
        for rec in self:
            if rec.approval != "pending":
                continue
            rec._validate_for_submission()
            rec.write({"approval": "approved"})

    def action_supervisor_reject_wizard(self):
        self.ensure_one()
        if self.approval != "pending":
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Reject Purchase Requisition"),
            "res_model": "purchase.requisition.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_requisition_id": self.id},
        }

    # Send approval activity only after the requester explicitly submits the PR.
    def _notify_supervisor(self):
        for rec in self:
            try:
                requester = rec.requested_user_id.sudo() if rec.requested_user_id else self.env.user.sudo()
                supervisor_user = requester.supervisor_user_id if requester else False

                if not supervisor_user:
                    _logger.warning("No supervisor configured for requester on PR=%s", rec.name)
                    continue

                rec.activity_schedule(
                    activity_type_id=self.env.ref("mail.mail_activity_data_todo").id,
                    user_id=supervisor_user.id,
                    summary="Review New PR",
                    note=_("Please review the new Purchase Requisition: <b>%s</b>.") % rec.name,
                )
                if supervisor_user.email:
                    self.env["mail.mail"].sudo().create({
                        "email_from": "noreply@petroraq.com",
                        "email_to": supervisor_user.email,
                        "subject": _("Purchase Requisition %s waiting for approval") % rec.name,
                        "body_html": _(
                            "<p>Dear Approver,</p><p>Please review Purchase Requisition <b>%s</b>.</p>") % rec.name,
                    }).send()
                _logger.info("Activity created for supervisor %s on PR=%s", supervisor_user.login, rec.name)

            except Exception as e:
                _logger.error("Error creating supervisor activity for PR=%s: %s", rec.name, str(e))

    # sending approved PR activity to procurment admin
    def _notify_procurement_admins(self):
        for pr in self:
            try:
                group = self.env.ref(
                    "pr_custom_purchase.procurement_admin"
                )  # 🔁 Replace
                procurement_users = (
                    self.env["res.users"].sudo().search([("groups_id", "in", group.id)])
                )
                activity_type_id = self.env.ref("mail.mail_activity_data_todo").id

                for user in procurement_users:
                    pr.activity_schedule(
                        activity_type_id=activity_type_id,
                        user_id=user.id,
                        summary="New Approved PR",
                        note=_(
                            "A new Purchase Requisition <b>%s</b> has been approved."
                        )
                             % pr.name,
                    )
                    if user.email:
                        self.env["mail.mail"].sudo().create({
                            "email_from": "noreply@petroraq.com",
                            "email_to": user.email,
                            "subject": _("Approved Purchase Requisition %s") % pr.name,
                            "body_html": _(
                                "<p>Purchase Requisition <b>%s</b> is approved and ready for processing.</p>") % pr.name,
                        }).send()

                requester_email = pr.requested_user_id.email if pr.requested_user_id else False
                if requester_email:
                    self.env["mail.mail"].sudo().create({
                        "email_from": "noreply@petroraq.com",
                        "email_to": requester_email,
                        "subject": _("Your Purchase Requisition %s is approved") % pr.name,
                        "body_html": _(
                            "<p>Your Purchase Requisition <b>%s</b> has been approved and sent to Procurement.</p>") % pr.name,
                    }).send()

                _logger.info(
                    "Activities scheduled for Procurement Admins on PR=%s", pr.name
                )

            except Exception as e:
                _logger.error(
                    "Error creating procurement admin activities for PR=%s: %s",
                    pr.name,
                    str(e),
                )

    # create RFQ PR
    # def action_create_rfq(self):
    #     """Create RFQ (purchase.order) from this PR and populate Custom Lines tab."""
    #     PurchaseOrder = self.env["purchase.order"]

    #     for pr in self:
    #         if not pr.line_ids:
    #             raise UserError(_("This PR has no line items to create an RFQ."))

    #         matched_project = self.env["project.project"].search(
    #             [
    #                 ("budget_type", "=", pr.budget_type),
    #                 ("budget_code", "=", pr.budget_details),
    #             ],
    #             limit=1,
    #         )

    #         # Create RFQ without normal order_line
    #         rfq_vals = {
    #             "origin": pr.name,
    #             "partner_id": pr.vendor_id.id if pr.vendor_id else False,
    #             'pr_name': self.name,
    #             "date_planned": pr.required_date,
    #             "budget_type": pr.budget_type,
    #             "budget_code": pr.budget_details,
    #             "order_line": [],  # Populate custom tab instead
    #             "date_request": pr.date_request,
    #             "requested_by": pr.requested_by,
    #             "department": pr.department,
    #             "supervisor": pr.supervisor,
    #             "supervisor_partner_id": pr.supervisor_partner_id,
    #         }

    #         # Fill custom_line_ids from PR lines
    #         for line in pr.line_ids:
    #             line_vals = (
    #                 0,
    #                 0,
    #                 {
    #                     "name": line.description,
    #                     "quantity": line.quantity,
    #                     "type": line.type,
    #                     "unit": line.unit,  # ✅ Added this
    #                     "price_unit": line.unit_price,
    #                 },
    #             )
    #             rfq_vals["custom_line_ids"].append(line_vals)

    #         # Create RFQ
    #         rfq = PurchaseOrder.sudo().create(rfq_vals)

    #         # sequence for Rfq
    #         if rfq.state == "draft":
    #             rfq.name = (
    #                 self.env["ir.sequence"].next_by_code("purchase.order.rfq")
    #                 or "RFQ0001"
    #             )

    #         # Update PR status
    #         pr.status = "rfq"

    #         # Log in PR chatter
    #         pr.message_post(
    #             body=_("RFQ %s created from this PR and populated in Custom Lines tab.")
    #             % rfq.name,
    #             message_type="notification",
    #         )

    #     return {
    #         "type": "ir.actions.act_window",
    #         "name": _("Purchase Order"),
    #         "res_model": "purchase.order",
    #         "res_id": rfq.id,
    #         "view_mode": "form",
    #         "target": "current",
    #     }
    def action_view_related_rfqs(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": "RFQs",
            "res_model": "purchase.order",
            "view_mode": "tree,form",
            "domain": [("requisition_id", "=", self.id)],
            "context": {
                "default_requisition_id": self.id,
                "default_pr_name": self.name,
            },
        }

    def _ensure_no_purchase_order_exists(self):
        self.ensure_one()
        existing_po = self.env["purchase.order"].sudo().search_count([
            ("requisition_id", "=", self.id),
            ("state", "in", ["pending", "purchase", "done"]),
        ])
        if existing_po:
            raise UserError(_("A Purchase Order already exists for requisition %s.") % self.name)

    def _get_requested_product_quantities(self):
        self.ensure_one()
        quantities = {}
        for line in self.line_ids.filtered("description"):
            quantities.setdefault(line.description.id, 0.0)
            quantities[line.description.id] += line.quantity or 0.0
        return quantities

    def _get_purchased_requisition_line_quantities(self):
        self.ensure_one()
        requisition_lines = self.line_ids.filtered("description")
        quantities = {line.id: 0.0 for line in requisition_lines}
        po_lines = self.env["purchase.order.line"].sudo().search([
            ("order_id.requisition_id", "=", self.id),
            ("order_id.state", "in", ["pending", "purchase", "done"]),
            ("product_id", "!=", False),
        ])

        for line in po_lines:
            requisition_line = line.custom_requisition_line_id
            if requisition_line and requisition_line.requisition_id.id == self.id:
                quantities.setdefault(requisition_line.id, 0.0)
                quantities[requisition_line.id] += line.product_qty or 0.0
                continue

            distribution = line.analytic_distribution or {}
            distribution_cc_ids = {int(key) for key in distribution.keys() if str(key).isdigit()}
            candidates = requisition_lines.filtered(
                lambda req_line: req_line.description.id == line.product_id.id
                and (
                    not distribution_cc_ids
                    or req_line.cost_center_id.id in distribution_cc_ids
                )
            ).sorted(key=lambda req_line: req_line.id)

            qty_to_apply = line.product_qty or 0.0
            for req_line in candidates:
                if qty_to_apply <= 1e-6:
                    break
                remaining_capacity = max((req_line.quantity or 0.0) - quantities.get(req_line.id, 0.0), 0.0)
                if remaining_capacity <= 1e-6:
                    continue
                applied_qty = min(qty_to_apply, remaining_capacity)
                quantities[req_line.id] = quantities.get(req_line.id, 0.0) + applied_qty
                qty_to_apply -= applied_qty

        return quantities

    def _get_purchased_product_quantities(self):
        self.ensure_one()
        purchased_by_line = self._get_purchased_requisition_line_quantities()
        quantities = {}
        for line in self.line_ids.filtered("description"):
            quantities.setdefault(line.description.id, 0.0)
            quantities[line.description.id] += purchased_by_line.get(line.id, 0.0)
        return quantities

    def _get_remaining_requisition_line_quantities(self):
        self.ensure_one()
        purchased_quantities = self._get_purchased_requisition_line_quantities()
        return {
            line.id: max((line.quantity or 0.0) - purchased_quantities.get(line.id, 0.0), 0.0)
            for line in self.line_ids.filtered("description")
        }

    def _get_remaining_product_quantities(self):
        self.ensure_one()
        remaining_by_line = self._get_remaining_requisition_line_quantities()
        quantities = {}
        for line in self.line_ids.filtered("description"):
            quantities.setdefault(line.description.id, 0.0)
            quantities[line.description.id] += remaining_by_line.get(line.id, 0.0)
        return quantities

    def _has_remaining_product_quantities(self):
        self.ensure_one()
        return any(quantity > 1e-6 for quantity in self._get_remaining_requisition_line_quantities().values())

    @api.onchange("cash_pr_payment_method")
    def _onchange_cash_pr_payment_method(self):
        for rec in self:
            if rec.pr_type == "cash":
                rec.cash_pr_payment_account_id = rec._get_default_cash_pr_payment_account(
                    rec.cash_pr_payment_method
                )

    def _get_default_cash_pr_payment_account(self, payment_method=False):
        self.ensure_one()
        if payment_method == "cash":
            domain = [
                ("main_head", "=", "assets"),
                ("assets_main_head", "=", "asset_current"),
                ("current_assets_category", "=", "cash_equivalents"),
            ]
        elif payment_method == "bank":
            domain = [
                ("main_head", "=", "assets"),
                ("assets_main_head", "=", "asset_current"),
                ("current_assets_category", "=", "banks"),
            ]
        else:
            return self.env["account.account"]
        return self.env["account.account"].sudo().search(domain, limit=1)

    def _check_cash_pr_account_user(self):
        user = self.env.user
        if not (
            user.has_group("account.group_account_invoice")
            or user.has_group("account.group_account_user")
            or user.has_group("account.group_account_manager")
        ):
            raise UserError(_("Only Accounts users can create Cash PR payment vouchers."))

    def _check_cash_pr_budget(self):
        for pr in self:
            for line in pr.line_ids:
                if not line.cost_center_id:
                    raise UserError(_("Please set a cost center on every PR line."))
            amount_by_cost_center = pr._amount_by_cost_center()
            for item in amount_by_cost_center.values():
                amount = item["amount"]
                if amount <= 0.0:
                    raise UserError(_("Cash PR lines must have a positive amount."))
            pr._check_amounts_against_selected_budget(amount_by_cost_center)

    def _get_cash_pr_expense_account(self, line):
        self.ensure_one()
        if not line.expense_account_id:
            raise UserError(
                _("Please select the line account for %s before creating the payment voucher.")
                % (line.description.display_name or _("this Cash PR line"))
            )
        return line.expense_account_id

    def _prepare_cash_pr_voucher_line_vals(self):
        self.ensure_one()
        line_vals = []
        for line in self.line_ids:
            amount = line.total_price or 0.0
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
                "account_id": self._get_cash_pr_expense_account(line).id,
                "description": line._get_document_line_description(),
                "reference_number": self.name,
                "budget_cost_center_id": line.cost_center_id.id,
                "cs_project_id": line.cost_center_id.id if cost_center_is_project else False,
                "partner_id": self.vendor_id.id if self.vendor_id else False,
                "amount": amount,
                "analytic_distribution": analytic_distribution,
            })
        if not line_vals:
            raise UserError(_("Cash PR has no positive amount lines to create a voucher."))
        return line_vals

    def _prepare_payment_request_line_vals(self):
        self.ensure_one()
        line_vals = []
        for line in self.line_ids:
            amount = line.total_price or 0.0
            if amount <= 0.0:
                continue
            line_vals.append((0, 0, {
                "source_line_id": line.id,
                "product_id": line.description.id,
                "description": line._get_document_line_description(),
                "cost_center_id": line.cost_center_id.id,
                "quantity": line.quantity,
                "unit": line.unit,
                "unit_price": line.unit_price,
                "amount": amount,
                "expense_account_id": line.expense_account_id.id,
            }))
        if not line_vals:
            raise UserError(_("Cash PR has no positive amount lines to request payment."))
        return line_vals

    def action_request_cash_pr_payment(self):
        PaymentRequest = self.env["purchase.requisition.payment.request"]
        request = False
        for pr in self:
            if pr.pr_type != "cash":
                raise UserError(_("Payment requests are only for Cash PRs."))
            if pr.approval != "approved":
                raise UserError(_("Supervisor approval is required before requesting payment."))
            if pr.cash_payment_id or pr.bank_payment_id:
                raise UserError(_("A payment voucher already exists for requisition %s.") % pr.name)
            if pr.payment_request_id:
                if pr.payment_request_id.state == "cancelled":
                    pr.payment_request_id.state = "requested"
                request = pr.payment_request_id
                continue
            if not pr.line_ids:
                raise UserError(_("This Cash PR has no line items."))

            pr._check_cash_pr_budget()
            request = PaymentRequest.create({
                "purchase_requisition_id": pr.id,
                "requested_user_id": self.env.user.id,
                "company_id": pr.company_id.id if "company_id" in pr._fields and pr.company_id else self.env.company.id,
                "line_ids": pr._prepare_payment_request_line_vals(),
            })
            request._copy_attachments_from_record(pr)
            pr.status = "payment"
            request._notify_accounts()
            pr.message_post(
                body=_("Payment request %s created and sent to Accounts.") % request.name,
                message_type="notification",
            )

        return {
            "type": "ir.actions.act_window",
            "name": _("Payment Request"),
            "res_model": "purchase.requisition.payment.request",
            "res_id": request.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_create_cash_pr_payment_voucher(self):
        self._check_cash_pr_account_user()
        voucher = False
        voucher_model = False

        for pr in self:
            if pr.pr_type != "cash":
                raise UserError(_("Payment voucher creation is only for Cash PRs."))
            if pr.approval != "approved":
                raise UserError(_("Supervisor approval is required before creating a payment voucher."))
            if pr.cash_payment_id or pr.bank_payment_id:
                raise UserError(_("A payment voucher already exists for requisition %s.") % pr.name)
            if not pr.line_ids:
                raise UserError(_("This Cash PR has no line items."))
            if not pr.cash_pr_payment_method:
                raise UserError(_("Please select Transfer Type: Cash or Bank Transfer."))

            payment_account = (
                pr.cash_pr_payment_account_id
                or pr._get_default_cash_pr_payment_account(pr.cash_pr_payment_method)
            )
            if not payment_account:
                raise UserError(_("Please select the Pay From Account for this Cash PR."))

            pr._check_cash_pr_budget()
            line_vals = pr._prepare_cash_pr_voucher_line_vals()
            common_vals = {
                "account_id": payment_account.id,
                "description": _("Generated from Cash PR %s") % pr.name,
                "accounting_date": fields.Date.context_today(pr),
                "purchase_requisition_id": pr.id,
            }

            if pr.cash_pr_payment_method == "cash":
                voucher_model = "pr.account.cash.payment"
                voucher = self.env[voucher_model].sudo().create({
                    **common_vals,
                    "cash_payment_line_ids": [(0, 0, vals) for vals in line_vals],
                })
                pr.cash_payment_id = voucher.id
            else:
                voucher_model = "pr.account.bank.payment"
                voucher = self.env[voucher_model].sudo().create({
                    **common_vals,
                    "bank_payment_line_ids": [(0, 0, vals) for vals in line_vals],
                })
                pr.bank_payment_id = voucher.id

            pr.status = "payment"
            pr.message_post(
                body=_("%s %s created from this Cash PR in Draft.")
                % ("CPV" if pr.cash_pr_payment_method == "cash" else "BPV", voucher.name),
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

    def action_open_cash_pr_payment_voucher(self):
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

    def action_open_cash_pr_payment_request(self):
        self.ensure_one()
        if not self.payment_request_id:
            raise UserError(_("No payment request has been created yet."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Payment Request"),
            "res_model": "purchase.requisition.payment.request",
            "res_id": self.payment_request_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_create_rfq(self):
        """Create Custom RFQ from this PR and keep PO sequencing independent."""
        CustomRFQ = self.env["purchase.order"]

        rfq = False
        for pr in self:
            if pr.approval != "approved":
                raise UserError(_("Supervisor approval is required before creating RFQ."))
            if not pr.line_ids:
                raise UserError(_("This PR has no line items to create an RFQ."))
            remaining_quantities = pr._get_remaining_requisition_line_quantities()
            if not any(quantity > 1e-6 for quantity in remaining_quantities.values()):
                raise UserError(_("All requested products have already been fully purchased for requisition %s.") % pr.name)

            for line in pr.line_ids:
                if not line.cost_center_id:
                    raise UserError(_("Please set a cost center on every PR line."))
            pr._check_amounts_against_selected_budget(
                pr._amount_by_cost_center(remaining_quantities=remaining_quantities)
            )

            rfq_vals = {
                "name": self.env["ir.sequence"].sudo().next_by_code("purchase.order.rfq") or _("New"),
                "origin": pr.name,
                "requisition_id": pr.id,
                "partner_id": pr.vendor_id.id if pr.vendor_id else False,
                "pr_name": pr.name,
                "date_planned": pr.required_date,
                "order_line": [],
                "date_request": pr.date_request,
                "requested_by": pr.requested_by,
                "department": pr.department,
                "supervisor": pr.supervisor,
                "supervisor_partner_id": pr.supervisor_partner_id,
                "project_id": pr.project_id.id if pr.project_id else False,
                "budget_type": pr.budget_type,
                "budget_code": pr.budget_details,
            }

            for line in pr.line_ids:
                remaining_qty = remaining_quantities.get(line.id, 0.0)
                if remaining_qty <= 1e-6:
                    continue
                analytic_distribution = (
                    {str(line.cost_center_id.id): 100.0}
                    if line.cost_center_id
                    else False
                )
                rfq_vals["order_line"].append((0, 0, {
                    "name": line._get_document_line_description(),
                    "product_id": line.description.id,
                    "product_qty": remaining_qty,
                    "price_unit": 0.0,
                    "date_planned": fields.Datetime.now(),
                    "analytic_distribution": analytic_distribution,
                    "custom_requisition_line_id": line.id,
                }))

            rfq = CustomRFQ.sudo().create(rfq_vals)
            if not rfq.name or rfq.name == "New" or "RFQ" not in (rfq.name or ""):
                rfq.sudo().write({
                    "name": self.env["ir.sequence"].sudo().next_by_code("purchase.order.rfq") or "RFQ0001"
                })

            pr.status = "rfq"
            pr.message_post(
                body=_("Custom RFQ %s created from this PR.") % rfq.name,
                message_type="notification",
            )

        return {
            "type": "ir.actions.act_window",
            "name": _("Custom RFQ"),
            "res_model": "purchase.order",
            "res_id": rfq.id,
            "view_mode": "form",
            "target": "current",
        }

    # create cash PR
    def action_create_purchase_order(self):
        """Create a PO from cash PR using the same approval entry point as RFQ-selected POs."""
        if any(pr.pr_type == "cash" for pr in self):
            return self.filtered(lambda pr: pr.pr_type == "cash").action_request_cash_pr_payment()

        PurchaseOrder = self.env["purchase.order"]

        for pr in self:
            if pr.approval != "approved":
                raise UserError(_("Supervisor approval is required before creating Purchase Order."))
            if not pr.line_ids:
                raise UserError(
                    _("This PR has no line items to create a Purchase Order.")
                )
            remaining_quantities = pr._get_remaining_requisition_line_quantities()
            if not any(quantity > 1e-6 for quantity in remaining_quantities.values()):
                raise UserError(_("All requested products have already been fully purchased for requisition %s.") % pr.name)

            for line in pr.line_ids:
                if not line.cost_center_id:
                    raise UserError(_("Please set a cost center on every PR line."))
            pr._check_amounts_against_selected_budget(
                pr._amount_by_cost_center(remaining_quantities=remaining_quantities)
            )

            # Create PO values aligned with action_create_po_from_rfq (pending + approval flags)
            po_name = self.env["ir.sequence"].sudo().next_by_code("purchase.order") or "PO0001"
            po_vals = {
                "name": po_name,
                "state": "pending",
                "origin": pr.name,
                "pr_name": pr.name,
                "requisition_id": pr.id,
                "partner_id": pr.vendor_id.id if pr.vendor_id else False,
                "date_planned": pr.required_date or fields.Datetime.now(),
                "project_id": pr.project_id.id if pr.project_id else False,
                "budget_type": pr.budget_type,
                "budget_code": pr.budget_details,
                "order_line": [],
                "date_request": pr.date_request,
                "requested_by": pr.requested_by,
                "department": pr.department,
                "supervisor": pr.supervisor,
                "supervisor_partner_id": pr.supervisor_partner_id,
                "pe_approved": False,
                "pm_approved": False,
                "od_approved": False,
                "md_approved": False,
            }

            for line in pr.line_ids:
                remaining_qty = remaining_quantities.get(line.id, 0.0)
                if remaining_qty <= 1e-6:
                    continue
                analytic_distribution = (
                    {str(line.cost_center_id.id): 100.0}
                    if line.cost_center_id
                    else False
                )
                line_vals = (
                    0,
                    0,
                    {
                        "name": line._get_document_line_description(),
                        "product_id": line.description.id,
                        "product_qty": remaining_qty,
                        "product_uom": line.description.uom_po_id.id if line.description.uom_po_id else False,
                        "price_unit": line.unit_price,
                        "date_planned": fields.Datetime.now(),
                        "analytic_distribution": analytic_distribution,
                        "custom_requisition_line_id": line.id,
                    },
                )
                po_vals["order_line"].append(line_vals)

            po = PurchaseOrder.sudo().create(po_vals)

            amount = po.subtotal
            if amount <= 10000:
                po._schedule_activity_for_group(
                    "pr_custom_purchase.project_engineer",
                    "Review Purchase Order",
                    f"PO {po.name} created from cash PR {pr.name}. Please review.",
                )
            elif amount <= 100000:
                for group_xml_id in ["pr_custom_purchase.project_engineer", "pr_custom_purchase.project_manager"]:
                    po._schedule_activity_for_group(
                        group_xml_id,
                        "Review Purchase Order",
                        f"PO {po.name} created from cash PR {pr.name}. Please review.",
                    )
            elif amount <= 500000:
                for group_xml_id in [
                    "pr_custom_purchase.project_engineer",
                    "pr_custom_purchase.project_manager",
                    "pr_custom_purchase.operations_director",
                ]:
                    po._schedule_activity_for_group(
                        group_xml_id,
                        "Review Purchase Order",
                        f"PO {po.name} created from cash PR {pr.name}. Please review.",
                    )
            else:
                for group_xml_id in [
                    "pr_custom_purchase.project_engineer",
                    "pr_custom_purchase.project_manager",
                    "pr_custom_purchase.operations_director",
                    "pr_custom_purchase.managing_director",
                ]:
                    po._schedule_activity_for_group(
                        group_xml_id,
                        "Review Purchase Order",
                        f"PO {po.name} created from cash PR {pr.name}. Please review.",
                    )

            pr.status = "po"
            pr.message_post(
                body=_(
                    "Purchase Order %s created from this PR and moved to pending approval."
                )
                % po.name,
                message_type="notification",
            )

        return {
            "type": "ir.actions.act_window",
            "name": _("Purchase Order"),
            "res_model": "purchase.order",
            "res_id": po.id,
            "view_mode": "form",
            "target": "current",
        }

    # check user if he/she is supervisor
    @api.depends("supervisor_partner_id")
    def _compute_is_supervisor(self):
        for rec in self:
            try:
                supervisor_partner_id = (
                    int(rec.supervisor_partner_id) if rec.supervisor_partner_id else 0
                )
            except (ValueError, TypeError):
                supervisor_partner_id = 0

            current_user = rec.env.user
            current_partner_id = current_user.partner_id.id if current_user.partner_id else 0
            requester_supervisor = rec.requested_user_id.supervisor_user_id if rec.requested_user_id else False

            rec.is_supervisor = (
                    (requester_supervisor and requester_supervisor.id == current_user.id)
                    or (supervisor_partner_id == current_partner_id)
            )


class PurchaseRequisitionRejectWizard(models.TransientModel):
    _name = "purchase.requisition.reject.wizard"
    _description = "Purchase Requisition Rejection Wizard"

    requisition_id = fields.Many2one("purchase.requisition", string="Purchase Requisition", required=True)
    rejection_reason = fields.Text(string="Reason for Rejection", required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        if self.requisition_id.approval != "pending":
            return {"type": "ir.actions.act_window_close"}
        self.requisition_id.write({
            "approval": "rejected",
            "rejection_reason": self.rejection_reason,
        })
        return {"type": "ir.actions.act_window_close"}


class PurchaseRequisitionResetWizard(models.TransientModel):
    _name = "purchase.requisition.reset.wizard"
    _description = "Purchase Requisition Reset Wizard"

    requisition_id = fields.Many2one(
        "purchase.requisition",
        string="Purchase Requisition",
        required=True,
        readonly=True,
    )
    warning_message = fields.Text(
        string="Reset Impact",
        required=True,
        readonly=True,
    )
    confirm_reset = fields.Boolean(
        string="I understand that the listed draft records will be permanently deleted.",
    )

    def action_confirm_reset(self):
        self.ensure_one()
        if not self.confirm_reset:
            raise UserError(_("Please confirm the reset and deletion warning."))
        return self.requisition_id._confirm_reset_to_draft()


class PurchaseRequisitionLine(models.Model):
    _name = "purchase.requisition.line"
    _description = "Purchase Requisition Line"

    requisition_id = fields.Many2one(
        "purchase.requisition", string="Requisition", ondelete="cascade"
    )
    description = fields.Many2one(
        'product.product',
        string="Product",
        required=True,
        ondelete="restrict",
        context={'display_default_code': False},
    )
    line_description = fields.Text(
        string="Description",
        help="Line description copied to RFQs, purchase orders, and payment vouchers.",
    )
    product_internal_reference = fields.Many2one(
        "product.internal.reference.lookup",
        string="Product Code",
        compute="_compute_product_internal_reference",
        inverse="_inverse_product_internal_reference",
        readonly=False,
    )
    expense_account_id = fields.Many2one(
        "account.account",
        string="Expense Account",
        domain="[('deprecated', '=', False)]",
        help="Debit account used on generated Cash/Bank Payment Voucher lines.",
    )

    type = fields.Char(string="Type")
    quantity = fields.Float(string="Quantity")
    unit = fields.Char(string="Unit")
    unit_price = fields.Float(string="Unit Cost")
    cost_center_id = fields.Many2one(
        "account.analytic.account", string="Cost Center", required=True,
        domain="[('id', 'in', requisition_id.allowed_cost_center_ids)]",
    )

    @api.model
    def _get_product_purchase_defaults(self, product):
        """Return the PR values configured on the selected product."""
        if not product:
            return {
                "type": False,
                "unit": False,
                "unit_price": 0.0,
            }
        purchase_uom = product.uom_po_id or product.uom_id
        unit_price = product.standard_price or 0.0
        if product.uom_id and purchase_uom and purchase_uom != product.uom_id:
            unit_price = product.uom_id._compute_price(unit_price, purchase_uom)
        detailed_type = (
            product.detailed_type
            if "detailed_type" in product._fields
            else product.type
        )
        return {
            "type": "service" if detailed_type == "service" else "material",
            "unit": purchase_uom.name if purchase_uom else False,
            "unit_price": unit_price,
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            product = self.env["product.product"].browse(vals.get("description")).exists()
            if not product:
                continue
            defaults = self._get_product_purchase_defaults(product)
            vals["type"] = defaults["type"]
            vals["unit"] = defaults["unit"]
            vals.setdefault("unit_price", defaults["unit_price"])
        return super().create(vals_list)

    def write(self, vals):
        if "description" in vals:
            vals = dict(vals)
            product = self.env["product.product"].browse(vals.get("description")).exists()
            defaults = self._get_product_purchase_defaults(product)
            product_actually_changed = any(
                line.description != product
                for line in self
            )
            vals["type"] = defaults["type"]
            vals["unit"] = defaults["unit"]
            if product_actually_changed:
                vals.setdefault("unit_price", defaults["unit_price"])
        return super().write(vals)

    @api.depends("description")
    def _compute_product_internal_reference(self):
        ProductRef = self.env["product.internal.reference.lookup"]
        for line in self:
            line.product_internal_reference = ProductRef.browse(line.description.id) if line.description else False

    def _inverse_product_internal_reference(self):
        for line in self:
            product = line.product_internal_reference.product_id
            if line.description != product:
                line.description = product

    @api.onchange("product_internal_reference")
    def _onchange_product_internal_reference(self):
        for line in self:
            line.description = line.product_internal_reference.product_id
            line._onchange_description()
            if not line.description:
                line.product_internal_reference = False

    @api.onchange("description")
    def _onchange_description(self):
        for rec in self:
            defaults = rec._get_product_purchase_defaults(rec.description)
            rec.type = defaults["type"]
            rec.unit = defaults["unit"]
            rec.unit_price = defaults["unit_price"]

    def _get_document_line_description(self):
        """Return the user-entered description, with a safe fallback for old PR lines."""
        self.ensure_one()
        return (
            (self.line_description or "").strip()
            or self.description.with_context(display_default_code=False).display_name
            or ""
        )

    @api.constrains("cost_center_id", "requisition_id")
    def _check_cost_center_matches_bucket(self):
        for rec in self:
            bucket = rec.requisition_id.expense_bucket_id
            allowed = bucket.crossovered_budget_line.mapped("analytic_account_id")
            if rec.cost_center_id and bucket and rec.cost_center_id not in allowed:
                raise ValidationError(_("Selected cost center must belong to the selected expense bucket."))

    total_price = fields.Float(string="Total", compute="_compute_total", store=True)

    @api.depends("quantity", "unit_price")
    def _compute_total(self):
        for rec in self:
            rec.total_price = rec.quantity * rec.unit_price

    @api.constrains("quantity", "unit_price")
    def _check_non_negative_values(self):
        for rec in self:
            if rec.quantity < 0:
                raise ValidationError("Quantity cannot be negative.")
            if rec.unit_price < 0:
                raise ValidationError("Unit Price cannot be negative.")

    def _get_wo_product_caps(self):
        self.ensure_one()

        if not self.cost_center_id or not self.description:
            return False

        if "pr.work.order.cost.center" not in self.env:
            return False

        wo_cc = self.env["pr.work.order.cost.center"].sudo().search([
            ("analytic_account_id", "=", self.cost_center_id.id),
            ("work_order_id.state", "in",
             ["ops_approval", "acc_approval", "final_approval", "approved", "in_progress", "done"]),
        ], limit=1)

        if not wo_cc:
            return False

        boq_lines = wo_cc.work_order_id.boq_line_ids.filtered(
            lambda l: l.display_type not in ("line_section", "line_note")
                      and l.section_name == wo_cc.section_name
                      and l.product_id
                      and l.product_id.id == self.description.id
        )

        if not boq_lines:
            return {
                "allowed_qty": 0.0,
                "allowed_unit_price": 0.0,
                "allowed_amount": 0.0,
                "work_order": wo_cc.work_order_id,
                "section_name": wo_cc.section_name,
            }

        return {
            "allowed_qty": sum(boq_lines.mapped("qty")),
            "allowed_unit_price": max(boq_lines.mapped("unit_cost") or [0.0]),
            "allowed_amount": sum(boq_lines.mapped("total")),
            "work_order": wo_cc.work_order_id,
            "section_name": wo_cc.section_name,
        }

    def _get_trading_sale_product_caps(self):
        self.ensure_one()

        requisition = self.requisition_id
        bucket = requisition.expense_bucket_id
        if not bucket or bucket.scope != "trading" or not bucket.sale_order_id:
            return False
        if not self.cost_center_id or not self.description:
            return False

        sale_order = bucket.sale_order_id.sudo()
        so_lines = sale_order.order_line.filtered(
            lambda l: not l.display_type and l.product_id and l.product_id.id == self.description.id
        )
        if not so_lines:
            return {
                "sale_order": sale_order,
                "allowed_qty": 0.0,
                "allowed_unit_price": 0.0,
                "allowed_amount": 0.0,
            }

        relevant_lines = self.env["sale.order.line"]
        for line in so_lines:
            distribution = line.analytic_distribution or {}
            line_cc_ids = {int(key) for key in distribution.keys() if str(key).isdigit()}
            if line_cc_ids:
                if self.cost_center_id.id in line_cc_ids:
                    relevant_lines |= line
            elif len(requisition.allowed_cost_center_ids) == 1 and self.cost_center_id in requisition.allowed_cost_center_ids:
                relevant_lines |= line

        if not relevant_lines:
            return {
                "sale_order": sale_order,
                "allowed_qty": 0.0,
                "allowed_unit_price": 0.0,
                "allowed_amount": 0.0,
            }

        return {
            "sale_order": sale_order,
            "allowed_qty": sum(relevant_lines.mapped("product_uom_qty")),
            "allowed_unit_price": max(relevant_lines.mapped("price_unit") or [0.0]),
            "allowed_amount": sum(relevant_lines.mapped("price_subtotal")),
        }

    @api.constrains("cost_center_id", "description", "quantity", "unit_price", "requisition_id")
    def _check_work_order_product_limits(self):
        for rec in self:
            if not rec.cost_center_id or not rec.description:
                continue

            caps = rec._get_wo_product_caps()
            if not caps:
                continue

            if not caps["allowed_qty"]:
                raise ValidationError(_(
                    "Product '%(product)s' is not budgeted in Work Order '%(wo)s' section '%(section)s' for cost center '%(cc)s'."
                ) % {
                                          "product": rec.description.display_name,
                                          "wo": caps["work_order"].display_name,
                                          "section": caps["section_name"] or "-",
                                          "cc": rec.cost_center_id.display_name,
                                      })

            current_req_lines = rec.requisition_id.line_ids.filtered(
                lambda l: l.cost_center_id.id == rec.cost_center_id.id
                          and l.description.id == rec.description.id
            )
            current_req_amount = sum(current_req_lines.mapped("total_price"))

            other_pr_lines = self.env["purchase.requisition.line"].sudo().search([
                ("id", "not in", rec.requisition_id.line_ids.ids),
                ("cost_center_id", "=", rec.cost_center_id.id),
                ("description", "=", rec.description.id),
                ("requisition_id.approval", "in", ("pending", "approved")),
            ])
            total_requested_amount = current_req_amount + sum(other_pr_lines.mapped("total_price"))

            if total_requested_amount > caps["allowed_amount"]:
                raise ValidationError(_(
                    "Requested amount for '%(product)s' exceeds Work Order amount for cost center '%(cc)s'. Allowed: %(allowed)s, Requested (including other PRs): %(requested)s."
                ) % {
                                          "product": rec.description.display_name,
                                          "cc": rec.cost_center_id.display_name,
                                          "allowed": caps["allowed_amount"],
                                          "requested": total_requested_amount,
                                      })

    @api.constrains("cost_center_id", "description", "quantity", "unit_price", "requisition_id")
    def _check_trading_sale_order_product_limits(self):
        for rec in self:
            if not rec.cost_center_id or not rec.description or not rec.requisition_id:
                continue

            caps = rec._get_trading_sale_product_caps()
            if not caps:
                continue

            if not caps["allowed_qty"]:
                raise ValidationError(_(
                    "Product '%(product)s' is not available in Sale Order '%(so)s' for cost center '%(cc)s'."
                ) % {
                    "product": rec.description.display_name,
                    "so": caps["sale_order"].display_name,
                    "cc": rec.cost_center_id.display_name,
                })

            current_req_lines = rec.requisition_id.line_ids.filtered(
                lambda l: l.cost_center_id.id == rec.cost_center_id.id
                and l.description.id == rec.description.id
            )
            current_req_qty = sum(current_req_lines.mapped("quantity"))
            current_req_amount = sum(current_req_lines.mapped("total_price"))

            other_pr_lines = self.env["purchase.requisition.line"].sudo().search([
                ("id", "not in", rec.requisition_id.line_ids.ids),
                ("cost_center_id", "=", rec.cost_center_id.id),
                ("description", "=", rec.description.id),
                ("requisition_id.expense_bucket_id", "=", rec.requisition_id.expense_bucket_id.id),
                ("requisition_id.approval", "in", ("pending", "approved")),
            ])
            total_requested_qty = current_req_qty + sum(other_pr_lines.mapped("quantity"))
            total_requested_amount = current_req_amount + sum(other_pr_lines.mapped("total_price"))

            if total_requested_qty > caps["allowed_qty"]:
                raise ValidationError(_(
                    "Requested quantity for '%(product)s' exceeds Sale Order '%(so)s' quantity for cost center '%(cc)s'. Allowed: %(allowed)s, Requested (including other PRs): %(requested)s."
                ) % {
                    "product": rec.description.display_name,
                    "so": caps["sale_order"].display_name,
                    "cc": rec.cost_center_id.display_name,
                    "allowed": caps["allowed_qty"],
                    "requested": total_requested_qty,
                })

            if rec.unit_price > caps["allowed_unit_price"]:
                raise ValidationError(_(
                    "Unit cost for '%(product)s' cannot exceed Sale Order '%(so)s' unit price for cost center '%(cc)s'. Allowed max: %(allowed)s, Entered: %(entered)s."
                ) % {
                    "product": rec.description.display_name,
                    "so": caps["sale_order"].display_name,
                    "cc": rec.cost_center_id.display_name,
                    "allowed": caps["allowed_unit_price"],
                    "entered": rec.unit_price,
                })

            if total_requested_amount > caps["allowed_amount"]:
                raise ValidationError(_(
                    "Requested amount for '%(product)s' exceeds Sale Order '%(so)s' amount for cost center '%(cc)s'. Allowed: %(allowed)s, Requested (including other PRs): %(requested)s."
                ) % {
                    "product": rec.description.display_name,
                    "so": caps["sale_order"].display_name,
                    "cc": rec.cost_center_id.display_name,
                    "allowed": caps["allowed_amount"],
                    "requested": total_requested_amount,
                })


class AccountCashPayment(models.Model):
    _inherit = "pr.account.cash.payment"

    purchase_requisition_id = fields.Many2one(
        "purchase.requisition",
        string="Cash PR",
        readonly=True,
        copy=False,
    )

    def _check_purchase_requisition_voucher_budget(self, line_field):
        for voucher in self.filtered("purchase_requisition_id"):
            if voucher.state != "draft":
                continue
            amount_by_cost_center = (
                voucher.purchase_requisition_id._get_voucher_budget_amounts(
                    voucher[line_field]
                )
            )
            for item in amount_by_cost_center.values():
                if item["amount"] <= 0.0:
                    raise UserError(_("Cash PR voucher lines must have a positive amount."))
            voucher.purchase_requisition_id._check_amounts_against_selected_budget(amount_by_cost_center)

    def action_submit(self):
        self._check_purchase_requisition_voucher_budget("cash_payment_line_ids")
        return super().action_submit()

    def action_post(self):
        res = super().action_post()
        self.mapped("purchase_requisition_id").filtered(lambda pr: pr.pr_type == "cash").write({
            "status": "completed",
        })
        return res


class AccountBankPayment(models.Model):
    _inherit = "pr.account.bank.payment"

    purchase_requisition_id = fields.Many2one(
        "purchase.requisition",
        string="Cash PR",
        readonly=True,
        copy=False,
    )

    def _check_purchase_requisition_voucher_budget(self, line_field):
        for voucher in self.filtered("purchase_requisition_id"):
            if voucher.state != "draft":
                continue
            amount_by_cost_center = (
                voucher.purchase_requisition_id._get_voucher_budget_amounts(
                    voucher[line_field]
                )
            )
            for item in amount_by_cost_center.values():
                if item["amount"] <= 0.0:
                    raise UserError(_("Cash PR voucher lines must have a positive amount."))
            voucher.purchase_requisition_id._check_amounts_against_selected_budget(amount_by_cost_center)

    def action_submit(self):
        self._check_purchase_requisition_voucher_budget("bank_payment_line_ids")
        return super().action_submit()

    def action_post(self):
        res = super().action_post()
        self.mapped("purchase_requisition_id").filtered(lambda pr: pr.pr_type == "cash").write({
            "status": "completed",
        })
        return res


class AccountCashPaymentLine(models.Model):
    _inherit = "pr.account.cash.payment.line"

    budget_cost_center_id = fields.Many2one(
        "account.analytic.account",
        string="PR Budget Cost Center",
        readonly=True,
        copy=False,
        help="Original Cash PR cost center used exclusively for budget validation.",
    )


class AccountBankPaymentLine(models.Model):
    _inherit = "pr.account.bank.payment.line"

    budget_cost_center_id = fields.Many2one(
        "account.analytic.account",
        string="PR Budget Cost Center",
        readonly=True,
        copy=False,
        help="Original Cash PR cost center used exclusively for budget validation.",
    )


class PurchaseQuotation(models.Model):
    _inherit = "purchase.order"

    project_id = fields.Many2one("project.project", string="Project")
    budget_type = fields.Selection(
        [("opex", "Opex"), ("capex", "Capex")], string="Budget Type"
    )

    budget_code = fields.Char(string="Budget Code")


class PurchaseOrderCustomLine(models.Model):
    _name = "purchase.order.custom.line"
    _description = "Custom Purchase Order Line"

    order_id = fields.Many2one(
        "purchase.order", string="Purchase Order", ondelete="cascade"
    )
    name = fields.Char(string="Description")
    quantity = fields.Float(string="Quantity")
    unit = fields.Char(string="Unit")
    type = fields.Selection(
        [
            ('material', 'Material'),
            ('service', 'Service')
        ],
        string="Type",
        default='material',
        required=True
    )
    price_unit = fields.Float(string="Unit Price")
    cost_center_id = fields.Many2one("account.analytic.account", string="Cost Center", required=True)
    subtotal = fields.Float(string="Subtotal", compute="_compute_subtotal", store=True)

    @api.depends("quantity", "price_unit")
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit

    @api.constrains("quantity", "price_unit")
    def _check_non_negative_subtotal_inputs(self):
        for line in self:
            if line.quantity < 0:
                raise ValidationError("Quantity cannot be negative.")
            if line.price_unit < 0:
                raise ValidationError("Unit Price cannot be negative.")


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    custom_requisition_line_id = fields.Many2one(
        "purchase.requisition.line",
        string="Source PR Line",
        index=True,
        copy=False,
        ondelete="set null",
    )
