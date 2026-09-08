from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError, ValidationError
from markupsafe import Markup
from email.utils import getaddresses


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    # Budgetary RFQs collect prices, not financial liabilities. Keep a real
    # vendor mandatory for every other purchase document via a constraint.
    partner_id = fields.Many2one(required=False)
    rfq_vendor_name = fields.Char(string="Vendor Name (Unregistered)", tracking=True)
    rfq_vendor_email = fields.Char(string="Vendor Email", tracking=True)
    is_budgetary_rfq = fields.Boolean(compute="_compute_is_budgetary_rfq")

    @api.depends("requisition_id.pr_type", "state")
    def _compute_is_budgetary_rfq(self):
        for order in self:
            order.is_budgetary_rfq = (
                order.requisition_id.pr_type == "budgetary"
                and order.state in ("draft", "sent", "cancel")
            )

    @api.constrains("partner_id", "requisition_id", "state")
    def _check_registered_purchase_vendor(self):
        for order in self:
            if not order.partner_id and not order.is_budgetary_rfq:
                raise ValidationError(_("A registered vendor is required except on a Budgetary PR RFQ."))

    def action_rfq_send(self):
        self.ensure_one()
        if self.is_budgetary_rfq and not self.partner_id:
            self._require_terms_and_conditions()
            if not self.rfq_vendor_name or not tools.email_normalize(self.rfq_vendor_email or ""):
                raise UserError(_("Enter the unregistered vendor's name and a valid email address."))
            rows = Markup("").join(
                Markup("<tr><td>%s</td><td>%s</td><td>%s</td></tr>")
                % (line.name, line.product_qty, line.product_uom.display_name)
                for line in self.order_line if not line.display_type
            )
            body = Markup("<p>Dear %s,</p><p>Please provide price and availability for RFQ %s.</p>"
                          "<table border='1'><tr><th>Description</th><th>Quantity</th><th>Unit</th></tr>%s</table>%s")
            body = body % (self.rfq_vendor_name, self.name, rows, self.notes or "")
            return {
                "type": "ir.actions.act_window", "name": _("Send Budgetary RFQ"),
                "res_model": "budgetary.rfq.email", "view_mode": "form", "target": "new",
                "context": {"default_order_id": self.id,
                            "default_email_to": self.rfq_vendor_email,
                            "default_body_html": str(body),
                            "default_subject": _("Request for Quotation: %s") % self.name},
            }
        return super().action_rfq_send()

    def action_send_purchase_order_email(self):
        if self.is_budgetary_rfq and not self.partner_id:
            return self.action_rfq_send()
        return super().action_send_purchase_order_email()


class BudgetaryRfqEmail(models.TransientModel):
    _name = "budgetary.rfq.email"
    _description = "Send Budgetary RFQ without registering a vendor"

    order_id = fields.Many2one("purchase.order", required=True, readonly=True)
    email_to = fields.Char(required=True)
    email_cc = fields.Char(string="CC Emails")
    subject = fields.Char(required=True)
    body_html = fields.Html(string="Message", required=True,
                           default="<p>Please provide your price and availability for the attached RFQ.</p>")
    attachment_ids = fields.Many2many("ir.attachment", string="Attachments")

    def action_send(self):
        self.ensure_one()
        order = self.order_id
        order.check_access_rights("write")
        order.check_access_rule("write")
        if not order.is_budgetary_rfq or order.state == "cancel":
            raise UserError(_("Only open budgetary RFQs can be sent with this wizard."))
        if not tools.email_normalize(self.email_to or ""):
            raise ValidationError(_("Enter a valid recipient email address."))
        if "\n" in self.subject or "\r" in self.subject:
            raise ValidationError(_("The subject must not contain line breaks."))
        self.attachment_ids.check_access_rights("read")
        self.attachment_ids.check_access_rule("read")
        cc_addresses = []
        if self.email_cc:
            if "\n" in self.email_cc or "\r" in self.email_cc:
                raise ValidationError(_("CC addresses must not contain line breaks."))
            for name, address in getaddresses([self.email_cc.replace(";", ",")]):
                normalized = tools.email_normalize(address)
                if not normalized:
                    raise ValidationError(_("Invalid CC email address: %s") % address)
                cc_addresses.append(tools.formataddr((name, normalized)))
        # Queue the email; do not commit or contact an SMTP server in this transaction.
        self.env["mail.mail"].create({
            "subject": self.subject, "body_html": self.body_html,
            "email_from": self.env.user.email_formatted,
            "reply_to": self.env.user.email_formatted,
            "email_to": tools.formataddr((order.rfq_vendor_name or "", self.email_to)),
            "email_cc": ", ".join(cc_addresses),
            "attachment_ids": [(6, 0, self.attachment_ids.ids)],
            "model": order._name, "res_id": order.id,
        })
        order.write({"state": "sent"})
        order.message_post(body=_("Budgetary RFQ queued for %s without creating a vendor contact.") % self.email_to)
        return {"type": "ir.actions.act_window_close"}
