from odoo import fields, models


class ServiceReceiptNote(models.Model):
    _inherit = "service.receipt.note"

    pr_vendor_portal_attachment_ids = fields.Many2many(
        "ir.attachment",
        string="SRN Attachments",
        compute="_compute_pr_vendor_portal_attachment_ids",
    )

    def _compute_pr_vendor_portal_attachment_ids(self):
        Attachment = self.env["ir.attachment"].sudo()
        for receipt in self:
            receipt.pr_vendor_portal_attachment_ids = Attachment.search([
                ("res_model", "=", receipt._name),
                ("res_id", "=", receipt.id),
                ("res_field", "=", False),
            ])
