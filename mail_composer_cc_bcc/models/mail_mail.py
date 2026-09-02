# Copyright 2023 Camptocamp SA
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).


from odoo import fields, models, tools
from copy import deepcopy
from email.utils import getaddresses

from odoo.addons.base.models.ir_mail_server import extract_rfc2822_addresses


def format_emails(partners):
    emails = [tools.formataddr((p.name or "", p.email)) for p in partners if p.email]
    return ", ".join(emails)


def format_emails_raw(partners):
    emails = [p.email for p in partners if p.email]
    return ", ".join(emails)


class MailMail(models.Model):
    _inherit = "mail.mail"

    email_bcc = fields.Char("Bcc", help="Blind Cc message recipients")

    def _prepare_outgoing_list(self, recipients_follower_status=None):
        # First, return if we're not coming from the Mail Composer
        res = super()._prepare_outgoing_list(
            recipients_follower_status=recipients_follower_status
        )
        is_out_of_scope = len(self.ids) > 1
        is_from_composer = self.env.context.get("is_from_composer", False)

        if is_out_of_scope or not is_from_composer:
            return res

        # Prepare values for To, Cc headers
        partners_cc_bcc = self.recipient_cc_ids + self.recipient_bcc_ids
        partner_to_ids = [r.id for r in self.recipient_ids if r not in partners_cc_bcc]
        partner_to = self.env["res.partner"].browse(partner_to_ids)
        email_to = format_emails(partner_to)
        email_to_raw = format_emails_raw(partner_to)
        # Preserve directly entered CC addresses as well as contact recipients.
        email_cc = self.email_cc or format_emails(self.recipient_cc_ids)
        email_bcc = [r.email for r in self.recipient_bcc_ids if r.email]

        # Collect recipients (RCPT TO) and update all emails
        # with the same To, Cc headers (to be shown by email client as users expect)
        recipients = []
        for m in res:
            rcpt_to = None
            if m["email_to"]:
                rcpt_to = extract_rfc2822_addresses(m["email_to"][0])[0]

                # If the recipient is a Bcc, we had an explicit header X-Odoo-Bcc
                # - It won't be shown by the email client, but can be useful for a recipient # noqa: E501
                #   to understand why he received a given email
                # - Also note that in python3, the smtp.send_message method does not
                #   transmit the Bcc field of a Message object
                if rcpt_to in email_bcc:
                    m["headers"].update({"X-Odoo-Bcc": m["email_to"][0]})

            # in the absence of self.email_to, Odoo creates one special mail for CC
            # see https://github.com/odoo/odoo/commit/46bad8f0
            elif m["email_cc"]:
                rcpt_to = extract_rfc2822_addresses(m["email_cc"][0])[0]

            if rcpt_to:
                recipients.append(rcpt_to)

            m.update(
                {
                    "email_to": email_to,
                    "email_to_raw": email_to_raw,
                    "email_cc": email_cc,
                }
            )

        # This module sends one SMTP envelope per recipient. A CC header alone
        # is insufficient because ir.mail_server replaces the SMTP recipients.
        # Add envelopes for free-text addresses that have no partner notification.
        known = {address.lower() for address in recipients}
        for _name, address in getaddresses([email_cc or ""]):
            normalized = tools.email_normalize(address)
            if normalized and normalized.lower() not in known and res:
                outgoing = deepcopy(res[0])
                outgoing.get("headers", {}).pop("X-Odoo-Bcc", None)
                res.append(outgoing)
                recipients.append(normalized)
                known.add(normalized.lower())
        self.env.context = {**self.env.context, "recipients": recipients}
        return res
