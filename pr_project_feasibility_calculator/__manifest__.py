{
    "name": "Project Feasibility Calculator",
    "summary": "Forward and reverse investment feasibility calculator",
    "version": "17.0.1.0.3",
    "author": "Petroraq Engineering & Construction Co. Ltd.",
    "category": "Accounting/Finance",
    "license": "LGPL-3",
    "depends": ["base", "web", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "security/project_feasibility_security.xml",
        "data/feasibility_sequence.xml",
        "views/project_feasibility_views.xml",
        "views/project_feasibility_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pr_project_feasibility_calculator/static/src/js/feasibility_calculator.js",
            "pr_project_feasibility_calculator/static/src/xml/feasibility_calculator.xml",
            "pr_project_feasibility_calculator/static/src/scss/feasibility_calculator.scss",
        ],
    },
    "images": ["static/description/icon.svg"],
    "installable": True,
    "application": True,
}
