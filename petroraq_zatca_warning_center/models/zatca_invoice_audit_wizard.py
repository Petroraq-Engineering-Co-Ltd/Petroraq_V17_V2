from odoo import _, fields, models


class PetroraqZatcaInvoiceAuditWizard(models.TransientModel):
    _name = "petroraq.zatca.invoice.audit.wizard"
    _description = "Audit Existing Customer Invoices for ZATCA Risks"

    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company,
    )
    date_from = fields.Date()
    date_to = fields.Date()
    include_draft = fields.Boolean(
        string="Include Draft Invoices", default=False,
        help="Draft invoices can also be reviewed with the normal pre-check button.",
    )

    def action_run_audit(self):
        self.ensure_one()
        domain = [
            ("company_id", "=", self.company_id.id),
            ("move_type", "in", ("out_invoice", "out_refund")),
            ("state", "!=", "cancel"),
        ]
        if not self.include_draft:
            domain.append(("state", "=", "posted"))
        if self.date_from:
            domain.append(("invoice_date", ">=", self.date_from))
        if self.date_to:
            domain.append(("invoice_date", "<=", self.date_to))

        cases = self.env["petroraq.zatca.warning.case"].browse()
        for invoice in self.env["account.move"].search(domain):
            cases |= self.env["petroraq.zatca.warning.case"].capture_existing_invoice_audit(
                invoice, invoice._pr_get_zatca_customer_issues()
            )

        if not cases:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "success",
                    "message": _("No current customer master-data risks were found in the selected invoices."),
                    "sticky": False,
                },
            }
        return {
            "type": "ir.actions.act_window",
            "name": _("ZATCA Invoice Audit Results"),
            "res_model": "petroraq.zatca.warning.case",
            "view_mode": "tree,form",
            "domain": [("id", "in", cases.ids)],
            "context": {"create": False},
        }

    def action_import_chatter_warnings(self):
        self.ensure_one()
        domain = [
            ("company_id", "=", self.company_id.id),
            ("move_type", "in", ("out_invoice", "out_refund")),
        ]
        if self.date_from:
            domain.append(("invoice_date", ">=", self.date_from))
        if self.date_to:
            domain.append(("invoice_date", "<=", self.date_to))
        cases = self.env["petroraq.zatca.warning.case"].browse()
        for invoice in self.env["account.move"].search(domain):
            cases |= self.env["petroraq.zatca.warning.case"].capture_zatca_chatter(invoice)
        if not cases:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "info",
                    "message": _("No importable ZATCA warning messages were found in the selected invoice chatter."),
                    "sticky": False,
                },
            }
        return {
            "type": "ir.actions.act_window",
            "name": _("Imported ZATCA Warnings"),
            "res_model": "petroraq.zatca.warning.case",
            "view_mode": "tree,form",
            "domain": [("id", "in", cases.ids)],
            "context": {"create": False},
        }
