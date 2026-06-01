# -*- coding: utf-8 -*-
{
    "name": "Petroraq Sales Dashboard",
    "summary": "Executive sales dashboard with revenue, customers, products, geography, and team KPIs.",
    "version": "17.0.1.0.0",
    "category": "Sales",
    "author": "Mudassir Amin",
    "website": "https://www.petroraq.com",
    "license": "LGPL-3",
    "depends": ["sale"],
    "data": [
        "views/sales_dashboard_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pr_sales_dashboard/static/src/js/sales_dashboard_action.js",
            "pr_sales_dashboard/static/src/xml/sales_dashboard_templates.xml",
            "pr_sales_dashboard/static/src/css/sales_dashboard.css",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
