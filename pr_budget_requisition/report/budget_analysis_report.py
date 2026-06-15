import re

from odoo import models


class PrBudgetAnalysisPdfReport(models.AbstractModel):
    _name = "report.pr_budget_requisition.budget_analysis_pdf"
    _description = "Budget Analysis PDF Report"

    def _get_report_values(self, docids, data=None):
        wizard = self.env["pr.budget.report.wizard"].browse(docids[:1])
        wizard.ensure_one()
        wizard._refresh_report_lines()
        return {
            "doc_ids": wizard.ids,
            "doc_model": wizard._name,
            "docs": wizard,
            "filters": wizard._get_report_filters(),
            "summary": wizard._get_report_summary(),
            "groups": wizard._get_budget_report_groups(include_spend_documents=True),
        }


class PrBudgetAnalysisXlsxReport(models.AbstractModel):
    _name = "report.pr_budget_requisition.budget_analysis_xlsx_report"
    _inherit = "report.report_xlsx.abstract"
    _description = "Budget Analysis XLSX Report"

    def _sheet_name(self, name, used_names):
        clean_name = re.sub(r"[\[\]\:\*\?\/\\]", " ", name or "Sheet").strip() or "Sheet"
        clean_name = clean_name[:31]
        candidate = clean_name
        counter = 1
        while candidate in used_names:
            suffix = " %s" % counter
            candidate = "%s%s" % (clean_name[: 31 - len(suffix)], suffix)
            counter += 1
        used_names.add(candidate)
        return candidate

    def _formats(self, workbook):
        blue = "#173b76"
        light_blue = "#d9eaf7"
        return {
            "title": workbook.add_format({
                "bold": True,
                "font_size": 15,
                "bg_color": blue,
                "font_color": "#ffffff",
                "align": "center",
                "valign": "vcenter",
                "border": 1,
            }),
            "subtitle": workbook.add_format({
                "bold": True,
                "font_size": 11,
                "bg_color": light_blue,
                "align": "left",
                "valign": "vcenter",
                "border": 1,
            }),
            "label": workbook.add_format({
                "bold": True,
                "bg_color": "#f2f6fa",
                "border": 1,
                "valign": "vcenter",
            }),
            "value": workbook.add_format({"border": 1, "valign": "vcenter"}),
            "header": workbook.add_format({
                "bold": True,
                "bg_color": blue,
                "font_color": "#ffffff",
                "align": "center",
                "valign": "vcenter",
                "border": 1,
            }),
            "text": workbook.add_format({"border": 1, "valign": "vcenter"}),
            "money": workbook.add_format({"num_format": "#,##0.00", "border": 1, "valign": "vcenter"}),
            "percent": workbook.add_format({"num_format": "0.00", "border": 1, "valign": "vcenter"}),
            "total_label": workbook.add_format({
                "bold": True,
                "bg_color": blue,
                "font_color": "#ffffff",
                "border": 1,
                "align": "right",
            }),
            "total_money": workbook.add_format({
                "bold": True,
                "bg_color": blue,
                "font_color": "#ffffff",
                "num_format": "#,##0.00",
                "border": 1,
            }),
        }

    def _write_pair(self, sheet, row, col, label, value, formats):
        sheet.write(row, col, label, formats["label"])
        sheet.write(row, col + 1, value or "", formats["value"])

    def _write_amount(self, sheet, row, col, value, formats):
        sheet.write_number(row, col, float(value or 0.0), formats["money"])

    def _write_summary_sheet(self, workbook, wizard, formats):
        filters = wizard._get_report_filters()
        summary = wizard._get_report_summary()
        groups = wizard._get_budget_report_groups()
        sheet = workbook.add_worksheet("Summary")
        sheet.set_landscape()
        sheet.fit_to_pages(1, 0)
        sheet.set_column("A:A", 22)
        sheet.set_column("B:B", 28)
        sheet.set_column("C:D", 18)
        sheet.set_column("E:J", 16)

        sheet.merge_range(0, 0, 0, 9, filters["company"], formats["title"])
        sheet.merge_range(1, 0, 1, 9, "BUDGET ANALYSIS REPORT", formats["title"])

        self._write_pair(sheet, 3, 0, "Budget Period", "%s to %s" % (filters["date_from"], filters["date_to"]), formats)
        self._write_pair(sheet, 3, 4, "Generated On", filters["generated_on"], formats)
        self._write_pair(sheet, 4, 0, "Departments", filters["departments"], formats)
        self._write_pair(sheet, 4, 4, "Applies To", filters["scope"], formats)
        self._write_pair(sheet, 5, 0, "Expense Type", filters["expense_type"], formats)
        self._write_pair(sheet, 5, 4, "Budget Status", filters["budget_state"], formats)

        row = 7
        sheet.merge_range(row, 0, row, 9, "Executive Summary", formats["subtitle"])
        row += 1
        headers = [
            "Budgets",
            "Requisitions",
            "Departments",
            "Cost Centers",
            "Created Budget",
            "Requested",
            "Spent",
            "Remaining",
            "Utilization %",
            "Currency",
        ]
        sheet.write_row(row, 0, headers, formats["header"])
        row += 1
        sheet.write_number(row, 0, summary["budget_count"], formats["text"])
        sheet.write_number(row, 1, summary["requisition_count"], formats["text"])
        sheet.write_number(row, 2, summary["department_count"], formats["text"])
        sheet.write_number(row, 3, summary["cost_center_count"], formats["text"])
        self._write_amount(sheet, row, 4, summary["planned_amount"], formats)
        self._write_amount(sheet, row, 5, summary["requested_amount"], formats)
        self._write_amount(sheet, row, 6, summary["spent_amount"], formats)
        self._write_amount(sheet, row, 7, summary["remaining_amount"], formats)
        sheet.write_number(row, 8, float(summary["utilization_rate"] or 0.0), formats["percent"])
        sheet.write(row, 9, filters["currency"], formats["text"])

        row += 3
        sheet.merge_range(row, 0, row, 9, "Budget Summary", formats["subtitle"])
        row += 1
        headers = [
            "Budget",
            "Requisition",
            "Department",
            "Manager",
            "Period",
            "Created Budget",
            "Spent",
            "Remaining",
            "Utilization %",
            "Status",
        ]
        sheet.write_row(row, 0, headers, formats["header"])
        row += 1
        for group in groups:
            sheet.write(row, 0, group["budget_name"], formats["text"])
            sheet.write(row, 1, group["source_requisition_name"], formats["text"])
            sheet.write(row, 2, group["department_name"], formats["text"])
            sheet.write(row, 3, group["manager_name"], formats["text"])
            sheet.write(row, 4, "%s to %s" % (group["date_from"], group["date_to"]), formats["text"])
            self._write_amount(sheet, row, 5, group["planned_amount"], formats)
            self._write_amount(sheet, row, 6, group["spent_amount"], formats)
            self._write_amount(sheet, row, 7, group["remaining_amount"], formats)
            sheet.write_number(row, 8, float(group["utilization_rate"] or 0.0), formats["percent"])
            sheet.write(row, 9, group["budget_state_label"], formats["text"])
            row += 1

    def _write_budget_lines_sheet(self, workbook, wizard, formats):
        sheet = workbook.add_worksheet("Budget Lines")
        sheet.set_landscape()
        sheet.freeze_panes(1, 0)
        sheet.autofilter(0, 0, 0, 18)
        sheet.set_column("A:D", 24)
        sheet.set_column("E:H", 16)
        sheet.set_column("I:O", 15)
        sheet.set_column("P:S", 13)
        headers = [
            "Department",
            "Budget",
            "Requisition",
            "Cost Center",
            "Expense Type",
            "Applies To",
            "Period",
            "Budget Status",
            "Created Budget",
            "Requested",
            "PR/PO Spend",
            "CPV Spend",
            "BPV Spend",
            "Total Spent",
            "Remaining",
            "Utilization %",
            "PR/PO Count",
            "CPV Count",
            "BPV Count",
        ]
        sheet.write_row(0, 0, headers, formats["header"])
        row = 1
        for line in wizard._report_lines():
            sheet.write(row, 0, line.department_id.display_name or "", formats["text"])
            sheet.write(row, 1, line.budget_id.display_name or "", formats["text"])
            sheet.write(row, 2, line.source_requisition_id.display_name or "", formats["text"])
            sheet.write(row, 3, line.cost_center_id.display_name or "", formats["text"])
            sheet.write(row, 4, wizard._selection_label(line, "expense_type") if line.expense_type else "", formats["text"])
            sheet.write(row, 5, wizard._selection_label(line, "scope") if line.scope else "", formats["text"])
            sheet.write(row, 6, "%s to %s" % (line.date_from, line.date_to), formats["text"])
            sheet.write(row, 7, wizard._selection_label(line, "budget_state") if line.budget_state else "", formats["text"])
            self._write_amount(sheet, row, 8, line.planned_amount, formats)
            self._write_amount(sheet, row, 9, line.requested_amount, formats)
            self._write_amount(sheet, row, 10, line.po_spent_amount, formats)
            self._write_amount(sheet, row, 11, line.cash_spent_amount, formats)
            self._write_amount(sheet, row, 12, line.bank_spent_amount, formats)
            self._write_amount(sheet, row, 13, line.spent_amount, formats)
            self._write_amount(sheet, row, 14, line.remaining_amount, formats)
            sheet.write_number(row, 15, float(line.utilization_rate or 0.0), formats["percent"])
            sheet.write_number(row, 16, line.po_count or 0, formats["text"])
            sheet.write_number(row, 17, line.cash_voucher_count or 0, formats["text"])
            sheet.write_number(row, 18, line.bank_voucher_count or 0, formats["text"])
            row += 1

    def _write_requisition_items_sheet(self, workbook, wizard, formats):
        sheet = workbook.add_worksheet("Requisition Items")
        sheet.set_landscape()
        sheet.freeze_panes(1, 0)
        sheet.autofilter(0, 0, 0, 14)
        sheet.set_column("A:D", 24)
        sheet.set_column("E:E", 36)
        sheet.set_column("F:H", 16)
        sheet.set_column("I:O", 15)
        headers = [
            "Requisition",
            "Budget",
            "Department",
            "Cost Center",
            "Item Description",
            "Product",
            "Quantity",
            "Unit",
            "Unit Price",
            "Requested",
            "Current Budget",
            "Spent",
            "Budget Left",
            "Remaining After Request",
            "Remarks",
        ]
        sheet.write_row(0, 0, headers, formats["header"])
        row = 1
        for group in wizard._get_budget_report_groups():
            for item in group["items"]:
                sheet.write(row, 0, group["source_requisition_name"], formats["text"])
                sheet.write(row, 1, group["budget_name"], formats["text"])
                sheet.write(row, 2, group["department_name"], formats["text"])
                sheet.write(row, 3, item.cost_center_id.display_name or "", formats["text"])
                sheet.write(row, 4, item.item_name or "", formats["text"])
                sheet.write(row, 5, item.product_id.display_name or "", formats["text"])
                sheet.write_number(row, 6, float(item.quantity or 0.0), formats["text"])
                sheet.write(row, 7, item.unit or "", formats["text"])
                self._write_amount(sheet, row, 8, item.unit_price, formats)
                self._write_amount(sheet, row, 9, item.requested_amount, formats)
                self._write_amount(sheet, row, 10, item.current_budget, formats)
                self._write_amount(sheet, row, 11, item.budget_spent, formats)
                self._write_amount(sheet, row, 12, item.budget_left, formats)
                self._write_amount(sheet, row, 13, item.remaining_after_request, formats)
                sheet.write(row, 14, item.remarks or "", formats["text"])
                row += 1

    def _write_spend_details_sheet(self, workbook, wizard, formats):
        sheet = workbook.add_worksheet("Spend Details")
        sheet.set_landscape()
        sheet.freeze_panes(1, 0)
        sheet.autofilter(0, 0, 0, 9)
        sheet.set_column("A:D", 22)
        sheet.set_column("E:E", 28)
        sheet.set_column("F:H", 24)
        sheet.set_column("I:I", 42)
        sheet.set_column("J:J", 16)
        headers = [
            "Source",
            "Document",
            "Date",
            "Status",
            "Partner",
            "Cost Center",
            "Budget",
            "Requisition",
            "Description",
            "Amount",
        ]
        sheet.write_row(0, 0, headers, formats["header"])
        row = 1
        for group in wizard._get_budget_report_groups(include_spend_documents=True):
            for doc in group["spend_documents"]:
                sheet.write(row, 0, doc["source"], formats["text"])
                sheet.write(row, 1, doc["document"], formats["text"])
                sheet.write(row, 2, str(doc["date"] or ""), formats["text"])
                sheet.write(row, 3, doc["state"], formats["text"])
                sheet.write(row, 4, doc["partner"], formats["text"])
                sheet.write(row, 5, doc["cost_center"], formats["text"])
                sheet.write(row, 6, doc["budget"], formats["text"])
                sheet.write(row, 7, doc["requisition"], formats["text"])
                sheet.write(row, 8, doc["description"], formats["text"])
                self._write_amount(sheet, row, 9, doc["amount"], formats)
                row += 1

    def generate_xlsx_report(self, workbook, data, wizards):
        wizard = wizards[:1]
        wizard.ensure_one()
        wizard._refresh_report_lines()
        formats = self._formats(workbook)
        self._write_summary_sheet(workbook, wizard, formats)
        self._write_budget_lines_sheet(workbook, wizard, formats)
        self._write_requisition_items_sheet(workbook, wizard, formats)
        self._write_spend_details_sheet(workbook, wizard, formats)
