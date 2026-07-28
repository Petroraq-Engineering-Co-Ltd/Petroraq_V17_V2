from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PrEosSendWizard(models.TransientModel):
    _name = "pr.eos.send.wizard"
    _description = "Send EOS Final Settlement"

    eos_id = fields.Many2one(
        "pr.end.of.service",
        string="End of Service",
        required=True,
        readonly=True,
    )
    template_id = fields.Many2one(
        "mail.template",
        string="Email Template",
        domain="[('model', '=', 'pr.end.of.service')]",
    )
    recipient_mode = fields.Selection(
        [
            ("employee", "Employee Email"),
            ("private", "Private Email"),
            ("custom", "Custom Email"),
        ],
        default="employee",
        required=True,
    )
    employee_email = fields.Char(compute="_compute_employee_emails", readonly=True)
    employee_private_email = fields.Char(compute="_compute_employee_emails", readonly=True)
    email_to = fields.Char(string="To", required=True)
    email_cc = fields.Char(string="Cc")
    email_bcc = fields.Char(string="Bcc")
    subject = fields.Char(required=True)
    body_html = fields.Html(string="Email Body", sanitize_style=True)
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "pr_eos_send_wizard_attachment_rel",
        "wizard_id",
        "attachment_id",
        string="Attachments",
    )

    @api.depends("eos_id", "eos_id.employee_id")
    def _compute_employee_emails(self):
        for wizard in self:
            employee = wizard.eos_id.employee_id.sudo()
            wizard.employee_email = (
                employee.work_email
                or (employee.user_id.email if employee.user_id else False)
                or (
                    employee.work_contact_id.email
                    if "work_contact_id" in employee._fields and employee.work_contact_id
                    else False
                )
            )
            wizard.employee_private_email = (
                employee.private_email
                if "private_email" in employee._fields and employee.private_email
                else (
                    employee.address_home_id.email
                    if "address_home_id" in employee._fields and employee.address_home_id
                    else False
                )
            )

    @api.model
    def _render_template_values(self, template, eos):
        values = {}
        if not template or not eos:
            return values
        for field_name in ("subject", "body_html", "email_to", "email_cc", "email_bcc"):
            if field_name not in template._fields:
                continue
            try:
                rendered = template._render_field(field_name, [eos.id], compute_lang=True)
                values[field_name] = rendered.get(eos.id)
            except Exception:
                values[field_name] = template[field_name]
        return values

    def _get_email_from(self):
        company_partner = self.env.company.partner_id
        return (
            self.env.user.email_formatted
            or (company_partner.email_formatted if company_partner else False)
            or self.env.company.email
            or False
        )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        eos = self.env["pr.end.of.service"].browse(
            values.get("eos_id") or self.env.context.get("active_id")
        ).exists()
        if not eos:
            return values
        values["eos_id"] = eos.id
        template = self.env.ref(
            "pr_end_of_service.mail_template_eos_employee_acceptance",
            raise_if_not_found=False,
        )
        if template:
            values["template_id"] = template.id
            rendered = self._render_template_values(template, eos)
            values["subject"] = rendered.get("subject") or _("Final Settlement for Review - %s") % eos.name
            values["body_html"] = rendered.get("body_html")
            values["email_cc"] = rendered.get("email_cc") or False
            values["email_bcc"] = rendered.get("email_bcc") or False
        else:
            values["subject"] = _("Final Settlement for Review - %s") % eos.name
        values["email_to"] = eos._get_employee_acceptance_email() or ""
        return values

    @api.onchange("eos_id", "recipient_mode")
    def _onchange_recipient_mode(self):
        for wizard in self:
            if wizard.recipient_mode == "employee":
                wizard.email_to = wizard.employee_email or ""
            elif wizard.recipient_mode == "private":
                wizard.email_to = wizard.employee_private_email or ""

    @api.onchange("template_id")
    def _onchange_template_id(self):
        for wizard in self:
            if not wizard.template_id or not wizard.eos_id:
                continue
            rendered = wizard._render_template_values(wizard.template_id, wizard.eos_id)
            wizard.subject = rendered.get("subject") or wizard.subject
            wizard.body_html = rendered.get("body_html") or wizard.body_html
            wizard.email_cc = rendered.get("email_cc") or False
            wizard.email_bcc = rendered.get("email_bcc") or False
            if wizard.recipient_mode == "custom" and rendered.get("email_to"):
                wizard.email_to = rendered["email_to"]

    def action_send(self):
        self.ensure_one()
        eos = self.eos_id
        if eos.state != "employee_acceptance":
            raise UserError(
                _("The settlement can only be emailed while waiting for Employee Acceptance.")
            )
        email_to = (self.email_to or "").strip()
        if not email_to:
            raise UserError(_("Please set an email recipient before sending."))
        if not self.subject or not self.body_html:
            raise UserError(_("Please enter the email subject and body before sending."))

        pdf_attachment = eos._generate_final_settlement_pdf_attachment()
        attachments = self.attachment_ids | pdf_attachment
        mail = self.env["mail.mail"].sudo().create({
            "model": eos._name,
            "res_id": eos.id,
            "subject": self.subject,
            "body_html": self.body_html,
            "email_from": self._get_email_from(),
            "email_to": email_to,
            "email_cc": self.email_cc or False,
            "email_bcc": self.email_bcc or False,
            "auto_delete": False,
            "attachment_ids": [(6, 0, attachments.ids)],
        })
        mail.send()
        sent_at = fields.Datetime.now()
        eos.write({
            "employee_acceptance_email": email_to,
            "employee_acceptance_email_sent_at": sent_at,
            "employee_acceptance_state": "sent",
        })
        eos.message_post(
            body=_("EOS settlement document emailed to %s for employee acceptance.") % email_to,
            attachment_ids=attachments.ids,
            message_type="notification",
        )
        return {"type": "ir.actions.act_window_close"}
