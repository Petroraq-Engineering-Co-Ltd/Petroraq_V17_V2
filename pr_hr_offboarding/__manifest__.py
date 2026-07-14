# -*- coding: utf-8 -*-
{
    "name": "Petroraq HR Offboarding",
    "summary": "Termination and resignation request approval workflow",
    "description": """
        Manage the first stage of employee offboarding: an HR Supervisor
        creates and submits a termination or resignation request for approval
        by the employee's department manager, HR Manager, and MD.
    """,
    "author": "Muhammad Mudassir",
    "website": "https://www.petroraq.com",
    "category": "Human Resources",
    "version": "17.0.1.0.0",
    "license": "LGPL-3",
    "depends": [
        "hr",
        "mail",
        "de_hr_workspace",
        "pr_hr_recruitment_request",
        "pr_end_of_service",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/offboarding_security.xml",
        "data/offboarding_sequence.xml",
        "data/offboarding_clearance_template_data.xml",
        "wizard/offboarding_reject_wizard_views.xml",
        "views/offboarding_request_views.xml",
        "views/offboarding_clearance_template_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
