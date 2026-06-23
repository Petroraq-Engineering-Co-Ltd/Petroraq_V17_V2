# Attendance Entry Control

Employees have one protected **Attendance Entry Mode**:

- **Automated Attendance**: biometric employees and management/WFH employees
  handled by scheduled attendance. Attendance times cannot be manually created,
  edited, reassigned, or deleted.
- **Manual / Site Attendance**: attendance officers may create, import, correct,
  reassign, and delete attendance received from field timesheets.

Trusted biometric synchronization, scheduled management attendance, and
approved shortage corrections identify their source internally. A caller cannot
unlock automated attendance merely by passing a normal RPC context flag.

## Changing an employee's mode

Use **Request Mode Change** on the employee. The request stores the current and
requested mode, reason, requester, dates, and decision user. Only a user in the
Onboarding MD group can approve or reject it. Approval changes the employee
mode atomically; direct edits are blocked even for normal administrators.

Pending requests appear under **Approvals > Attendance Mode Changes** and are
automatically included as a tile on the existing Approvals Dashboard. All
requests remain available from the employee smart button and Attendance menu
for audit history.
