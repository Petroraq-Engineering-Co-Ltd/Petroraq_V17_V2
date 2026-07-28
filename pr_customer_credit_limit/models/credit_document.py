from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CustomerCreditDocumentType(models.Model):
    _name = "pr.customer.credit.document.type"
    _description = "Customer Credit Document Type"
    _order = "sequence, name, id"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    required = fields.Boolean(
        string="Required for Submission",
        help="A credit facility request cannot be submitted until this document is uploaded.",
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
        help="Leave empty to use this document type in every company.",
    )
    note = fields.Text()

    _sql_constraints = [
        (
            "name_company_unique",
            "unique(name, company_id)",
            "A credit document type with this name already exists for the company.",
        ),
    ]


class CustomerCreditRequestDocument(models.Model):
    _name = "pr.customer.credit.request.document"
    _description = "Customer Credit Request Document"
    _order = "sequence, id"

    request_id = fields.Many2one(
        "pr.customer.credit.limit.request",
        required=True,
        ondelete="cascade",
    )
    document_type_id = fields.Many2one(
        "pr.customer.credit.document.type",
        string="Document",
        required=True,
        ondelete="restrict",
    )
    sequence = fields.Integer(related="document_type_id.sequence", store=True)
    required = fields.Boolean(
        string="Required",
        help="Snapshot of the requirement when the line was added to the request.",
    )
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "pr_credit_request_document_attachment_rel",
        "document_line_id",
        "attachment_id",
        string="Uploaded Files",
    )
    fulfilled = fields.Boolean(compute="_compute_fulfilled", store=True)
    note = fields.Char()

    _sql_constraints = [
        (
            "request_document_type_unique",
            "unique(request_id, document_type_id)",
            "Each document type can only occur once on a credit request.",
        ),
    ]

    @api.depends("attachment_ids")
    def _compute_fulfilled(self):
        for line in self:
            line.fulfilled = bool(line.attachment_ids)

    @api.model_create_multi
    def create(self, vals_list):
        requests = self.env["pr.customer.credit.limit.request"].browse(
            [vals.get("request_id") for vals in vals_list if vals.get("request_id")]
        )
        if any(request.state != "draft" for request in requests):
            raise UserError(_("Registration documents can only be added while the request is in Draft."))
        return super().create(vals_list)

    def write(self, vals):
        if any(line.request_id.state != "draft" for line in self):
            raise UserError(_("Registration documents can only be changed while the request is in Draft."))
        return super().write(vals)

    def unlink(self):
        # Checklist lines are controlled by configuration; deleting one must not
        # be a way to bypass a required document.
        required = self.filtered("required")
        if required and not self.env.context.get("pr_credit_document_cleanup"):
            raise UserError(
                _(
                    "Required document checklist lines cannot be deleted. "
                    "Change the document configuration for future requests instead."
                )
            )
        if any(line.request_id.state != "draft" for line in self):
            raise UserError(_("Registration documents can only be deleted while the request is in Draft."))
        return super().unlink()


class CustomerCreditRequestTerm(models.Model):
    _name = "pr.customer.credit.request.term"
    _description = "Requested Customer Credit Term Allocation"
    _order = "payment_term_id, id"

    request_id = fields.Many2one(
        "pr.customer.credit.limit.request",
        required=True,
        ondelete="cascade",
    )
    currency_id = fields.Many2one(related="request_id.currency_id", readonly=True)
    payment_term_id = fields.Many2one(
        "account.payment.term",
        string="Payment Term",
        required=True,
        ondelete="restrict",
        domain="[('petroraq_selectable', '=', True)]",
    )
    limit_amount = fields.Monetary(
        string="Allocated Limit",
        required=True,
        currency_field="currency_id",
    )
    note = fields.Char()

    _sql_constraints = [
        (
            "request_payment_term_unique",
            "unique(request_id, payment_term_id)",
            "A payment term can only be allocated once on the same request.",
        ),
        (
            "positive_term_limit",
            "CHECK(limit_amount > 0)",
            "The allocated payment-term limit must be greater than zero.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        requests = self.env["pr.customer.credit.limit.request"].browse(
            [vals.get("request_id") for vals in vals_list if vals.get("request_id")]
        )
        if any(request.state != "draft" for request in requests):
            raise UserError(_("Payment-term allocations can only be added while the request is in Draft."))
        return super().create(vals_list)

    def write(self, vals):
        if any(line.request_id.state != "draft" for line in self):
            raise UserError(_("Payment-term allocations can only be changed while the request is in Draft."))
        return super().write(vals)

    def unlink(self):
        if any(line.request_id.state != "draft" for line in self):
            raise UserError(_("Payment-term allocations can only be deleted while the request is in Draft."))
        return super().unlink()


class CustomerCreditTermLimit(models.Model):
    _name = "pr.customer.credit.term.limit"
    _description = "Approved Customer Credit Term Limit"
    _order = "payment_term_id, id"

    partner_id = fields.Many2one(
        "res.partner",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one("res.company", required=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id", readonly=True)
    payment_term_id = fields.Many2one(
        "account.payment.term",
        string="Payment Term",
        required=True,
        ondelete="restrict",
        index=True,
    )
    limit_amount = fields.Monetary(
        string="Approved Limit",
        required=True,
        currency_field="currency_id",
    )
    approved_request_id = fields.Many2one(
        "pr.customer.credit.limit.request",
        required=True,
        ondelete="restrict",
    )
    validity_start = fields.Date()
    validity_end = fields.Date()
    receivable_exposure = fields.Monetary(
        compute="_compute_exposure",
        currency_field="currency_id",
    )
    sale_order_exposure = fields.Monetary(
        compute="_compute_exposure",
        currency_field="currency_id",
    )
    total_exposure = fields.Monetary(
        compute="_compute_exposure",
        currency_field="currency_id",
    )
    remaining_amount = fields.Monetary(
        compute="_compute_exposure",
        currency_field="currency_id",
    )

    _sql_constraints = [
        (
            "partner_company_payment_term_unique",
            "unique(partner_id, company_id, payment_term_id)",
            "Only one active approved limit is allowed per customer and payment term.",
        ),
    ]

    @api.depends("partner_id", "company_id", "payment_term_id", "limit_amount")
    def _compute_exposure(self):
        for line in self:
            if not line.partner_id or not line.company_id or not line.payment_term_id:
                receivable = sale_orders = 0.0
            else:
                receivable = line.partner_id._pr_get_receivable_exposure(
                    line.company_id, payment_term=line.payment_term_id
                )
                sale_orders = line.partner_id._pr_get_sale_order_exposure(
                    line.company_id, payment_term=line.payment_term_id
                )
            total = line.currency_id.round(receivable + sale_orders)
            line.receivable_exposure = receivable
            line.sale_order_exposure = sale_orders
            line.total_exposure = total
            line.remaining_amount = line.currency_id.round(line.limit_amount - total)
