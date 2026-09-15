{
    "name": "Petroraq ZATCA Warning Center",
    "version": "17.0.1.0.0",
    "summary": "Capture, route, and prevent recurring ZATCA invoice warnings",
    "category": "Accounting/Localizations/EDI",
    "license": "LGPL-3",
    "depends": ["account_accountant", "l10n_sa_edi", "pr_account"],
    "data": [
        "security/zatca_warning_security.xml",
        "security/ir.model.access.csv",
        "data/zatca_warning_rule_data.xml",
        "views/zatca_warning_views.xml",
        "views/zatca_invoice_audit_wizard_views.xml",
        "views/account_move_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "application": False,
}
