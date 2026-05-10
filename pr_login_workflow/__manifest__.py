{
    "name": "Login Workflow",
    "version": "17.0.1.0.0",
    "category": "Hidden",
    "author": "Mudassir",
    "website": "https://www.petroraq.com",
    "description": """
    """,
    "depends": [
        "web", "portal"
    ],

    "data": [
        "view/login_as.xml",
        "view/template.xml",
        "security/ir.model.access.csv",
        "view/action.xml"

    ],

    "assets": {
        "web.assets_backend": [
            "pr_login_workflow/static/src/js/*.js",
            "pr_login_workflow/static/src/xml/*.xml"
        ]
    },

    "installable": True,
    "auto_install": False,
    "application": False,

}
