# -*- coding: utf-8 -*-
{
    "name": "Petroraq HR Offboarding",
    "summary": "Termination and resignation request approval workflow",
    "description": """
        Manage the first stage of employee offboarding: an HR Supervisor
        creates and submits a termination or resignation request for approval
        by the employee's department manager.
    """,
    "author": "Muhammad Mudassir",
    "website": "https://www.petroraq.com",
    "category": "Human Resources",
    "version": "17.0.1.0.0",
    "license": "LGPL-3",
    "depends": [
        "mail",
        "de_hr_workspace",
        "pr_hr_recruitment_request",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/offboarding_security.xml",
        "data/offboarding_sequence.xml",
        "wizard/offboarding_reject_wizard_views.xml",
        "views/offboarding_request_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
