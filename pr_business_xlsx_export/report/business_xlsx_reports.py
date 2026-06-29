# -*- coding: utf-8 -*-

import re
from datetime import date, datetime

from odoo import fields, models
from odoo.tools import html2plaintext
from xlsxwriter.utility import xl_range


class BusinessXlsxReportMixin:
    """Shared, deliberately non-ORM helpers for all business XLSX reports."""

    BRAND_BLUE = "#173B76"
    BRAND_LIGHT_BLUE = "#D9E1F2"
    BRAND_GOLD = "#E8AA2B"
    BORDER_COLOR = "#B8C2D1"
    BODY_FONT = "Arial"
    MONEY_FORMAT = "#,##0.00;[Red]-#,##0.00;0.00"
    QUANTITY_FORMAT = "#,##0.00####;[Red]-#,##0.00####;0"
    ORDER_LINE_HEADERS = [
        "#",
        "Product Code",
        "Product Name",
        "Description",
        "Ordered Qty",
        "UoM",
        "Unit Price",
        "Discount %",
        "Discount Amount",
        "Unit Price After Discount",
        "Untaxed Amount",
        "VAT Amount",
        "Total Amount",
    ]
    ORDER_LINE_FORMATS = [
        "center",
        "text",
        "text",
        "text_wrap",
        "quantity",
        "center",
        "money",
        "percent",
        "money",
        "money",
        "money",
        "money",
        "money",
    ]
    ORDER_LINE_WIDTHS = [6, 16, 24, 42, 13, 12, 14, 12, 16, 20, 16, 16, 16]
    INVOICE_LINE_HEADERS = [
        "#",
        "Product Code",
        "Product Name",
        "Description",
        "Account",
        "Qty",
        "UoM",
        "Unit Price",
        "Discount %",
        "Discount Amount",
        "Unit Price After Discount",
        "Taxes",
        "Analytic Distribution",
        "Untaxed Amount",
        "VAT Amount",
        "Total Amount",
    ]
    INVOICE_LINE_FORMATS = [
        "center",
        "text",
        "text",
        "text_wrap",
        "text",
        "quantity",
        "center",
        "money",
        "percent",
        "money",
        "money",
        "text_wrap",
        "text_wrap",
        "money",
        "money",
        "money",
    ]
    INVOICE_LINE_WIDTHS = [
        6, 16, 24, 42, 25, 12, 12, 14, 12, 16, 20, 20, 30, 16, 16, 16
    ]

    def _build_formats(self, workbook):
        base = {"font_name": self.BODY_FONT, "font_size": 10}

        def add(**values):
            return workbook.add_format(dict(base, **values))

        return {
            "title": add(
                bold=True,
                font_size=15,
                font_color="#FFFFFF",
                bg_color=self.BRAND_BLUE,
                border=1,
                border_color=self.BRAND_BLUE,
                align="center",
                valign="vcenter",
            ),
            "subtitle": add(
                bold=True,
                font_size=12,
                font_color="#FFFFFF",
                bg_color=self.BRAND_BLUE,
                border=1,
                border_color=self.BRAND_BLUE,
                align="center",
                valign="vcenter",
            ),
            "meta_label": add(
                bold=True,
                bg_color=self.BRAND_LIGHT_BLUE,
                border=1,
                border_color=self.BORDER_COLOR,
                align="left",
                valign="vcenter",
            ),
            "meta_value": add(
                border=1,
                border_color=self.BORDER_COLOR,
                align="left",
                valign="vcenter",
            ),
            "meta_wrap": add(
                border=1,
                border_color=self.BORDER_COLOR,
                align="left",
                valign="vcenter",
                text_wrap=True,
            ),
            "meta_date": add(
                border=1,
                border_color=self.BORDER_COLOR,
                align="left",
                valign="vcenter",
                num_format="dd-mmm-yyyy",
            ),
            "header": add(
                bold=True,
                font_color="#FFFFFF",
                bg_color=self.BRAND_BLUE,
                border=1,
                border_color="#FFFFFF",
                align="center",
                valign="vcenter",
                text_wrap=True,
            ),
            "text": add(
                border=1,
                border_color=self.BORDER_COLOR,
                align="left",
                valign="top",
            ),
            "text_wrap": add(
                border=1,
                border_color=self.BORDER_COLOR,
                align="left",
                valign="top",
                text_wrap=True,
            ),
            "center": add(
                border=1,
                border_color=self.BORDER_COLOR,
                align="center",
                valign="top",
            ),
            "date": add(
                border=1,
                border_color=self.BORDER_COLOR,
                align="center",
                valign="top",
                num_format="dd-mmm-yyyy",
            ),
            "quantity": add(
                border=1,
                border_color=self.BORDER_COLOR,
                align="right",
                valign="top",
                num_format=self.QUANTITY_FORMAT,
            ),
            "money": add(
                border=1,
                border_color=self.BORDER_COLOR,
                align="right",
                valign="top",
                num_format=self.MONEY_FORMAT,
            ),
            "percent": add(
                border=1,
                border_color=self.BORDER_COLOR,
                align="right",
                valign="top",
                num_format="0.00%",
            ),
            "section": add(
                bold=True,
                font_color=self.BRAND_BLUE,
                bg_color="#EDF2F8",
                border=1,
                border_color=self.BORDER_COLOR,
                align="left",
                valign="vcenter",
            ),
            "note": add(
                italic=True,
                font_color="#4B5563",
                bg_color="#F8FAFC",
                border=1,
                border_color=self.BORDER_COLOR,
                align="left",
                valign="top",
                text_wrap=True,
            ),
            "total_label": add(
                bold=True,
                bg_color=self.BRAND_LIGHT_BLUE,
                border=1,
                border_color=self.BRAND_BLUE,
                align="right",
                valign="vcenter",
            ),
            "total_money": add(
                bold=True,
                bg_color=self.BRAND_LIGHT_BLUE,
                border=1,
                border_color=self.BRAND_BLUE,
                align="right",
                valign="vcenter",
                num_format=self.MONEY_FORMAT,
            ),
            "grand_total_label": add(
                bold=True,
                font_color="#FFFFFF",
                bg_color=self.BRAND_BLUE,
                border=1,
                border_color=self.BRAND_BLUE,
                align="right",
                valign="vcenter",
            ),
            "grand_total_money": add(
                bold=True,
                font_color="#FFFFFF",
                bg_color=self.BRAND_BLUE,
                border=1,
                border_color=self.BRAND_BLUE,
                align="right",
                valign="vcenter",
                num_format=self.MONEY_FORMAT,
            ),
            "notes_label": add(
                bold=True,
                font_color=self.BRAND_BLUE,
                bg_color=self.BRAND_LIGHT_BLUE,
                border=1,
                border_color=self.BORDER_COLOR,
                align="left",
                valign="top",
            ),
            "notes_value": add(
                border=1,
                border_color=self.BORDER_COLOR,
                align="left",
                valign="top",
                text_wrap=True,
            ),
        }

    def _safe_sheet_name(self, value, used_names):
        value = re.sub(r"[\[\]:*?/\\]", "-", str(value or "Document")).strip()
        value = value or "Document"
        base = value[:31]
        candidate = base
        counter = 2
        while candidate.casefold() in used_names:
            suffix = "-%s" % counter
            candidate = "%s%s" % (base[: 31 - len(suffix)], suffix)
            counter += 1
        used_names.add(candidate.casefold())
        return candidate

    def _selection_label(self, record, field_name):
        field = record._fields.get(field_name)
        if not field:
            return ""
        return dict(field._description_selection(self.env)).get(
            record[field_name], record[field_name] or ""
        )

    def _partner_address(self, partner):
        if not partner:
            return ""
        return partner._display_address(without_company=True) or ""

    def _tax_names(self, taxes):
        return ", ".join(taxes.mapped("name")) if taxes else ""

    def _analytic_distribution(self, distribution):
        if not distribution:
            return ""
        values = []
        AnalyticAccount = self.env["account.analytic.account"]
        for key, percentage in distribution.items():
            account_ids = []
            for account_id in str(key).split(","):
                account_id = account_id.strip()
                if account_id.isdigit():
                    account_ids.append(int(account_id))
            names = AnalyticAccount.browse(account_ids).exists().mapped("display_name")
            account_label = " / ".join(names) or str(key)
            try:
                percentage_label = "%g%%" % float(percentage)
            except (TypeError, ValueError):
                percentage_label = str(percentage)
            values.append("%s (%s)" % (account_label, percentage_label))
        return "; ".join(values)

    def _discount_values(self, unit_price, quantity, discount):
        """Return display values for a discount, or blanks when none applies."""
        discount = float(discount or 0.0)
        if not discount:
            return None, None, None
        unit_price = float(unit_price or 0.0)
        quantity = float(quantity or 0.0)
        rate = discount / 100.0
        return rate, unit_price * quantity * rate, unit_price * (1.0 - rate)

    def _order_line_values(self, line, sequence, quantity, uom):
        discount = line.discount if "discount" in line._fields else 0.0
        discount_rate, discount_amount, discounted_unit_price = self._discount_values(
            line.price_unit, quantity, discount
        )
        product = line.product_id
        return [
            sequence,
            (product.default_code or "") if product else "",
            (product.name or "") if product else "",
            line.name or "",
            quantity,
            uom.display_name if uom else "",
            line.price_unit,
            discount_rate,
            discount_amount,
            discounted_unit_price,
            line.price_subtotal,
            line.price_total - line.price_subtotal,
            line.price_total,
        ]

    def _invoice_line_values(self, line, sequence):
        discount = line.discount if "discount" in line._fields else 0.0
        discount_rate, discount_amount, discounted_unit_price = self._discount_values(
            line.price_unit, line.quantity, discount
        )
        product = line.product_id
        return [
            sequence,
            (product.default_code or "") if product else "",
            (product.name or "") if product else "",
            line.name or "",
            line.account_id.display_name if line.account_id else "",
            line.quantity,
            line.product_uom_id.display_name if line.product_uom_id else "",
            line.price_unit,
            discount_rate,
            discount_amount,
            discounted_unit_price,
            self._tax_names(line.tax_ids),
            self._analytic_distribution(line.analytic_distribution),
            line.price_subtotal,
            line.price_total - line.price_subtotal,
            line.price_total,
        ]

    def _plain_text(self, value):
        if not value:
            return ""
        return html2plaintext(value).strip()

    def _prepare_sheet(self, workbook, name, used_names, tab_color=None):
        worksheet = workbook.add_worksheet(self._safe_sheet_name(name, used_names))
        worksheet.hide_gridlines(2)
        worksheet.set_landscape()
        worksheet.set_paper(9)  # A4
        worksheet.fit_to_pages(1, 0)
        worksheet.center_horizontally()
        worksheet.set_margins(left=0.25, right=0.25, top=0.4, bottom=0.5)
        worksheet.set_default_row(18)
        worksheet.set_tab_color(tab_color or self.BRAND_BLUE)
        return worksheet

    def _write_string(self, worksheet, row, col, value, cell_format):
        # write_string also prevents user-provided values beginning with '=' from
        # being interpreted as formulas by Excel.
        worksheet.write_string(row, col, str(value or ""), cell_format)

    def _write_value(self, worksheet, row, col, value, cell_format):
        if value in (None, False):
            worksheet.write_blank(row, col, None, cell_format)
        elif isinstance(value, datetime):
            worksheet.write_datetime(row, col, value, cell_format)
        elif isinstance(value, date):
            worksheet.write_datetime(
                row, col, datetime.combine(value, datetime.min.time()), cell_format
            )
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            worksheet.write_number(row, col, float(value), cell_format)
        else:
            self._write_string(worksheet, row, col, value, cell_format)

    def _merge_text(self, worksheet, first_row, first_col, last_row, last_col, value, cell_format):
        worksheet.merge_range(first_row, first_col, last_row, last_col, "", cell_format)
        self._write_string(worksheet, first_row, first_col, value, cell_format)

    def _write_title(self, worksheet, company, report_title, document_label, last_col, formats):
        company_title = company.display_name or ""
        if company.vat:
            company_title += " - VAT Number %s" % company.vat
        self._merge_text(worksheet, 0, 0, 0, last_col, company_title, formats["title"])
        self._merge_text(worksheet, 1, 0, 1, last_col, report_title, formats["title"])
        self._merge_text(worksheet, 2, 0, 2, last_col, document_label, formats["subtitle"])
        worksheet.set_row(0, 28)
        worksheet.set_row(1, 25)
        worksheet.set_row(2, 22)

    def _write_metadata(self, worksheet, start_row, entries, last_col, formats):
        half = (last_col + 1) // 2
        left_value_end = half - 1
        right_label_col = half
        right_value_end = last_col
        for index in range(0, len(entries), 2):
            row = start_row + (index // 2)
            row_entries = entries[index:index + 2]
            for side, entry in enumerate(row_entries):
                label, value = entry[:2]
                value_kind = entry[2] if len(entry) > 2 else "text"
                label_col = 0 if side == 0 else right_label_col
                value_col = label_col + 1
                value_end = left_value_end if side == 0 else right_value_end
                self._write_string(worksheet, row, label_col, label, formats["meta_label"])
                value_format = formats[
                    "meta_date" if value_kind == "date" else
                    "meta_wrap" if value_kind == "wrap" else
                    "meta_value"
                ]
                if value_end > value_col:
                    worksheet.merge_range(row, value_col, row, value_end, "", value_format)
                self._write_value(worksheet, row, value_col, value, value_format)
                if value_kind == "wrap":
                    worksheet.set_row(row, 32)
        return start_row + ((len(entries) + 1) // 2)

    def _write_table_header(self, worksheet, row, headers, formats):
        for col, header in enumerate(headers):
            self._write_string(worksheet, row, col, header, formats["header"])
        worksheet.set_row(row, 34)

    def _write_special_line(
        self, worksheet, row, col_count, label, formats, kind, label_col=1
    ):
        cell_format = formats[kind]
        for col in range(col_count):
            worksheet.write_blank(row, col, None, cell_format)
        target_col = min(label_col, col_count - 1) if col_count else 0
        self._write_string(worksheet, row, target_col, label, cell_format)
        worksheet.set_row(row, 30 if kind == "note" else 21)

    def _write_totals(self, worksheet, row, first_data_row, last_data_row,
                      subtotal_col, total_col, untaxed, tax, total, formats,
                      tax_col=None):
        label_col = total_col - 1
        data_range = lambda col: xl_range(first_data_row, col, last_data_row, col)
        tax_formula = (
            "=SUM(%s)" % data_range(tax_col)
            if tax_col is not None
            else "=SUM(%s)-SUM(%s)"
            % (data_range(total_col), data_range(subtotal_col))
        )
        totals = [
            ("Untaxed Amount", "=SUM(%s)" % data_range(subtotal_col), untaxed, False),
            ("Tax Amount", tax_formula, tax, False),
            ("Total Amount", "=SUM(%s)" % data_range(total_col), total, True),
        ]
        for label, formula, cached_value, is_grand_total in totals:
            label_format = formats["grand_total_label" if is_grand_total else "total_label"]
            amount_format = formats["grand_total_money" if is_grand_total else "total_money"]
            self._write_string(worksheet, row, label_col, label, label_format)
            worksheet.write_formula(row, total_col, formula, amount_format, cached_value or 0.0)
            row += 1
        return row

    def _write_notes(self, worksheet, row, last_col, notes, formats):
        notes = self._plain_text(notes)
        if not notes:
            return row
        row += 1
        self._write_string(worksheet, row, 0, "Notes", formats["notes_label"])
        if last_col > 1:
            worksheet.merge_range(row, 1, row, last_col, "", formats["notes_value"])
        self._write_string(worksheet, row, 1, notes, formats["notes_value"])
        worksheet.set_row(row, min(90, max(32, 15 * (notes.count("\n") + 2))))
        return row + 1

    def _finalize_sheet(self, worksheet, document_name, table_header_row,
                        first_data_row, last_data_row, last_col):
        if last_data_row >= first_data_row:
            worksheet.autofilter(table_header_row, 0, last_data_row, last_col)
        worksheet.freeze_panes(first_data_row, 0)
        worksheet.repeat_rows(0, table_header_row)
        generated = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        footer_name = re.sub(r"[&]", "&&", str(document_name or ""))
        worksheet.set_footer(
            "&L%s&CPage &P of &N&RGenerated %s"
            % (footer_name, generated.strftime("%d-%b-%Y %H:%M"))
        )


class PurchaseOrderXlsx(BusinessXlsxReportMixin, models.AbstractModel):
    _name = "report.pr_business_xlsx_export.purchase_order_xlsx"
    _inherit = "report.report_xlsx.abstract"
    _description = "Purchase Order XLSX Export"

    def generate_xlsx_report(self, workbook, data, orders):
        formats = self._build_formats(workbook)
        used_names = set()
        headers = self.ORDER_LINE_HEADERS
        for order in orders:
            sheet = self._prepare_sheet(workbook, order.name, used_names, self.BRAND_GOLD)
            last_col = len(headers) - 1
            state = self._selection_label(order, "state")
            self._write_title(
                sheet, order.company_id, "Purchase Order", "%s | %s | %s"
                % (order.name or "Draft", state, order.currency_id.name), last_col, formats
            )
            metadata = [
                ("Vendor", order.partner_id.display_name),
                ("Vendor Reference", order.partner_ref or ""),
                ("Order Date", order.date_order, "date"),
                ("Expected Arrival", order.date_planned, "date"),
                ("Buyer", order.user_id.display_name),
                ("Currency", order.currency_id.display_name),
                ("Payment Terms", order.payment_term_id.display_name),
                ("Status", state),
                ("Vendor VAT", order.partner_id.vat or ""),
                ("Delivery Address", self._partner_address(order.dest_address_id or order.company_id.partner_id), "wrap"),
                ("Vendor Address", self._partner_address(order.partner_id), "wrap"),
                ("Operation Type", order.picking_type_id.display_name),
            ]
            next_row = self._write_metadata(sheet, 4, metadata, last_col, formats)
            table_header_row = next_row + 1
            self._write_table_header(sheet, table_header_row, headers, formats)
            first_data_row = table_header_row + 1
            row = first_data_row
            sequence = 1
            for line in order.order_line.sorted(lambda item: (item.sequence, item.id)):
                if line.display_type in ("line_section", "line_note"):
                    self._write_special_line(
                        sheet, row, len(headers), line.name or "", formats,
                        "section" if line.display_type == "line_section" else "note",
                        label_col=2,
                    )
                    row += 1
                    continue
                values = self._order_line_values(
                    line, sequence, line.product_qty, line.product_uom
                )
                for col, (value, format_name) in enumerate(
                    zip(values, self.ORDER_LINE_FORMATS)
                ):
                    self._write_value(sheet, row, col, value, formats[format_name])
                sheet.set_row(row, 30)
                sequence += 1
                row += 1
            last_data_row = row - 1
            if last_data_row < first_data_row:
                for col in range(len(headers)):
                    sheet.write_blank(first_data_row, col, None, formats["text"])
                last_data_row = first_data_row
                row = first_data_row + 1
            row += 1
            row = self._write_totals(
                sheet, row, first_data_row, last_data_row, 10, 12,
                order.amount_untaxed, order.amount_tax, order.amount_total, formats,
                tax_col=11,
            )
            self._write_notes(sheet, row, last_col, order.notes, formats)
            for col, width in enumerate(self.ORDER_LINE_WIDTHS):
                sheet.set_column(col, col, width)
            self._finalize_sheet(
                sheet, order.name, table_header_row, first_data_row, last_data_row, last_col
            )


class SaleOrderXlsx(BusinessXlsxReportMixin, models.AbstractModel):
    _name = "report.pr_business_xlsx_export.sale_order_xlsx"
    _inherit = "report.report_xlsx.abstract"
    _description = "Sale Order XLSX Export"

    def generate_xlsx_report(self, workbook, data, orders):
        formats = self._build_formats(workbook)
        used_names = set()
        headers = self.ORDER_LINE_HEADERS
        for order in orders:
            sheet = self._prepare_sheet(workbook, order.name, used_names)
            last_col = len(headers) - 1
            state = self._selection_label(order, "state")
            self._write_title(
                sheet, order.company_id, "Sales Order / Quotation", "%s | %s | %s"
                % (order.name or "Draft", state, order.currency_id.name), last_col, formats
            )
            po_number = getattr(order, "po_number", False) or order.client_order_ref or ""
            po_date = getattr(order, "po_date", False)
            metadata = [
                ("Customer", order.partner_id.display_name),
                ("Customer PO Number", po_number),
                ("Order Date", order.date_order, "date"),
                ("Customer PO Date", po_date, "date"),
                ("Salesperson", order.user_id.display_name),
                ("Currency", order.currency_id.display_name),
                ("Payment Terms", order.payment_term_id.display_name),
                ("Status", state),
                ("Customer VAT", order.partner_id.vat or ""),
                ("Validity Date", order.validity_date, "date"),
                ("Customer Address", self._partner_address(order.partner_invoice_id or order.partner_id), "wrap"),
                ("Delivery Address", self._partner_address(order.partner_shipping_id), "wrap"),
                ("Warehouse", order.warehouse_id.display_name),
                ("Expected Date", order.commitment_date, "date"),
            ]
            next_row = self._write_metadata(sheet, 4, metadata, last_col, formats)
            table_header_row = next_row + 1
            self._write_table_header(sheet, table_header_row, headers, formats)
            first_data_row = table_header_row + 1
            row = first_data_row
            sequence = 1
            for line in order.order_line.sorted(lambda item: (item.sequence, item.id)):
                if line.display_type in ("line_section", "line_note"):
                    self._write_special_line(
                        sheet, row, len(headers), line.name or "", formats,
                        "section" if line.display_type == "line_section" else "note",
                        label_col=2,
                    )
                    row += 1
                    continue
                values = self._order_line_values(
                    line, sequence, line.product_uom_qty, line.product_uom
                )
                for col, (value, format_name) in enumerate(
                    zip(values, self.ORDER_LINE_FORMATS)
                ):
                    self._write_value(sheet, row, col, value, formats[format_name])
                sheet.set_row(row, 30)
                sequence += 1
                row += 1
            last_data_row = row - 1
            if last_data_row < first_data_row:
                for col in range(len(headers)):
                    sheet.write_blank(first_data_row, col, None, formats["text"])
                last_data_row = first_data_row
                row = first_data_row + 1
            row += 1
            row = self._write_totals(
                sheet, row, first_data_row, last_data_row, 10, 12,
                order.amount_untaxed, order.amount_tax, order.amount_total, formats,
                tax_col=11,
            )
            self._write_notes(sheet, row, last_col, order.note, formats)
            for col, width in enumerate(self.ORDER_LINE_WIDTHS):
                sheet.set_column(col, col, width)
            self._finalize_sheet(
                sheet, order.name, table_header_row, first_data_row, last_data_row, last_col
            )


class AccountMoveXlsx(BusinessXlsxReportMixin, models.AbstractModel):
    _name = "report.pr_business_xlsx_export.account_move_xlsx"
    _inherit = "report.report_xlsx.abstract"
    _description = "Invoice Bill and Journal Entry XLSX Export"

    MOVE_TITLES = {
        "out_invoice": "Customer Invoice",
        "out_refund": "Customer Credit Note",
        "in_invoice": "Vendor Bill",
        "in_refund": "Vendor Credit Note",
        "out_receipt": "Sales Receipt",
        "in_receipt": "Purchase Receipt",
        "entry": "Journal Entry",
    }

    def generate_xlsx_report(self, workbook, data, moves):
        formats = self._build_formats(workbook)
        used_names = set()
        for move in moves:
            title = self.MOVE_TITLES.get(move.move_type, "Accounting Entry")
            sheet = self._prepare_sheet(workbook, move.name or title, used_names)
            if move.is_invoice(include_receipts=True):
                self._write_invoice_sheet(sheet, move, title, formats)
            else:
                self._write_journal_sheet(sheet, move, title, formats)

    def _move_metadata(self, move):
        return [
            ("Partner", move.partner_id.display_name),
            ("Reference", move.ref or ""),
            ("Invoice / Bill Date", move.invoice_date, "date"),
            ("Accounting Date", move.date, "date"),
            ("Due Date", move.invoice_date_due, "date"),
            ("Payment Reference", move.payment_reference or ""),
            ("Journal", move.journal_id.display_name),
            ("Currency", move.currency_id.display_name),
            ("Payment Terms", move.invoice_payment_term_id.display_name),
            ("Responsible", move.invoice_user_id.display_name),
            ("Status", self._selection_label(move, "state")),
            ("Partner VAT", move.partner_id.vat or ""),
            ("Partner Address", self._partner_address(move.partner_id), "wrap"),
            ("Source Document", move.invoice_origin or ""),
            ("PO Number", getattr(move, "po_number", False) or ""),
            ("PO Date", getattr(move, "po_date", False), "date"),
        ]

    def _write_invoice_sheet(self, sheet, move, title, formats):
        headers = self.INVOICE_LINE_HEADERS
        last_col = len(headers) - 1
        state = self._selection_label(move, "state")
        self._write_title(
            sheet, move.company_id, title,
            "%s | %s | %s" % (move.name or "Draft", state, move.currency_id.name),
            last_col, formats,
        )
        next_row = self._write_metadata(sheet, 4, self._move_metadata(move), last_col, formats)
        table_header_row = next_row + 1
        self._write_table_header(sheet, table_header_row, headers, formats)
        first_data_row = table_header_row + 1
        row = first_data_row
        sequence = 1
        for line in move.invoice_line_ids.sorted(lambda item: (item.sequence, item.id)):
            if line.display_type in ("line_section", "line_note"):
                self._write_special_line(
                    sheet, row, len(headers), line.name or "", formats,
                    "section" if line.display_type == "line_section" else "note",
                    label_col=2,
                )
                row += 1
                continue
            values = self._invoice_line_values(line, sequence)
            for col, (value, format_name) in enumerate(
                zip(values, self.INVOICE_LINE_FORMATS)
            ):
                self._write_value(sheet, row, col, value, formats[format_name])
            sheet.set_row(row, 30)
            sequence += 1
            row += 1
        last_data_row = row - 1
        if last_data_row < first_data_row:
            for col in range(len(headers)):
                sheet.write_blank(first_data_row, col, None, formats["text"])
            last_data_row = first_data_row
            row = first_data_row + 1
        row += 1
        row = self._write_totals(
            sheet, row, first_data_row, last_data_row, 13, 15,
            move.amount_untaxed, move.amount_tax, move.amount_total, formats,
            tax_col=14,
        )
        self._write_notes(sheet, row, last_col, move.narration, formats)
        for col, width in enumerate(self.INVOICE_LINE_WIDTHS):
            sheet.set_column(col, col, width)
        self._finalize_sheet(
            sheet, move.name, table_header_row, first_data_row, last_data_row, last_col
        )

    def _write_journal_sheet(self, sheet, move, title, formats):
        headers = [
            "#", "Date", "Partner", "Account Code", "Account Name", "Label",
            "Analytic Distribution", "Currency", "Amount Currency", "Debit",
            "Credit", "Balance",
        ]
        last_col = len(headers) - 1
        state = self._selection_label(move, "state")
        self._write_title(
            sheet, move.company_id, title,
            "%s | %s | %s" % (move.name or "Draft", state, move.currency_id.name),
            last_col, formats,
        )
        metadata = [
            ("Journal", move.journal_id.display_name),
            ("Reference", move.ref or ""),
            ("Accounting Date", move.date, "date"),
            ("Status", state),
            ("Company", move.company_id.display_name),
            ("Currency", move.currency_id.display_name),
            ("Partner", move.partner_id.display_name),
            ("Created By", move.create_uid.display_name),
        ]
        next_row = self._write_metadata(sheet, 4, metadata, last_col, formats)
        table_header_row = next_row + 1
        self._write_table_header(sheet, table_header_row, headers, formats)
        first_data_row = table_header_row + 1
        row = first_data_row
        sequence = 1
        for line in move.line_ids.sorted(lambda item: (item.sequence, item.id)):
            if line.display_type in ("line_section", "line_note"):
                self._write_special_line(
                    sheet, row, len(headers), line.name or "", formats,
                    "section" if line.display_type == "line_section" else "note",
                )
                row += 1
                continue
            values = [
                sequence,
                line.date,
                line.partner_id.display_name,
                line.account_id.code or "",
                line.account_id.name or "",
                line.name or "",
                self._analytic_distribution(line.analytic_distribution),
                line.currency_id.name or move.company_currency_id.name,
                line.amount_currency,
                line.debit,
                line.credit,
                line.balance,
            ]
            row_formats = [
                "center", "date", "text", "text", "text", "text_wrap",
                "text_wrap", "center", "money", "money", "money", "money",
            ]
            for col, (value, format_name) in enumerate(zip(values, row_formats)):
                self._write_value(sheet, row, col, value, formats[format_name])
            sheet.set_row(row, 26)
            sequence += 1
            row += 1
        last_data_row = row - 1
        if last_data_row < first_data_row:
            for col in range(len(headers)):
                sheet.write_blank(first_data_row, col, None, formats["text"])
            last_data_row = first_data_row
            row = first_data_row + 1
        row += 1
        ranges = {col: xl_range(first_data_row, col, last_data_row, col) for col in (8, 9, 10, 11)}
        self._write_string(sheet, row, 7, "Totals", formats["grand_total_label"])
        cached = {
            8: sum(move.line_ids.mapped("amount_currency")),
            9: sum(move.line_ids.mapped("debit")),
            10: sum(move.line_ids.mapped("credit")),
            11: sum(move.line_ids.mapped("balance")),
        }
        for col in (8, 9, 10, 11):
            sheet.write_formula(
                row, col, "=SUM(%s)" % ranges[col], formats["grand_total_money"], cached[col]
            )
        self._write_notes(sheet, row + 1, last_col, move.narration, formats)
        widths = [6, 13, 25, 14, 26, 38, 30, 12, 16, 16, 16, 16]
        for col, width in enumerate(widths):
            sheet.set_column(col, col, width)
        self._finalize_sheet(
            sheet, move.name, table_header_row, first_data_row, last_data_row, last_col
        )
