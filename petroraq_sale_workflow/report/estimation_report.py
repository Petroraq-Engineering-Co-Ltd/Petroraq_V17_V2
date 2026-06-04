import re

from odoo import api, models


class PetroraqEstimationPdfReport(models.AbstractModel):
    _name = "report.petroraq_sale_workflow.estimation_pdf"
    _description = "Estimation PDF Report"

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["petroraq.estimation"].browse(docids)
        for doc in docs:
            if not doc.display_line_ids:
                doc._rebuild_display_lines()
        return {
            "doc_ids": docids,
            "doc_model": "petroraq.estimation",
            "docs": docs,
        }


class PetroraqEstimationXlsxReport(models.AbstractModel):
    _name = "report.petroraq_sale_workflow.estimation_xlsx_report"
    _inherit = "report.report_xlsx.abstract"
    _description = "Estimation XLSX Report"

    def _sheet_name(self, name, used_names):
        clean_name = re.sub(r"[\[\]\:\*\?\/\\]", " ", name or "Estimation").strip() or "Estimation"
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
                "bg_color": "#d9eaf7",
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
            "note": workbook.add_format({"italic": True, "border": 1, "valign": "vcenter"}),
            "text": workbook.add_format({"border": 1, "valign": "vcenter"}),
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

    def generate_xlsx_report(self, workbook, data, estimations):
        formats = self._formats(workbook)
        used_names = set()

        for estimation in estimations:
            if not estimation.display_line_ids:
                estimation._rebuild_display_lines()

            sheet = workbook.add_worksheet(self._sheet_name(estimation.name, used_names))
            sheet.freeze_panes(11, 0)
            sheet.set_landscape()
            sheet.fit_to_pages(1, 0)
            sheet.set_column("A:A", 6)
            sheet.set_column("B:B", 16)
            sheet.set_column("C:C", 24)
            sheet.set_column("D:D", 42)
            sheet.set_column("E:E", 12)
            sheet.set_column("F:F", 12)
            sheet.set_column("G:H", 16)

            company_name = estimation.company_id.display_name or self.env.company.display_name
            sheet.merge_range(0, 0, 0, 7, company_name, formats["title"])
            sheet.merge_range(1, 0, 1, 7, "ESTIMATION EXPORT", formats["title"])

            self._write_pair(sheet, 3, 0, "Estimation", estimation.name, formats)
            self._write_pair(sheet, 3, 4, "Status", self._selection_label(estimation, "approval_state"), formats)
            self._write_pair(sheet, 4, 0, "Customer", estimation.partner_id.display_name, formats)
            self._write_pair(sheet, 4, 4, "Date", str(estimation.date or ""), formats)
            self._write_pair(sheet, 5, 0, "Quotation", estimation.sale_order_id.name, formats)
            self._write_pair(sheet, 5, 4, "Work Order", estimation.work_order_id.name, formats)
            self._write_pair(sheet, 6, 0, "Currency", estimation.currency_id.name, formats)
            self._write_pair(sheet, 6, 4, "Revision", str(getattr(estimation, "revision_number", "") or ""), formats)

            row = 9
            sheet.merge_range(row, 0, row, 7, "Estimation Lines", formats["subtitle"])
            row += 1
            sheet.write_row(row, 0, ["#", "Section", "Product", "Description", "Qty", "UoM", "Unit Cost", "Subtotal"], formats["header"])
            row += 1

            line_no = 1
            for line in estimation.display_line_ids.sorted(lambda item: (item.sequence or 0, item.id or 0)):
                if line.display_type == "line_section":
                    subtotal = "Sub Total: {:,.2f}".format(line.section_subtotal_amount or 0.0)
                    sheet.merge_range(row, 0, row, 4, line.name or "", formats["section"])
                    sheet.merge_range(row, 5, row, 7, subtotal, formats["section"])
                    row += 1
                    continue
                if line.display_type == "line_note":
                    sheet.merge_range(row, 0, row, 7, line.name or "", formats["note"])
                    row += 1
                    continue

                qty = line.quantity_hours if line.section_type in ("labor", "equipment") else line.quantity
                sheet.write_number(row, 0, line_no, formats["text"])
                sheet.write(row, 1, self._selection_label(line, "section_type"), formats["text"])
                sheet.write(row, 2, line.product_id.display_name or "", formats["text"])
                sheet.write(row, 3, line.name or "", formats["text"])
                sheet.write_number(row, 4, float(qty or 0.0), formats["number"])
                sheet.write(row, 5, line.uom_id.name or "", formats["text"])
                sheet.write_number(row, 6, float(line.unit_cost or 0.0), formats["money"])
                sheet.write_number(row, 7, float(line.subtotal or 0.0), formats["money"])
                row += 1
                line_no += 1

            row += 1
            row = self._write_amount_summary(sheet, row, "Material Total", estimation.material_total, formats)
            row = self._write_amount_summary(sheet, row, "Labor Total", estimation.labor_total, formats)
            row = self._write_amount_summary(sheet, row, "Equipment Total", estimation.equipment_total, formats)
            row = self._write_amount_summary(sheet, row, "Sub Contract / TPS Total", estimation.subcontract_total, formats)
            row = self._write_amount_summary(sheet, row, "Base Total", estimation.total_amount, formats)
            row = self._write_amount_summary(sheet, row, "Overhead", estimation.overhead_amount, formats)
            row = self._write_amount_summary(sheet, row, "Risk", estimation.risk_amount, formats)
            row = self._write_amount_summary(sheet, row, "Computed Total", estimation.buffer_total_amount, formats)
            row = self._write_amount_summary(sheet, row, "Profit", estimation.profit_amount, formats)
            self._write_amount_summary(sheet, row, "Total With Profit", estimation.total_with_profit, formats)
