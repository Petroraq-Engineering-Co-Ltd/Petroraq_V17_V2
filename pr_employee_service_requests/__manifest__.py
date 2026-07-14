# -*- coding: utf-8 -*-
{
    "name": "Petroraq Employee Service Requests",
    "summary": "Employee payments and HR compliance record/renewal workflows",
    "description": """
Employee self-service requests for reimbursements, exit/re-entry visas, combined
Iqama/work permit processing, and medical insurance. New compliance requests
create record-only entries; renewals use HR Manager and MD approval with
budget-controlled BPVs.
""",
    "author": "Mudassir Amin",
    "website": "https://www.petroraq.com",
    "category": "Human Resources",
    "version": "17.0.1.0.4",
    "license": "LGPL-3",
    "depends": [
        "de_hr_workspace",
        "pr_hr_contract",
        "pr_account",
        "pr_hr",
        "pr_hr_recruitment",
        "pr_hr_account",
        "pr_hr_recruitment_request",
        "pr_custom_purchase",
        "prt_report_attachment_preview",
        "pr_tax_Invoice_report_custom",
        "petroraq_sale_workflow",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "data/ir_sequence_data.xml",
        "data/employee_letter_mail_templates.xml",
        "reports/employee_document_letter_report.xml",
        "views/employee_service_request_views.xml",
        "views/employee_document_letter_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
