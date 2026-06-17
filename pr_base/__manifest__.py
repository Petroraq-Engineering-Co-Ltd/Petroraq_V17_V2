# -*- coding: utf-8 -*-
{
    'name': "Petroraq Base",

    'summary': """
        Manage custom development on Odoo Base Module""",

    'description': """

    """,

    'author': "Mahmoud Salah",
    'company': "Petroraq",
    'website': "https://webmail.petroraq.com/",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/master/odoo/addons/base/module/module_data.xml
    # for the full list
    'category': 'dashboard',
    'version': '17.0.0.0.3',

    # any module necessary for this one to work correctly
    'depends': ['base', 'contacts', 'product', 'l10n_sa_edi','hr'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'views/menus.xml',
        'views/res_partner.xml',
        'views/product_template.xml',
        'views/hr_employee.xml',
        'data/product_sequence.xml',
        'data/product_internal_reference_actions.xml',
        'data/partner_sequence.xml',
        'data/partner_resequence_server_action.xml',
        'wizards/pr_reject_record.xml',
    ],
    # only loaded in demonstration mode
    'demo': [],
    'assets': {}
}
