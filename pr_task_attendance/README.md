# Daily task attendance

Install `pr_task_attendance` after updating the app list. It also auto-installs
when its three dependencies are installed together. Restart Odoo when deploying
the Python files. No employee group reassignment is required.

## Policy

- Each employee must submit a task list covering that working day **on that day**.
  A previous day's submission, a saved draft, or a manager assignment does not count.
  The existing task approval history supplies the submission timestamp. A submitted
  list returned by a manager still counts as a submission.
- For an ongoing task list spanning multiple days, the employee uses **Submit
  for Today** each working day. It records a fresh submission without resetting
  the task workflow. The initial normal submission also counts for its day.
- Use the employee's local attendance timezone and resource working calendar,
  including alternating weeks, calendar leave, and public holidays. If no working
  intervals remain, no task submission is required.
- At the first scheduler tick after local midnight (normally within one minute),
  an employee with attendance but no qualifying submission is marked absent.
  Actual check-in/check-out, worked hours, and attendance-source audit data are
  retained. No synthetic punches are created for employees without attendance.
- The cron catches up after downtime and also processes attendance imported late.
  One absence/request record exists per employee/date. A late submission does not
  clear a recorded absence; HR approval is required.
- Enforcement starts on the module's installation date (Saudi business date),
  stored in `pr_task_attendance.enforce_from`. Earlier history is untouched.

## Employee and HR workflow

Employees open **My Workspace → Attendance → My Mark Present Requests**, select
the affected day, enter a reason, and click **Request Mark Present**. The same
record can be opened from the employee's attendance form.

The request appears under **My Approvals → Mark Present Requests** and in the HR
approval dashboard. Existing HR Manager groups receive review activities.
HR can approve actual attendance or reject with a reason. Rejected requests can
be resubmitted; chatter and decision fields retain the approval trail.

Approval removes only the missing-task penalty. Existing late-arrival and
missing-checkout policies are then applied to the original punches. Employees
cannot approve requests, overwrite their state, or access another employee's
requests. Company record rules apply to HR as well.

Draft and confirmed attendance sheets apply the absence and restore their
underlying attendance values on approval. Finalized sheets/payslips are not
rewritten; their normal payroll adjustment/reopening process must be used.

## Validation

Run the Odoo regression suite with `--test-tags /pr_task_attendance` against a
test database after installing the module. The suite covers midnight, daily
submission dates, schedule exceptions, late imports, access control, approval,
and preservation of actual punches.
