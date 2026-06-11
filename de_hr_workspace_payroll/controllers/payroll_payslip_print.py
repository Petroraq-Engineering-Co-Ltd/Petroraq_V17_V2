# -*- coding: utf-8 -*-

import io
import re
from email.utils import encode_rfc2231

from odoo import http
from odoo.http import request
from odoo.tools.pdf import PdfFileReader, PdfFileWriter
from odoo.tools.safe_eval import safe_eval


class PayrollPayslipPrint(http.Controller):
    @http.route("/print/payslips/inline", type="http", auth="user")
    def get_payroll_report_inline(self, list_ids="", **post):
        if not list_ids or re.search(r"[^0-9,]", list_ids):
            return request.not_found()

        ids = [int(payslip_id) for payslip_id in list_ids.split(",") if payslip_id]
        if not ids:
            return request.not_found()

        payslips = request.env["hr.payslip"].browse(ids).exists()
        if not payslips:
            return request.not_found()

        is_payroll_user = request.env.user.has_group("hr_payroll.group_hr_payroll_user")
        if not is_payroll_user and any(payslip.employee_id.user_id != request.env.user for payslip in payslips):
            return request.not_found()

        pdf_writer = PdfFileWriter()
        payslip_reports = payslips._get_pdf_reports()

        for report, slips in payslip_reports.items():
            for payslip in slips:
                pdf_content, _report_type = (
                    request.env["ir.actions.report"]
                    .with_context(lang=payslip.employee_id.lang or payslip.env.lang)
                    .sudo()
                    ._render_qweb_pdf(report, payslip.id, data={"company_id": payslip.company_id})
                )
                reader = PdfFileReader(io.BytesIO(pdf_content), strict=False, overwriteWarnings=False)
                for page in range(reader.getNumPages()):
                    pdf_writer.addPage(reader.getPage(page))

        buffer = io.BytesIO()
        pdf_writer.write(buffer)
        merged_pdf = buffer.getvalue()
        buffer.close()

        report_name = self._get_report_name(payslips, payslip_reports)
        filename = "%s.pdf" % report_name
        return request.make_response(
            merged_pdf,
            headers=[
                ("Content-Type", "application/pdf"),
                ("Content-Length", str(len(merged_pdf))),
                ("Content-Disposition", "inline; filename*=%s" % encode_rfc2231(filename, "utf-8")),
            ],
        )

    def _get_report_name(self, payslips, payslip_reports):
        if (
            len(payslip_reports) == 1
            and len(payslips) == 1
            and payslips.struct_id.report_id.print_report_name
        ):
            return safe_eval(payslips.struct_id.report_id.print_report_name, {"object": payslips})

        report_name = " - ".join(report.name for report in payslip_reports)
        employees = payslips.employee_id.mapped("name")
        if len(employees) == 1:
            report_name = "%s - %s" % (report_name, employees[0])
        return report_name or "Payslip"
