# -*- coding: utf-8 -*-
{
    'name': "Petroraq HR Holidays",

    'summary': """
        This Module is created to manage Time Off""",

    'description': """
    """,

    'author': "Mahmoud Salah",
    'company': "Petroraq",
    'website': "https://webmail.petroraq.com/",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/master/odoo/addons/base/module/module_data.xml
    # for the full list
    'category': 'Human Resources/Time Off',
    'version': '17.0.1.0.11',
    # any module necessary for this one to work correctly
    'depends': ['pr_hr_contract', 'hr_holidays', 'pr_base'],

    # always loaded
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'views/menu_items.xml',
        'views/hr_leave_request_view.xml',
        'views/hr_leave_type.xml',
        'views/hr_leave.xml',
        'views/hr_employee.xml',
        'data/data.xml',
        'data/ir_sequence.xml',
        'data/annual_leave_cron.xml',
    ],
    # only loaded in demonstration mode
    'demo': [],
}
