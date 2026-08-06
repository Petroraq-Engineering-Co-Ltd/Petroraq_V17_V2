# -*- coding: utf-8 -*-
{
    "name": "Petroraq IT Service Requests",
    "summary": "Configurable IT requests with grouped sequential approvals",
    "description": """
Professional IT service request tracking for access, account creation, device
assignment, deployments, and other configurable IT services. Employees select
or adjust a grouped sequential approval chain before submission; approvers receive
activities and process requests from the central Approvals workspace.
""",
    "version": "17.0.1.0.6",
    "category": "Services/IT Services",
    "author": "Petroraq Engineering & Construction Co. Ltd.",
    "website": "https://www.petroraq.com",
    "license": "LGPL-3",
    "depends": ["mail", "hr", "de_hr_workspace"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "data/ir_sequence_data.xml",
        "data/mail_activity_type_data.xml",
        "data/it_request_type_data.xml",
        "views/it_service_request_views.xml",
        "views/it_request_type_views.xml",
        "wizard/it_service_request_reject_wizard_views.xml",
    ],
    "images": ["static/description/icon.svg"],
    "application": True,
    "installable": True,
    "auto_install": False,
}
