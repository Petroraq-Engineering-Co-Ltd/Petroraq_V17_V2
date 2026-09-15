{
    "name": "Daily Task Attendance Approval",
    "version": "17.0.1.0.0",
    "category": "Human Resources/Attendance",
    "summary": "Daily task submission attendance policy and HR mark-present requests",
    "license": "LGPL-3",
    "depends": ["employee_task_management", "pr_hr_attendance", "de_hr_workspace_attendance"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/task_attendance_views.xml",
        "data/cron.xml",
    ],
    "auto_install": True,
    "installable": True,
}
