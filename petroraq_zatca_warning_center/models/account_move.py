from odoo import _, api, fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    zatca_warning_case_ids = fields.One2many(
        "petroraq.zatca.warning.case", "invoice_id", string="ZATCA Warning Cases",
    )
    zatca_warning_count = fields.Integer(compute="_compute_zatca_warning_counts")
    zatca_open_warning_count = fields.Integer(compute="_compute_zatca_warning_counts")

    @api.depends("zatca_warning_case_ids", "zatca_warning_case_ids.state")
    def _compute_zatca_warning_counts(self):
        for move in self:
            cases = move.zatca_warning_case_ids
            move.zatca_warning_count = len(cases)
            move.zatca_open_warning_count = len(cases.filtered(
                lambda case: case.state in ("open", "in_progress")
            ))

    def _l10n_sa_log_results(self, xml_content, response_data=None, error=False):
        result = super()._l10n_sa_log_results(xml_content, response_data, error)
        for move in self:
            self.env["petroraq.zatca.warning.case"].capture_zatca_response(
                move, response_data
            )
        return result

    def action_run_zatca_precheck(self):
        self.ensure_one()
        if self.state != "draft" or self.move_type not in ("out_invoice", "out_refund"):
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "warning",
                    "message": _("ZATCA pre-check is available only for draft customer invoices and credit notes."),
                    "sticky": False,
                },
            }
        issues = self._pr_get_zatca_customer_issues()
        if not issues:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "success",
                    "message": _("The existing customer ZATCA pre-check found no issues."),
                    "sticky": False,
                },
            }
        cases = self.env["petroraq.zatca.warning.case"].capture_draft_precheck(
            self, issues
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("ZATCA Pre-check Issues"),
            "res_model": "petroraq.zatca.warning.case",
            "view_mode": "tree,form",
            "domain": [("id", "in", cases.ids)],
            "context": {"create": False},
        }

    def action_view_zatca_warning_cases(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("ZATCA Warning Cases"),
            "res_model": "petroraq.zatca.warning.case",
            "view_mode": "tree,form",
            "domain": [("invoice_id", "=", self.id)],
            "context": {"create": False},
        }
