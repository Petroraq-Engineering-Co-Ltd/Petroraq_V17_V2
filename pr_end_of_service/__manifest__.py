# -*- coding: utf-8 -*-
{
    "name": "Petroraq End of Service",
    "summary": "End of service settlement workflow for Petroraq HR and accounting",
    "description": """
        Manage employee end of service settlements using Petroraq contracts,
        leave balances, employee lifecycle states, and bank payment vouchers.
    """,
    "author": "Mudassir Amin",
    "website": "https://webmail.petroraq.com/",
    "category": "Human Resources",
    "version": "17.0.1.1.0",
    "license": "LGPL-3",
    "depends": [
        "pr_hr_payroll",
        "pr_hr_holidays",
        "pr_hr_account",
        "de_hr_workspace",
        "pr_hr_recruitment_request",
        "mail",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "data/sequence.xml",
        "data/end_service_reason_data.xml",
        "views/pr_end_service_reason_views.xml",
        "views/pr_end_of_service_views.xml",
        "views/eos_calculator_views.xml",
        "views/hr_employee_views.xml",
        "views/bank_payment_views.xml",
        "views/res_config_settings_views.xml",
        "reports/pr_end_of_service_report.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
