# -*- coding: utf-8 -*-

from datetime import datetime

from odoo import fields, models


class CashMovementXlsx(models.AbstractModel):
    _name = "report.pr_account_dashboard.cash_movement_xlsx"
    _inherit = "report.report_xlsx.abstract"
    _description = "Accounting Dashboard Cash Movement Excel"

    def generate_xlsx_report(self, workbook, data, companies):
        payload = data or {}
        options = payload.get("options") or {}
        direction = payload.get("direction") or "in"
        search = (payload.get("search") or "").strip().lower()
        details = self.env["pr.account.dashboard"].get_cash_movement_details(
            options, direction
        )
        rows = details["rows"]
        if search:
            searchable = (
                "reference", "source", "source_label", "partner",
                "journal", "memo", "state", "date",
            )
            rows = [
                row for row in rows
                if any(search in str(row.get(key) or "").lower() for key in searchable)
            ]

        company_id = int(options.get("company_id") or self.env.company.id)
        company = self.env.companies.filtered(lambda item: item.id == company_id)[:1]
        company = company or self.env.company
        currency = company.currency_id
        symbol = currency.symbol or ""
        currency_format = (
            '#,##0.00 "%s"' % symbol
            if currency.position == "after"
            else '"%s" #,##0.00' % symbol
        )
        formats = self._formats(workbook, currency_format)
        self._write_summary_sheet(
            workbook, formats, details, company, options, search, rows
        )
        self._write_detail_sheet(workbook, formats, rows)

    def _formats(self, workbook, currency_format):
        return {
            "title": workbook.add_format({
                "bold": True, "font_size": 20, "font_color": "#FFFFFF",
                "bg_color": "#123B57", "align": "left", "valign": "vcenter",
            }),
            "subtitle": workbook.add_format({
                "font_color": "#D8EAF2", "bg_color": "#123B57",
                "align": "left", "valign": "vcenter",
            }),
            "label": workbook.add_format({
                "bold": True, "font_color": "#52657A", "bg_color": "#F3F7FA",
                "border": 1, "border_color": "#D9E3EC",
            }),
            "value": workbook.add_format({
                "font_color": "#172B3A", "bg_color": "#FFFFFF",
                "border": 1, "border_color": "#D9E3EC",
            }),
            "money": workbook.add_format({
                "bold": True, "font_color": "#087F5B", "bg_color": "#FFFFFF",
                "border": 1, "border_color": "#D9E3EC", "num_format": currency_format,
            }),
            "count": workbook.add_format({
                "bold": True, "font_color": "#172B3A", "bg_color": "#FFFFFF",
                "border": 1, "border_color": "#D9E3EC", "num_format": "#,##0",
            }),
            "section": workbook.add_format({
                "bold": True, "font_color": "#FFFFFF", "bg_color": "#28678A",
                "border": 1, "border_color": "#28678A",
            }),
            "header": workbook.add_format({
                "bold": True, "font_color": "#FFFFFF", "bg_color": "#123B57",
                "border": 1, "border_color": "#123B57", "align": "center",
                "valign": "vcenter", "text_wrap": True,
            }),
            "text": workbook.add_format({
                "font_color": "#243746", "border": 1, "border_color": "#DFE7ED",
                "valign": "top",
            }),
            "date": workbook.add_format({
                "font_color": "#243746", "border": 1, "border_color": "#DFE7ED",
                "num_format": "yyyy-mm-dd", "align": "center",
            }),
            "detail_money": workbook.add_format({
                "font_color": "#087F5B", "border": 1, "border_color": "#DFE7ED",
                "num_format": currency_format,
            }),
            "total_label": workbook.add_format({
                "bold": True, "font_color": "#FFFFFF", "bg_color": "#087F5B",
                "border": 1, "border_color": "#087F5B", "align": "right",
            }),
            "total_money": workbook.add_format({
                "bold": True, "font_color": "#FFFFFF", "bg_color": "#087F5B",
                "border": 1, "border_color": "#087F5B", "num_format": currency_format,
            }),
        }

    def _write_summary_sheet(self, workbook, fmt, details, company, options, search, rows):
        sheet = workbook.add_worksheet("Summary")
        sheet.hide_gridlines(2)
        widths = [13, 12, 30, 32, 32, 28, 42, 16, 18]
        for column, width in enumerate(widths):
            sheet.set_column(column, column, width)
        sheet.set_row(0, 32)
        sheet.merge_range("A1:I1", details["title"], fmt["title"])
        sheet.merge_range(
            "A2:I2", "%s | Generated %s" % (
                company.display_name,
                fields.Datetime.context_timestamp(self, fields.Datetime.now()).strftime("%Y-%m-%d %H:%M"),
            ), fmt["subtitle"]
        )
        filters = [
            ("From", options.get("date_from") or ""),
            ("To", options.get("date_to") or ""),
            ("Search filter", search or "All entries"),
            ("Exported entries", len(rows)),
        ]
        for row_index, (label, value) in enumerate(filters, start=3):
            sheet.write(row_index, 0, label, fmt["label"])
            sheet.merge_range(row_index, 1, row_index, 8, value, fmt["value"])

        sheet.merge_range("A9:I9", "Source Reconciliation", fmt["section"])
        headers = ["Source", "Description", "Entries", "Amount"]
        for column, header in enumerate(headers):
            sheet.write(9, column, header, fmt["header"])
        row_index = 10
        exported_sources = {}
        for row in rows:
            source = row.get("source") or ""
            item = exported_sources.setdefault(source, {"count": 0, "amount": 0.0})
            item["count"] += 1
            item["amount"] += row.get("amount") or 0.0
        for source in details["sources"]:
            exported = exported_sources.get(source["code"], {"count": 0, "amount": 0.0})
            sheet.write(row_index, 0, source["code"], fmt["text"])
            sheet.write(row_index, 1, source["label"], fmt["text"])
            sheet.write_number(row_index, 2, exported["count"], fmt["count"])
            sheet.write_number(row_index, 3, exported["amount"], fmt["money"])
            row_index += 1
        sheet.merge_range(row_index, 0, row_index, 2, "Export Total", fmt["total_label"])
        sheet.write_number(
            row_index, 3, sum(row.get("amount") or 0.0 for row in rows), fmt["total_money"]
        )
        detail_title_row = row_index + 2
        sheet.merge_range(
            detail_title_row, 0, detail_title_row, 8,
            "Detailed Cash Movement Entries", fmt["section"]
        )
        self._write_transaction_table(sheet, fmt, rows, detail_title_row + 1)

    def _write_detail_sheet(self, workbook, fmt, rows):
        sheet = workbook.add_worksheet("Transactions")
        sheet.hide_gridlines(2)
        sheet.freeze_panes(1, 0)
        widths = [13, 12, 30, 32, 32, 28, 42, 16, 18]
        for column, width in enumerate(widths):
            sheet.set_column(column, column, width)
        self._write_transaction_table(sheet, fmt, rows, 0)

    def _write_transaction_table(self, sheet, fmt, rows, header_row):
        headers = [
            "Date", "Source", "Reference", "Source Description", "Partner",
            "Journal / Account", "Memo", "Status", "Amount",
        ]
        sheet.set_row(header_row, 28)
        for column, header in enumerate(headers):
            sheet.write(header_row, column, header, fmt["header"])
        for row_index, row in enumerate(rows, start=header_row + 1):
            date_value = fields.Date.to_date(row.get("date"))
            if date_value:
                sheet.write_datetime(
                    row_index, 0,
                    datetime.combine(date_value, datetime.min.time()), fmt["date"]
                )
            else:
                sheet.write(row_index, 0, "", fmt["text"])
            values = [
                row.get("source"), row.get("reference"), row.get("source_label"),
                row.get("partner"), row.get("journal"), row.get("memo"), row.get("state"),
            ]
            for column, value in enumerate(values, start=1):
                sheet.write(row_index, column, value or "", fmt["text"])
            sheet.write_number(row_index, 8, row.get("amount") or 0.0, fmt["detail_money"])
        total_row = header_row + len(rows) + 1
        sheet.merge_range(total_row, 0, total_row, 7, "Total", fmt["total_label"])
        sheet.write_number(
            total_row, 8, sum(row.get("amount") or 0.0 for row in rows), fmt["total_money"]
        )
        if rows:
            sheet.autofilter(
                header_row, 0, header_row + len(rows), len(headers) - 1
            )
