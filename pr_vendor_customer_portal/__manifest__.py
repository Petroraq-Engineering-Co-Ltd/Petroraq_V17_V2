# -*- coding: utf-8 -*-
{
    "name": "Petroraq Customer & Vendor Portal",
    "summary": "Customer deliveries and vendor invoice portal adapted for Petroraq workflows",
    "version": "17.0.1.0.0",
    "author": "Petroraq Engineering & Construction Co. Ltd.",
    "category": "Portal",
    "license": "OPL-1",
    "depends": [
        "portal",
        "website",
        "sale",
        "sale_stock",
        "purchase",
        "purchase_stock",
        "account",
        "mail",
        "petroraq_sale_workflow",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/vendor_invoice_sequence.xml",
        "views/vendor_invoice_views.xml",
        "views/portal_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "pr_vendor_customer_portal/static/src/scss/portal.scss",
        ],
    },
    "post_init_hook": "post_init_cleanup_legacy_portal_access",
    "installable": True,
    "application": False,
}
