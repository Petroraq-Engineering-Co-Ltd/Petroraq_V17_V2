{
    'name': 'Qiwa Contract OCR Processor',
    'version': '17.0.1.0.4',
    'depends': [
        'hr_recruitment',
        'pr_hr_recruitment',
        'pr_hr_recruitment_request',
        'pr_hr_contract',
        'pr_account',
        'pr_employee_service_requests',
        'mail',
    ],
    'author': 'Mudassir Amin',
    'data': [
        'security/ir.model.access.csv',
        'data/onboarding_compliance_sequence.xml',
        'data/onboarding_reminder_cron.xml',
        'views/wizard_views.xml',
        'views/hr_applicant_views.xml',
        'views/onboarding_compliance_views.xml',
    ],
    'external_dependencies': {
        'python': ['pypdf'],
    },
    'assets': {
        'web.assets_backend': [
            'qiwa_contract_ocr/static/src/js/reminder_dashboard_action.js',
            'qiwa_contract_ocr/static/src/xml/reminder_dashboard_action_templates.xml',
            'qiwa_contract_ocr/static/src/css/reminder_dashboard.css',
        ],
    },
    'installable': True,
    'auto_install': False,
}