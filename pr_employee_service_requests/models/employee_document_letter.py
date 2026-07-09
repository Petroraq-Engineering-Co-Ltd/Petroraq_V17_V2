from odoo import _, api, fields, models
from odoo.exceptions import UserError


LETTER_TEMPLATE_XML_IDS = {
    "experience": "pr_employee_service_requests.mail_template_employee_letter_experience",
    "warning": "pr_employee_service_requests.mail_template_employee_letter_warning",
    "appraisal": "pr_employee_service_requests.mail_template_employee_letter_appraisal",
    "salary_certificate": "pr_employee_service_requests.mail_template_employee_letter_salary_certificate",
    "employment_certificate": "pr_employee_service_requests.mail_template_employee_letter_employment_certificate",
    "other": "pr_employee_service_requests.mail_template_employee_letter_generic",
}


class PrEmployeeDocumentLetter(models.Model):
    _name = "pr.employee.document.letter"
    _description = "Employee Document Letter"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(string="Reference", default="New", readonly=True, copy=False, tracking=True)
    letter_type = fields.Selection(
        [
            ("experience", "Experience Letter"),
            ("warning", "Warning Letter"),
            ("appraisal", "Appraisal Letter"),
            ("salary_certificate", "Salary Certificate"),
            ("employment_certificate", "Employment Certificate"),
            ("other", "Other"),
        ],
        string="Letter Type",
        default="experience",
        required=True,
        tracking=True,
    )
    requested_by_id = fields.Many2one(
        "res.users",
        string="Requested By",
        default=lambda self: self.env.user,
        readonly=True,
        tracking=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        default=lambda self: self._default_employee_id(),
        required=True,
        tracking=True,
    )
    employee_email = fields.Char(string="Employee Email", compute="_compute_employee_email")
    department_id = fields.Many2one("hr.department", related="employee_id.department_id", store=True, readonly=True)
    job_id = fields.Many2one("hr.job", related="employee_id.job_id", store=True, readonly=True)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True,
        tracking=True,
    )
    request_date = fields.Date(
        string="Request Date",
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    issue_date = fields.Date(
        string="Letter Date",
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    subject = fields.Char(string="Subject", required=True, tracking=True)
    body_html = fields.Html(string="Letter Content", sanitize_style=True)
    reason = fields.Text(string="Reason / Notes", tracking=True)
    rejection_reason = fields.Text(string="Rejection Reason", tracking=True)
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "pr_employee_document_letter_attachment_rel",
        "letter_id",
        "attachment_id",
        string="Letter Attachments",
        help="Approved letter document or supporting attachments to send with the email.",
    )
    attachment_count = fields.Integer(string="Attachments", compute="_compute_attachment_count")
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("hr_manager_approval", "HR Manager Approval"),
            ("approved", "Approved"),
            ("sent", "Sent"),
            ("rejected", "Rejected"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        tracking=True,
        copy=False,
    )
    hr_manager_approved_by_id = fields.Many2one(
        "res.users",
        string="HR Manager Approved By",
        readonly=True,
        copy=False,
    )
    hr_manager_approved_date = fields.Datetime(
        string="HR Manager Approved On",
        readonly=True,
        copy=False,
    )
    sent_by_id = fields.Many2one("res.users", string="Sent By", readonly=True, copy=False)
    sent_date = fields.Datetime(string="Sent On", readonly=True, copy=False)
    sent_email_to = fields.Char(string="Sent To", readonly=True, copy=False)

    can_submit = fields.Boolean(compute="_compute_action_flags")
    can_hr_manager_approve = fields.Boolean(compute="_compute_action_flags")
    can_send = fields.Boolean(compute="_compute_action_flags")
    can_reject = fields.Boolean(compute="_compute_action_flags")
    can_reset_to_draft = fields.Boolean(compute="_compute_action_flags")
    can_cancel = fields.Boolean(compute="_compute_action_flags")

    @api.model
    def _default_employee_id(self):
        employee = self.env["hr.employee"].sudo().search([
            ("user_id", "=", self.env.uid),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        return employee.id if employee else False

    @api.depends("employee_id", "employee_id.work_email")
    def _compute_employee_email(self):
        for rec in self:
            rec.employee_email = rec._get_employee_email()

    @api.depends("attachment_ids")
    def _compute_attachment_count(self):
        for rec in self:
            rec.attachment_count = len(rec._get_letter_attachments())

    @api.depends("state", "requested_by_id", "employee_id.user_id")
    @api.depends_context("uid")
    def _compute_action_flags(self):
        user = self.env.user
        is_hr_manager = user.has_group("hr.group_hr_manager")
        for rec in self:
            is_owner = rec.requested_by_id == user or rec.employee_id.user_id == user
            rec.can_submit = rec.state == "draft" and (is_owner or is_hr_manager)
            rec.can_hr_manager_approve = rec.state == "hr_manager_approval" and is_hr_manager
            rec.can_send = rec.state in ("approved", "sent") and is_hr_manager
            rec.can_reject = rec.state == "hr_manager_approval" and is_hr_manager
            rec.can_reset_to_draft = rec.state in ("hr_manager_approval", "rejected", "cancelled") and (
                is_owner or is_hr_manager
            )
            rec.can_cancel = rec.state in ("draft", "hr_manager_approval") and (is_owner or is_hr_manager)

    @api.model
    def _get_letter_type_label(self, letter_type):
        return dict(self._fields["letter_type"].selection).get(letter_type, letter_type or "")

    @api.model
    def _get_default_letter_values(self, letter_type, employee, company=False):
        label = self._get_letter_type_label(letter_type)
        employee_name = employee.name or _("Employee")
        company_name = (company or self.env.company).name or _("Company")
        subject = _("%(letter_type)s - %(employee)s") % {
            "letter_type": label,
            "employee": employee_name,
        }

        if letter_type == "experience":
            body_html = _(
                "<p>To whom it may concern,</p>"
                "<p>This is to certify that <strong>%(employee)s</strong> has been employed with "
                "<strong>%(company)s</strong>. This letter is issued upon request for official use.</p>"
                "<p>Regards,<br/>Human Resources</p>"
            ) % {"employee": employee_name, "company": company_name}
        elif letter_type == "warning":
            body_html = _(
                "<p>Dear <strong>%(employee)s</strong>,</p>"
                "<p>This letter is issued as a formal warning. Please review the attached document "
                "and comply with the required corrective actions.</p>"
                "<p>Regards,<br/>Human Resources</p>"
            ) % {"employee": employee_name}
        elif letter_type == "appraisal":
            body_html = _(
                "<p>Dear <strong>%(employee)s</strong>,</p>"
                "<p>Please find your appraisal letter attached. We appreciate your contribution "
                "and continued commitment.</p>"
                "<p>Regards,<br/>Human Resources</p>"
            ) % {"employee": employee_name}
        elif letter_type == "salary_certificate":
            body_html = _(
                "<p>Dear <strong>%(employee)s</strong>,</p>"
                "<p>Please find your salary certificate attached for your official use.</p>"
                "<p>Regards,<br/>Human Resources</p>"
            ) % {"employee": employee_name}
        elif letter_type == "employment_certificate":
            body_html = _(
                "<p>Dear <strong>%(employee)s</strong>,</p>"
                "<p>Please find your employment certificate attached for your official use.</p>"
                "<p>Regards,<br/>Human Resources</p>"
            ) % {"employee": employee_name}
        else:
            body_html = _(
                "<p>Dear <strong>%(employee)s</strong>,</p>"
                "<p>Please find the requested employee letter attached.</p>"
                "<p>Regards,<br/>Human Resources</p>"
            ) % {"employee": employee_name}
        return {"subject": subject, "body_html": body_html}

    def _get_employee_email(self):
        self.ensure_one()
        employee = self.employee_id
        if employee.work_email:
            return employee.work_email
        if "work_contact_id" in employee._fields and employee.work_contact_id.email:
            return employee.work_contact_id.email
        if "address_home_id" in employee._fields and employee.address_home_id.email:
            return employee.address_home_id.email
        return False

    def _get_letter_attachments(self):
        self.ensure_one()
        chatter_attachments = self.env["ir.attachment"].sudo().search([
            ("res_model", "=", self._name),
            ("res_id", "=", self.id),
        ])
        return self.attachment_ids.sudo() | chatter_attachments

    def _get_default_mail_template(self):
        self.ensure_one()
        xml_id = LETTER_TEMPLATE_XML_IDS.get(self.letter_type)
        return self.env.ref(xml_id, raise_if_not_found=False) if xml_id else self.env["mail.template"]

    @api.onchange("letter_type", "employee_id", "company_id")
    def _onchange_letter_defaults(self):
        for rec in self:
            if rec.state != "draft" or not rec.letter_type or not rec.employee_id:
                continue
            values = rec._get_default_letter_values(rec.letter_type, rec.employee_id, rec.company_id)
            rec.subject = values["subject"]
            rec.body_html = values["body_html"]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("pr.employee.document.letter") or _("New")
            employee = self.env["hr.employee"].browse(vals.get("employee_id")) if vals.get("employee_id") else False
            if employee and (not vals.get("subject") or not vals.get("body_html")):
                values = self._get_default_letter_values(
                    vals.get("letter_type") or "experience",
                    employee,
                    self.env["res.company"].browse(vals.get("company_id")) if vals.get("company_id") else self.env.company,
                )
                if not vals.get("subject"):
                    vals["subject"] = values["subject"]
                if not vals.get("body_html"):
                    vals["body_html"] = values["body_html"]
        return super().create(vals_list)

    def _check_hr_manager(self):
        if not self.env.user.has_group("hr.group_hr_manager"):
            raise UserError(_("Only HR Managers can perform this action."))

    def action_view_attachments(self):
        self.ensure_one()
        attachments = self._get_letter_attachments()
        if not attachments:
            raise UserError(_("No attachments found."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Attachments - %s") % self.display_name,
            "res_model": "ir.attachment",
            "view_mode": "tree,form",
            "domain": [("id", "in", attachments.ids)],
            "target": "current",
            "context": {"create": False},
        }

    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                continue
            if not rec.subject or not rec.body_html:
                raise UserError(_("Please enter the subject and letter content before submitting."))
            rec.state = "hr_manager_approval"
            rec.message_post(body=_("Employee letter submitted for HR Manager approval."))

    def action_hr_manager_approve(self):
        self._check_hr_manager()
        for rec in self:
            if rec.state != "hr_manager_approval":
                continue
            rec.write({
                "state": "approved",
                "hr_manager_approved_by_id": self.env.user.id,
                "hr_manager_approved_date": fields.Datetime.now(),
            })
            rec.message_post(body=_("Employee letter approved by HR Manager."))

    def action_reject(self):
        self._check_hr_manager()
        for rec in self:
            if rec.state == "hr_manager_approval":
                rec.state = "rejected"
                rec.message_post(body=_("Employee letter rejected."))

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state not in ("hr_manager_approval", "rejected", "cancelled"):
                continue
            if not (self.env.user.has_group("hr.group_hr_manager") or rec.requested_by_id == self.env.user):
                raise UserError(_("Only the requester or an HR Manager can reset this letter to draft."))
            rec.write({
                "state": "draft",
                "hr_manager_approved_by_id": False,
                "hr_manager_approved_date": False,
            })

    def action_cancel(self):
        for rec in self:
            if rec.state in ("draft", "hr_manager_approval"):
                rec.state = "cancelled"

    def action_open_send_wizard(self):
        self.ensure_one()
        if self.state not in ("approved", "sent"):
            raise UserError(_("Only approved letters can be sent."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Send Employee Letter"),
            "res_model": "pr.employee.letter.send.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_letter_id": self.id,
                "active_model": self._name,
                "active_id": self.id,
            },
        }


class PrEmployeeLetterSendWizard(models.TransientModel):
    _name = "pr.employee.letter.send.wizard"
    _description = "Send Employee Letter"

    letter_id = fields.Many2one("pr.employee.document.letter", required=True, readonly=True)
    template_id = fields.Many2one(
        "mail.template",
        string="Email Template",
        domain="[('model', '=', 'pr.employee.document.letter')]",
    )
    recipient_mode = fields.Selection(
        [("employee", "Employee Email"), ("custom", "Custom Email")],
        default="employee",
        required=True,
    )
    employee_email = fields.Char(related="letter_id.employee_email", readonly=True)
    email_to = fields.Char(string="To", required=True)
    email_cc = fields.Char(string="Cc")
    subject = fields.Char(required=True)
    body_html = fields.Html(string="Email Body", sanitize_style=True)
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "pr_employee_letter_send_wizard_attachment_rel",
        "wizard_id",
        "attachment_id",
        string="Additional Attachments",
    )
    include_letter_attachments = fields.Boolean(
        string="Include Letter Attachments",
        default=True,
        help="Include attachments already stored on the approved letter record.",
    )

    @api.model
    def _render_template_values(self, template, letter):
        values = {}
        if not template or not letter:
            return values
        for field_name in ("subject", "body_html", "email_to", "email_cc"):
            try:
                rendered = template._render_field(field_name, [letter.id], compute_lang=True)
                values[field_name] = rendered.get(letter.id)
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
        letter = self.env["pr.employee.document.letter"].browse(
            values.get("letter_id") or self.env.context.get("active_id")
        ).exists()
        if not letter:
            return values
        values["letter_id"] = letter.id
        values["email_to"] = letter._get_employee_email() or ""
        template = letter._get_default_mail_template()
        if template:
            values["template_id"] = template.id
            rendered = self._render_template_values(template, letter)
            values["subject"] = rendered.get("subject") or letter.subject
            values["body_html"] = rendered.get("body_html") or letter.body_html
        else:
            values["subject"] = letter.subject
            values["body_html"] = letter.body_html
        return values

    @api.onchange("letter_id", "recipient_mode")
    def _onchange_recipient_mode(self):
        for rec in self:
            if rec.recipient_mode == "employee":
                rec.email_to = rec.letter_id._get_employee_email() or ""

    @api.onchange("template_id")
    def _onchange_template_id(self):
        for rec in self:
            if not rec.template_id or not rec.letter_id:
                continue
            rendered = rec._render_template_values(rec.template_id, rec.letter_id)
            rec.subject = rendered.get("subject") or rec.subject
            rec.body_html = rendered.get("body_html") or rec.body_html
            if rec.recipient_mode == "custom" and rendered.get("email_to"):
                rec.email_to = rendered["email_to"]

    def action_send(self):
        self.ensure_one()
        letter = self.letter_id
        letter._check_hr_manager()
        if letter.state not in ("approved", "sent"):
            raise UserError(_("Only approved letters can be sent."))

        email_to = (self.email_to or "").strip()
        if self.recipient_mode == "employee":
            email_to = letter._get_employee_email()
        if not email_to:
            raise UserError(_("Please set an email recipient before sending."))
        if not self.subject or not self.body_html:
            raise UserError(_("Please enter the email subject and body before sending."))

        if self.attachment_ids:
            letter.attachment_ids = [(4, attachment.id) for attachment in self.attachment_ids]
        attachments = self.env["ir.attachment"]
        if self.include_letter_attachments:
            attachments |= letter._get_letter_attachments()
        attachments |= self.attachment_ids

        mail = self.env["mail.mail"].sudo().create({
            "model": letter._name,
            "res_id": letter.id,
            "subject": self.subject,
            "body_html": self.body_html,
            "email_from": self._get_email_from(),
            "email_to": email_to,
            "email_cc": self.email_cc or False,
            "auto_delete": False,
            "attachment_ids": [(6, 0, attachments.ids)],
        })
        mail.send()
        letter.write({
            "state": "sent",
            "sent_by_id": self.env.user.id,
            "sent_date": fields.Datetime.now(),
            "sent_email_to": email_to,
        })
        letter.message_post(
            body=_("Employee letter sent to %s.") % email_to,
            attachment_ids=attachments.ids,
            message_type="notification",
        )
        return {"type": "ir.actions.act_window_close"}
