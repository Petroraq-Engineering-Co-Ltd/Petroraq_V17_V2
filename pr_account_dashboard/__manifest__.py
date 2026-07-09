# -*- coding: utf-8 -*-
{
    "name": "Petroraq Accounting Dashboard",
    "summary": "Executive accounting dashboard for invoices, bills, vouchers, cash, journals, aging, VAT, and approvals.",
    "version": "17.0.1.0.3",
    "category": "Accounting/Accounting",
    "author": "Petroraq",
    "website": "https://www.petroraq.com",
    "license": "LGPL-3",
    "depends": ["account_accountant", "pr_account", "account_ledger"],
    "data": [
        "views/account_dashboard_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pr_account_dashboard/static/src/js/account_dashboard_action.js",
            "pr_account_dashboard/static/src/xml/account_dashboard_templates.xml",
            "pr_account_dashboard/static/src/css/account_dashboard.css",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
