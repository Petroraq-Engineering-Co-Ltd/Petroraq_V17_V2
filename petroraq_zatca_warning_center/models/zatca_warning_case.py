import hashlib
import re
from html import unescape

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from lxml import etree


WARNING_TARGET_SELECTION = [
    ("customer", "Customer"),
    ("company", "Company"),
    ("journal", "Journal / ZATCA Setup"),
    ("invoice", "Invoice"),
    ("manual", "Manual Review"),
]


class PetroraqZatcaWarningRule(models.Model):
    _name = "petroraq.zatca.warning.rule"
    _description = "ZATCA Warning Rule"
    _order = "code"

    active = fields.Boolean(default=True)
    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    severity = fields.Selection(
        [("low", "Low"), ("medium", "Medium"), ("high", "High")],
        default="medium",
        required=True,
    )
    target_type = fields.Selection(
        WARNING_TARGET_SELECTION,
        default="manual",
        required=True,
    )
    recommended_action = fields.Html(required=True)

    _sql_constraints = [
        ("zatca_warning_rule_code_unique", "unique(code)", "A ZATCA warning code can be configured only once."),
    ]


class PetroraqZatcaWarningCase(models.Model):
    _name = "petroraq.zatca.warning.case"
    _description = "ZATCA Warning Case"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    invoice_id = fields.Many2one(
        "account.move",
        required=True,
        readonly=True,
        ondelete="cascade",
        index=True,
    )
    edi_document_id = fields.Many2one(
        "account.edi.document",
        string="ZATCA EDI Document",
        readonly=True,
        ondelete="set null",
    )
    xml_attachment_id = fields.Many2one(
        "ir.attachment", string="Analysed UBL XML", readonly=True, ondelete="set null",
    )
    xml_diagnosis = fields.Text(readonly=True)
    company_id = fields.Many2one(related="invoice_id.company_id", store=True, readonly=True)
    journal_id = fields.Many2one(related="invoice_id.journal_id", store=True, readonly=True)
    partner_id = fields.Many2one(
        related="invoice_id.commercial_partner_id", store=True, readonly=True,
    )
    rule_id = fields.Many2one("petroraq.zatca.warning.rule", ondelete="set null")
    code = fields.Char(required=True, readonly=True, index=True)
    message = fields.Text(required=True, readonly=True)
    message_hash = fields.Char(required=True, readonly=True, index=True)
    source = fields.Selection(
        [
            ("zatca", "ZATCA Response"),
            ("precheck", "Draft Pre-check"),
            ("audit", "Existing Invoice Audit"),
            ("chatter", "Chatter Import"),
            ("test", "Manual Test"),
        ],
        required=True,
        readonly=True,
        default="zatca",
    )
    severity = fields.Selection(
        [("low", "Low"), ("medium", "Medium"), ("high", "High")],
        default="medium",
        required=True,
        tracking=True,
    )
    target_type = fields.Selection(
        WARNING_TARGET_SELECTION,
        compute="_compute_recommended_action",
        compute_sudo=True,
        readonly=True,
    )
    recommended_action = fields.Html(
        compute="_compute_recommended_action", compute_sudo=True, readonly=True,
    )
    suggestion_origin = fields.Selection(
        [("rule", "Configured Rule"), ("builtin", "Built-in Guidance")],
        compute="_compute_recommended_action",
        compute_sudo=True,
        readonly=True,
    )
    state = fields.Selection(
        [
            ("open", "Open"),
            ("in_progress", "In Progress"),
            ("resolved", "Resolved"),
            ("accepted_risk", "Accepted Risk"),
        ],
        default="open",
        required=True,
        tracking=True,
        index=True,
    )
    owner_id = fields.Many2one("res.users", required=True, tracking=True)
    resolution_note = fields.Text(tracking=True)
    resolved_by_id = fields.Many2one("res.users", readonly=True)
    resolved_on = fields.Datetime(readonly=True)
    recurrence_count = fields.Integer(compute="_compute_recurrence_count")

    _sql_constraints = [
        (
            "zatca_warning_case_unique_response",
            "unique(invoice_id, source, code, message_hash)",
            "This ZATCA warning has already been registered for the invoice.",
        ),
    ]

    @api.depends("code", "invoice_id")
    def _compute_name(self):
        for case in self:
            case.name = "%s: %s" % (case.code, case.invoice_id.display_name)

    def _compute_recurrence_count(self):
        for case in self:
            if not case.partner_id or not case.code:
                case.recurrence_count = 0
                continue
            case.recurrence_count = self.search_count([
                ("partner_id", "=", case.partner_id.id),
                ("code", "=", case.code),
                ("id", "!=", case.id),
            ])

    def _builtin_suggestion(self):
        """Return a safe, useful next step when no customer-specific rule exists."""
        self.ensure_one()
        text = "%s %s" % (self.code or "", self.message or "")
        text = text.lower()

        customer_terms = (
            "buyer", "customer", "recipient", "vat number", "tax number",
            "address", "street", "city", "postal", "zip", "district",
            "building", "additional number", "country",
        )
        journal_terms = (
            "certificate", "csid", "signing", "signature", "stamp",
            "cryptographic", "onboarding", "otp", "production",
        )
        company_terms = ("seller", "supplier", "issuer", "company vat", "legal name")

        if self.code == "PR-CUSTOMER-DATA" or any(term in text for term in customer_terms):
            return (
                "customer",
                _("<p><strong>Fix the customer master data.</strong> Open the customer and complete the address and Accounting/ZATCA fields. For a Saudi B2B customer, verify the 15-digit VAT number, district, building number, and additional number.</p><p>For an invoice already accepted by ZATCA, do not edit or resubmit it; apply the correction to future invoices.</p>"),
            )
        if any(term in text for term in journal_terms):
            return (
                "journal",
                _("<p><strong>Check the ZATCA journal setup.</strong> Review the Production CSID/certificate, signing configuration, company linkage, and current certificate status. Escalate to the authorised ZATCA administrator if a certificate or onboarding value is invalid.</p><p>Do not alter an invoice already accepted by ZATCA.</p>"),
            )
        if any(term in text for term in company_terms):
            return (
                "company",
                _("<p><strong>Check the seller/company master data.</strong> Verify the legal name, VAT registration, national address, and ZATCA configuration on the company record before issuing the next invoice.</p><p>Do not alter an invoice already accepted by ZATCA.</p>"),
            )
        return (
            "invoice",
            _("<p><strong>Review the invoice source data and the original ZATCA response.</strong> Identify the affected invoice field, tax, product, payment method, or XML element, then correct the underlying master data or the next draft invoice.</p><p>If this invoice was already accepted by ZATCA, do not edit or resubmit it. Use the approved correction process where applicable and document the resolution below.</p>"),
        )

    @api.depends("rule_id", "rule_id.target_type", "rule_id.recommended_action", "code", "message")
    def _compute_recommended_action(self):
        for case in self:
            if case.rule_id:
                case.target_type = case.rule_id.target_type
                case.recommended_action = case.rule_id.recommended_action
                case.suggestion_origin = "rule"
            else:
                target_type, action = case._builtin_suggestion()
                case.target_type = target_type
                case.recommended_action = action
                case.suggestion_origin = "builtin"

    @staticmethod
    def _message_hash(code, message):
        content = "%s\n%s" % (code or "", message or "")
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _html_to_text(value):
        return " ".join(unescape(re.sub(r"<[^>]+>", " ", value or "")).split())

    def _invoice_xml_attachment(self, invoice):
        return self.env["ir.attachment"].sudo().search([
            ("res_model", "=", "account.move"),
            ("res_id", "=", invoice.id),
            "|", ("mimetype", "in", ("application/xml", "text/xml")),
            ("name", "ilike", ".xml"),
        ], order="create_date desc, id desc", limit=1)

    def _diagnose_xml_warning(self, invoice, code):
        """Return stored UBL evidence for rules that can be checked locally."""
        attachment = self._invoice_xml_attachment(invoice)
        if not attachment or code != "BR-KSA-EN16931-09":
            return attachment, False
        try:
            xml = attachment.raw
            root = etree.fromstring(
                xml,
                parser=etree.XMLParser(resolve_entities=False, no_network=True),
            )
        except (etree.XMLSyntaxError, TypeError, ValueError):
            return attachment, _("The attached XML could not be parsed. Check the UBL attachment before issuing the next invoice.")

        namespaces = {
            "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
            "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        }
        tax_currency = root.xpath("string(./cbc:TaxCurrencyCode)", namespaces=namespaces)
        tax_totals = root.xpath("./cac:TaxTotal", namespaces=namespaces)
        totals_without_subtotals = [
            total for total in tax_totals
            if not total.xpath("./cac:TaxSubtotal", namespaces=namespaces)
        ]
        if tax_currency and (len(tax_totals) != 2 or len(totals_without_subtotals) != 1):
            return attachment, _(
                "XML evidence: TaxCurrencyCode is %(currency)s; found %(total)s document-level TaxTotal element(s), including %(plain)s without TaxSubtotal. ZATCA requires a second document-level TaxTotal containing only TaxAmount when TaxCurrencyCode is present."
            ) % {
                "currency": tax_currency,
                "total": len(tax_totals),
                "plain": len(totals_without_subtotals),
            }
        return attachment, _("The attached XML has the expected TaxCurrencyCode/TaxTotal structure. Review the submitted XML version and the original ZATCA response.")

    def _find_rule(self, code):
        return self.sudo().env["petroraq.zatca.warning.rule"].search([
            ("code", "=", code),
            ("active", "=", True),
        ], limit=1)

    def _edi_document_for_invoice(self, invoice):
        return invoice.edi_document_ids.filtered(
            lambda document: document.edi_format_id.code == "sa_zatca"
        )[:1]

    def _upsert_warning(self, invoice, code, message, source, xml_attachment=False, xml_diagnosis=False):
        code = (code or "ZATCA-WARNING").strip()
        message = (message or _("No warning message was provided.")).strip()
        message_hash = self._message_hash(code, message)
        case = self.sudo().search([
            ("invoice_id", "=", invoice.id),
            ("source", "=", source),
            ("code", "=", code),
            ("message_hash", "=", message_hash),
        ], limit=1)
        if case:
            if xml_attachment and not case.xml_attachment_id:
                case.write({
                    "xml_attachment_id": xml_attachment.id,
                    "xml_diagnosis": xml_diagnosis or False,
                })
            return case
        rule = self._find_rule(code)
        return self.sudo().create({
            "invoice_id": invoice.id,
            "edi_document_id": self._edi_document_for_invoice(invoice.sudo()).id,
            "xml_attachment_id": xml_attachment.id if xml_attachment else False,
            "xml_diagnosis": xml_diagnosis or False,
            "rule_id": rule.id,
            "code": code,
            "message": message,
            "message_hash": message_hash,
            "source": source,
            "severity": rule.severity if rule else "medium",
            "owner_id": invoice.company_id.zatca_warning_owner_id.id or self.env.user.id,
        })

    def capture_zatca_response(self, invoice, response_data):
        """Persist accepted-with-warning messages returned by standard Odoo ZATCA EDI."""
        warnings = (response_data or {}).get("validationResults", {}).get(
            "warningMessages", []
        )
        cases = self.browse()
        for warning in warnings:
            if isinstance(warning, dict):
                cases |= self._upsert_warning(
                    invoice,
                    warning.get("code"),
                    warning.get("message"),
                    "zatca",
                )
        return cases

    def capture_zatca_chatter(self, invoice):
        """Import historic ZATCA warning messages preserved in invoice chatter."""
        cases = self.browse()
        messages = self.env["mail.message"].sudo().search([
            ("model", "=", "account.move"),
            ("res_id", "=", invoice.id),
            ("body", "ilike", "ZATCA"),
        ])
        pattern = re.compile(r"(?P<code>(?:BR|KSA|EN|UBL|CII)-[A-Za-z0-9._-]+)\s*:\s*(?P<message>.+)")
        for message in messages:
            text = self._html_to_text(message.body)
            for match in pattern.finditer(text):
                code = match.group("code")
                warning = match.group("message").strip()
                attachment, diagnosis = self._diagnose_xml_warning(invoice, code)
                cases |= self._upsert_warning(
                    invoice, code, warning, "chatter", attachment, diagnosis,
                )
        return cases

    def capture_draft_precheck(self, invoice, issues):
        cases = self.browse()
        for issue in issues:
            cases |= self._upsert_warning(
                invoice,
                "PR-CUSTOMER-DATA",
                issue,
                "precheck",
            )
        return cases

    def capture_existing_invoice_audit(self, invoice, issues):
        """Store current master-data risks found while auditing existing invoices."""
        cases = self.browse()
        for issue in issues:
            cases |= self._upsert_warning(
                invoice,
                "PR-CUSTOMER-DATA",
                issue,
                "audit",
            )
        return cases

    def action_start(self):
        self.write({"state": "in_progress"})

    def action_resolve(self):
        self.write({
            "state": "resolved",
            "resolved_by_id": self.env.user.id,
            "resolved_on": fields.Datetime.now(),
        })

    def action_accept_risk(self):
        self.write({
            "state": "accepted_risk",
            "resolved_by_id": self.env.user.id,
            "resolved_on": fields.Datetime.now(),
        })

    def action_open_target(self):
        self.ensure_one()
        target = False
        if self.target_type == "customer":
            target = self.partner_id
        elif self.target_type == "company":
            target = self.company_id
        elif self.target_type == "journal":
            target = self.journal_id
        elif self.target_type == "invoice":
            target = self.invoice_id
        if not target:
            raise UserError(_("This warning requires manual review."))
        return {
            "type": "ir.actions.act_window",
            "name": target.display_name,
            "res_model": target._name,
            "res_id": target.id,
            "view_mode": "form",
            "target": "current",
        }
