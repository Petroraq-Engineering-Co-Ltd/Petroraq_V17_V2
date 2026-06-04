# -*- coding: utf-8 -*-
{
    "name": "Petroraq Budget Requisition",
    "summary": "Department budget proposal approvals that create approved backend budgets",
    "description": """
Department budget requisitions for Opex/Capex planning.

Departments submit requested budget amounts by cost center, then Department
Manager, Accounts, and Managing Director approvals create the final analytic
budget used by purchase requisitions.
""",
    "author": "Mudassir Amin",
    "website": "https://www.petroraq.com",
    "category": "Operations/Purchase",
    "version": "17.0.1.0.4",
    "license": "LGPL-3",
    "depends": ["pr_custom_purchase", "de_hr_workspace", "report_xlsx"],
    "data": [
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "data/ir_sequence_data.xml",
        "report/budget_analysis_report.xml",
        "views/budget_requisition_views.xml",
        "views/budget_report_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
