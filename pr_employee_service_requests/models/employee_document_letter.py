import base64

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.osv import expression


LETTER_TEMPLATE_XML_IDS = {
    "experience": "pr_employee_service_requests.mail_template_employee_letter_experience",
    "warning": "pr_employee_service_requests.mail_template_employee_letter_warning",
    "appraisal": "pr_employee_service_requests.mail_template_employee_letter_appraisal",
    "salary_certificate": "pr_employee_service_requests.mail_template_employee_letter_salary_certificate",
    "employment_certificate": "pr_employee_service_requests.mail_template_employee_letter_employment_certificate",
    "other": "pr_employee_service_requests.mail_template_employee_letter_generic",
}


class PrEmployeeCodeLookup(models.Model):
    _name = "pr.employee.code.lookup"
    _description = "Employee Code Lookup"
    _rec_name = "code"
    _order = "code, employee_name"

    employee_id = fields.Many2one("hr.employee", string="Employee", required=True, ondelete="cascade", index=True)
    code = fields.Char(related="employee_id.code", store=True, readonly=True)
    employee_name = fields.Char(related="employee_id.name", store=True, readonly=True)

    _sql_constraints = [
        ("employee_unique", "unique(employee_id)", "Each employee can only have one code lookup record."),
    ]

    @api.model
    def _get_or_create_for_employee(self, employee):
        employee = employee.exists()
        if not employee:
            return self
        lookup = self.sudo().search([("employee_id", "=", employee.id)], limit=1)
        if lookup:
            return lookup
        return self.sudo().create({"employee_id": employee.id})

    @api.model
    def _get_or_create_for_employees(self, employees):
        lookups = self.sudo()
        for employee in employees.exists():
            lookups |= self._get_or_create_for_employee(employee)
        return lookups

    def name_get(self):
        return [(lookup.id, lookup.code or "") for lookup in self]

    @api.model
    def name_search(self, name="", args=None, operator="ilike", limit=100):
        args = list(args or [])
        if name:
            employee_domain = expression.OR([
                [("code", operator, name)],
                [("name", operator, name)],
            ])
            employees = self.env["hr.employee"].search(employee_domain, limit=limit)
            lookups = self._get_or_create_for_employees(employees)
            if args:
                lookups = lookups.filtered_domain(args)
            return lookups.name_get()

        lookups = self.search(args, limit=limit)
        if not lookups and not args:
            employees = self.env["hr.employee"].search([], limit=limit)
            lookups = self._get_or_create_for_employees(employees)
        return lookups.name_get()


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
    employee_code_id = fields.Many2one(
        "pr.employee.code.lookup",
        string="Employee Id",
        compute="_compute_employee_code_id",
        inverse="_inverse_employee_code_id",
        help="Search and select the employee by internal employee code.",
    )
    employee_email = fields.Char(string="Employee Email", compute="_compute_employee_email")
    employee_private_email = fields.Char(string="Private Email", compute="_compute_employee_private_email")
    department_id = fields.Many2one("hr.department", related="employee_id.department_id", store=True, readonly=True)
    job_id = fields.Many2one("hr.job", related="employee_id.job_id", store=True, readonly=True)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True,
        tracking=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        readonly=True,
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
    appraisal_increment_amount = fields.Monetary(
        string="Increment Amount",
        currency_field="currency_id",
        tracking=True,
        help="Optional increment amount printed on appraisal letters.",
    )
    appraisal_effective_date = fields.Date(
        string="Increment Effective Date",
        tracking=True,
        help="Optional effective date printed on appraisal letters.",
    )
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
    generated_letter_attachment_id = fields.Many2one(
        "ir.attachment",
        string="Generated Letter PDF",
        readonly=True,
        copy=False,
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

    @api.depends("employee_id")
    def _compute_employee_email(self):
        for rec in self:
            rec.employee_email = rec._get_employee_email()

    @api.depends("employee_id")
    def _compute_employee_private_email(self):
        for rec in self:
            rec.employee_private_email = rec._get_employee_private_email()

    @api.depends("employee_id")
    def _compute_employee_code_id(self):
        for rec in self:
            rec.employee_code_id = self.env["pr.employee.code.lookup"]._get_or_create_for_employee(rec.employee_id)

    def _inverse_employee_code_id(self):
        for rec in self:
            rec.employee_id = rec.employee_code_id.employee_id

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
                "<p>During the period of employment, <strong>%(employee)s</strong> carried out the duties "
                "and responsibilities assigned in a professional and satisfactory manner.</p>"
                "<p>This certificate is issued upon the employee's request for whatever purpose it may serve.</p>"
            ) % {"employee": employee_name, "company": company_name}
        elif letter_type == "warning":
            body_html = _(
                "<p>This letter serves as an official warning regarding conduct that is not in accordance "
                "with the standards of professionalism and workplace ethics expected by %(company)s.</p>"
                "<p>You are hereby advised to maintain professional behavior and conduct yourself "
                "appropriately with colleagues, supervisors, clients, and other stakeholders at all times.</p>"
                "<p>Please be informed that any repetition of such behavior or any similar misconduct "
                "in the future may result in further disciplinary action.</p>"
                "<p>We expect immediate improvement and trust that this matter will not be repeated.</p>"
            ) % {"employee": employee_name, "company": company_name}
        elif letter_type == "appraisal":
            body_html = _(
                "<p>Dear <strong>%(employee)s</strong>,</p>"
                "<p>We are pleased to inform you that based on your good performance, the management "
                "has approved a performance appraisal in recognition of your efforts and contributions "
                "to %(company)s.</p>"
                "<p>This appraisal is a reflection of your performance rating and your commitment to "
                "achieving organizational goals. We appreciate your dedication and professionalism, "
                "and encourage you to continue striving for excellence in your role.</p>"
                "<p>We look forward to your continued success at Petroraq.</p>"
            ) % {"employee": employee_name, "company": company_name}
        elif letter_type == "salary_certificate":
            body_html = _(
                "<p>This certificate is issued upon the request of the above-mentioned employee for "
                "whatever purpose it may serve. It does not constitute any financial liability on "
                "the part of the company.</p>"
            ) % {"employee": employee_name}
        elif letter_type == "employment_certificate":
            body_html = _(
                "<p>This is to certify that <strong>%(employee)s</strong> is employed with "
                "<strong>%(company)s</strong>. This certificate is issued upon request for official use.</p>"
            ) % {"employee": employee_name, "company": company_name}
        else:
            body_html = _(
                "<p>Dear <strong>%(employee)s</strong>,</p>"
                "<p>Please find the requested employee letter attached.</p>"
            ) % {"employee": employee_name}
        return {"subject": subject, "body_html": body_html}

    def _get_current_contract(self):
        self.ensure_one()
        employee = self.employee_id.sudo()
        contract = employee.contract_id if "contract_id" in employee._fields else self.env["hr.contract"]
        if contract:
            return contract.sudo()
        return self.env["hr.contract"].sudo().search(
            [
                ("employee_id", "=", employee.id),
                ("company_id", "in", [False, self.company_id.id]),
                ("state", "in", ["open", "close", "draft"]),
            ],
            order="state desc, date_start desc, id desc",
            limit=1,
        )

    def _get_record_field_value(self, record, field_name):
        if not record or field_name not in record._fields:
            return False
        return record[field_name]

    def _format_report_date(self, value=False, long=False):
        value = value or fields.Date.context_today(self)
        if isinstance(value, str):
            value = fields.Date.from_string(value)
        if not value:
            return ""
        if not long:
            return value.strftime("%d/%m/%Y")
        suffix = "th"
        if value.day % 100 not in (11, 12, 13):
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(value.day % 10, "th")
        return "%s%s %s %s" % (value.day, suffix, value.strftime("%B"), value.year)

    def _format_report_amount(self, amount, currency=False, force_decimals=False):
        amount = amount or 0.0
        if force_decimals:
            formatted = "%s" % ("{:,.2f}".format(amount))
        elif float(amount).is_integer():
            formatted = "%s" % ("{:,.0f}".format(amount))
        else:
            formatted = "%s" % ("{:,.2f}".format(amount))
        if currency:
            return "%s %s" % (formatted, currency.name or "")
        return formatted

    def _get_employee_title(self):
        self.ensure_one()
        return "Ms." if self.employee_id.gender == "female" else "Mr."

    def _get_employee_pronouns(self):
        self.ensure_one()
        if self.employee_id.gender == "female":
            return {"subject": "She", "object": "her", "possessive": "her"}
        return {"subject": "He", "object": "him", "possessive": "his"}

    def _get_letter_signatory_values(self):
        self.ensure_one()
        signatory_user = self.env["res.users"]
        md_group = self.env.ref("pr_custom_purchase.managing_director", raise_if_not_found=False)
        if md_group:
            signatory_user = self.env["res.users"].sudo().search(
                [("groups_id", "in", md_group.id), ("share", "=", False), ("active", "=", True)],
                limit=1,
            )
        signatory_employee = self.env["hr.employee"].sudo()
        if signatory_user:
            signatory_employee = signatory_employee.search([("user_id", "=", signatory_user.id)], limit=1)
        return {
            "name": (
                signatory_employee.name
                or signatory_user.name
                or self.hr_manager_approved_by_id.name
                or _("Authorized Signatory")
            ),
            "designation": (
                signatory_employee.job_id.name
                or _("Managing Director")
            ),
        }

    def _get_salary_certificate_lines(self, contract):
        self.ensure_one()
        lines = []
        if not contract:
            return lines, 0.0
        if contract.wage:
            lines.append({
                "name": _("Basic Salary"),
                "amount": contract.wage,
                "amount_display": self._format_report_amount(contract.wage),
            })
        allowance_total = 0.0
        for salary_line in contract.contract_salary_rule_ids.filtered(lambda line: line.pay_in_payslip and line.amount):
            allowance_total += salary_line.amount
            name = salary_line.salary_rule_id.name or _("Allowance")
            if "allowance" not in name.lower():
                name = _("%s Allowance") % name
            lines.append({
                "name": _("%s (Monthly)") % name,
                "amount": salary_line.amount,
                "amount_display": self._format_report_amount(salary_line.amount),
            })
        gross_amount = contract.gross_amount or (contract.wage or 0.0) + allowance_total
        known_total = sum(line["amount"] for line in lines)
        difference = gross_amount - known_total
        if abs(difference) >= 0.01:
            lines.append({
                "name": _("Other Allowance (Monthly)"),
                "amount": difference,
                "amount_display": self._format_report_amount(difference),
            })
            known_total += difference
        return lines, known_total

    def _get_appraisal_body_html(self):
        self.ensure_one()
        if not self.appraisal_increment_amount:
            return self.body_html
        amount = self._format_report_amount(self.appraisal_increment_amount, self.currency_id, force_decimals=True)
        effective_date = self._format_report_date(self.appraisal_effective_date, long=True)
        effective_sentence = ""
        if effective_date:
            effective_sentence = _(" The increment will be effective from %s.") % effective_date
        return _(
            "<p>Dear %(employee)s,</p>"
            "<p>We are pleased to inform you that based on your good performance, the management has "
            "approved a salary increment of <strong>%(amount)s</strong> in recognition of your efforts "
            "and contributions to %(company)s.</p>"
            "<p>This increment is a reflection of your performance rating and your commitment to "
            "achieving organizational goals. We appreciate your dedication and professionalism, and "
            "we encourage you to continue striving for excellence in your role.</p>"
            "<p>%(effective_sentence)s For any clarifications regarding this increment, please feel "
            "free to contact the HR department.</p>"
            "<p>We look forward to your continued success at Petroraq.</p>"
        ) % {
            "employee": self.employee_id.name or _("Employee"),
            "amount": amount,
            "company": self.company_id.name or _("Petroraq Engineering Company"),
            "effective_sentence": effective_sentence.strip(),
        }

    def _get_employee_letter_report_values(self):
        self.ensure_one()
        employee = self.employee_id.sudo()
        contract = self._get_current_contract()
        joining_date = (
            self._get_record_field_value(contract, "joining_date")
            or self._get_record_field_value(employee, "joining_date")
            or self._get_record_field_value(employee, "first_contract_date")
            or self._get_record_field_value(contract, "date_start")
        )
        service_end_date = (
            self._get_record_field_value(contract, "date_end")
            or self._get_record_field_value(employee, "last_working_date")
            or self.issue_date
        )
        salary_lines, total_salary = self._get_salary_certificate_lines(contract)
        pronouns = self._get_employee_pronouns()
        return {
            "type": self.letter_type,
            "type_label": self._get_letter_type_label(self.letter_type),
            "date_long": self._format_report_date(self.issue_date, long=True),
            "date_short": self._format_report_date(self.issue_date),
            "employee_title": self._get_employee_title(),
            "employee_name": employee.name or "",
            "employee_first_name": (employee.name or "").split(" ")[0] if employee.name else "",
            "employee_code": employee.code if "code" in employee._fields else "",
            "company_name": self.company_id.name or _("Petroraq Engineering Co. Ltd."),
            "iqama_no": employee.identification_id or "",
            "passport_no": employee.passport_id if "passport_id" in employee._fields else "",
            "nationality": employee.country_id.name or "",
            "position": employee.job_id.name or "",
            "department": employee.department_id.name or "",
            "joining_date": self._format_report_date(joining_date),
            "joining_date_long": self._format_report_date(joining_date, long=True),
            "service_end_date": self._format_report_date(service_end_date),
            "service_end_date_long": self._format_report_date(service_end_date, long=True),
            "subject": self.subject or self._get_letter_type_label(self.letter_type),
            "body_html": self._get_appraisal_body_html() if self.letter_type == "appraisal" else self.body_html,
            "salary_lines": salary_lines,
            "total_salary": total_salary,
            "total_salary_display": self._format_report_amount(total_salary),
            "currency_name": self.currency_id.name or "",
            "signatory": self._get_letter_signatory_values(),
            "pronouns": pronouns,
        }

    def _get_letter_pdf_filename(self):
        self.ensure_one()
        label = self._get_letter_type_label(self.letter_type) or _("Employee Letter")
        employee_name = self.employee_id.name or _("Employee")
        safe_name = "%s - %s - %s.pdf" % (label, employee_name, self.name or fields.Date.today())
        return safe_name.replace("/", "-")

    def _create_letter_pdf_attachment(self):
        self.ensure_one()
        report = self.env.ref("pr_employee_service_requests.action_report_employee_document_letter", raise_if_not_found=False)
        if not report:
            raise UserError(_("Employee letter PDF report is not configured."))
        pdf_content, _content_type = self.env["ir.actions.report"].sudo()._render_qweb_pdf(
            report.report_name,
            [self.id],
        )
        return self.env["ir.attachment"].sudo().create({
            "name": self._get_letter_pdf_filename(),
            "type": "binary",
            "datas": base64.b64encode(pdf_content),
            "res_model": self._name,
            "res_id": self.id,
            "mimetype": "application/pdf",
        })

    def _generate_letter_pdf_attachment(self):
        self.ensure_one()
        old_attachment = self.generated_letter_attachment_id.sudo()
        if old_attachment and self.state != "sent":
            self.write({"attachment_ids": [(3, old_attachment.id)]})
            old_attachment.unlink()
        attachment = self._create_letter_pdf_attachment()
        self.write({
            "generated_letter_attachment_id": attachment.id,
            "attachment_ids": [(4, attachment.id)],
        })
        return attachment

    def _ensure_letter_pdf_attachment(self):
        self.ensure_one()
        if self.generated_letter_attachment_id.exists():
            return self.generated_letter_attachment_id.sudo()
        return self._generate_letter_pdf_attachment()

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

    def _get_employee_private_email(self):
        self.ensure_one()
        employee = self.employee_id
        if not employee:
            return False
        if "private_email" in employee._fields and employee.private_email:
            return employee.private_email
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
            rec.employee_code_id = self.env["pr.employee.code.lookup"]._get_or_create_for_employee(rec.employee_id)
            if rec.state != "draft" or not rec.letter_type or not rec.employee_id:
                continue
            values = rec._get_default_letter_values(rec.letter_type, rec.employee_id, rec.company_id)
            rec.subject = values["subject"]
            rec.body_html = values["body_html"]

    @api.onchange("employee_code_id")
    def _onchange_employee_code_id(self):
        for rec in self:
            rec.employee_id = rec.employee_code_id.employee_id
            if rec.state == "draft" and rec.letter_type and rec.employee_id:
                values = rec._get_default_letter_values(rec.letter_type, rec.employee_id, rec.company_id)
                rec.subject = values["subject"]
                rec.body_html = values["body_html"]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "employee_code_id" in vals:
                lookup = self.env["pr.employee.code.lookup"].browse(vals.pop("employee_code_id"))
                vals["employee_id"] = lookup.employee_id.id if lookup else False
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

    def write(self, vals):
        if "employee_code_id" in vals:
            vals = dict(vals)
            lookup = self.env["pr.employee.code.lookup"].browse(vals.pop("employee_code_id"))
            vals["employee_id"] = lookup.employee_id.id if lookup else False
        return super().write(vals)

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
        generated_attachment = self._generate_letter_pdf_attachment()
        return {
            "type": "ir.actions.act_window",
            "name": _("Send Employee Letter"),
            "res_model": "pr.employee.letter.send.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_letter_id": self.id,
                "default_attachment_ids": [(6, 0, [generated_attachment.id])],
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
        [
            ("employee", "Employee Email"),
            ("private", "Private Email"),
            ("custom", "Custom Email"),
        ],
        default="employee",
        required=True,
    )
    employee_email = fields.Char(related="letter_id.employee_email", readonly=True)
    employee_private_email = fields.Char(related="letter_id.employee_private_email", readonly=True)
    email_to = fields.Char(string="To", required=True)
    email_cc = fields.Char(string="Cc")
    subject = fields.Char(required=True)
    body_html = fields.Html(string="Email Body", sanitize_style=True)
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "pr_employee_letter_send_wizard_attachment_rel",
        "wizard_id",
        "attachment_id",
        string="Email Attachments",
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
            elif rec.recipient_mode == "private":
                rec.email_to = rec.letter_id._get_employee_private_email() or ""

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
        if not email_to:
            raise UserError(_("Please set an email recipient before sending."))
        if not self.subject or not self.body_html:
            raise UserError(_("Please enter the email subject and body before sending."))

        if self.attachment_ids:
            letter.attachment_ids = [(4, attachment.id) for attachment in self.attachment_ids]
        letter._ensure_letter_pdf_attachment()
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
