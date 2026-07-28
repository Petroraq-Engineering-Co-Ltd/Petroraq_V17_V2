from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


class ResPartner(models.Model):
    _inherit = "res.partner"

    pr_credit_limit_currency_id = fields.Many2one(
        "res.currency",
        string="Credit Limit Currency",
        default=lambda self: self.env.company.currency_id,
        readonly=True,
    )
    pr_credit_limit_enabled = fields.Boolean(
        string="Credit Facility Approved",
        readonly=True,
        copy=False,
        tracking=True,
    )
    pr_credit_limit_amount = fields.Monetary(
        string="Approved Credit Limit",
        currency_field="pr_credit_limit_currency_id",
        readonly=True,
        copy=False,
        tracking=True,
    )
    pr_credit_limit_approved_request_id = fields.Many2one(
        "pr.customer.credit.limit.request",
        string="Approved Credit Request",
        readonly=True,
        copy=False,
    )
    pr_credit_term_limit_ids = fields.One2many(
        "pr.customer.credit.term.limit",
        "partner_id",
        string="Approved Payment-Term Limits",
        readonly=True,
    )
    pr_credit_limit_receivable_exposure = fields.Monetary(
        string="Unpaid Receivables",
        compute="_compute_pr_credit_limit_exposure",
        currency_field="pr_credit_limit_currency_id",
    )
    pr_credit_limit_sale_order_exposure = fields.Monetary(
        string="Open Credit SO Exposure",
        compute="_compute_pr_credit_limit_exposure",
        currency_field="pr_credit_limit_currency_id",
    )
    pr_credit_limit_total_exposure = fields.Monetary(
        string="Total Credit Exposure",
        compute="_compute_pr_credit_limit_exposure",
        currency_field="pr_credit_limit_currency_id",
    )
    pr_credit_limit_remaining = fields.Monetary(
        string="Remaining Credit",
        compute="_compute_pr_credit_limit_exposure",
        currency_field="pr_credit_limit_currency_id",
    )
    pr_credit_limit_request_count = fields.Integer(
        string="Credit Requests",
        compute="_compute_pr_credit_limit_request_count",
    )

    def _pr_credit_limit_commercial_partner(self):
        self.ensure_one()
        return self.commercial_partner_id or self

    def _pr_get_receivable_exposure(self, company, payment_term=False):
        """Posted unpaid customer receivables in company currency."""
        self.ensure_one()
        commercial_partner = self._pr_credit_limit_commercial_partner()
        moves = self.env["account.move"].sudo().search([
            ("partner_id", "child_of", commercial_partner.id),
            ("company_id", "=", company.id),
            ("move_type", "in", ("out_invoice", "out_refund")),
            ("state", "=", "posted"),
            ("payment_state", "not in", ("paid", "reversed")),
            *([("invoice_payment_term_id", "=", payment_term.id)] if payment_term else []),
        ])
        exposure = sum(moves.mapped("amount_residual_signed"))
        return max(company.currency_id.round(exposure), 0.0)

    def _pr_get_sale_order_exposure(self, company, exclude_sale_order=False, payment_term=False):
        """Confirmed credit SO amount that has not yet become posted receivable."""
        self.ensure_one()
        commercial_partner = self._pr_credit_limit_commercial_partner()
        domain = [
            ("partner_id", "child_of", commercial_partner.id),
            ("company_id", "=", company.id),
            ("state", "in", ("sale", "done")),
        ]
        if exclude_sale_order:
            domain.append(("id", "not in", exclude_sale_order.ids))
        if payment_term:
            domain.append(("payment_term_id", "=", payment_term.id))
        orders = self.env["sale.order"].sudo().search(domain)
        exposure = sum(order._pr_credit_open_order_amount_company_currency() for order in orders)
        return max(company.currency_id.round(exposure), 0.0)

    def _pr_get_credit_exposure(self, company, exclude_sale_order=False, payment_term=False):
        self.ensure_one()
        return (
            self._pr_get_receivable_exposure(company, payment_term=payment_term)
            + self._pr_get_sale_order_exposure(
                company,
                exclude_sale_order=exclude_sale_order,
                payment_term=payment_term,
            )
        )

    def _pr_get_term_credit_limit(self, company, payment_term, on_date=False):
        self.ensure_one()
        if not payment_term:
            return self.env["pr.customer.credit.term.limit"]
        check_date = fields.Date.to_date(on_date) if on_date else fields.Date.context_today(self)
        return self.env["pr.customer.credit.term.limit"].sudo().search([
            ("partner_id", "=", self._pr_credit_limit_commercial_partner().id),
            ("company_id", "=", company.id),
            ("payment_term_id", "=", payment_term.id),
            "|",
            ("validity_start", "=", False),
            ("validity_start", "<=", check_date),
            "|",
            ("validity_end", "=", False),
            ("validity_end", ">=", check_date),
        ], limit=1)

    @api.depends("pr_credit_limit_amount", "pr_credit_limit_enabled")
    def _compute_pr_credit_limit_exposure(self):
        company = self.env.company
        currency = company.currency_id
        for partner in self:
            commercial_partner = partner._pr_credit_limit_commercial_partner()
            receivable = commercial_partner._pr_get_receivable_exposure(company)
            sale_orders = commercial_partner._pr_get_sale_order_exposure(company)
            total = currency.round(receivable + sale_orders)
            limit = commercial_partner.pr_credit_limit_amount if commercial_partner.pr_credit_limit_enabled else 0.0

            partner.pr_credit_limit_receivable_exposure = receivable
            partner.pr_credit_limit_sale_order_exposure = sale_orders
            partner.pr_credit_limit_total_exposure = total
            partner.pr_credit_limit_remaining = currency.round(limit - total)

    def _compute_pr_credit_limit_request_count(self):
        Request = self.env["pr.customer.credit.limit.request"].sudo()
        for partner in self:
            commercial_partner = partner._pr_credit_limit_commercial_partner()
            partner.pr_credit_limit_request_count = Request.search_count([
                ("partner_id", "=", commercial_partner.id),
            ])

    @api.constrains("pr_credit_limit_amount")
    def _check_pr_credit_limit_amount(self):
        for partner in self:
            currency = partner.pr_credit_limit_currency_id or self.env.company.currency_id
            if float_compare(
                partner.pr_credit_limit_amount or 0.0,
                0.0,
                precision_rounding=currency.rounding,
            ) < 0:
                raise ValidationError(_("Approved credit limit cannot be negative."))

    def write(self, vals):
        protected_fields = {
            "pr_credit_limit_enabled",
            "pr_credit_limit_amount",
            "pr_credit_limit_approved_request_id",
        }
        if (
            protected_fields.intersection(vals)
            and not self.env.context.get("pr_credit_limit_approval_write")
            and not self.env.context.get("install_mode")
        ):
            raise UserError(
                _("Customer credit limits can only be changed through an approved Credit Limit Request.")
            )
        return super().write(vals)

    def action_create_credit_limit_request(self):
        self.ensure_one()
        partner = self._pr_credit_limit_commercial_partner()
        return {
            "type": "ir.actions.act_window",
            "name": _("New Credit Limit Request"),
            "res_model": "pr.customer.credit.limit.request",
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_partner_id": partner.id,
                "default_requested_limit_amount": partner.pr_credit_limit_amount or 0.0,
            },
        }

    def action_create_opening_credit_facility(self):
        self.ensure_one()
        partner = self._pr_credit_limit_commercial_partner()
        return {
            "type": "ir.actions.act_window",
            "name": _("Enter Opening Credit Facility"),
            "res_model": "pr.customer.credit.limit.request",
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_partner_id": partner.id,
                "default_request_type": "migration",
                "default_requested_limit_amount": partner.pr_credit_limit_amount or 0.0,
            },
        }

    def action_revise_credit_facility(self):
        self.ensure_one()
        partner = self._pr_credit_limit_commercial_partner()
        term_commands = [
            (0, 0, {
                "payment_term_id": line.payment_term_id.id,
                "limit_amount": line.limit_amount,
            })
            for line in partner.pr_credit_term_limit_ids.filtered(
                lambda line: line.company_id == self.env.company
            )
        ]
        return {
            "type": "ir.actions.act_window",
            "name": _("Revise Credit Facility"),
            "res_model": "pr.customer.credit.limit.request",
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_partner_id": partner.id,
                "default_request_type": "revision",
                "default_requested_limit_amount": partner.pr_credit_limit_amount or 0.0,
                "default_term_line_ids": term_commands,
            },
        }

    def action_reset_credit_facility(self):
        self.ensure_one()
        partner = self._pr_credit_limit_commercial_partner()
        return {
            "type": "ir.actions.act_window",
            "name": _("Close Credit Facility"),
            "res_model": "pr.customer.credit.limit.request",
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_partner_id": partner.id,
                "default_request_type": "reset",
                "default_requested_limit_amount": 0.0,
            },
        }

    def action_open_credit_limit_requests(self):
        self.ensure_one()
        partner = self._pr_credit_limit_commercial_partner()
        return {
            "type": "ir.actions.act_window",
            "name": _("Credit Limit Requests"),
            "res_model": "pr.customer.credit.limit.request",
            "view_mode": "tree,form",
            "domain": [("partner_id", "=", partner.id)],
            "context": {"default_partner_id": partner.id},
        }
