from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import format_amount
from odoo.tools.float_utils import float_compare


class SaleOrder(models.Model):
    _inherit = "sale.order"

    pr_credit_company_currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        string="Credit Currency",
        readonly=True,
    )
    pr_credit_limit_partner_id = fields.Many2one(
        "res.partner",
        string="Credit Customer",
        compute="_compute_pr_credit_limit_status",
    )
    pr_is_credit_payment_term = fields.Boolean(
        string="Credit Payment Term",
        compute="_compute_pr_credit_limit_status",
    )
    pr_approved_credit_limit = fields.Monetary(
        string="Approved Credit Limit",
        compute="_compute_pr_credit_limit_status",
        currency_field="pr_credit_company_currency_id",
    )
    pr_credit_exposure_before_order = fields.Monetary(
        string="Existing Credit Exposure",
        compute="_compute_pr_credit_limit_status",
        currency_field="pr_credit_company_currency_id",
    )
    pr_credit_projected_exposure = fields.Monetary(
        string="Projected Credit Exposure",
        compute="_compute_pr_credit_limit_status",
        currency_field="pr_credit_company_currency_id",
    )
    pr_credit_remaining_after_order = fields.Monetary(
        string="Remaining Credit After SO",
        compute="_compute_pr_credit_limit_status",
        currency_field="pr_credit_company_currency_id",
    )
    pr_credit_exceeded_amount = fields.Monetary(
        string="Credit Exceeded By",
        compute="_compute_pr_credit_limit_status",
        currency_field="pr_credit_company_currency_id",
    )

    def _pr_uses_credit_payment_term(self):
        self.ensure_one()
        term = self.payment_term_id
        if not term:
            return False

        term_name = (term.name or "").strip().lower()
        if "credit" in term_name:
            return True
        if "advance" in term_name or "immediate" in term_name:
            return False

        return any((line.nb_days or 0) > 0 for line in term.line_ids)

    def _pr_order_amount_company_currency(self):
        self.ensure_one()
        company = self.company_id or self.env.company
        company_currency = company.currency_id
        order_currency = self.currency_id or company_currency
        conversion_date = fields.Date.to_date(self.date_order) if self.date_order else fields.Date.context_today(self)
        return company_currency.round(
            order_currency._convert(self.amount_total or 0.0, company_currency, company, conversion_date)
        )

    def _pr_credit_open_order_amount_company_currency(self):
        self.ensure_one()
        if not self._pr_uses_credit_payment_term():
            return 0.0

        company = self.company_id or self.env.company
        company_currency = company.currency_id
        order_total = self._pr_order_amount_company_currency()
        posted_invoices = self.invoice_ids.filtered(
            lambda move: move.state == "posted" and move.move_type in ("out_invoice", "out_refund")
        )
        posted_total = sum(posted_invoices.mapped("amount_total_signed"))
        return max(company_currency.round(order_total - posted_total), 0.0)

    @api.depends(
        "partner_id",
        "payment_term_id",
        "amount_total",
        "currency_id",
        "company_id",
        "date_order",
        "state",
        "invoice_ids.state",
        "invoice_ids.move_type",
        "invoice_ids.amount_total_signed",
    )
    def _compute_pr_credit_limit_status(self):
        for order in self:
            company = order.company_id or self.env.company
            currency = company.currency_id
            partner = order.partner_id.commercial_partner_id if order.partner_id else self.env["res.partner"]
            is_credit_term = order._pr_uses_credit_payment_term() if order.payment_term_id else False

            limit = partner.pr_credit_limit_amount if partner and partner.pr_credit_limit_enabled else 0.0
            exposure_before = 0.0
            current_order_exposure = 0.0
            projected = 0.0

            if partner and is_credit_term:
                exposure_before = partner._pr_get_credit_exposure(company, exclude_sale_order=order)
                if order.state in ("sale", "done"):
                    current_order_exposure = order._pr_credit_open_order_amount_company_currency()
                else:
                    current_order_exposure = order._pr_order_amount_company_currency()
                projected = currency.round(exposure_before + current_order_exposure)

            remaining = currency.round(limit - projected)

            order.pr_credit_limit_partner_id = partner
            order.pr_is_credit_payment_term = is_credit_term
            order.pr_approved_credit_limit = limit
            order.pr_credit_exposure_before_order = exposure_before
            order.pr_credit_projected_exposure = projected
            order.pr_credit_remaining_after_order = remaining
            order.pr_credit_exceeded_amount = max(currency.round(projected - limit), 0.0) if is_credit_term else 0.0

    def _pr_check_credit_limit_before_confirm(self):
        for order in self:
            if not order._pr_uses_credit_payment_term():
                continue

            partner = order.partner_id.commercial_partner_id
            company = order.company_id or self.env.company
            currency = company.currency_id

            if not partner.pr_credit_limit_enabled or currency.is_zero(partner.pr_credit_limit_amount or 0.0):
                raise ValidationError(_(
                    "Customer %(customer)s has no approved credit limit. "
                    "Please approve a Customer Credit Limit Request before confirming credit sales orders."
                ) % {"customer": partner.display_name})

            exposure_before = partner._pr_get_credit_exposure(company, exclude_sale_order=order)
            order_amount = order._pr_order_amount_company_currency()
            projected = currency.round(exposure_before + order_amount)
            limit = currency.round(partner.pr_credit_limit_amount or 0.0)

            if float_compare(projected, limit, precision_rounding=currency.rounding) > 0:
                remaining = currency.round(limit - exposure_before)
                exceeded = currency.round(projected - limit)
                raise ValidationError(_(
                    "Cannot confirm %(order)s because it exceeds the approved credit limit for %(customer)s.\n\n"
                    "Approved Limit: %(limit)s\n"
                    "Existing Exposure: %(exposure)s\n"
                    "This Sale Order: %(order_amount)s\n"
                    "Remaining Before This SO: %(remaining)s\n"
                    "Exceeded By: %(exceeded)s"
                ) % {
                    "order": order.name or _("this quotation"),
                    "customer": partner.display_name,
                    "limit": format_amount(self.env, limit, currency),
                    "exposure": format_amount(self.env, exposure_before, currency),
                    "order_amount": format_amount(self.env, order_amount, currency),
                    "remaining": format_amount(self.env, remaining, currency),
                    "exceeded": format_amount(self.env, exceeded, currency),
                })

    def action_confirm(self):
        self._pr_check_credit_limit_before_confirm()
        return super().action_confirm()
