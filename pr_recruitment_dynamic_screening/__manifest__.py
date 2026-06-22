# -*- coding: utf-8 -*-
{
    "name": "Petroraq Dynamic Recruitment Screening",
    "version": "17.0.1.4.0",
    "category": "Human Resources/Recruitment",
    "summary": "Per-job application questions with automatic candidate screening",
    "author": "Mudassir Amin",
    "website": "https://petroraq.com",
    "license": "LGPL-3",
    "depends": [
        "pr_website",
        "pr_hr_recruitment",
        "pr_hr_recruitment_request",
        "hr_recruitment_skills",
    ],
    "data": [
        "security/recruitment_question_security.xml",
        "security/ir.model.access.csv",
        "data/recruitment_data.xml",
        "views/hr_job_views.xml",
        "views/hr_recruitment_request_views.xml",
        "views/hr_applicant_views.xml",
        "views/automatic_refusal_reporting_views.xml",
        "views/website_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "pr_recruitment_dynamic_screening/static/src/css/dynamic_screening.css",
            "pr_recruitment_dynamic_screening/static/src/js/dynamic_screening.js",
        ],
        "web.assets_backend": [
            "pr_recruitment_dynamic_screening/static/src/xml/recruitment_dashboard_extension.xml",
        ],
    },
    "installable": True,
    "application": False,
}
