import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_amount
from odoo.tools.float_utils import float_compare, float_round


class PRWorkOrder(models.Model):
    _name = "pr.work.order"
    _description = "Construction Work Order"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    def _notify_group_for_approval(self, group_xml_id, summary, body_html):
        self.ensure_one()
        group = self.env.ref(group_xml_id, raise_if_not_found=False)
        if not group:
            return
        activity_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        for user in group.users.filtered(lambda u: u.active):
            if activity_type:
                self.activity_schedule(
                    activity_type_id=activity_type.id,
                    user_id=user.id,
                    summary=summary,
                    note=body_html,
                )
            if user.email:
                self.env["mail.mail"].sudo().create({
                    "email_from": "noreply@petroraq.com",
                    "email_to": user.email,
                    "subject": summary,
                    "body_html": body_html,
                }).send()

    def _reset_approval_metadata(self):
        self.write({
            "ops_approver_id": False,
            "ops_approved_date": False,
            "acc_approver_id": False,
            "acc_approved_date": False,
            "final_approver_id": False,
            "final_approved_date": False,
            "rejected_by": False,
            "rejected_date": False,
            "rejection_reason": False,
        })

    def _validate_budget_within_sale_order(self):
        for rec in self:
            if not rec.sale_order_id:
                continue
            currency = rec.currency_id or rec.company_id.currency_id
            precision_cost = self.env["decimal.precision"].precision_get("Product Price")
            contract_amount = float_round(rec.sale_order_id.amount_total or 0.0, precision_digits=precision_cost)
            budgeted_cost = float_round(rec.budgeted_cost or 0.0, precision_digits=precision_cost)
            if float_compare(
                budgeted_cost,
                contract_amount,
                precision_digits=precision_cost,
            ) > 0:
                raise ValidationError(_(
                    "Work Order budget (%(budget)s) cannot exceed linked Sales Order total "
                    "(%(sale)s). Revise the Estimation/Sales Order first or reduce the WO budget."
                ) % {
                    "budget": format_amount(rec.env, rec.budgeted_cost or 0.0, currency),
                    "sale": format_amount(rec.env, contract_amount, currency),
                })
        return True

    def _remove_linked_expense_bucket(self):
        for rec in self:
            if not rec.expense_bucket_id:
                continue
            linked_custom_pr_count = self.env["custom.pr"].sudo().search_count([
                ("expense_bucket_id", "=", rec.expense_bucket_id.id)
            ])
            linked_requisition_count = self.env["purchase.requisition"].sudo().search_count([
                ("expense_bucket_id", "=", rec.expense_bucket_id.id)
            ])
            if linked_custom_pr_count or linked_requisition_count:
                raise UserError(
                    _(
                        "Cannot delete expense bucket %s because it is already linked to Purchase Requisitions."
                    ) % rec.expense_bucket_id.display_name
                )
            rec.expense_bucket_id.sudo().unlink()
            rec.expense_bucket_id = False

    def _sync_work_order_budget_state(self, target):
        for rec in self:
            bucket = rec.expense_bucket_id.sudo()
            if not bucket:
                continue

            if target == "draft":
                bucket.write({"state": "draft", "approval_state": "draft"})
                continue

            if target == "pm_approved":
                if bucket.state == "draft":
                    bucket.write({"state": "confirm"})
                bucket.write({"approval_state": "accounts_approval"})
                continue

            if target == "accounts_approved":
                if bucket.state == "draft":
                    bucket.write({"state": "confirm"})
                bucket.write({"approval_state": "md_approval"})
                continue

            if target == "md_approved":
                if bucket.state == "draft":
                    bucket.write({"state": "confirm"})
                bucket.write({"approval_state": "approved"})
                if bucket.state not in ("validate", "done"):
                    bucket.write({"state": "validate"})
                bucket._sync_cost_center_budget_allowance()
                continue

            if target == "rejected":
                bucket.write({"approval_state": "rejected"})
                if bucket.state != "cancel":
                    bucket.write({"state": "cancel"})
                continue

            if target == "cancel":
                bucket.write({"approval_state": "rejected"})
                if bucket.state != "cancel":
                    bucket.write({"state": "cancel"})

    name = fields.Char(
        string="Work Order",
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _("New"),
        tracking=True,
    )
    unrevisioned_name = fields.Char(
        string="Base Work Order Name",
        readonly=True,
        copy=False,
        index=True,
    )
    revision_number = fields.Integer(
        string="Revision Number",
        readonly=True,
        copy=False,
        default=0,
    )
    previous_revision_id = fields.Many2one(
        "pr.work.order",
        string="Previous Revision",
        readonly=True,
        copy=False,
    )
    revision_count = fields.Integer(
        string="Revisions Count",
        compute="_compute_revision_count",
    )
    # budget_id = fields.Many2one("crossovered.budget", string="Budget", readonly=True)

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True,
    )
    boq_line_ids = fields.One2many(
        "pr.work.order.boq",
        "work_order_id",
        string="BOQ / Budget Lines"
    )

    sale_order_id = fields.Many2one("sale.order", string="Sale Order", ondelete="restrict", readonly=True)
    partner_id = fields.Many2one("res.partner", string="Customer", related="sale_order_id.partner_id", store=True)
    po_number = fields.Char(string="Customer PO", tracking=True)

    project_id = fields.Many2one("project.project", string="Construction Project", ondelete="restrict")
    analytic_account_id = fields.Many2one("account.analytic.account", string="Cost Center", ondelete="restrict")
    expense_bucket_id = fields.Many2one(
        "crossovered.budget",
        string="Expense Bucket",
        copy=False,
        readonly=True,
    )
    expense_bucket_count = fields.Integer(
        string="Expense Bucket Count",
        compute="_compute_expense_bucket_count",
    )
    cost_center_ids = fields.One2many(
        "pr.work.order.cost.center",
        "work_order_id",
        string="Cost Centers"
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("ops_approval", "Operations Approval"),
            ("acc_approval", "Accounts Approval"),
            ("final_approval", "Final Approval"),
            ("approved", "Approved"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
            ("cancel", "Cancelled"),
        ],
        string="Status",
        default="draft",
        tracking=True,
    )

    date_start = fields.Date(string="Planned Start Date", )
    date_end = fields.Date(string="Planned End Date")

    # Budget / amounts
    contract_amount = fields.Monetary(
        string="Contract Amount",
        currency_field="currency_id",
        help="Total selling value (from SO).",
        compute="_compute_budgeted_cost",
        store=True
    )
    budgeted_cost = fields.Monetary(string="Budgeted Cost", currency_field="currency_id",
                                    compute="_compute_budgeted_cost", store=True)

    @api.depends("boq_line_ids.total")
    def _compute_budgeted_cost(self):
        precision_cost = self.env["decimal.precision"].precision_get("Product Price")
        for order in self:
            order.budgeted_cost = float_round(
                sum(order.boq_line_ids.mapped("total")),
                precision_digits=precision_cost,
            )
            order.contract_amount = order.sale_order_id.amount_total

    budgeted_margin = fields.Monetary(
        string="Budgeted Margin",
        currency_field="currency_id",
        compute="_compute_budgeted_margin",
        store=True,
    )

    overhead_percent = fields.Float(
        string="Overhead (%)",
        default=0.0,
        digits=(16, 2),
    )
    risk_percent = fields.Float(
        string="Risk (%)",
        default=0.0,
        digits=(16, 2),
    )
    profit_percent = fields.Float(
        string="Profit (%)",
        default=0.0,
        digits=(16, 2),
    )
    overhead_amount = fields.Monetary(
        string="Overhead Amount",
        currency_field="currency_id",
        compute="_compute_cost_buffers",
        store=True,
    )
    risk_amount = fields.Monetary(
        string="Risk Amount",
        currency_field="currency_id",
        compute="_compute_cost_buffers",
        store=True,
    )
    profit_amount = fields.Monetary(
        string="Profit Amount",
        currency_field="currency_id",
        compute="_compute_cost_buffers",
        store=True,
    )
    total_expected_cost = fields.Monetary(
        string="Total Expected Cost",
        currency_field="currency_id",
        compute="_compute_cost_buffers",
        store=True,
        help="Budgeted cost plus overhead and risk buffers.",
    )
    total_with_profit = fields.Monetary(
        string="Total With Profit",
        currency_field="currency_id",
        compute="_compute_cost_buffers",
        store=True,
    )

    actual_revenue = fields.Monetary(
        string="Actual Revenue",
        currency_field="currency_id",
        compute="_compute_actuals",
        store=True,
    )
    actual_cost = fields.Monetary(
        string="Actual Cost",
        currency_field="currency_id",
        compute="_compute_actuals",
        store=True,
    )
    actual_margin = fields.Monetary(
        string="Actual Margin",
        currency_field="currency_id",
        compute="_compute_actuals",
        store=True,
    )

    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        default=lambda self: self.env.company.currency_id,
    )

    # Links to other resources
    task_ids = fields.One2many("project.task", "work_order_id", string="Tasks")
    stock_move_ids = fields.One2many("stock.move", "work_order_id", string="Material Movements")
    vendor_bill_ids = fields.One2many("account.move", "work_order_id", domain=[("move_type", "=", "in_invoice")])
    customer_invoice_ids = fields.One2many("account.move", "work_order_id", domain=[("move_type", "=", "out_invoice")])

    # Simple tracking of resources (you can split later)
    labour_ids = fields.One2many("account.analytic.line", "work_order_id", string="Timesheets / Labour")
    equipment_note = fields.Text(string="Equipment / Machinery Notes")
    materials_note = fields.Text(string="Materials Notes")

    # Approvals
    ops_approver_id = fields.Many2one("res.users", string="Operations Approver")
    ops_approved_date = fields.Datetime(string="Operations Approved On")

    acc_approver_id = fields.Many2one("res.users", string="Accounts Approver")
    acc_approved_date = fields.Datetime(string="Accounts Approved On")

    final_approver_id = fields.Many2one("res.users", string="Final Approver")
    final_approved_date = fields.Datetime(string="Final Approved On")

    note = fields.Text(string="Internal Notes")

    rejection_reason = fields.Text(string="Rejection Reason", tracking=True)
    rejected_by = fields.Many2one("res.users", string="Rejected By", tracking=True)
    rejected_date = fields.Datetime(string="Rejected On", tracking=True)

    drawings_attachment_ids = fields.Many2many(
        "ir.attachment",
        "pr_work_order_drawings_attachment_rel",
        "work_order_id",
        "attachment_id",
        string="Drawings Attachments",
        help="Drawings required for this work order.",
    )
    scope_attachment_ids = fields.Many2many(
        "ir.attachment",
        "pr_work_order_scope_attachment_rel",
        "work_order_id",
        "attachment_id",
        string="Scope of Work Attachments",
        help="Scope of work documents required for this work order.",
    )
    boq_attachment_ids = fields.Many2many(
        "ir.attachment",
        "pr_work_order_boq_attachment_rel",
        "work_order_id",
        "attachment_id",
        string="BOQ Attachments",
        help="BOQ documents required for this work order.",
    )

    @api.constrains("drawings_attachment_ids", "scope_attachment_ids", "boq_attachment_ids")
    def _check_required_attachments(self):
        for rec in self:
            # if not rec.drawings_attachment_ids:
            #     raise ValidationError(_("Please upload at least one Drawing attachment."))
            if not rec.scope_attachment_ids:
                raise ValidationError(_("Please upload at least one Scope of Work attachment."))
            if not rec.boq_attachment_ids:
                raise ValidationError(_("Please upload at least one BOQ attachment."))

    @api.depends("expense_bucket_id")
    def _compute_expense_bucket_count(self):
        for rec in self:
            rec.expense_bucket_count = 1 if rec.expense_bucket_id else 0

    def _format_section_cost_center_name(self, section_name):
        self.ensure_one()
        section_label = section_name or _("General")
        return "%s - %s" % (self.name or _("Work Order"), section_label)

    def _sync_section_cost_center_names(self):
        for rec in self:
            source_names = set()
            if rec.sale_order_id and rec.sale_order_id.name:
                source_names.add(rec.sale_order_id.name)
            if "source_estimation_id" in rec._fields and rec.source_estimation_id and rec.source_estimation_id.name:
                source_names.add(rec.source_estimation_id.name)

            for line in rec.cost_center_ids.filtered(lambda cost_center: cost_center.analytic_account_id and cost_center.section_name):
                expected_name = rec._format_section_cost_center_name(line.section_name)
                analytic = line.analytic_account_id.sudo()
                current_name = analytic.name or ""
                previous_names = {
                    "%s - %s" % (source_name, line.section_name)
                    for source_name in source_names
                }
                if current_name == expected_name:
                    continue
                if not current_name or current_name in previous_names:
                    analytic.write({"name": expected_name})

    def action_view_expense_bucket(self):
        self.ensure_one()
        if not self.expense_bucket_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Budget"),
            "res_model": "crossovered.budget",
            "view_mode": "form",
            "res_id": self.expense_bucket_id.id,
            "target": "current",
        }

    @api.depends("contract_amount", "budgeted_cost")
    def _compute_budgeted_margin(self):
        for rec in self:
            rec.budgeted_margin = (rec.contract_amount or 0.0) - (rec.budgeted_cost or 0.0)

    @api.depends("budgeted_cost", "overhead_percent", "risk_percent", "profit_percent")
    def _compute_cost_buffers(self):
        for rec in self:
            budget = rec.budgeted_cost or 0.0
            overhead = budget * (rec.overhead_percent or 0.0) / 100.0
            risk = budget * (rec.risk_percent or 0.0) / 100.0
            buffer_total = budget + overhead + risk
            profit = buffer_total * (rec.profit_percent or 0.0) / 100.0
            rec.overhead_amount = overhead
            rec.risk_amount = risk
            rec.total_expected_cost = buffer_total
            rec.profit_amount = profit
            rec.total_with_profit = buffer_total + profit

    @api.depends("analytic_account_id")
    def _compute_actuals(self):
        AnalyticLine = self.env["account.analytic.line"]
        for rec in self:
            rec.actual_revenue = rec.actual_cost = rec.actual_margin = 0.0
            if not rec.analytic_account_id:
                continue

            lines = AnalyticLine.read_group(
                [
                    ("account_id", "=", rec.analytic_account_id.id),
                    ("company_id", "=", rec.company_id.id),
                ],
                ["amount"],
                [],
            )
            # In analytic: revenue is positive, cost negative (usually)
            amount = lines and lines[0]["amount"] or 0.0
            # Split into cost & revenue
            # (If you want more accuracy, do two read_groups with domain on 'amount > 0' and '< 0')
            revenue = amount if amount > 0 else 0.0
            cost = -amount if amount < 0 else 0.0
            rec.actual_revenue = revenue
            rec.actual_cost = cost
            rec.actual_margin = revenue - cost

    # -------------------------------------------------
    # Revision workflow
    # -------------------------------------------------
    @api.depends("name", "unrevisioned_name")
    def _compute_revision_count(self):
        for rec in self:
            base_name = rec.unrevisioned_name or (re.sub(r"-R\d+$", "", rec.name) if rec.name else False)
            if not base_name:
                rec.revision_count = 0
                continue
            count = self.search_count([
                "|",
                ("unrevisioned_name", "=", base_name),
                ("name", "=like", f"{base_name}%"),
                ("company_id", "=", rec.company_id.id),
            ])
            rec.revision_count = count

    def action_view_revisions(self):
        self.ensure_one()
        base_name = self.unrevisioned_name or (re.sub(r"-R\d+$", "", self.name) if self.name else False)
        domain = [
            "|",
            ("unrevisioned_name", "=", base_name),
            ("name", "=like", f"{base_name}%"),
            ("company_id", "=", self.company_id.id),
        ]
        return {
            "type": "ir.actions.act_window",
            "name": _("Work Order Revisions"),
            "res_model": "pr.work.order",
            "view_mode": "tree,form",
            "domain": domain,
            "context": {"default_sale_order_id": self.sale_order_id.id if self.sale_order_id else False},
        }

    def action_new_revision(self):
        self.ensure_one()
        base_name = self.unrevisioned_name or (re.sub(r"-R\d+$", "", self.name) if self.name else "")

        # Find all existing Work Orders in the company sharing this base sequence
        existing_wos = self.env["pr.work.order"].with_context(active_test=False).search([
            "|",
            ("name", "=like", f"{base_name}%"),
            ("unrevisioned_name", "=", base_name),
            ("company_id", "=", self.company_id.id),
        ])

        existing_revs = [0]
        for wo in existing_wos:
            if wo.name == base_name:
                existing_revs.append(0)
            else:
                match = re.search(r"-R(\d+)$", wo.name or "")
                if match:
                    existing_revs.append(int(match.group(1)))
                elif getattr(wo, "revision_number", 0):
                    existing_revs.append(wo.revision_number)

        next_rev = max(existing_revs) + 1
        new_name = f"{base_name}-R{next_rev}"

        default_vals = {
            "name": new_name,
            "unrevisioned_name": base_name,
            "revision_number": next_rev,
            "previous_revision_id": self.id,
            "sale_order_id": self.sale_order_id.id if self.sale_order_id else False,
            "state": "draft",
            "expense_bucket_id": False,
            "ops_approver_id": False,
            "ops_approved_date": False,
            "acc_approver_id": False,
            "acc_approved_date": False,
            "final_approver_id": False,
            "final_approved_date": False,
            "rejected_by": False,
            "rejected_date": False,
            "rejection_reason": False,
        }
        if self.project_id:
            default_vals["project_id"] = self.project_id.id
        if self.analytic_account_id:
            default_vals["analytic_account_id"] = self.analytic_account_id.id

        new_wo = self.copy(default=default_vals)

        self.message_post(body=_("New revision %(new)s created from this Work Order.") % {"new": new_wo.name})
        new_wo.message_post(body=_("Created as revision %(new)s of %(orig)s.") % {"new": new_wo.name, "orig": self.name})

        return {
            "type": "ir.actions.act_window",
            "name": _("Work Order"),
            "res_model": "pr.work.order",
            "res_id": new_wo.id,
            "view_mode": "form",
            "target": "current",
        }

    @api.model
    def _get_related_sale_order_chain(self, sale_order):
        """Find all sale.order records associated with the given sale_order across
        the revision chain, estimation chain, and order inquiry."""
        if not sale_order:
            return self.env["sale.order"]

        SaleOrder = self.env["sale.order"].with_context(active_test=False)
        chain = SaleOrder.browse(sale_order.id)
        visited = set()
        to_visit = {sale_order.id}

        # 1. Traverse old_revision_ids and current_revision_id
        while to_visit:
            current_id = to_visit.pop()
            if current_id in visited:
                continue
            visited.add(current_id)
            rec = SaleOrder.browse(current_id)
            if not rec.exists():
                continue
            chain |= rec
            if hasattr(rec, "old_revision_ids"):
                for old in rec.old_revision_ids:
                    if old.id not in visited:
                        to_visit.add(old.id)
            if hasattr(rec, "current_revision_id") and rec.current_revision_id:
                if rec.current_revision_id.id not in visited:
                    to_visit.add(rec.current_revision_id.id)

        # 2. Search by base SO name and unrevisioned_name
        base_names = set()
        for rec in chain:
            if rec.name:
                base_names.add(re.sub(r"-R\d+$", "", rec.name))
            if getattr(rec, "unrevisioned_name", False):
                base_names.add(re.sub(r"-R\d+$", "", rec.unrevisioned_name))

        for base_name in base_names:
            if base_name and "-SO-" in base_name:
                matching_orders = SaleOrder.search([
                    "|",
                    ("name", "=like", f"{base_name}%"),
                    ("unrevisioned_name", "=", base_name),
                    ("company_id", "=", sale_order.company_id.id),
                ])
                chain |= matching_orders

        # 3. Search via estimation chain
        if "estimation_id" in chain._fields:
            est_ids = chain.mapped("estimation_id")
            for est in est_ids:
                base_est = getattr(est, "unrevisioned_name", False) or (re.sub(r"-R\d+$", "", est.name) if est.name else False)
                if base_est and "petroraq.estimation" in self.env:
                    related_ests = self.env["petroraq.estimation"].with_context(active_test=False).search([
                        "|",
                        ("name", "=like", f"{base_est}%"),
                        ("unrevisioned_name", "=", base_est),
                        ("company_id", "=", sale_order.company_id.id),
                    ])
                    chain |= related_ests.mapped("sale_order_id")

        # 4. Search via order inquiry
        if "order_inquiry_id" in chain._fields:
            for inq in chain.mapped("order_inquiry_id"):
                inq_orders = inq.sale_order_ids.filtered(lambda o: "-SO-" in (o.name or ""))
                chain |= inq_orders

        return chain

    @api.model
    def _get_existing_work_orders_for_chain(self, so_chain, company=None):
        if not so_chain:
            return self.env["pr.work.order"]

        WorkOrder = self.env["pr.work.order"].with_context(active_test=False)
        company_id = company.id if company else so_chain[0].company_id.id

        # 1. Search WOs linked to any SO in the chain
        wos = WorkOrder.search([
            "|",
            ("sale_order_id", "in", so_chain.ids),
            ("id", "in", [wo_id for wo_id in so_chain.mapped("work_order_id").ids if wo_id]),
        ])

        # 2. Check estimations in chain
        if "estimation_id" in so_chain._fields:
            ests = so_chain.mapped("estimation_id")
            for est in ests:
                if getattr(est, "work_order_id", False):
                    wos |= est.work_order_id

        # 3. For any found WO, expand search by base WO name to ensure all revisions are caught
        base_wo_names = set()
        for wo in wos:
            if wo.name and wo.name not in (_("New"), "/", "New"):
                base_name = getattr(wo, "unrevisioned_name", False) or re.sub(r"-R\d+$", "", wo.name)
                if base_name:
                    base_wo_names.add(base_name)

        for base_wo in base_wo_names:
            matching_wos = WorkOrder.search([
                "|",
                ("name", "=like", f"{base_wo}%"),
                ("unrevisioned_name", "=", base_wo),
                ("company_id", "=", company_id),
            ])
            wos |= matching_wos

        return wos.filtered(lambda w: w.name and w.name not in (_("New"), "/", "New"))

    @api.model
    def _compute_next_work_order_name(self, sale_order=None, company=None):
        """Determine the next work order name, base sequence, and revision number.
        Returns: (name, base_name, revision_number)
        """
        company_rec = company or (sale_order.company_id if sale_order else self.env.company)

        if not sale_order:
            # Standalone Work Order: normal sequence
            seq_name = self.env["ir.sequence"].with_company(company_rec).next_by_code("pr.work.order") or _("New")
            return seq_name, seq_name, 0

        so_chain = self._get_related_sale_order_chain(sale_order)
        existing_wos = self._get_existing_work_orders_for_chain(so_chain, company=company_rec)

        if not existing_wos:
            # No existing Work Order in chain: generate new base sequence
            seq_name = self.env["ir.sequence"].with_company(company_rec).next_by_code("pr.work.order") or _("New")
            return seq_name, seq_name, 0

        # Existing Work Order found in chain: determine base sequence and highest revision
        base_wo_name = False
        # Prefer the base name of the oldest/original WO (no -R suffix)
        for wo in existing_wos.sorted(lambda w: w.id):
            candidate = getattr(wo, "unrevisioned_name", False) or re.sub(r"-R\d+$", "", wo.name)
            if candidate:
                base_wo_name = candidate
                break

        if not base_wo_name:
            base_wo_name = re.sub(r"-R\d+$", "", existing_wos[0].name)

        existing_revs = [0]
        for wo in existing_wos:
            if wo.name == base_wo_name:
                existing_revs.append(0)
            else:
                match = re.search(r"-R(\d+)$", wo.name or "")
                if match and (wo.name.startswith(base_wo_name) or getattr(wo, "unrevisioned_name", False) == base_wo_name):
                    existing_revs.append(int(match.group(1)))
                elif getattr(wo, "revision_number", 0):
                    existing_revs.append(wo.revision_number)

        next_rev = max(existing_revs) + 1
        new_wo_name = f"{base_wo_name}-R{next_rev}"
        return new_wo_name, base_wo_name, next_rev

    def _get_other_work_orders_in_chain(self):
        self.ensure_one()
        WorkOrder = self.env["pr.work.order"].sudo().with_context(active_test=False)
        other_wos = WorkOrder

        # 1. Base sequence name in company
        base_name = self.unrevisioned_name or (re.sub(r"-R\d+$", "", self.name) if self.name else False)
        if base_name and base_name not in (_("New"), "/", "New"):
            other_wos |= WorkOrder.search([
                ("id", "!=", self.id),
                ("company_id", "=", self.company_id.id),
                "|",
                ("unrevisioned_name", "=", base_name),
                ("name", "=like", f"{base_name}%"),
            ])

        # 2. Previous revision id chain (upstream and downstream)
        curr = self.previous_revision_id
        while curr:
            if curr.id != self.id:
                other_wos |= curr
            curr = curr.previous_revision_id

        downstream = WorkOrder.search([("previous_revision_id", "=", self.id)])
        if downstream:
            other_wos |= downstream

        # 3. Via Sale Order chain if linked
        if self.sale_order_id:
            so_chain = self._get_related_sale_order_chain(self.sale_order_id)
            chain_wos = self._get_existing_work_orders_for_chain(so_chain, company=self.company_id)
            other_wos |= chain_wos

        # 4. Via Estimation chain if linked
        if hasattr(self, "source_estimation_id") and self.source_estimation_id:
            est_chain = self.source_estimation_id
            if hasattr(est_chain, "old_revision_ids"):
                est_chain |= est_chain.old_revision_ids
            if hasattr(est_chain, "current_revision_id") and est_chain.current_revision_id:
                est_chain |= est_chain.current_revision_id
            for est in est_chain:
                if getattr(est, "work_order_id", False) and est.work_order_id != self:
                    other_wos |= est.work_order_id

        return (other_wos - self).filtered(lambda w: w.exists())

    def _cancel_other_work_order_revisions(self):
        self.ensure_one()
        other_wos = self._get_other_work_orders_in_chain()
        to_cancel = other_wos.filtered(lambda w: w.state not in ("cancel", "done"))
        if not to_cancel:
            return

        to_cancel.with_context(cancelling_other_work_orders=True).write({"state": "cancel"})
        for wo in to_cancel:
            if hasattr(wo, "_sync_work_order_budget_state"):
                wo._sync_work_order_budget_state("cancel")
            wo.message_post(body=_(
                "Work Order cancelled automatically because revision %s was approved."
            ) % self.name)

        # Clear obsolete work order pointers pointing to cancelled work orders
        for wo in to_cancel:
            if wo.sale_order_id and wo.sale_order_id.work_order_id == wo:
                wo.sale_order_id.sudo().write({"work_order_id": False})
            if (
                hasattr(wo, "source_estimation_id")
                and wo.source_estimation_id
                and getattr(wo.source_estimation_id, "work_order_id", False) == wo
            ):
                wo.source_estimation_id.sudo().with_context(
                    allow_estimation_write=True
                ).write({"work_order_id": False})

        # Point active Sales Order and Estimation to this approved revision
        if self.sale_order_id and self.sale_order_id.work_order_id != self:
            self.sale_order_id.sudo().write({"work_order_id": self.id})
        if (
            hasattr(self, "source_estimation_id")
            and self.source_estimation_id
            and getattr(self.source_estimation_id, "work_order_id", False) != self
        ):
            self.source_estimation_id.sudo().with_context(
                allow_estimation_write=True
            ).write({"work_order_id": self.id})

        cancelled_names = ", ".join(to_cancel.mapped("name"))
        self.message_post(body=_(
            "Work Order revision %(new)s approved. Previous/competing Work Order(s) (%(cancelled)s) have been cancelled."
        ) % {
            "new": self.name,
            "cancelled": cancelled_names,
        })

    # -------------------------------------------------
    # Business logic / workflow
    # -------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) in (False, _("New"), "New", "/"):
                sale_order = False
                if vals.get("sale_order_id"):
                    sale_order = self.env["sale.order"].browse(vals["sale_order_id"])
                company = self.env["res.company"].browse(vals["company_id"]) if vals.get("company_id") else False
                name, base_name, rev_num = self._compute_next_work_order_name(sale_order=sale_order, company=company)
                vals["name"] = name
                vals["unrevisioned_name"] = base_name
                vals["revision_number"] = rev_num
            elif not vals.get("unrevisioned_name"):
                vals["unrevisioned_name"] = re.sub(r"-R\d+$", "", vals["name"])
                match = re.search(r"-R(\d+)$", vals["name"])
                if match:
                    vals["revision_number"] = int(match.group(1))

        records = super().create(vals_list)
        records._ensure_project_expense_bucket(sync_budget=True)
        return records

    def write(self, vals):
        res = super().write(vals)
        sync_fields = {"name", "date_start", "date_end", "cost_center_ids", "boq_line_ids"}
        if sync_fields.intersection(vals.keys()):
            self._ensure_project_expense_bucket(sync_budget=True)
        if vals.get("state") == "approved" and not self.env.context.get("cancelling_other_work_orders"):
            for rec in self:
                rec._cancel_other_work_order_revisions()
        return res


    def _get_stage_approver_ids(self, group_xml_id):
        group = self.env.ref(group_xml_id, raise_if_not_found=False)
        if not group:
            return set()
        return set(group.users.filtered(lambda u: u.active).ids)

    def _apply_deduplicated_approval_route(self):
        """Auto-skip duplicate approvers across stages and exclude submitter from approvals."""
        self.ensure_one()
        submitter_id = self.create_uid.id
        stages = [
            ("ops_approval", "pr_work_order.custom_group_work_order_operations"),
            ("acc_approval", "pr_work_order.custom_group_work_order_accounts"),
            ("final_approval", "pr_work_order.custom_group_work_order_management"),
        ]

        stage_approvers = {}
        for stage, group_xml in stages:
            approver_ids = self._get_stage_approver_ids(group_xml)
            if submitter_id in approver_ids:
                approver_ids.remove(submitter_id)
            stage_approvers[stage] = approver_ids

        # If the same user appears in multiple stages, keep that user only in the last stage.
        seen_future = set()
        for stage, _group_xml in reversed(stages):
            current = stage_approvers.get(stage, set())
            stage_approvers[stage] = current - seen_future
            seen_future |= current

        if self.state == "ops_approval" and not stage_approvers.get("ops_approval"):
            self.action_ops_approve()
        if self.state == "acc_approval" and not stage_approvers.get("acc_approval"):
            self.action_acc_approve()
        if self.state == "final_approval" and not stage_approvers.get("final_approval"):
            self.action_final_approve()

    def action_submit_ops(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only draft work orders can be submitted for approval"))
            rec._validate_budget_within_sale_order()
            rec._ensure_project_expense_bucket(sync_budget=True)
            rec.state = "ops_approval"
            rec.rejection_reason = ""
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            record_url = f"{base_url}/web#id={rec.id}&model=pr.work.order&view_type=form"
            rec._notify_group_for_approval(
                "pr_work_order.custom_group_work_order_operations",
                _("Work Order %s waiting for operations approval") % rec.name,
                _("""<p>Dear Approver,</p><p>Work Order <b>%s</b> requires Operations approval.</p><p><a href=\"%s\">Open Work Order</a></p>""") % (
                rec.name, record_url),
            )
            rec._apply_deduplicated_approval_route()

            # # ---------------------------------------
            # # AUTO CREATE BUDGET (ONLY IF NOT EXISTS)
            # # ---------------------------------------
            # if not rec.budget_id:
            #     Budget = rec.env["crossovered.budget"]
            #     BudgetLine = rec.env["crossovered.budget.lines"]
            #
            #     budget = Budget.create({
            #         "name": f"Budget for {rec.name}",
            #         "company_id": rec.company_id.id,
            #         "user_id": rec.env.user.id,
            #         "date_from": rec.date_start or fields.Date.today(),
            #         "date_to": rec.date_end or fields.Date.today(),
            #     })

            # for cc in rec.cost_center_ids:
            #     BudgetLine.create({
            #         "crossovered_budget_id": budget.id,
            #         "analytic_account_id": cc.analytic_account_id.id,
            #         "date_from": rec.date_start or fields.Date.today(),
            #         "date_to": rec.date_end or fields.Date.today(),
            #         "planned_amount": -abs(cc.estimated_cost),
            #     })
            #
            # rec.budget_id = budget.id

    def action_open_create_pr_wizard(self):
        self.ensure_one()

        if not self.env.user.has_group("pr_custom_purchase.group_custom_pr_end_user"):
            raise UserError(_("Only End Users can create PR from Work Order."))

        if self.state not in ["acc_approval", "final_approval", "approved", "in_progress", "done"]:
            raise UserError(_("PR can be created only after Operations approval."))

        if not self.boq_line_ids.filtered(
                lambda l: l.display_type not in ("line_section", "line_note") and l.product_id):
            raise UserError(_("No BOQ product lines found to create PR."))

        return {
            "type": "ir.actions.act_window",
            "name": _("Create PR"),
            "res_model": "pr.work.order.create.pr.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_work_order_id": self.id,
            },
        }

    def action_ops_approve(self):
        for rec in self:
            if rec.state != "ops_approval":
                continue

            rec._validate_budget_within_sale_order()
            rec.ops_approver_id = self.env.user
            rec.ops_approved_date = fields.Datetime.now()
            rec.state = "acc_approval"
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            record_url = f"{base_url}/web#id={rec.id}&model=pr.work.order&view_type=form"
            rec._notify_group_for_approval(
                "pr_work_order.custom_group_work_order_accounts",
                _("Work Order %s waiting for accounts approval") % rec.name,
                _("""<p>Dear Approver,</p><p>Work Order <b>%s</b> requires Accounts approval.</p><p><a href=\"%s\">Open Work Order</a></p>""") % (
                rec.name, record_url),
            )
            rec._ensure_project_expense_bucket(sync_budget=True)
            rec._sync_work_order_budget_state("pm_approved")
            rec._apply_deduplicated_approval_route()

    def _ensure_project_expense_bucket(self, sync_budget=False):
        Budget = self.env["crossovered.budget"].sudo()
        BudgetLine = self.env["crossovered.budget.lines"].sudo()
        today = fields.Date.context_today(self)

        for rec in self:
            cost_center_lines = rec.cost_center_ids.filtered("analytic_account_id")
            cost_centers = cost_center_lines.mapped("analytic_account_id").filtered(lambda a: a)
            if not cost_centers:
                continue

            rec._sync_section_cost_center_names()

            planned_by_analytic = {}
            for line in cost_center_lines:
                analytic = line.analytic_account_id
                planned_by_analytic[analytic.id] = planned_by_analytic.get(analytic.id, 0.0) + (line.estimated_cost or 0.0)

            total_budget = sum(planned_by_analytic.values())

            if not rec.expense_bucket_id:
                bucket = Budget.create({
                    "name": _("%s - CAPEX Budget") % rec.name,
                    "scope": "project",
                    "expense_type": "capex",
                    "work_order_id": rec.id,
                    "source_budget_limit": total_budget,
                    "date_from": rec.date_start or today,
                    "date_to": rec.date_end or today,
                    "company_id": rec.company_id.id,
                    "user_id": self.env.user.id,
                })
                rec.sudo().write({"expense_bucket_id": bucket.id})
            else:
                bucket = rec.expense_bucket_id.sudo()
                if bucket.work_order_id != rec:
                    bucket.write({"work_order_id": rec.id})
                if sync_budget:
                    bucket.write({
                        "name": _("%s - CAPEX Budget") % rec.name,
                        "scope": "project",
                        "expense_type": "capex",
                        "date_from": rec.date_start or bucket.date_from or today,
                        "date_to": rec.date_end or bucket.date_to or today,
                        "source_budget_limit": total_budget,
                    })

            existing_lines = {
                line.analytic_account_id.id: line
                for line in bucket.crossovered_budget_line.filtered("analytic_account_id")
            }
            wanted_ids = set(planned_by_analytic.keys())

            for analytic_id, planned in planned_by_analytic.items():
                if analytic_id in existing_lines:
                    existing_lines[analytic_id].write({
                        "planned_amount": planned,
                        "date_from": bucket.date_from or today,
                        "date_to": bucket.date_to or today,
                    })
                else:
                    BudgetLine.create({
                        "crossovered_budget_id": bucket.id,
                        "analytic_account_id": analytic_id,
                        "date_from": bucket.date_from or today,
                        "date_to": bucket.date_to or today,
                        "planned_amount": planned,
                    })

            for analytic_id, line in existing_lines.items():
                if analytic_id not in wanted_ids:
                    line.unlink()

    def action_acc_approve(self):
        for rec in self:
            if rec.state != "acc_approval":
                continue
            rec._validate_budget_within_sale_order()
            rec.acc_approver_id = self.env.user
            rec.acc_approved_date = fields.Datetime.now()
            rec.state = "final_approval"
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            record_url = f"{base_url}/web#id={rec.id}&model=pr.work.order&view_type=form"
            rec._notify_group_for_approval(
                "pr_work_order.custom_group_work_order_management",
                _("Work Order %s waiting for final approval") % rec.name,
                _("""<p>Dear Approver,</p><p>Work Order <b>%s</b> requires Management final approval.</p><p><a href=\"%s\">Open Work Order</a></p>""") % (
                rec.name, record_url),
            )
            rec._sync_work_order_budget_state("accounts_approved")
            rec._apply_deduplicated_approval_route()

    def action_final_approve(self):
        for rec in self:
            if rec.state != "final_approval":
                continue
            rec._validate_budget_within_sale_order()
            rec.final_approver_id = self.env.user
            rec.final_approved_date = fields.Datetime.now()
            rec.state = "approved"
            rec._sync_work_order_budget_state("md_approved")
            rec._cancel_other_work_order_revisions()

    def action_reject(self):
        self.ensure_one()

        if self.state in ("done", "cancel"):
            raise UserError(_("You cannot reject a completed or cancelled Work Order."))

        return {
            "name": _("Reject Work Order"),
            "type": "ir.actions.act_window",
            "res_model": "pr.work.order.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_work_order_id": self.id,
            },
        }

    def action_start_operations(self):
        for rec in self:
            if rec.state not in ("approved", "in_progress"):
                raise UserError(_("Work Order must be approved before starting operations."))
            rec.state = "in_progress"

    def _get_issue_picking_type(self):
        self.ensure_one()
        warehouse = self.sale_order_id.warehouse_id if self.sale_order_id else False
        if warehouse and warehouse.int_type_id:
            return warehouse.int_type_id

        picking_type = self.env["stock.picking.type"].search([
            ("code", "=", "internal"),
            ("company_id", "in", [self.company_id.id, False]),
        ], limit=1)
        if not picking_type:
            raise UserError(_("No internal transfer operation type was found for this company."))
        return picking_type

    def action_create_material_issue(self):
        self.ensure_one()
        if self.state not in ("approved", "in_progress", "done"):
            raise UserError(_("Material issue is allowed only after Work Order approval."))

        picking_type = self._get_issue_picking_type()
        src_location = picking_type.default_location_src_id
        if not src_location:
            raise UserError(_("Please configure source location on the internal operation type."))

        dest_location = self.env.ref("stock.stock_location_production", raise_if_not_found=False)
        if not dest_location:
            dest_location = picking_type.default_location_dest_id
        if not dest_location:
            raise UserError(_("Please configure destination location on the internal operation type."))

        issueable_lines = self.boq_line_ids.filtered(
            lambda l: l.display_type == "product"
                      and l.product_id
                      and l.product_id.type in ("product", "consu")
                      and l.qty > 0
        )
        if not issueable_lines:
            raise UserError(_("No stockable/consumable BOQ lines are available for material issue."))

        move_commands = []
        Move = self.env["stock.move"]
        for line in issueable_lines:
            issued_qty = sum(Move.search([
                ("work_order_id", "=", self.id),
                ("work_order_boq_line_id", "=", line.id),
                ("state", "=", "done"),
                ("picking_id.picking_type_id.code", "=", "internal"),
            ]).mapped("product_uom_qty"))
            remaining_qty = (line.qty or 0.0) - issued_qty
            if remaining_qty <= 0:
                continue

            move_commands.append((0, 0, {
                "name": line.name or line.product_id.display_name,
                "product_id": line.product_id.id,
                "product_uom_qty": remaining_qty,
                "product_uom": (line.uom_id or line.product_id.uom_id).id,
                "location_id": src_location.id,
                "location_dest_id": dest_location.id,
                "company_id": self.company_id.id,
                "work_order_id": self.id,
                "work_order_boq_line_id": line.id,
            }))

        if not move_commands:
            raise UserError(_("All BOQ material quantities are already issued."))

        picking = self.env["stock.picking"].create({
            "partner_id": self.partner_id.id,
            "origin": _("%s - Material Issue") % (self.name,),
            "picking_type_id": picking_type.id,
            "location_id": src_location.id,
            "location_dest_id": dest_location.id,
            "company_id": self.company_id.id,
            "work_order_id": self.id,
            "move_ids_without_package": move_commands,
        })
        picking.action_confirm()
        picking.action_assign()

        return {
            "type": "ir.actions.act_window",
            "name": _("Material Issue"),
            "res_model": "stock.picking",
            "view_mode": "form",
            "res_id": picking.id,
            "target": "current",
        }

    def action_mark_done(self):
        for rec in self:
            rec.state = "done"

    def action_cancel(self):
        for rec in self:
            rec.state = "cancel"
            rec._sync_work_order_budget_state("cancel")


class WorkOrderBOQ(models.Model):
    _name = "pr.work.order.boq"
    _description = "Work Order BOQ / Budget Lines"
    _order = "sequence, id"

    work_order_id = fields.Many2one("pr.work.order", ondelete="cascade")
    sale_order_line_id = fields.Many2one(
        "sale.order.line",
        string="Source Sales Order Line",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    sequence = fields.Integer(default=10)
    section_name = fields.Char("Section")

    display_type = fields.Selection([
        ('line_section', 'Section'),
        ('line_note', 'Note'),
        ('product', 'Product'),
    ], default='product')

    name = fields.Char("Description", required=True)

    product_id = fields.Many2one("product.product", string="Product")
    product_internal_reference = fields.Many2one(
        "product.internal.reference.lookup",
        string="Product Code",
        compute="_compute_product_internal_reference",
        inverse="_inverse_product_internal_reference",
        readonly=False,
    )
    uom_id = fields.Many2one("uom.uom", string="Unit")
    qty = fields.Float("Qty", digits="Product Unit of Measure")

    unit_cost = fields.Float("Unit Cost", digits="Product Price")

    total = fields.Float("Total", compute="_compute_total", store=True, digits="Product Price")

    can_edit_boq = fields.Boolean(
        compute="_compute_can_edit_boq",
        store=False
    )

    @api.depends()
    def _compute_can_edit_boq(self):
        user = self.env.user
        can_edit = (
                user.has_group("pr_work_order.custom_group_work_order_user")
                or user.has_group("pr_work_order.custom_group_work_order_management")
        )
        for line in self:
            line.can_edit_boq = can_edit

    @api.depends("qty", "unit_cost")
    def _compute_total(self):
        precision_cost = self.env["decimal.precision"].precision_get("Product Price")
        for rec in self:
            rec.total = float_round(
                (rec.qty or 0.0) * (rec.unit_cost or 0.0),
                precision_digits=precision_cost,
            )

    @api.depends("product_id")
    def _compute_product_internal_reference(self):
        ProductRef = self.env["product.internal.reference.lookup"]
        for line in self:
            line.product_internal_reference = ProductRef.browse(line.product_id.id) if line.product_id else False

    def _inverse_product_internal_reference(self):
        for line in self:
            product = line.product_internal_reference.product_id
            if line.product_id != product:
                line.product_id = product

    def _get_purchase_requisition_description(self):
        """Keep WO wording, recovering source text when only a product label remains."""
        self.ensure_one()
        description = (self.name or "").strip()
        product = self.product_id
        product_labels = {
            (product.name or "").strip(),
            (product.display_name or "").strip(),
            (product.with_context(display_default_code=False).display_name or "").strip(),
        }
        if description and description not in product_labels:
            return description
        # Use explicit source links: matching by product alone mixes separate
        # lines that intentionally use the same product with different specs.
        for field_name in ("sale_order_line_id", "estimation_line_id"):
            source = self[field_name] if field_name in self._fields else False
            if source and source.product_id == product and (source.name or "").strip():
                return source.name.strip()
        return description or product.with_context(display_default_code=False).display_name or ""

    @api.onchange("product_internal_reference")
    def _onchange_product_internal_reference(self):
        for line in self:
            product = line.product_internal_reference.product_id
            if line.product_id == product:
                continue
            line.product_id = product
            if line.product_id:
                line.name = line.product_id.display_name
                line.uom_id = line.product_id.uom_id
                line.unit_cost = line.product_id.standard_price
            else:
                line.product_internal_reference = False

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.mapped("work_order_id")._ensure_project_expense_bucket(sync_budget=True)
        return records

    def write(self, vals):
        res = super().write(vals)
        self.mapped("work_order_id")._ensure_project_expense_bucket(sync_budget=True)
        return res

    def unlink(self):
        work_orders = self.mapped("work_order_id")
        res = super().unlink()
        work_orders._ensure_project_expense_bucket(sync_budget=True)
        return res


class WorkOrderCostCenter(models.Model):
    _name = "pr.work.order.cost.center"
    _description = "Work Order Dynamic Cost Centers"
    _order = "sequence"
    _rec_name = "section_name"

    work_order_id = fields.Many2one("pr.work.order", ondelete="cascade")

    section_name = fields.Char("Section")
    analytic_account_id = fields.Many2one("account.analytic.account", string="Cost Center")
    sequence = fields.Integer(default=10)

    partner_id = fields.Many2one("res.partner", string="Partner")

    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id
    )

    estimated_cost = fields.Monetary(
        string="Total Cost",
        currency_field="currency_id",
        compute="_compute_estimated_cost",
        store=True,
    )
    department_id = fields.Many2one('account.analytic.account', string="Department",
                                    domain="[('analytic_plan_type', '=', 'department')]")
    section_id = fields.Many2one('account.analytic.account', string="Section",
                                 domain="[('analytic_plan_type', '=', 'section')]")
    spent_amount = fields.Monetary(
        string="Spent",
        currency_field="currency_id",
        compute="_compute_spent_amount",
        store=False,
    )

    remaining_amount = fields.Monetary(
        string="Remaining",
        currency_field="currency_id",
        compute="_compute_remaining_amount",
        store=False,
    )

    @api.depends("analytic_account_id")
    def _compute_spent_amount(self):
        analytics = self.mapped("analytic_account_id").sudo()
        spent_by_analytic = analytics._get_po_budget_spent_map() if analytics else {}
        for rec in self:
            rec.spent_amount = spent_by_analytic.get(rec.analytic_account_id.id, 0.0) if rec.analytic_account_id else 0.0

    def _compute_remaining_amount(self):
        for rec in self:
            rec.remaining_amount = (rec.estimated_cost or 0.0) - (rec.spent_amount or 0.0)

    @api.depends(
        "work_order_id.boq_line_ids.qty",
        "work_order_id.boq_line_ids.unit_cost",
        "work_order_id.boq_line_ids.total",
        "work_order_id.boq_line_ids.section_name",
        "section_name",
        "analytic_account_id",
    )
    def _compute_estimated_cost(self):
        precision_cost = self.env["decimal.precision"].precision_get("Product Price")
        for rec in self:
            lines = rec.work_order_id.boq_line_ids.filtered(
                lambda l: l.display_type not in ("line_section", "line_note")
                          and l.section_name == rec.section_name
            )
            rec.estimated_cost = float_round(sum(lines.mapped("total")), precision_digits=precision_cost)

            analytic = rec.analytic_account_id
            if not analytic:
                continue

            analytic_vals = {}
            if "budget_type" in analytic._fields:
                analytic_vals["budget_type"] = "capex"
            if "budget_allowance" in analytic._fields:
                analytic_vals["budget_allowance"] = rec.estimated_cost

            if analytic_vals:
                analytic.sudo().write(analytic_vals)

    @api.onchange("department_id", "section_id")
    def _sync_fields_to_analytic_account(self):
        for rec in self:
            analytic = rec.analytic_account_id
            if analytic:
                analytic.write({
                    "department_id": rec.department_id.id,
                    "section_id": rec.section_id.id,
                })

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.mapped("work_order_id")._ensure_project_expense_bucket(sync_budget=True)
        return records

    def write(self, vals):
        res = super().write(vals)
        self.mapped("work_order_id")._ensure_project_expense_bucket(sync_budget=True)
        return res

    def unlink(self):
        work_orders = self.mapped("work_order_id")
        res = super().unlink()
        work_orders._ensure_project_expense_bucket(sync_budget=True)
        return res


class PRWorkOrderRejectWizard(models.TransientModel):
    _name = "pr.work.order.reject.wizard"
    _description = "Reject Work Order"

    work_order_id = fields.Many2one(
        "pr.work.order",
        string="Work Order",
        required=True,
        readonly=True,
    )

    reason = fields.Text(string="Rejection Reason", required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        wo = self.work_order_id

        if wo.state in ("done", "cancel"):
            raise UserError(_("You cannot reject a completed or cancelled Work Order."))

        wo.write({
            "state": "draft",
            "rejection_reason": self.reason,
            "rejected_by": self.env.user.id,
            "rejected_date": fields.Datetime.now(),
        })

        wo._reset_approval_metadata()
        wo.write({
            "rejection_reason": self.reason,
            "rejected_by": self.env.user.id,
            "rejected_date": fields.Datetime.now(),
        })
        wo._sync_work_order_budget_state("rejected")

        wo.message_post(
            body=_(
                "<b>Work Order Rejected</b><br/>"
                "<b>Reason:</b> %s"
            ) % self.reason
        )

        return {"type": "ir.actions.act_window_close"}
