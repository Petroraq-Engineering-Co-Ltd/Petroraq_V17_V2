{
    "name": "Daily Task Attendance Approval",
    "version": "17.0.1.1.3",
    "category": "Human Resources/Attendance",
    "summary": "Daily task submission attendance policy and HR mark-present requests",
    "license": "LGPL-3",
    "depends": ["employee_task_management", "pr_hr_attendance", "de_hr_workspace_attendance"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/employee_attendance_repair_action.xml",
        "views/task_attendance_views.xml",
        "data/cron.xml",
    ],
    "auto_install": True,
    "installable": True,
}
