from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta


class CustomPR(models.Model):
    _name = 'custom.pr'
    _description = 'Custom Purchase Requisition'

    name = fields.Char(string="PR Number", readonly=True, copy=False)
    pr_type = fields.Selection(
        [('standard', 'PR'), ('cash', 'Cash PR')],
        string="Type",
        default='standard',
        required=True,
    )
    requested_by = fields.Char(string="Requested By")
    requested_user_id = fields.Many2one('res.users', string="Requested User", readonly=True)
    date_request = fields.Datetime(string="Request Date", default=fields.Datetime.now, required=True, readonly=True)
    description = fields.Text(string="Description")
    department = fields.Char(string="Department")
    supervisor = fields.Char(string="Supervisor")
    supervisor_partner_id = fields.Char(string="supervisor_partner_id")
    required_date = fields.Date(string="Required Date", required=True, readonly=True)
    priority = fields.Selection(
        [("low", "Low"), ("medium", "Medium"), ("high", "High"), ("urgent", "Urgent")],
        string="Priority",
        required=True,
        default="low",
    )
    comments = fields.Text(string="Comments")
    notes = fields.Text(string="Notes")
    rejection_reason = fields.Text(string="Reason for Rejection")
    approval = fields.Selection(
        [("pending", "Pending"), ("rejected", "Rejected"), ("approved", "Approved")],
        default="pending",
        string="Internal Approval",
    )
    wo_variance_requires_approval = fields.Boolean(
        string="WO Variance Requires Approval",
        default=False,
        help="Checked when requested quantity/unit cost exceeds WO product baselines but total amount remains within allowed WO amount.",
    )

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
    pr_created = fields.Boolean(string="PR Created", default=False)
    purchase_requisition_id = fields.Many2one(
        "purchase.requisition",
        string="Linked Purchase Requisition",
        readonly=True,
        copy=False,
        index=True,
    )
    legacy_migrated = fields.Boolean(
        string="Migrated to Purchase Requisition",
        readonly=True,
        copy=False,
    )
    line_ids = fields.One2many('custom.pr.line', 'pr_id', string="PR Lines")
    expense_type = fields.Selection(
        [('opex', 'Opex'), ('capex', 'Capex')],
        string='Expense Type',
        required=True,
    )
    expense_bucket_id = fields.Many2one(
        'crossovered.budget',
        string='Expense',
        required=True,
        domain="[('expense_type', '=', expense_type), ('state', 'in', ['validate', 'done']), ('pr_under_revision', '=', False)]",
    )
    allowed_cost_center_ids = fields.Many2many(
        "account.analytic.account",
        compute="_compute_allowed_cost_center_ids",
        store=False,
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('rfq_sent', 'RFQ Sent'),
            ('pending', 'Pending'),
            ('purchase', 'Purchase Order'),
            ('cancel', 'Cancelled'),
        ],
        string="Status",
        default='draft',
        tracking=True,
    )
    budget_increase_request_count = fields.Integer(compute="_compute_budget_increase_request_count")
    show_request_budget_increase_button = fields.Boolean(
        compute="_compute_show_request_budget_increase_button"
    )
    linked_requisition_status = fields.Selection(
        [
            ('missing', 'Not Created'),
            ('pending', 'Pending Approval'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
        ],
        string="PR Approval Status",
        compute="_compute_linked_document_statuses",
    )
    linked_rfq_status = fields.Selection(
        [
            ('missing', 'Not Created'),
            ('draft', 'Draft'),
            ('sent', 'RFQ Sent'),
            ('pending', 'Pending Approval'),
            ('purchase', 'Purchase Order'),
            ('done', 'Locked'),
            ('rejected', 'Rejected'),
            ('cancel', 'Cancelled'),
        ],
        string="RFQ Status",
        compute="_compute_linked_document_statuses",
    )
    linked_quotation_status = fields.Selection(
        [
            ('missing', 'Not Submitted'),
            ('quote', 'Quote'),
            ('po', 'Purchase'),
        ],
        string="Quotation Status",
        compute="_compute_linked_document_statuses",
    )
    linked_po_status = fields.Selection(
        [
            ('missing', 'Not Created'),
            ('draft', 'RFQ'),
            ('sent', 'RFQ Sent'),
            ('pending', 'Pending'),
            ('purchase', 'Purchase Order'),
            ('done', 'Locked'),
            ('rejected', 'Rejected'),
            ('cancel', 'Cancelled'),
        ],
        string="Purchase Order Status",
        compute="_compute_linked_document_statuses",
    )

    @api.depends("expense_bucket_id", "expense_bucket_id.crossovered_budget_line",
                 "expense_bucket_id.crossovered_budget_line.analytic_account_id")
    def _compute_allowed_cost_center_ids(self):
        for rec in self:
            rec.allowed_cost_center_ids = rec.expense_bucket_id.crossovered_budget_line.mapped("analytic_account_id")

    def _compute_linked_document_statuses(self):
        rfq_priority = {
            'draft': 1, 'sent': 2, 'cancel': 3, 'rejected': 4,
            'pending': 5, 'purchase': 6, 'done': 7,
        }
        po_priority = {
            'draft': 1, 'sent': 2, 'cancel': 3, 'rejected': 4,
            'pending': 5, 'purchase': 6, 'done': 7,
        }

        for rec in self:
            requisition = rec.purchase_requisition_id or self.env['purchase.requisition'].sudo().search([('name', '=', rec.name)], limit=1)
            rec.linked_requisition_status = requisition.approval if requisition else 'missing'

            rfqs = self.env['purchase.order'].sudo().search([('pr_name', '=', rec.name)])
            if rfqs:
                best_rfq = max(rfqs, key=lambda rfq: rfq_priority.get(rfq.state, 0))
                rec.linked_rfq_status = best_rfq.state
            else:
                rec.linked_rfq_status = 'missing'

            rfqs_for_quote_status = self.env['purchase.order'].sudo().search([('pr_name', '=', rec.name)])
            if rfqs_for_quote_status:
                best_rfq_for_quote = max(rfqs_for_quote_status, key=lambda rfq: po_priority.get(rfq.state, 0))
                rec.linked_quotation_status = (
                    'po'
                    if best_rfq_for_quote.state in ('pending', 'purchase', 'done', 'rejected')
                    else 'quote'
                )
            else:
                rec.linked_quotation_status = 'missing'

            purchase_orders = self.env['purchase.order'].sudo().search([('pr_name', '=', rec.name)])
            if purchase_orders:
                best_po = max(purchase_orders, key=lambda po: po_priority.get(po.state, 0))
                rec.linked_po_status = best_po.state
            else:
                rec.linked_po_status = 'missing'

    def _compute_budget_increase_request_count(self):
        Request = self.env['budget.increase.request'].sudo()
        for rec in self:
            rec.budget_increase_request_count = Request.search_count([('custom_pr_id', '=', rec.id)])

    def _budget_usage_date(self):
        self.ensure_one()
        return fields.Date.to_date(self.date_request) or fields.Date.context_today(self)

    def _amount_by_cost_center(self):
        self.ensure_one()
        amount_by_cost_center = {}
        for line in self.line_ids:
            if not line.cost_center_id:
                continue
            cc = line.cost_center_id.sudo()
            amount_by_cost_center.setdefault(cc.id, {"cc": cc, "amount": 0.0})
            amount_by_cost_center[cc.id]["amount"] += line.total_price
        return amount_by_cost_center

    def _get_selected_budget_remaining_by_cost_center(self):
        self.ensure_one()
        if not self.expense_bucket_id:
            return {}
        return self.expense_bucket_id.sudo()._get_remaining_by_cost_center()

    def _get_selected_budget_requisition(self):
        self.ensure_one()
        if not self.expense_bucket_id or "pr.budget.requisition" not in self.env:
            return False
        return self.env["pr.budget.requisition"].sudo().search([
            ("generated_budget_id", "=", self.expense_bucket_id.id),
        ], order="revision_number desc, id desc", limit=1)

    @api.depends(
        'line_ids.total_price',
        'line_ids.cost_center_id',
        'expense_bucket_id',
        'expense_bucket_id.budget_remaining_amount',
    )
    def _compute_show_request_budget_increase_button(self):
        for rec in self:
            remaining_by_cost_center = rec._get_selected_budget_remaining_by_cost_center()
            rec.show_request_budget_increase_button = any(
                item['amount'] > remaining_by_cost_center.get(item['cc'].id, 0.0)
                for item in rec._amount_by_cost_center().values()
            ) and bool(rec._get_selected_budget_requisition())

    def _required_date_from_priority(self, priority):
        today = fields.Date.context_today(self)
        offsets = {
            'low': 30,
            'medium': 10,
            'high': 3,
            'urgent': 0,
        }
        return today + relativedelta(days=offsets.get(priority, 0))

    @api.onchange('priority')
    def _onchange_priority_set_required_date(self):
        for rec in self:
            if rec.priority:
                rec.required_date = rec._required_date_from_priority(rec.priority)

    @api.onchange('expense_type')
    def _onchange_expense_type(self):
        for rec in self:
            if rec.expense_bucket_id and rec.expense_bucket_id.expense_type != rec.expense_type:
                rec.expense_bucket_id = False

    @api.depends('line_ids.total_price')
    def _compute_totals(self):
        for rec in self:
            subtotal = sum(line.total_price for line in rec.line_ids)
            rec.total_excl_vat = subtotal
            rec.vat_amount = subtotal * 0.15
            rec.total_incl_vat = subtotal + rec.vat_amount

    @api.model
    def create(self, vals):
        if vals.get('priority'):
            vals['required_date'] = self._required_date_from_priority(vals['priority'])
        if vals.get('pr_type') == 'cash':
            vals['name'] = self.env['ir.sequence'].next_by_code('custom.cash.pr') or '/'
        else:
            vals['name'] = self.env['ir.sequence'].next_by_code('custom.pr') or '/'
        return super(CustomPR, self).create(vals)

    @api.model
    def default_get(self, fields_list):
        res = super(CustomPR, self).default_get(fields_list)

        # Get current user
        user = self.env.user
        employee = self.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)

        supervisor_user = user.supervisor_user_id

        if employee:
            res.update({
                'requested_by': employee.name,
                'requested_user_id': user.id,
                'department': employee.department_id.name if employee.department_id else False,
                'supervisor': supervisor_user.name if supervisor_user else (
                    employee.parent_id.name if employee.parent_id else False),
                'supervisor_partner_id': (
                    supervisor_user.partner_id.id if supervisor_user and supervisor_user.partner_id
                    else (
                        employee.parent_id.user_id.partner_id.id if employee.parent_id and employee.parent_id.user_id else False)
                ),
            })
        else:
            res.update({
                'requested_by': user.name,
                'requested_user_id': user.id,
                'supervisor': supervisor_user.name if supervisor_user else False,
                'supervisor_partner_id': supervisor_user.partner_id.id if supervisor_user and supervisor_user.partner_id else False,
            })

        return res

    def _prepare_source_product_line_values(self):
        """Build PR line values from the selected budget source document.

        Project budgets are sourced from Work Order BOQ lines, while trading
        budgets are sourced from Sale Order lines. Quantities are reduced by
        quantities already requested on other non-rejected PRs for the same
        budget/cost center/product so the generated lines are immediately
        selectable/editable without exceeding the source document baseline.
        """
        self.ensure_one()
        bucket = self.expense_bucket_id.sudo()
        if not bucket:
            return []

        def _remaining_quantity(cost_center, product, allowed_qty):
            if not cost_center or not product:
                return 0.0
            domain = [
                ("id", "not in", self.line_ids.ids),
                ("pr_id.expense_bucket_id", "=", bucket.id),
                ("pr_id.approval", "!=", "rejected"),
                ("cost_center_id", "=", cost_center.id),
                ("description", "=", product.id),
            ]
            if isinstance(self.id, int):
                domain.append(("pr_id", "!=", self.id))
            other_lines = self.env["custom.pr.line"].sudo().search(domain)
            remaining = (allowed_qty or 0.0) - sum(other_lines.mapped("quantity"))
            return remaining if remaining > 0.0 else 0.0

        grouped = {}

        def _add_line(cost_center, product, quantity, unit, unit_price):
            if not cost_center or not product or quantity <= 0.0:
                return
            key = (cost_center.id, product.id, unit.id if unit else False)
            data = grouped.setdefault(key, {
                "cost_center_id": cost_center.id,
                "description": product.id,
                "quantity": 0.0,
                "unit": unit.id if unit else product.uom_id.id,
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
            for boq_line in work_order.boq_line_ids.sorted(key=lambda l: (l.sequence, l.id)):
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
            for sale_line in sale_order.order_line.sorted(key=lambda l: (l.sequence, l.id)):
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
            (line.cost_center_id.id, line.description.id, line.unit.id if line.unit else False)
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

    def action_create_pr(self):
        self.ensure_one()
        rec = self

        # Check required fields
        if not rec.line_ids:
            raise ValidationError("You must add at least one line before submitting the Purchase Requisition.")
        if rec.expense_bucket_id.state not in ("validate", "done"):
            raise ValidationError(
                _("Only validated budgets can be used. Please submit and approve the selected budget first.")
            )
        rec.expense_bucket_id._check_active_for_date(rec._budget_usage_date())

        # Enforce WO per-product mini-budget caps at submit time as a hard gate
        # (in addition to line-level constrains) so users cannot bypass via UI flow.
        rec.line_ids._check_work_order_product_limits()

        wo_variance_requires_approval = False
        for line in rec.line_ids:
            caps = line._get_wo_product_caps()
            if not caps:
                continue
            if line.quantity > caps['allowed_qty'] or line.unit_price > caps['allowed_unit_price']:
                wo_variance_requires_approval = True
                break

        if rec.wo_variance_requires_approval != wo_variance_requires_approval:
            rec.wo_variance_requires_approval = wo_variance_requires_approval

        # Validate cost center budget per line (supports multiple cost centers in one PR)
        amount_by_cost_center = rec._amount_by_cost_center()
        remaining_by_cost_center = rec._get_selected_budget_remaining_by_cost_center()
        for line in rec.line_ids:
            cost_center = line.cost_center_id.sudo()
            if not cost_center:
                raise ValidationError(
                    f"Please select a cost center for line '{line.description.display_name}'."
                )

        for item in amount_by_cost_center.values():
            cost_center = item["cc"]
            required_amount = item["amount"]
            remaining = remaining_by_cost_center.get(cost_center.id, 0.0)
            if required_amount > remaining:
                raise ValidationError(
                    f"This cost center {cost_center.display_name}has low budget for this PR "
                    f"Required budget is SAR. ({required_amount}) Remaining budget is SAR. ({remaining})."
                )

        # Validation: prevent 0 amount PR
        if rec.total_excl_vat == 0.00:
            raise ValidationError("Add Unit Price First.")

        requisition = rec._ensure_purchase_requisition_from_legacy(
            skip_notifications=False,
            wo_variance_requires_approval=wo_variance_requires_approval,
        )

        rec.pr_created = True

        return rec.action_open_purchase_requisition()

    def _get_existing_purchase_requisition(self):
        self.ensure_one()
        requisition = self.purchase_requisition_id
        if not requisition and self.name:
            requisition = self.env["purchase.requisition"].sudo().search([("name", "=", self.name)], limit=1)
        return requisition

    def _prepare_purchase_requisition_vals(self, wo_variance_requires_approval=False):
        self.ensure_one()
        requester = self.requested_user_id.sudo() if self.requested_user_id else self.env.user.sudo()
        supervisor_user = requester.supervisor_user_id if requester else False
        supervisor_name = self.supervisor or (supervisor_user.name if supervisor_user else False)
        supervisor_partner_id = self.supervisor_partner_id or (
            supervisor_user.partner_id.id if supervisor_user and supervisor_user.partner_id else False
        )
        return {
            "name": self.name,
            "date_request": fields.Date.to_date(self.date_request) or fields.Date.context_today(self),
            "requested_user_id": requester.id if requester else False,
            "requested_by": self.requested_by,
            "department": self.department,
            "supervisor": supervisor_name,
            "supervisor_partner_id": str(supervisor_partner_id) if supervisor_partner_id else False,
            "required_date": self.required_date,
            "priority": self.priority,
            "notes": self.notes,
            "comments": self.comments,
            "approval": self.approval or "pending",
            "status": self._map_legacy_status(),
            "pr_type": "cash" if self.pr_type == "cash" else "pr",
            "wo_variance_requires_approval": wo_variance_requires_approval,
            "expense_bucket_id": self.expense_bucket_id.id,
            "expense_scope": self.expense_bucket_id.scope,
            "expense_type": self.expense_type,
            "legacy_custom_pr_id": self.id,
        }

    def _prepare_purchase_requisition_line_vals(self):
        self.ensure_one()
        line_vals = []
        for line in self.line_ids:
            line_vals.append({
                "description": line.description.id,
                "line_description": line.line_description,
                "type": line.type,
                "cost_center_id": line.cost_center_id.id,
                "quantity": line.quantity,
                "unit": line.unit.name if line.unit else False,
                "unit_price": line.unit_price,
            })
        return line_vals

    def _map_legacy_status(self):
        self.ensure_one()
        return {
            "draft": "pr",
            "pending": "pr",
            "rfq_sent": "rfq",
            "purchase": "po",
            "cancel": "pr",
        }.get(self.state or "draft", "pr")

    def _link_purchase_requisition(self, requisition):
        self.ensure_one()
        if requisition:
            self.sudo().write({
                "purchase_requisition_id": requisition.id,
                "legacy_migrated": True,
                "pr_created": True,
            })
            if "legacy_custom_pr_id" in requisition._fields and not requisition.legacy_custom_pr_id:
                requisition.sudo().legacy_custom_pr_id = self.id

    def _ensure_purchase_requisition_from_legacy(self, skip_notifications=True, wo_variance_requires_approval=False):
        self.ensure_one()
        requisition = self._get_existing_purchase_requisition()
        if requisition:
            self._link_purchase_requisition(requisition)
            if not requisition.line_ids and self.line_ids:
                for line_vals in self._prepare_purchase_requisition_line_vals():
                    line_vals["requisition_id"] = requisition.id
                    self.env["purchase.requisition.line"].sudo().create(line_vals)
            return requisition

        requisition = self.env["purchase.requisition"].sudo().with_context(
            skip_pr_notifications=skip_notifications
        ).create({
            **self._prepare_purchase_requisition_vals(wo_variance_requires_approval),
            "line_ids": [
                (0, 0, line_vals)
                for line_vals in self._prepare_purchase_requisition_line_vals()
            ],
        })
        self._link_purchase_requisition(requisition)
        requisition.message_post(
            body=_("Created from legacy Custom PR %s.") % self.display_name,
            message_type="notification",
        )
        return requisition

    def action_migrate_to_purchase_requisition(self):
        migrated = self.env["purchase.requisition"]
        for rec in self:
            migrated |= rec._ensure_purchase_requisition_from_legacy(skip_notifications=True)
        if len(migrated) == 1:
            requisition = migrated[0]
            return {
                "type": "ir.actions.act_window",
                "name": _("Purchase Requisition"),
                "res_model": "purchase.requisition",
                "res_id": requisition.id,
                "view_mode": "form",
                "target": "current",
            }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Legacy PR Migration"),
                "message": _("%s legacy Custom PR records are now linked to Purchase Requisitions.") % len(migrated),
                "sticky": False,
            },
        }

    @api.model
    def action_migrate_all_legacy_custom_prs(self):
        legacy_prs = self.search([("purchase_requisition_id", "=", False)])
        return legacy_prs.action_migrate_to_purchase_requisition()

    def action_open_purchase_requisition(self):
        self.ensure_one()
        requisition = self._get_existing_purchase_requisition()
        if not requisition:
            raise UserError(_("No linked Purchase Requisition exists yet."))
        self._link_purchase_requisition(requisition)
        return {
            "type": "ir.actions.act_window",
            "name": _("Purchase Requisition"),
            "res_model": "purchase.requisition",
            "res_id": requisition.id,
            "view_mode": "form",
            "target": "current",
        }


    def action_reset_to_draft(self):
        for rec in self:
            linked_pos = self.env["purchase.order"].sudo().search([("pr_name", "=", rec.name)])
            if linked_pos.filtered(lambda po: po.state in ("purchase", "done")):
                raise ValidationError(_("Cannot reset PR %s because it already has a confirmed Purchase Order.") % rec.name)

            linked_pos.sudo().unlink()
            linked_rfqs = self.env["purchase.order"].sudo().search([("pr_name", "=", rec.name)])
            linked_rfqs.unlink()
            linked_reqs = self.env["purchase.requisition"].sudo().search([("name", "=", rec.name)])
            linked_reqs.unlink()

            rec.write({
                "state": "draft",
                "approval": "pending",
                "rejection_reason": False,
                "pr_created": False,
            })

    def action_open_budget_requests(self):
        self.ensure_one()
        requisition = self._get_selected_budget_requisition()
        if requisition:
            return {
                'name': 'Budget Requisition',
                'type': 'ir.actions.act_window',
                'res_model': 'pr.budget.requisition',
                'view_mode': 'form',
                'res_id': requisition.id,
                'target': 'current',
            }
        return {
            'name': 'Budget Increase Requests',
            'type': 'ir.actions.act_window',
            'res_model': 'budget.increase.request',
            'view_mode': 'tree,form',
            'domain': [('custom_pr_id', '=', self.id)],
            'context': {'default_custom_pr_id': self.id},
        }

    def action_request_cash_pr_payment(self):
        self.ensure_one()
        if self.pr_type != "cash":
            raise UserError(_("Payment requests are only for Cash PRs."))
        requisition = self.env["purchase.requisition"].sudo().search([("name", "=", self.name)], limit=1)
        if not requisition:
            raise UserError(_("Create and approve the linked Cash PR before requesting payment."))
        return requisition.with_user(self.env.user).action_request_cash_pr_payment()

    def action_request_budget_increase(self):
        self.ensure_one()
        remaining_by_cost_center = self._get_selected_budget_remaining_by_cost_center()

        exceeded_cost_centers = [
            item for item in self._amount_by_cost_center().values()
            if item['amount'] > remaining_by_cost_center.get(item['cc'].id, 0.0)
        ]

        if not exceeded_cost_centers:
            raise ValidationError(
                _("All cost center lines are within budget. Budget revision is not required."))

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
            'type': 'ir.actions.act_window',
            'name': 'Budget Revision',
            'res_model': 'pr.budget.requisition',
            'res_id': requisition.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def write(self, vals):
        if vals.get('priority'):
            vals['required_date'] = self._required_date_from_priority(vals['priority'])
        return super(CustomPR, self).write(vals)

    @api.constrains('expense_type', 'expense_bucket_id')
    def _check_expense_type_bucket(self):
        for rec in self:
            if rec.expense_bucket_id and rec.expense_type and rec.expense_bucket_id.expense_type != rec.expense_type:
                raise ValidationError(_('Expense bucket must match selected expense type.'))
            if rec.expense_bucket_id and rec.expense_bucket_id.state not in ("validate", "done"):
                raise ValidationError(_('Selected budget must be validated before it can be used in PR.'))
            if rec.expense_bucket_id:
                rec.expense_bucket_id._check_active_for_date(rec._budget_usage_date())


class CustomPRLine(models.Model):
    _name = 'custom.pr.line'
    _description = 'Custom PR Line'

    _sql_constraints = [
        ('custom_pr_line_qty_non_negative', 'CHECK(quantity >= 0)', 'Quantity cannot be negative.'),
        ('custom_pr_line_price_non_negative', 'CHECK(unit_price >= 0)', 'Unit Price cannot be negative.'),
    ]

    pr_id = fields.Many2one('custom.pr', string="Purchase Requisition", ondelete="cascade")
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
    cost_center_id = fields.Many2one(
        'account.analytic.account',
        string='Cost Center',
        required=True,
        domain="[('id', 'in', pr_id.allowed_cost_center_ids)]",
    )

    @api.onchange('pr_id.expense_bucket_id')
    def _onchange_expense_bucket(self):
        for rec in self:
            bucket = rec.pr_id.expense_bucket_id
            allowed = bucket.crossovered_budget_line.mapped("analytic_account_id")
            if rec.cost_center_id and bucket and rec.cost_center_id not in allowed:
                rec.cost_center_id = False

    @api.constrains('cost_center_id', 'pr_id')
    def _check_cost_center_matches_bucket(self):
        for rec in self:
            bucket = rec.pr_id.expense_bucket_id
            allowed = bucket.crossovered_budget_line.mapped("analytic_account_id")
            if rec.cost_center_id and bucket and rec.cost_center_id not in allowed:
                raise ValidationError(_('Selected cost center must belong to the selected expense bucket.'))

    @api.depends("description")
    def _compute_product_internal_reference(self):
        ProductRef = self.env["product.internal.reference.lookup"]
        for line in self:
            line.product_internal_reference = ProductRef.browse(line.description.id) if line.description else False

    def _inverse_product_internal_reference(self):
        for line in self:
            line.description = line.product_internal_reference.product_id

    @api.onchange("product_internal_reference")
    def _onchange_product_internal_reference(self):
        for line in self:
            line.description = line.product_internal_reference.product_id
            line._onchange_description()
            line._onchange_product_set_price()
            if not line.description:
                line.product_internal_reference = False

    type = fields.Selection(
        [
            ('material', 'Material'),
            ('service', 'Service')
        ],
        string="Type",
        compute="_compute_type_from_product",
        store=True,
        readonly=True,
        required=False,
    )
    quantity = fields.Float(string="Quantity", default=1.0)
    # unit = fields.Selection(
    #     [
    #         ('Kilogram', 'Kilogram'),
    #         ('Gram', 'Gram'),
    #         ('Litre', 'Litre'),
    #         ('Millilitre', 'Millilitre'),
    #         ('Meter', 'Metre'),
    #         ('Each', 'Each'),
    #     ],
    #     string="Unit",
    #     required=True,
    # )
    unit = fields.Many2one(
        'uom.uom',
        string="Unit of Measure"
    )

    unit_price = fields.Float(
        string="Unit Cost",
        digits="Product Price",
        default=0.0,
    )

    @api.onchange("description", "unit")
    def _onchange_product_set_price(self):
        for rec in self:
            if not rec.description:
                rec.unit_price = 0.0
                return

            rec.unit_price = rec.description.standard_price or 0.0

            if rec.unit and rec.description.uom_id and rec.unit != rec.description.uom_id:
                rec.unit_price = rec.description.uom_id._compute_price(
                    rec.unit_price, rec.unit
                )

    total_price = fields.Float(string="Total", compute="_compute_total", store=True)

    @api.depends('quantity', 'unit_price')
    def _compute_total(self):
        for line in self:
            line.total_price = line.quantity * line.unit_price

    @api.onchange('description')
    def _onchange_description(self):
        for rec in self:
            if rec.description:
                rec.unit = rec.description.uom_po_id or rec.description.uom_id

    @api.depends('description', 'description.detailed_type')
    def _compute_type_from_product(self):
        for rec in self:
            if rec.description and rec.description.detailed_type == 'service':
                rec.type = 'service'
            else:
                rec.type = 'material'

    @api.constrains('quantity', 'unit_price')
    def _check_non_negative_values(self):
        for rec in self:
            if rec.quantity < 0:
                raise ValidationError('Quantity cannot be negative.')
            if rec.unit_price < 0:
                raise ValidationError('Unit Price cannot be negative.')

    def _get_wo_product_caps(self):
        """Return allowed qty/price/amount for this cost center + product from approved WO BOQ."""
        self.ensure_one()

        if not self.cost_center_id or not self.description:
            return False

        if 'pr.work.order.cost.center' not in self.env:
            return False

        wo_cc = self.env['pr.work.order.cost.center'].sudo().search([
            ('analytic_account_id', '=', self.cost_center_id.id),
            ('work_order_id.state', 'in',
             ['ops_approval', 'acc_approval', 'final_approval', 'approved', 'in_progress', 'done']),
        ], limit=1)

        if not wo_cc:
            return False

        boq_lines = wo_cc.work_order_id.boq_line_ids.filtered(
            lambda l: l.display_type not in ('line_section', 'line_note')
                      and l.section_name == wo_cc.section_name
                      and l.product_id
                      and l.product_id.id == self.description.id
        )

        if not boq_lines:
            return {
                'found_work_order': True,
                'allowed_qty': 0.0,
                'allowed_unit_price': 0.0,
                'allowed_amount': 0.0,
                'work_order': wo_cc.work_order_id,
                'section_name': wo_cc.section_name,
            }

        allowed_qty = sum(boq_lines.mapped('qty'))
        allowed_amount = sum(boq_lines.mapped('total'))
        allowed_unit_price = max(boq_lines.mapped('unit_cost') or [0.0])

        return {
            'found_work_order': True,
            'allowed_qty': allowed_qty,
            'allowed_unit_price': allowed_unit_price,
            'allowed_amount': allowed_amount,
            'work_order': wo_cc.work_order_id,
            'section_name': wo_cc.section_name,
        }

    def _get_trading_sale_product_caps(self):
        """Return allowed qty/price/amount for this cost center + product from confirmed Trading SO."""
        self.ensure_one()

        bucket = self.pr_id.expense_bucket_id
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
            elif len(self.pr_id.allowed_cost_center_ids) == 1 and self.cost_center_id in self.pr_id.allowed_cost_center_ids:
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

    @api.constrains('cost_center_id', 'description', 'quantity', 'unit_price', 'pr_id')
    def _check_work_order_product_limits(self):
        for rec in self:
            if not rec.cost_center_id or not rec.description:
                continue

            caps = rec._get_wo_product_caps()
            if not caps:
                continue

            if not caps['allowed_qty']:
                raise ValidationError(_(
                    "Product '%(product)s' is not budgeted in approved Work Order '%(wo)s' section '%(section)s' for cost center '%(cc)s'."
                ) % {
                                          'product': rec.description.display_name,
                                          'wo': caps['work_order'].display_name,
                                          'section': caps['section_name'] or '-',
                                          'cc': rec.cost_center_id.display_name,
                                      })

            sibling_lines = rec.pr_id.line_ids.filtered(
                lambda l: l.cost_center_id.id == rec.cost_center_id.id
                          and l.description.id == rec.description.id
            )
            current_pr_amount = sum(sibling_lines.mapped('total_price'))

            already_requested_lines = self.env['custom.pr.line'].sudo().search([
                ('id', 'not in', rec.pr_id.line_ids.ids),
                ('cost_center_id', '=', rec.cost_center_id.id),
                ('description', '=', rec.description.id),
                ('pr_id.approval', '!=', 'rejected'),
            ])
            already_requested_amount = sum(already_requested_lines.mapped('total_price'))

            total_requested_amount = current_pr_amount + already_requested_amount

            if total_requested_amount > caps['allowed_amount']:
                raise ValidationError(_(
                    "Requested amount for '%(product)s' exceeds Work Order amount for cost center '%(cc)s'. Allowed: %(allowed)s, Requested (including other PRs): %(requested)s."
                ) % {
                                          'product': rec.description.display_name,
                                          'cc': rec.cost_center_id.display_name,
                                          'allowed': caps['allowed_amount'],
                                          'requested': total_requested_amount,
                                      })

    @api.constrains("cost_center_id", "description", "quantity", "unit_price", "pr_id")
    def _check_trading_sale_order_product_limits(self):
        for rec in self:
            if not rec.cost_center_id or not rec.description or not rec.pr_id:
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

            sibling_lines = rec.pr_id.line_ids.filtered(
                lambda l: l.cost_center_id.id == rec.cost_center_id.id
                and l.description.id == rec.description.id
            )
            current_pr_qty = sum(sibling_lines.mapped("quantity"))
            current_pr_amount = sum(sibling_lines.mapped("total_price"))

            other_lines = self.env["custom.pr.line"].sudo().search([
                ("id", "not in", rec.pr_id.line_ids.ids),
                ("cost_center_id", "=", rec.cost_center_id.id),
                ("description", "=", rec.description.id),
                ("pr_id.expense_bucket_id", "=", rec.pr_id.expense_bucket_id.id),
                ("pr_id.approval", "!=", "rejected"),
            ])
            total_requested_qty = current_pr_qty + sum(other_lines.mapped("quantity"))
            total_requested_amount = current_pr_amount + sum(other_lines.mapped("total_price"))

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


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    pr_name = fields.Char(string="PR Name", readonly=True)

    def _update_pr_state(self):
        """Helper to sync PR state with the highest PO state for the same pr_name"""
        for order in self:
            if order.pr_name:
                pr = self.env['custom.pr'].sudo().search([('name', '=', order.pr_name)], limit=1)
                requisition = order.requisition_id or self.env["purchase.requisition"].sudo().search(
                    [("name", "=", order.pr_name)], limit=1
                )
                all_pos = self.env['purchase.order'].sudo().search([('pr_name', '=', order.pr_name)])
                if not all_pos:
                    continue
                priority = {'draft': 1, 'sent': 2, 'pending': 3, 'purchase': 4, 'done': 5, 'cancel': 6}
                best_po = max(all_pos, key=lambda po: priority.get(po.state, 0))

                if requisition:
                    status_mapping = {
                        'draft': 'rfq',
                        'sent': 'rfq',
                        'pending': 'po',
                        'purchase': 'po',
                        'done': 'completed',
                        'cancel': 'pr',
                    }
                    requisition.sudo().status = status_mapping.get(best_po.state, requisition.status)

                if pr:
                    mapping = {
                        'draft': 'draft',
                        'sent': 'rfq_sent',
                        'pending': 'pending',
                        'purchase': 'purchase',
                        'done': 'purchase',
                        'cancel': 'cancel',
                    }
                    pr.state = mapping.get(best_po.state, pr.state)

    @api.model
    def create(self, vals):
        order = super().create(vals)
        # When PO is created, immediately set PR → pending
        if order.pr_name:
            requisition = order.requisition_id or self.env["purchase.requisition"].sudo().search(
                [("name", "=", order.pr_name)], limit=1
            )
            if requisition:
                requisition.sudo().status = "rfq"
            pr = self.env['custom.pr'].sudo().search([('name', '=', order.pr_name)], limit=1)
            if pr:
                pr.state = 'pending'
        return order

    def write(self, vals):
        res = super().write(vals)
        if 'state' in vals:
            self._update_pr_state()
        return res

    def print_quotation(self):
        """Override Print RFQ to use custom PetroRaq Draft Invoice report"""
        return self.env.ref('pr_custom_purchase.petroraq_purchase_order_action_id').report_action(self)
