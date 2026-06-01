# -*- coding: utf-8 -*-
{
    "name": "Petroraq Purchase Dashboard",
    "summary": "Purchase dashboard with PR, RFQ, PO approval, vendor, product, budget, and cost-center KPIs.",
    "version": "17.0.1.0.0",
    "category": "Purchases",
    "author": "Mudassir Amin",
    "website": "https://www.petroraq.com",
    "license": "LGPL-3",
    "depends": ["purchase", "pr_custom_purchase"],
    "data": [
        "views/purchase_dashboard_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pr_purchase_dashboard/static/src/js/purchase_dashboard_action.js",
            "pr_purchase_dashboard/static/src/xml/purchase_dashboard_templates.xml",
            "pr_purchase_dashboard/static/src/css/purchase_dashboard.css",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
