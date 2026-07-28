{
    "name": "Employee Task Management",
    "summary": "Employee task lists with immediate-manager approval and progress tracking",
    "version": "17.0.1.0.0",
    "category": "Human Resources",
    "author": "Petroraq",
    "license": "LGPL-3",
    "depends": ["hr", "mail", "web"],
    "data": [
        "security/employee_task_security.xml",
        "security/ir.model.access.csv",
        "data/employee_task_sequence.xml",
        "data/employee_task_cron.xml",
        "views/employee_task_list_views.xml",
        "views/employee_task_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pr_employee_task_management/static/src/js/task_dashboard.js",
            "pr_employee_task_management/static/src/xml/task_dashboard.xml",
            "pr_employee_task_management/static/src/scss/task_dashboard.scss",
        ],
    },
    "application": True,
    "installable": True,
}
