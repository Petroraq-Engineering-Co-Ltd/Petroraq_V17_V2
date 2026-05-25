import re

from odoo import models


class PRWorkOrderXlsxReport(models.AbstractModel):
    _name = "report.pr_work_order.work_order_xlsx_report"
    _inherit = "report.report_xlsx.abstract"
    _description = "Work Order XLSX Report"

    def _sheet_name(self, name, used_names):
        clean_name = re.sub(r"[\[\]\:\*\?\/\\]", " ", name or "Work Order").strip() or "Work Order"
        clean_name = clean_name[:31]
        candidate = clean_name
        counter = 1
        while candidate in used_names:
            suffix = " %s" % counter
            candidate = "%s%s" % (clean_name[: 31 - len(suffix)], suffix)
            counter += 1
        used_names.add(candidate)
        return candidate

    def _selection_label(self, record, field_name):
        field = record._fields.get(field_name)
        if not field:
            return ""
        selection = field.selection
        if callable(selection):
            selection = selection(record)
        return dict(selection).get(record[field_name], record[field_name] or "")

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
            "section": workbook.add_format({
                "bold": True,
                "bg_color": "#cfe2f3",
                "border": 1,
                "valign": "vcenter",
            }),
            "text": workbook.add_format({"border": 1, "valign": "vcenter"}),
            "note": workbook.add_format({"italic": True, "border": 1, "valign": "vcenter"}),
            "number": workbook.add_format({"num_format": "#,##0.00", "border": 1, "valign": "vcenter"}),
            "money": workbook.add_format({"num_format": "#,##0.00", "border": 1, "valign": "vcenter"}),
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

    def _write_amount_summary(self, sheet, row, label, amount, formats):
        sheet.merge_range(row, 5, row, 6, label, formats["total_label"])
        sheet.write_number(row, 7, float(amount or 0.0), formats["total_money"])
        return row + 1

    def generate_xlsx_report(self, workbook, data, work_orders):
        formats = self._formats(workbook)
        used_names = set()

        for order in work_orders:
            sheet = workbook.add_worksheet(self._sheet_name(order.name, used_names))
            sheet.freeze_panes(11, 0)
            sheet.set_landscape()
            sheet.fit_to_pages(1, 0)
            sheet.set_column("A:A", 6)
            sheet.set_column("B:B", 18)
            sheet.set_column("C:C", 22)
            sheet.set_column("D:D", 42)
            sheet.set_column("E:E", 12)
            sheet.set_column("F:F", 12)
            sheet.set_column("G:H", 16)

            company_name = order.company_id.display_name or self.env.company.display_name
            sheet.merge_range(0, 0, 0, 7, company_name, formats["title"])
            sheet.merge_range(1, 0, 1, 7, "WORK ORDER EXPORT", formats["title"])

            self._write_pair(sheet, 3, 0, "Work Order", order.name, formats)
            self._write_pair(sheet, 3, 4, "Status", self._selection_label(order, "state"), formats)
            self._write_pair(sheet, 4, 0, "Customer", order.partner_id.display_name, formats)
            self._write_pair(sheet, 4, 4, "Sale Order", order.sale_order_id.name, formats)
            self._write_pair(sheet, 5, 0, "Project", order.project_id.display_name, formats)
            self._write_pair(sheet, 5, 4, "Cost Center", order.analytic_account_id.display_name, formats)
            self._write_pair(sheet, 6, 0, "Planned Start", str(order.date_start or ""), formats)
            self._write_pair(sheet, 6, 4, "Planned End", str(order.date_end or ""), formats)
            self._write_pair(sheet, 7, 0, "Budget", order.expense_bucket_id.display_name, formats)
            self._write_pair(sheet, 7, 4, "Currency", order.currency_id.name, formats)

            row = 9
            sheet.merge_range(row, 0, row, 7, "BOQ / Budget Lines", formats["subtitle"])
            row += 1
            headers = ["#", "Section", "Product", "Description", "Qty", "UoM", "Unit Cost", "Total"]
            sheet.write_row(row, 0, headers, formats["header"])
            row += 1

            line_no = 1
            for line in order.boq_line_ids.sorted(lambda item: (item.sequence or 0, item.id or 0)):
                if line.display_type == "line_section":
                    section_name = line.name or line.section_name or "Section"
                    sheet.merge_range(row, 0, row, 7, section_name, formats["section"])
                    row += 1
                    continue
                if line.display_type == "line_note":
                    sheet.merge_range(row, 0, row, 7, line.name or "", formats["note"])
                    row += 1
                    continue

                sheet.write_number(row, 0, line_no, formats["text"])
                sheet.write(row, 1, line.section_name or "", formats["text"])
                sheet.write(row, 2, line.product_id.display_name or "", formats["text"])
                sheet.write(row, 3, line.name or "", formats["text"])
                sheet.write_number(row, 4, float(line.qty or 0.0), formats["number"])
                sheet.write(row, 5, line.uom_id.name or "", formats["text"])
                sheet.write_number(row, 6, float(line.unit_cost or 0.0), formats["money"])
                sheet.write_number(row, 7, float(line.total or 0.0), formats["money"])
                row += 1
                line_no += 1

            row += 1
            row = self._write_amount_summary(sheet, row, "Contract Amount", order.contract_amount, formats)
            row = self._write_amount_summary(sheet, row, "Budgeted Cost", order.budgeted_cost, formats)
            row = self._write_amount_summary(sheet, row, "Budgeted Margin", order.budgeted_margin, formats)
            row = self._write_amount_summary(sheet, row, "Overhead", order.overhead_amount, formats)
            row = self._write_amount_summary(sheet, row, "Risk", order.risk_amount, formats)
            row = self._write_amount_summary(sheet, row, "Total Expected Cost", order.total_expected_cost, formats)
            row = self._write_amount_summary(sheet, row, "Profit", order.profit_amount, formats)
            row = self._write_amount_summary(sheet, row, "Total With Profit", order.total_with_profit, formats)
            row = self._write_amount_summary(sheet, row, "Actual Cost", order.actual_cost, formats)
            row = self._write_amount_summary(sheet, row, "Actual Margin", order.actual_margin, formats)

            if order.cost_center_ids:
                row += 2
                sheet.merge_range(row, 0, row, 7, "Cost Centers", formats["subtitle"])
                row += 1
                sheet.write_row(row, 0, ["Section", "Cost Center", "Department", "Subsection", "Planned", "Spent", "Remaining", "Partner"], formats["header"])
                row += 1
                for cost_center in order.cost_center_ids.sorted(lambda item: (item.sequence or 0, item.id or 0)):
                    sheet.write(row, 0, cost_center.section_name or "", formats["text"])
                    sheet.write(row, 1, cost_center.analytic_account_id.display_name or "", formats["text"])
                    sheet.write(row, 2, cost_center.department_id.display_name or "", formats["text"])
                    sheet.write(row, 3, cost_center.section_id.display_name or "", formats["text"])
                    sheet.write_number(row, 4, float(cost_center.estimated_cost or 0.0), formats["money"])
                    sheet.write_number(row, 5, float(cost_center.spent_amount or 0.0), formats["money"])
                    sheet.write_number(row, 6, float(cost_center.remaining_amount or 0.0), formats["money"])
                    sheet.write(row, 7, cost_center.partner_id.display_name or "", formats["text"])
                    row += 1

            if order.note or order.equipment_note or order.materials_note:
                row += 2
                sheet.merge_range(row, 0, row, 7, "Notes", formats["subtitle"])
                row += 1
                notes = "\n".join(filter(None, [order.note, order.equipment_note, order.materials_note]))
                sheet.merge_range(row, 0, row, 7, notes, formats["text"])
