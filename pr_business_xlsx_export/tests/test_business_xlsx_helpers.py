# -*- coding: utf-8 -*-

from io import BytesIO
from zipfile import ZipFile

from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools.misc import xlsxwriter


@tagged("post_install", "-at_install")
class TestBusinessXlsxHelpers(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env["report.pr_business_xlsx_export.sale_order_xlsx"]

    def test_sheet_names_are_valid_and_unique(self):
        used = set()
        first = self.report._safe_sheet_name("SO/2026:0001*[test]", used)
        second = self.report._safe_sheet_name("SO/2026:0001*[test]", used)
        self.assertLessEqual(len(first), 31)
        self.assertNotRegex(first, r"[\[\]:*?/\\]")
        self.assertNotEqual(first.casefold(), second.casefold())

    def test_user_text_is_not_written_as_excel_formula(self):
        stream = BytesIO()
        workbook = xlsxwriter.Workbook(stream, {"in_memory": True})
        worksheet = workbook.add_worksheet("Safe Text")
        cell_format = workbook.add_format({"border": 1})
        self.report._write_string(worksheet, 0, 0, "=2+2", cell_format)
        workbook.close()

        with ZipFile(BytesIO(stream.getvalue())) as archive:
            sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
            strings_xml = archive.read("xl/sharedStrings.xml").decode("utf-8")
        self.assertNotIn("<f>", sheet_xml)
        self.assertIn("=2+2", strings_xml)

    def test_brand_formats_and_formula_totals_build_valid_xlsx(self):
        stream = BytesIO()
        workbook = xlsxwriter.Workbook(stream, {"in_memory": True})
        formats = self.report._build_formats(workbook)
        worksheet = workbook.add_worksheet("Totals")
        self.report._write_table_header(
            worksheet, 0, ["Description", "Untaxed", "Total"], formats
        )
        self.report._write_string(worksheet, 1, 0, "Service", formats["text"])
        worksheet.write_number(1, 1, 100.0, formats["money"])
        worksheet.write_number(1, 2, 115.0, formats["money"])
        self.report._write_totals(
            worksheet, 3, 1, 1, 1, 2, 100.0, 15.0, 115.0, formats
        )
        workbook.close()

        with ZipFile(BytesIO(stream.getvalue())) as archive:
            sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
            styles_xml = archive.read("xl/styles.xml").decode("utf-8")
        self.assertIn("SUM(B2)", sheet_xml)
        self.assertIn("SUM(C2)-SUM(B2)", sheet_xml)
        self.assertIn("FF173B76", styles_xml)

    def test_discount_values_are_blank_without_discount(self):
        self.assertEqual(
            self.report._discount_values(125.0, 4.0, 0.0),
            (None, None, None),
        )

    def test_purchase_and_sale_orders_share_requested_line_layout(self):
        self.assertEqual(
            self.report.ORDER_LINE_HEADERS,
            [
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
            ],
        )

    def test_invoice_and_bill_layout_keeps_existing_fields_and_adds_details(self):
        self.assertEqual(
            self.report.INVOICE_LINE_HEADERS,
            [
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
            ],
        )

    def test_discount_values_include_rate_amount_and_net_unit_price(self):
        rate, amount, net_unit_price = self.report._discount_values(
            125.0, 4.0, 10.0
        )
        self.assertEqual(rate, 0.10)
        self.assertEqual(amount, 50.0)
        self.assertEqual(net_unit_price, 112.5)

    def test_explicit_vat_column_is_used_by_totals(self):
        stream = BytesIO()
        workbook = xlsxwriter.Workbook(stream, {"in_memory": True})
        formats = self.report._build_formats(workbook)
        worksheet = workbook.add_worksheet("VAT")
        worksheet.write_number(1, 1, 100.0, formats["money"])
        worksheet.write_number(1, 2, 15.0, formats["money"])
        worksheet.write_number(1, 3, 115.0, formats["money"])
        self.report._write_totals(
            worksheet,
            3,
            1,
            1,
            1,
            3,
            100.0,
            15.0,
            115.0,
            formats,
            tax_col=2,
        )
        workbook.close()

        with ZipFile(BytesIO(stream.getvalue())) as archive:
            sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("SUM(C2)", sheet_xml)

