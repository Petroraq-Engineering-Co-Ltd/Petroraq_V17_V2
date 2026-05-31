# -*- coding: utf-8 -*-

from odoo import api, models


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    @api.model
    def _pr_find_payslip_report_action(self):
        report = self.env.ref("hr_payroll.action_report_payslip", raise_if_not_found=False)
        if report:
            return report.sudo()

        report = self.sudo().search([
            ("model", "=", "hr.payslip"),
            ("report_type", "=", "qweb-pdf"),
            ("report_name", "in", ["hr_payroll.report_payslip_lang", "hr_payroll.report_payslip"]),
        ], limit=1)
        if report:
            return report

        return self.sudo().search([
            ("model", "=", "hr.payslip"),
            ("report_type", "=", "qweb-pdf"),
        ], limit=1)

    @api.model
    def _pr_configure_payslip_paperformat(self):
        paperformat = self.env.ref(
            "de_hr_workspace_payroll.paperformat_payslip_custom_header_footer",
            raise_if_not_found=False,
        )
        if not paperformat:
            return False

        report = self._pr_find_payslip_report_action()
        if report and report.paperformat_id != paperformat:
            report.write({"paperformat_id": paperformat.id})
        return bool(report)
