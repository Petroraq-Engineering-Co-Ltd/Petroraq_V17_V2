{
    "name": "Petroraq Backend Language Switcher",
    "version": "17.0.1.0.0",
    "summary": "One-click English / Arabic switcher in the Odoo backend navbar",
    "category": "Tools",
    "author": "Noor ul Mustafa",
    "license": "LGPL-3",
    "depends": ["web"],
    "assets": {
        "web.assets_backend": [
            "petroraq_language_switcher/static/src/js/language_switcher.js",
            "petroraq_language_switcher/static/src/xml/language_switcher.xml",
            "petroraq_language_switcher/static/src/scss/language_switcher.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
