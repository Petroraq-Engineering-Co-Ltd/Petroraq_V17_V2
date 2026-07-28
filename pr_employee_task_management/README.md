# Employee Task Management

Odoo 17 application implementing the Petroraq Employee Task List approval workflow.

## Workflow

`Draft -> Submitted to Manager -> Manager Approved -> In Progress -> Completed -> Closed`

The manager can return a submitted list for correction. Returned lists can be edited and
resubmitted by the employee.

## Security roles

- **Employee**: creates and executes their own task lists.
- **Manager**: creates and reviews task lists for direct reports.
- **Administrator**: full access and configuration.

Assign roles from **Settings > Users & Companies > Users**, under
**Employee Task Management**. Each employee user must be linked to an `hr.employee`.
The employee's **Manager** field must point to an employee who is also linked to an
Odoo user.

## Installation

1. Add this repository to the Odoo addons path.
2. Update the Apps list.
3. Install **Employee Task Management**, or upgrade with:

   `odoo-bin -d <database> -u pr_employee_task_management --stop-after-init`

4. Assign the Employee, Manager, or Administrator role to users.

## Included

- Task-list and task-line models
- Immediate-manager approval workflow
- Return and resubmission
- Progress tracking and overdue detection
- Approval history and chatter
- Inbox notifications and scheduled activities
- Supporting attachments
- List, kanban, form, activity, pivot, and graph views
- Dashboard with status, department, employee, and monthly metrics
- Record rules and server-side authorization
- Automated workflow tests

