# -*- coding: utf-8 -*-
{
    "name": "PR Title Case Widget",
    "version": "17.0.1.0.2",
    "category": "Extra Tools",
    "summary": "Reusable Title Case field widget for selected Char fields.",
    "author": "Petroraq",
    "license": "LGPL-3",
    "depends": [
        "web",
        "base",
        "hr",
        "account",
        "project",
        "product",
        "stock",
    ],
    "data": [
        "views/title_case_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pr_title_case_widget/static/src/js/title_case_field.js",
            "pr_title_case_widget/static/src/xml/title_case_field.xml",
        ],
    },
    "installable": True,
    "application": False,
}
