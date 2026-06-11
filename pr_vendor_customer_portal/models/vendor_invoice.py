# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PrPortalVendorInvoice(models.Model):
    _name = "pr.portal.vendor.invoice"
    _description = "Vendor Portal Invoice"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    _sql_constraints = [
        (
            "unique_vendor_invoice_number",
            "unique(partner_id, vendor_invoice_number)",
            "This vendor invoice number already exists for this vendor.",
        ),
    ]

    name = fields.Char(default="/", required=True, readonly=True, copy=False, tracking=True)
    partner_id = fields.Many2one(
        "res.partner",
        string="Vendor",
        required=True,
        tracking=True,
        domain=[("supplier_rank", ">", 0)],
    )
    po_id = fields.Many2one("purchase.order", string="Related Purchase Order", tracking=True)
    vendor_invoice_number = fields.Char(required=True, tracking=True)
    invoice_date = fields.Date(required=True, tracking=True)
    amount_total = fields.Monetary(required=True, tracking=True)
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
        required=True,
        tracking=True,
    )
    attachment_id = fields.Many2one("ir.attachment", string="Invoice Document", copy=False)
    has_attachment = fields.Boolean(compute="_compute_has_attachment")
    state = fields.Selection(
        [
            ("submitted", "Submitted"),
            ("review", "Under Review"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="submitted",
        required=True,
        tracking=True,
    )
    notes = fields.Text(string="Vendor Notes")
    internal_notes = fields.Text(string="Internal Notes")
    portal_user_id = fields.Many2one("res.users", string="Portal User", readonly=True)

    @api.depends("attachment_id")
    def _compute_has_attachment(self):
        for invoice in self:
            invoice.has_attachment = bool(invoice.attachment_id)

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = sequence.next_by_code("pr.portal.vendor.invoice") or "/"
        records = super().create(vals_list)
        records._link_invoice_attachment()
        records._schedule_reviewer_activity()
        return records

    def write(self, vals):
        result = super().write(vals)
        if "attachment_id" in vals:
            self._link_invoice_attachment()
        return result

    def _link_invoice_attachment(self):
        for invoice in self.filtered("attachment_id"):
            invoice.attachment_id.write({
                "res_model": invoice._name,
                "res_id": invoice.id,
            })

    def _schedule_reviewer_activity(self):
        group = self.env.ref(
            "pr_vendor_customer_portal.group_vendor_invoice_reviewer",
            raise_if_not_found=False,
        )
        if not group:
            return
        for invoice in self:
            for user in group.users.filtered("active"):
                invoice.activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=user.id,
                    summary=_("New Vendor Invoice Submitted"),
                    note=_("A new vendor invoice has been uploaded from the portal and requires review."),
                )

    def action_set_review(self):
        self.write({"state": "review"})

    def action_approve(self):
        self.write({"state": "approved"})

    def action_reject(self):
        self.write({"state": "rejected"})

    def action_download_attachment(self):
        self.ensure_one()
        if not self.attachment_id:
            raise UserError(_("No attachment found to download."))
        return {
            "type": "ir.actions.act_url",
            "target": "self",
            "url": "/web/content/%s?download=1" % self.attachment_id.id,
        }
