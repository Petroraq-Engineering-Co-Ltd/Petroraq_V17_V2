# -*- coding: utf-8 -*-

{
    "name": "Petroraq Business XLSX Export",
    "summary": "Professional Excel exports for sales, purchases, invoices, bills, and journal entries",
    "version": "17.0.1.0.0",
    "category": "Productivity/Documents",
    "author": "Petroraq Engineering & Construction",
    "license": "LGPL-3",
    "depends": [
        "sale_management",
        "sale_stock",
        "purchase",
        "purchase_stock",
        "account",
        "report_xlsx",
    ],
    "data": [
        "report/business_xlsx_report_actions.xml",
        "views/business_export_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
