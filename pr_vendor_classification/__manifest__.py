# -*- coding: utf-8 -*-
{
    "name": "Petroraq Vendor Classification",
    "summary": "Classify vendors by business nature and manage products supplied by each vendor.",
    "version": "17.0.1.0.0",
    "category": "Purchases",
    "author": "Mudassir Amin",
    "website": "https://www.petroraq.com",
    "license": "LGPL-3",
    "depends": ["purchase", "contacts"],
    "data": [
        "security/ir.model.access.csv",
        "data/vendor_category_data.xml",
        "views/vendor_category_views.xml",
        "views/res_partner_views.xml",
        "views/product_supplierinfo_views.xml",
        "views/purchase_order_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
