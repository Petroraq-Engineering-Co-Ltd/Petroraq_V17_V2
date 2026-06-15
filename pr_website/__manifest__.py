{
    "name": "Petroraq Custom Website",
    "version": "1.1",
    "category": "Website",
    "summary": "Custom full website for Petroraq Engineering built in Odoo.",
    "author": "Mudassir Amin",
    "website": "https://petroraq.com",
    "license": "LGPL-3",

    # Required
    "depends": [
        "website",
        "google_recaptcha",
        "crm",
        "hr_recruitment",  # for careers page
        "hr_recruitment_skills",
        "pr_hr_recruitment_request",
    ],

    # Data files (XML Views)
    "data": [
        # "views/assets.xml",          # CSS/JS
        "views/layout.xml",  # custom header/footer
        "views/footer.xml",
        "views/hero.xml",
        "views/contact_us.xml",
        "views/about_us.xml",
        "views/clients.xml",
        "views/projects.xml",
        "views/design_engineering.xml",
        "views/architecture-planning.xml",
        "views/civil-structural.xml",
        "views/electrical-telecommunication.xml",
        "views/mechanical-piping.xml",
        "views/cad-services.xml",
        "views/other-services.xml",
        "views/project_management.xml",

        # "views/assets.xml",
        # "views/home.xml",
        # "views/about.xml",
        # "views/services.xml",
        # "views/projects.xml",
        # "views/careers.xml",
        "views/404.xml",
        # "views/job_detail.xml",
        # "views/contact.xml",
        "views/careers.xml",
    ],

    # QWeb templates (loaded globally)
    "assets": {
        "web.assets_frontend": [
            "pr_website/static/css/theme.css",
            "pr_website/static/js/theme.js",
        ],
    },

    "application": True,
    "installable": True,
}
