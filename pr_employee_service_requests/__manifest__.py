# -*- coding: utf-8 -*-
{
    "name": "Petroraq Employee Service Requests",
    "summary": "Employee reimbursement and exit/re-entry self-service requests",
    "description": """
Adds employee self-service requests for reimbursements and exit/re-entry visas,
with HR Supervisor, Employee Manager, HR Manager, MD, and accounting voucher flow.
""",
    "author": "Mudassir Amin",
    "website": "https://www.petroraq.com",
    "category": "Human Resources",
    "version": "17.0.1.0.1",
    "license": "LGPL-3",
    "depends": [
        "de_hr_workspace",
        "pr_account",
        "pr_hr",
        "pr_hr_account",
        "pr_hr_recruitment_request",
        "pr_custom_purchase",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "data/ir_sequence_data.xml",
        "views/employee_service_request_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
