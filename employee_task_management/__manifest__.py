# -*- coding: utf-8 -*-
{
    'name': 'Employee Task Management',
    'version': '17.0.1.19.1',
    'category': 'Human Resources',
    'summary': 'Employee Task List Approval Workflow',
    'description': """
Employee Task Management
========================
Create, approve, monitor, and close employee task lists through a
structured approval workflow.

Workflow:
Employee -> Immediate Manager -> Approved Task List -> Execution ->
Submit for Review -> Accept -> Closed

Developed for: Petroraq Digital Solutions
    """,
    'author': 'Petroraq Digital Solutions',
    'website': 'https://www.petroraq.com',
    'license': 'LGPL-3',
    'depends': ['base', 'hr', 'mail', 'web'],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'data/sequence_data.xml',
        'data/mail_template_data.xml',
        'data/cron_data.xml',
        'wizard/task_return_wizard_views.xml',
        'wizard/task_unlock_wizard_views.xml',
        'wizard/task_modification_wizard_views.xml',
        'wizard/task_reject_wizard_views.xml',
        'wizard/task_line_reject_wizard_views.xml',
        'views/activity_reject_wizard_views.xml',
        'views/employee_task_subtask_views.xml',
        'views/employee_task_list_views.xml',
        'views/employee_idle_day_views.xml',
        'views/approval_history_views.xml',
        'report/task_report_views.xml',
        'views/dashboard_views.xml',
        'views/menu_views.xml',
        'views/approval_workspace_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'employee_task_management/static/src/scss/task_management.scss',
            'employee_task_management/static/src/scss/dashboard.scss',
            'employee_task_management/static/src/js/dashboard/task_dashboard.js',
            'employee_task_management/static/src/xml/task_dashboard.xml',
            'employee_task_management/static/src/js/fields/masked_hours_field.js',
            'employee_task_management/static/src/xml/masked_hours_field.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
