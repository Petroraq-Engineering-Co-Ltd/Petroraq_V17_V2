{
    'name': 'Qiwa Contract OCR Processor',
    'version': '17.0.1.0.0',
    'depends': [
        'hr_recruitment',
        'pr_hr_recruitment',
        'pr_hr_recruitment_request',
        'pr_hr_contract',
        'pr_account',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/onboarding_compliance_sequence.xml',
        'views/wizard_views.xml',
        'views/hr_applicant_views.xml',
        'views/onboarding_compliance_views.xml',
    ],
    'external_dependencies': {
        'python': ['pypdf'],
    },
    'installable': True,
    'auto_install': False,
}
